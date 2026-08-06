"""`dhdr` — run the scenario and print the certificates.

The demo needs `fixtures/` and `scenarios/`, which live at the repository root
rather than inside the installed package: they are the world and the agent, not
the library. The root is resolved from this file's location so the command works
from any working directory and from anyone's checkout.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from reckon import MemorySink, Recorder

from .certify import Certificate, certify
from .coordinate import GMS_URL_ENV_VAR
from .coordinate import default_base_url as DEFAULT_BASE_URL_MARKER
from .coordinate import lineage_facts
from .proxy import CaptureProxy, McpCaptureProxy
from .publish import publish_certificate
from .sarif import to_sarif

REPO_ROOT = Path(__file__).resolve().parents[2]

# Where the published certificate artifacts are hosted. The URL written into
# DataHub has to resolve for a later reader (invariant 10), so it points at the
# project's own GitHub Pages site rather than a placeholder domain.
DEFAULT_CERT_BASE = "https://laolex.github.io/datahub-decision-records/certs"

# Where the artifact behind each published URL is written. The URL and the file
# have to be produced by the same run: publishing a link whose artifact nobody
# wrote is the failure invariant 10 forbids, and it is easy to do by accident
# because the write to DataHub succeeds either way.
CERT_DIR = REPO_ROOT / "docs" / "certs"


def quiet_mcp_logging() -> None:
    """Silence the MCP server's per-query debug logging.

    It prints the full GraphQL document for every call, which is useful when
    debugging the adapter and drowns the certificate when a human is reading.
    """
    import logging
    import warnings

    logging.disable(logging.INFO)

    # The DataHub SDK emits an ExperimentalWarning on import, twice, straight to
    # stderr — harmless, theirs not ours, and it lands in the middle of the
    # output a human is reading.
    try:
        from datahub.errors import ExperimentalWarning

        warnings.filterwarnings("ignore", category=ExperimentalWarning)
    except ImportError:  # pragma: no cover - SDK always present in practice
        warnings.filterwarnings("ignore", message=r".*[Ee]xperimental.*")

    try:
        from loguru import logger

        logger.remove()
    except ImportError:  # pragma: no cover - loguru ships with the MCP server
        pass


def _load_scenario():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from fixtures.seed import seed_schema_ops
        from scenarios.schema_ops import decide_drop_column
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            f"could not import the scenario from {REPO_ROOT}: {exc}. "
            "Run `dhdr demo` from a checkout of the repository — the fixtures and "
            "scenarios are not shipped inside the installed package."
        ) from exc
    return seed_schema_ops, decide_drop_column


def _load_live():
    """The pieces the live MCP flow needs, loaded from the repository root."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from fixtures.seed import CONSUMER, TARGET, set_consumer_lineage
        from scenarios.schema_ops import decide_drop_column_mcp
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            f"could not import the scenario from {REPO_ROOT}: {exc}. "
            "Run this from a checkout of the repository."
        ) from exc
    return CONSUMER, TARGET, set_consumer_lineage, decide_drop_column_mcp


@dataclass
class LiveDecision:
    """One decision made against the live world, through the MCP server."""

    outcome: str
    revision: int | None
    last_observed_ms: int | None
    decided_at_ms: int
    certificate: Certificate
    published_url: str | None
    record: dict
    change: object | None = None  # scenarios.schema_ops.ChangeRequest


async def _mcp_lineage(consumer: str) -> set[str]:
    async with McpCaptureProxy() as probe:
        return set(lineage_facts((await probe.call_lineage(consumer)).value))


async def _settle(
    consumer: str, upstreams: list[str], set_lineage, *, opposite: list[str], timeout_s=45.0
):
    """Move the world and wait until MCP itself reports the new state.

    MCP has no point-in-time parameter — it only ever answers about now — so the
    two halves of the demonstration cannot come from time travel. The world has
    to actually move between two live reads, and this waits for the change to
    reach the lineage query rather than assuming it has.

    One repair is built in. DataHub treats a write whose value already matches
    the stored aspect as a no-op and emits no change event, so if the graph index
    has drifted from the aspect store — which happens when OpenSearch is down
    while writes continue — re-writing the state we want can never fix it. The
    first timeout therefore forces a genuine transition through the opposite
    state, which does emit events, and tries again.
    """

    async def converge(deadline: float) -> set[str]:
        seen: set[str] = set()
        while time.time() < deadline:
            seen = await _mcp_lineage(consumer)
            if seen == set(upstreams):
                return seen
            await asyncio.sleep(2)
        return seen

    set_lineage(upstreams)
    seen = await converge(time.time() + timeout_s)
    if seen == set(upstreams):
        return

    # Force a real transition, then come back.
    set_lineage(opposite)
    await asyncio.sleep(4)
    set_lineage(upstreams)
    seen = await converge(time.time() + timeout_s)
    if seen == set(upstreams):
        return

    raise SystemExit(
        f"MCP never reported lineage {set(upstreams)} within {2 * timeout_s:.0f}s "
        f"(saw {seen}), including after forcing a real transition.\n"
        "Most likely GMS's lineage cache is on — run scripts/preflight.py.\n"
        "If preflight passes, check that OpenSearch is up: a graph index that "
        "drifted while it was down looks exactly like this."
    )


async def _decide_live(
    consumer: str,
    target: str,
    decide_drop_column_mcp,
    *,
    run_id: str,
    cert_base: str,
    publish: bool,
) -> LiveDecision:
    """Read through the real MCP server, decide, certify, and write back."""
    sink = MemorySink()
    async with McpCaptureProxy() as proxy:
        outcome = await decide_drop_column_mcp(
            proxy,
            Recorder(sink=sink, run_id=run_id, emitter="dhdr/0.1.0"),
            target,
            consumer,
        )
    read = proxy.reads[0]
    record = sink.records[0]

    # The concrete change this decision is about. Derived from the same outcome
    # the predicate produced, so the artifact and the verdict cannot disagree.
    from scenarios.schema_ops import DEFAULT_COLUMN, proposed_change

    change = proposed_change(
        target, DEFAULT_COLUMN, outcome=outcome, consumers=(consumer,)
    )

    decided_at_ms = read.response_received_ms or int(time.time() * 1000)
    events: list[dict] = []
    published_url = None
    if publish:
        _write_certificate_artifact(
            decided_at_ms,
            outcome=outcome,
            revision=read.revision,
            last_observed_ms=read.last_observed_ms,
            certificate=certify(record, proxy.reads, requested="C2"),
            change=change,
            record=record,
        )
        published_url = publish_certificate(
            consumer,
            certify(record, proxy.reads, requested="C2"),
            outcome=outcome,
            revision=read.revision,
            decided_at_ms=decided_at_ms,
            certificate_url=f"{cert_base.rstrip('/')}/{decided_at_ms}.json",
            events=events,
        )

    # The certificate is produced *after* the publish so the self-write boundary
    # is derived from an event the write actually emitted, never from a flag.
    certificate = certify(record, proxy.reads, requested="C2", publish_events=events)

    return LiveDecision(
        outcome=outcome,
        revision=read.revision,
        last_observed_ms=read.last_observed_ms,
        decided_at_ms=decided_at_ms,
        certificate=certificate,
        published_url=published_url,
        record=record,
        change=change,
    )


def _write_certificate_artifact(
    decided_at_ms: int, *, outcome, revision, last_observed_ms, certificate, change, record
) -> Path:
    """Write the artifact the published URL points at, in the same run."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    path = CERT_DIR / f"{decided_at_ms}.json"
    path.write_text(
        json.dumps(
            {
                "outcome": outcome,
                "revision": revision,
                "aspect_last_observed_ms": last_observed_ms,
                "decided_at_ms": decided_at_ms,
                "capability_class": certificate.cls,
                "satisfied": certificate.satisfied,
                "missing": certificate.missing,
                "certificate": certificate.render(),
                "proposed_change": change.render() if change is not None else None,
                "record": record,
            },
            indent=2,
            default=str,
        )
        + "\n"
    )
    return path


async def live_decisions(
    *, cert_base: str = DEFAULT_CERT_BASE, publish: bool = True, reset: bool = False
) -> list[LiveDecision]:
    """The headline claim, end to end and entirely live.

    Two decisions through the real MCP server, with the world moving between
    them, each bound to the revision that justified it and each written back
    into DataHub. Nothing here reads a past instant through the aspect API — the
    aspect API is used only to resolve the coordinate the MCP response does not
    carry.
    """
    return [
        d
        async for kind, d in live_flow(
            cert_base=cert_base, publish=publish, reset=reset
        )
        if kind == "decision"
    ]


def reset_institutional_memory(urn: str, base_url: str | None = None) -> None:
    """Clear the dataset's institutionalMemory before a demo run.

    Repeated demo runs otherwise accumulate certificates whose artifacts were
    never published anywhere, so the Documentation tab fills with links that
    404 — the precise failure invariant 10 forbids, on the screen a judge looks
    at. Off by default; the demo takes `--reset` because wiping institutional
    memory is not something to do silently.
    """
    import requests

    base_url = base_url or DEFAULT_BASE_URL_MARKER()
    requests.post(
        f"{base_url}/openapi/v3/entity/dataset",
        json=[{"urn": urn, "institutionalMemory": {"value": {"elements": []}}}],
        params={"async": "false"},
        timeout=30,
    ).raise_for_status()


async def live_flow(
    *, cert_base: str = DEFAULT_CERT_BASE, publish: bool = True, reset: bool = False
):
    """The same flow, yielded step by step so a caller can narrate around it.

    Yields `("settling", upstreams)` before each world change and
    `("decision", LiveDecision)` after each decision.
    """
    consumer, target, set_lineage, decide_mcp = _load_live()
    if reset:
        reset_institutional_memory(consumer)

    for label, upstreams in (("before", []), ("after", [target])):
        yield "settling", upstreams
        opposite = [target] if not upstreams else []
        await _settle(consumer, upstreams, set_lineage, opposite=opposite)
        decision = await _decide_live(
            consumer,
            target,
            decide_mcp,
            run_id=f"live-{label}",
            cert_base=cert_base,
            publish=publish,
        )
        yield "decision", decision


def _decide_once(at_ms: int, world, decide_drop_column, run_id: str):
    """One decision, returning the record, the outcome and the proxy that read."""
    sink = MemorySink()
    proxy = CaptureProxy()
    outcome = decide_drop_column(
        proxy,
        Recorder(sink=sink, run_id=run_id, emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=at_ms,
    )
    return sink.records[0], outcome, proxy


def _sarif(args: argparse.Namespace) -> int:
    """Emit the current decision as a SARIF annotation for a CI gate.

    Reads through the real MCP server, like the demo. A gate that certified a
    decision made by a different code path than the one being demonstrated would
    be certifying the wrong thing.
    """
    quiet_mcp_logging()
    decisions = asyncio.run(live_decisions(publish=False))
    decision = decisions[-1]
    cert = decision.certificate
    consumer, _target, _set_lineage, _decide = _load_live()
    json.dump(
        to_sarif(
            cert,
            path=args.path,
            line=args.line,
            strict=args.strict,
            outcome=decision.outcome,
            revision=decision.revision,
            dataset=consumer,
            change=decision.change.statement if decision.change else None,
        ),
        sys.stdout,
        indent=2,
    )
    print()
    # Exit non-zero only under --strict, and only when nothing is certifiable.
    # A gate that blocks a merge over a gap in its own instrumentation gets
    # uninstalled, and an uninstalled gate certifies nothing.
    return 1 if (args.strict and cert.cls is None) else 0


def _demo(args: argparse.Namespace) -> int:
    """The live path: real MCP reads, real write-back, no time travel.

    Printed as a numbered timeline rather than two result blocks. The claim is
    not "here are two outcomes" — it is that the *same question*, asked twice
    through the same server, was answered both ways, and that only the record
    can say which world each answer came from. A reader has to be able to watch
    that happen in order, which two summary blocks do not show.
    """
    quiet_mcp_logging()
    publish = not getattr(args, "no_publish", False)
    cert_base = getattr(args, "cert_base", DEFAULT_CERT_BASE)

    consumer, target, _set_lineage, _decide = _load_live()
    short_target = target.split(",")[-2] if "," in target else target
    column = "promo_code"

    step = 0
    decisions: list[LiveDecision] = []

    def emit(text: str) -> None:
        nonlocal step
        print(f"  #{step:<3}{text}")
        step += 1

    print("\nTIMELINE — one agent, one question, asked twice\n")

    async def run() -> None:
        first = True
        async for kind, payload in live_flow(
            cert_base=cert_base, publish=publish, reset=getattr(args, "reset", False)
        ):
            if kind == "settling":
                # The first settle is the world being put into its starting
                # state, not a change to it. Announcing "the world moves"
                # there would claim a pipeline change happened before the
                # agent had looked at anything.
                if first:
                    continue
                print(
                    "\n  ···  the world moves: a pipeline change rewires who reads "
                    f"{short_target}\n"
                )
                continue

            decision = payload
            decisions.append(decision)
            if first:
                emit(
                    f"Read downstream lineage for {short_target} "
                    "— through the real MCP server"
                )
            else:
                emit(
                    "The identical call, seconds later, same MCP server "
                    f"— {short_target}"
                )
            if decision.revision is None:
                emit(
                    "Could NOT bind that read to any revision — "
                    "certifying nothing rather than guessing"
                )
            else:
                emit(
                    f"Bound that read to upstreamLineage v{decision.revision} "
                    f"(lastObserved={decision.last_observed_ms})"
                )
            emit(
                f"Certified {decision.certificate.cls or 'none'} — "
                + (
                    "every deciding read named a revision"
                    if decision.certificate.cls
                    else "a read that cannot be placed in time certifies nothing"
                )
            )
            emit(
                f"DECISION: {decision.outcome} — "
                + (
                    f"nothing reads {column} at v{decision.revision}"
                    if decision.outcome == "admit"
                    else f"a consumer reads {column} at v{decision.revision}"
                )
            )
            if decision.change is not None:
                emit(f"Proposed, NOT applied: DROP COLUMN {column}")
            if decision.published_url:
                emit(f"Certificate published into DataHub → {decision.published_url}")
            first = False

    asyncio.run(run())

    print("\n  Same agent. Same call. Opposite decisions.")
    print("  Neither log can tell you which world it was made in. Both certificates can.")

    print("\n\nCERTIFICATES\n")
    for label, decision in zip(
        ("as the agent saw it", "as it actually was"), decisions, strict=False
    ):
        print(f"=== {label} ===")
        print(f"outcome:  {decision.outcome}")
        print(f"revision: v{decision.revision}  (lastObserved={decision.last_observed_ms})")
        print(decision.certificate.render())
        if decision.change is not None:
            print("proposed change:")
            for line in decision.change.render().splitlines():
                print(f"  {line}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dhdr", description="Decision records for DataHub agents."
    )
    parser.add_argument(
        "--base-url",
        default=None,
        metavar="URL",
        help=(
            f"DataHub GMS endpoint (default: ${GMS_URL_ENV_VAR}, "
            f"else {DEFAULT_BASE_URL_MARKER()})"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    demo = sub.add_parser(
        "demo", help="live MCP reads, two decisions, both written back into DataHub"
    )
    demo.add_argument(
        "--no-publish",
        action="store_true",
        help="decide and certify without writing back to institutionalMemory",
    )
    demo.add_argument(
        "--reset",
        action="store_true",
        help="clear the dataset's institutionalMemory first, so it shows only this run",
    )
    demo.add_argument(
        "--cert-base",
        default=DEFAULT_CERT_BASE,
        help="base URL the published certificate artifacts are hosted at",
    )
    demo.set_defaults(func=_demo)

    sarif = sub.add_parser("sarif", help="emit the certificate as SARIF 2.1.0")
    sarif.add_argument(
        "--path", default="scenarios/schema_ops.py", help="artifact URI to annotate"
    )
    sarif.add_argument(
        "--line",
        type=int,
        default=1,
        help="line to annotate; must be a line the diff touches to render inline",
    )
    sarif.add_argument(
        "--strict",
        action="store_true",
        help="fail closed: exit non-zero when nothing is certifiable",
    )
    sarif.set_defaults(func=_sarif)

    args = parser.parse_args(argv)

    # Export rather than thread: the MCP server and the DataHub SDK read this
    # same variable out of the environment, and a flag that moved only our own
    # reads would point the two halves of the demo at different instances.
    if args.base_url:
        os.environ[GMS_URL_ENV_VAR] = args.base_url

    if getattr(args, "func", None) is None:
        return _demo(args)          # bare `dhdr` runs the demo
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
