import sys
import time

import pytest
from reckon import MemorySink, Recorder

sys.path.insert(0, "/opt/datahub-decision-records")

from dhdr.coordinate import resolve_at  # noqa: E402
from dhdr.proxy import CaptureProxy  # noqa: E402
from fixtures.seed import (  # noqa: E402
    CONSUMER,
    TARGET,
    seed_schema_ops,
    set_consumer_lineage,
)


@pytest.mark.integration
def test_seeded_world_has_two_distinguishable_states():
    world = seed_schema_ops()

    at_decision = resolve_at(world.consumer_urn, "upstreamlineage", world.decision_ms)
    at_after = resolve_at(world.consumer_urn, "upstreamlineage", world.after_ms)

    assert at_decision is not None
    assert at_after is not None
    assert len(at_decision.value.get("upstreams", [])) == 0
    assert len(at_after.value.get("upstreams", [])) == 1
    assert at_decision.version != at_after.version


@pytest.mark.integration
def test_same_input_opposite_outcomes_across_revisions():
    """The finding, executable: identical call, opposite decisions."""
    from scenarios.schema_ops import decide_drop_column

    world = seed_schema_ops()

    proxy_then = CaptureProxy()
    outcome_then = decide_drop_column(
        proxy_then,
        Recorder(sink=MemorySink(), run_id="run-then", emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=world.decision_ms,
    )

    proxy_now = CaptureProxy()
    outcome_now = decide_drop_column(
        proxy_now,
        Recorder(sink=MemorySink(), run_id="run-now", emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=world.after_ms,
    )

    assert outcome_then == "admit"
    assert outcome_now == "reject"
    assert proxy_then.reads[0].revision != proxy_now.reads[0].revision


@pytest.mark.integration
def test_record_carries_the_revision():
    from scenarios.schema_ops import decide_drop_column

    world = seed_schema_ops()
    sink = MemorySink()
    decide_drop_column(
        proxy := CaptureProxy(),
        Recorder(sink=sink, run_id="r", emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=world.decision_ms,
    )
    record = sink.records[0]
    assert record["policy"]["resolution"]["revision"] == str(proxy.reads[0].revision)


@pytest.mark.integration
def test_unresolved_read_claims_no_revision():
    """Invariant 5 carried into the record: a read that bound to nothing must
    not leave a revision string on the policy, and must not claim `bundled`
    provenance for a threshold applied to a world we cannot date."""
    from scenarios.schema_ops import decide_drop_column

    sink = MemorySink()
    decide_drop_column(
        CaptureProxy(),
        Recorder(sink=sink, run_id="r", emitter="dhdr/0.1.0"),
        TARGET,
        CONSUMER,
        at_ms=1,
    )
    resolution = sink.records[0]["policy"]["resolution"]
    # RCDR omits the key rather than writing a null. Absence is still
    # distinguishable from a captured empty value, which is what invariant 5
    # requires; what must never appear is a revision the read did not earn.
    assert "revision" not in resolution
    assert resolution["provenance"] == "unknown"


async def _settle_mcp_lineage(upstreams: list[str], timeout_s: float = 45.0) -> None:
    """Move the world and wait until MCP actually reports the new state.

    Writing the aspect is not enough: the edge has to reach the graph index and
    then the lineage query, which takes a few seconds. This is world setup, not
    part of the assertion — the decision below reads the world again for itself.

    It only converges because GMS's lineage cache is switched off in
    `/opt/datahub-probe/docker-compose.override.yml`. With the shipped default
    TTL a lineage change stays invisible to MCP for hours, and this loop times
    out rather than passing on stale context.
    """
    import asyncio

    from dhdr.coordinate import lineage_facts
    from dhdr.proxy import McpCaptureProxy

    want = set(upstreams)
    set_consumer_lineage(upstreams)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        async with McpCaptureProxy() as probe:
            seen = set(lineage_facts((await probe.call_lineage(CONSUMER)).value))
        if seen == want:
            return
        await asyncio.sleep(2)
    raise AssertionError(
        f"MCP never reported lineage {want} within {timeout_s}s (saw {seen})"
    )


@pytest.mark.integration
async def test_agent_decides_through_real_mcp_and_flips():
    """The flagship: the agent's input is the live MCP response, and the same
    `get_lineage` call decides both ways as the world moves under it."""
    from dhdr.proxy import McpCaptureProxy
    from scenarios.schema_ops import decide_drop_column_mcp

    await _settle_mcp_lineage([])
    async with McpCaptureProxy() as proxy_then:
        sink_then = MemorySink()
        outcome_then = await decide_drop_column_mcp(
            proxy_then,
            Recorder(sink=sink_then, run_id="mcp-then", emitter="dhdr/0.1.0"),
            TARGET,
            CONSUMER,
        )

    await _settle_mcp_lineage([TARGET])
    async with McpCaptureProxy() as proxy_now:
        sink_now = MemorySink()
        outcome_now = await decide_drop_column_mcp(
            proxy_now,
            Recorder(sink=sink_now, run_id="mcp-now", emitter="dhdr/0.1.0"),
            TARGET,
            CONSUMER,
        )

    assert outcome_then == "admit"
    assert outcome_now == "reject"
    assert proxy_then.reads[0].value_source == "mcp"
    assert proxy_now.reads[0].value_source == "mcp"
    assert proxy_then.reads[0].revision != proxy_now.reads[0].revision
    assert (
        sink_then.records[0]["policy"]["resolution"]["revision"]
        != sink_now.records[0]["policy"]["resolution"]["revision"]
    )
