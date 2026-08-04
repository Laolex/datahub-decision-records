"""Regenerate everything in `examples/` from a live DataHub instance.

Judges should be able to inspect a real result without standing up DataHub, so
`examples/` holds actual artifacts rather than descriptions of them. This script
is what produced them; see the Reproduce section of the README.

Run from a checkout, with DataHub Core reachable at localhost:8080:

    python scripts/generate_examples.py
"""

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from reckon import JsonlSink, MemorySink, Recorder  # noqa: E402

from dhdr.certify import certify  # noqa: E402
from dhdr.coordinate import lineage_facts  # noqa: E402
from dhdr.proxy import CaptureProxy, McpCaptureProxy  # noqa: E402
from dhdr.cli import live_decisions  # noqa: E402
from dhdr.publish import read_published  # noqa: E402
from fixtures.seed import (  # noqa: E402
    CONSUMER,
    TARGET,
    seed_schema_ops,
    set_consumer_lineage,
)
from scenarios.schema_ops import decide_drop_column, decide_drop_column_mcp  # noqa: E402

EXAMPLES = REPO / "examples"
HOSTED = REPO / "docs" / "index.html"
CERTS = REPO / "docs" / "certs"


def _capture(args: list[str]) -> str:
    import subprocess

    result = subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def _extract_table(output: str) -> str:
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("ABLATION"))
    end = next(i for i, line in enumerate(lines[start:], start) if line.startswith("read binding"))
    return "\n".join(lines[start : end + 1]) + "\n"


def _reset_institutional_memory(urn: str) -> None:
    import requests

    from dhdr.coordinate import DEFAULT_BASE_URL

    requests.post(
        f"{DEFAULT_BASE_URL}/openapi/v3/entity/dataset",
        json=[{"urn": urn, "institutionalMemory": {"value": {"elements": []}}}],
        params={"async": "false"},
        timeout=30,
    ).raise_for_status()


def _one_world(label: str, at_ms: int, world) -> tuple[dict, str, CaptureProxy]:
    """Decide once at `at_ms`, writing the record through a JsonlSink."""
    path = EXAMPLES / f"record-{label}.jsonl"
    proxy = CaptureProxy()
    outcome = decide_drop_column(
        proxy,
        Recorder(sink=JsonlSink(str(path)), run_id=f"example-{label}", emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=at_ms,
    )
    record = json.loads(path.read_text().splitlines()[-1])
    (EXAMPLES / f"record-{label}.json").write_text(json.dumps(record, indent=2) + "\n")
    path.unlink()

    cert = certify(record, proxy.reads, requested="C2")
    rendered = (
        f"# {label}: {outcome} against aspect revision v{proxy.reads[0].revision}\n"
        f"# lastObserved={proxy.reads[0].last_observed_ms}\n\n{cert.render()}\n"
    )
    (EXAMPLES / f"certificate-{label}.txt").write_text(rendered)
    return record, outcome, proxy


async def _mcp_flip() -> str:
    """The flagship, through the real MCP server, captured as a transcript."""
    lines = []

    async def settle(state):
        set_consumer_lineage(state)
        for _ in range(25):
            async with McpCaptureProxy() as probe:
                seen = set(lineage_facts((await probe.call_lineage(CONSUMER)).value))
            if seen == set(state):
                return
            await asyncio.sleep(2)
        raise SystemExit("MCP never reflected the seeded lineage — is the GMS lineage cache on?")

    for label, state in (("no consumer yet", []), ("consumer wired up", [TARGET])):
        await settle(state)
        sink = MemorySink()
        async with McpCaptureProxy() as proxy:
            outcome = await decide_drop_column_mcp(
                proxy,
                Recorder(sink=sink, run_id=f"mcp-{label}", emitter="dhdr/0.1.0"),
                TARGET,
                CONSUMER,
            )
        read = proxy.reads[0]
        cert = certify(sink.records[0], proxy.reads, requested="C2")
        lines += [
            f"=== {label} ===",
            f"tool:         {read.tool} (via mcp-server-datahub)",
            f"value_source: {read.value_source}",
            f"outcome:      {outcome}",
            f"revision:     v{read.revision}",
            cert.render(),
            "",
        ]

    lines += [
        "The agent made the identical MCP call both times.",
        "value_source=mcp means it decided on the protocol response, not a re-fetch.",
        "",
    ]
    return "\n".join(lines)


def _sync_hosted_page() -> None:
    """Rewrite the embedded blocks in docs/index.html from the examples.

    The page used to carry hand-pasted copies, which is why it still showed
    placeholder certificate URLs long after the code stopped emitting them. A
    walkthrough that quietly disagrees with the artifacts it claims to show is
    worse than no walkthrough, so it is generated now.
    """
    import html

    page = HOSTED
    text = page.read_text()
    for name in (
        "demo-transcript.txt",
        "mcp-flip.txt",
        "published-institutional-memory.json",
        "ablation.txt",
        "record-then.json",
    ):
        begin, end = f"<!-- begin:{name} -->", f"<!-- end:{name} -->"
        if begin not in text or end not in text:
            raise SystemExit(f"{page} is missing the {name} markers")
        body = html.escape((EXAMPLES / name).read_text().rstrip("\n"))
        head, _, rest = text.partition(begin)
        _, _, tail = rest.partition(end)
        text = f"{head}{begin}\n<pre>{body}</pre>\n{end}{tail}"
    page.write_text(text)


def main() -> int:
    EXAMPLES.mkdir(exist_ok=True)

    # Start from an empty institutional memory so the artifact is deterministic
    # rather than accumulating every previous run of this script.
    _reset_institutional_memory(CONSUMER)

    world = seed_schema_ops()
    record_then, outcome_then, proxy_then = _one_world("then", world.decision_ms, world)
    record_now, outcome_now, proxy_now = _one_world("now", world.after_ms, world)

    # Write-back, through the live MCP path — the same flow `dhdr demo` runs, so
    # the committed artifact is what the demo actually produces rather than a
    # second implementation that could drift from it.
    #
    # The certificate artifacts are written into `docs/certs/`, which GitHub
    # Pages serves, so the URL published into DataHub genuinely resolves for a
    # later reader. Invariant 10 asks for exactly that, and a placeholder domain
    # would satisfy the `https://` check while resolving for nobody.
    decisions = asyncio.run(live_decisions())
    CERTS.mkdir(parents=True, exist_ok=True)
    for decision in decisions:
        (CERTS / f"{decision.decided_at_ms}.json").write_text(
            json.dumps(
                {
                    "outcome": decision.outcome,
                    "revision": decision.revision,
                    "aspect_last_observed_ms": decision.last_observed_ms,
                    "decided_at_ms": decision.decided_at_ms,
                    "capability_class": decision.certificate.cls,
                    "satisfied": decision.certificate.satisfied,
                    "missing": decision.certificate.missing,
                    "certificate": decision.certificate.render(),
                    "record": decision.record,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    published = read_published(CONSUMER)
    (EXAMPLES / "published-institutional-memory.json").write_text(
        json.dumps(published, indent=2) + "\n"
    )

    (EXAMPLES / "mcp-flip.txt").write_text(asyncio.run(_mcp_flip()))

    # The demo transcript and the ablation table, captured rather than retyped —
    # a table in the README that nobody regenerated is a table that drifts.
    # `--no-publish`: this run is for the transcript. Without it the demo publishes a
    # second pair of certificates whose artifacts nobody writes, leaving dangling
    # URLs in institutionalMemory — which is the failure invariant 10 forbids.
    (EXAMPLES / "demo-transcript.txt").write_text(
        _capture(["-m", "dhdr.cli", "demo", "--no-publish"])
    )
    (EXAMPLES / "ablation.txt").write_text(
        _extract_table(_capture(["-m", "pytest", "tests/test_ablation.py", "-s", "-q"]))
    )

    _sync_hosted_page()
    print(f"wrote {len(list(EXAMPLES.iterdir()))} files to {EXAMPLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
