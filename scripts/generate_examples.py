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
from dhdr.publish import publish_certificate, read_published  # noqa: E402
from fixtures.seed import (  # noqa: E402
    CONSUMER,
    TARGET,
    seed_schema_ops,
    set_consumer_lineage,
)
from scenarios.schema_ops import decide_drop_column, decide_drop_column_mcp  # noqa: E402

EXAMPLES = REPO / "examples"


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


def main() -> int:
    EXAMPLES.mkdir(exist_ok=True)

    # Start from an empty institutional memory so the artifact is deterministic
    # rather than accumulating every previous run of this script.
    _reset_institutional_memory(CONSUMER)

    world = seed_schema_ops()
    record_then, outcome_then, proxy_then = _one_world("then", world.decision_ms, world)
    record_now, outcome_now, proxy_now = _one_world("now", world.after_ms, world)

    # Write-back: what a later reader inherits. The certificate, the outcome and
    # the revision all come from the decision that was just made — publishing a
    # different revision than the one that decided is the exact substitution
    # invariant 7 exists to forbid.
    events: list[dict] = []
    for record, outcome, proxy, at_ms in (
        (record_then, outcome_then, proxy_then, world.decision_ms),
        (record_now, outcome_now, proxy_now, world.after_ms),
    ):
        publish_certificate(
            world.consumer_urn,
            certify(record, proxy.reads, requested="C2"),
            outcome=outcome,
            revision=proxy.reads[0].revision,
            decided_at_ms=at_ms,
            certificate_url=f"https://example.org/certs/{at_ms}.json",
            events=events,
        )
    published = read_published(world.consumer_urn)
    (EXAMPLES / "published-institutional-memory.json").write_text(
        json.dumps(published, indent=2) + "\n"
    )

    (EXAMPLES / "mcp-flip.txt").write_text(asyncio.run(_mcp_flip()))

    # The demo transcript and the ablation table, captured rather than retyped —
    # a table in the README that nobody regenerated is a table that drifts.
    (EXAMPLES / "demo-transcript.txt").write_text(_capture(["-m", "dhdr.cli"]))
    (EXAMPLES / "ablation.txt").write_text(
        _extract_table(_capture(["-m", "pytest", "tests/test_ablation.py", "-s", "-q"]))
    )

    print(f"wrote {len(list(EXAMPLES.iterdir()))} files to {EXAMPLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
