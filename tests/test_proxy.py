import pytest

from dhdr.proxy import CapturedRead, CaptureProxy

URN = "urn:li:dataset:(urn:li:dataPlatform:hive,probe_orders2,PROD)"


@pytest.mark.integration
def test_call_captures_the_revision():
    proxy = CaptureProxy()
    read = proxy.call("get_lineage", URN, "upstreamlineage")
    assert isinstance(read, CapturedRead)
    assert read.resolved is True
    assert read.revision is not None
    assert read.last_observed_ms > 0
    assert proxy.reads == [read]


@pytest.mark.integration
def test_call_at_past_instant_returns_past_world():
    proxy = CaptureProxy()
    latest = proxy.call("get_lineage", URN, "upstreamlineage")
    earliest_stamp = min(r.last_observed_ms for r in proxy.reads)
    past = proxy.call("get_lineage", URN, "upstreamlineage", at_ms=earliest_stamp)
    assert past.revision <= latest.revision


@pytest.mark.integration
def test_unresolvable_read_is_recorded_as_absence_not_as_now():
    """Invariant 5: absence of evidence is recorded as absence."""
    proxy = CaptureProxy()
    read = proxy.call("get_lineage", URN, "upstreamlineage", at_ms=1)
    assert read.resolved is False
    assert read.revision is None
    assert read.value == {}


# A real datapack dataset whose declared upstreams all exist as entities, so
# MCP's entity-resolved view and the aspect's declared view agree.
DBT_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:dbt,"
    "b2fd91.ORDER_ENTRY_DB.analytics.order_details,PROD)"
)


@pytest.mark.integration
async def test_mcp_response_is_the_decision_input():
    """Invariant 7: the agent decides on what MCP returned, not a re-fetch."""
    from dhdr.proxy import McpCaptureProxy

    async with McpCaptureProxy() as proxy:
        read = await proxy.call_lineage(DBT_URN)

    assert read.tool == "get_lineage"
    assert read.mcp_response is not None
    assert read.value_source == "mcp"
    assert read.response_received_ms > 0
    assert read.value is read.mcp_response


@pytest.mark.integration
async def test_mcp_response_carries_no_version_coordinate():
    """The finding, asserted precisely rather than by substring search."""
    from dhdr.proxy import McpCaptureProxy

    async with McpCaptureProxy() as proxy:
        read = await proxy.call_lineage(DBT_URN)

    payload = read.mcp_response
    assert isinstance(payload, dict)
    forbidden = {"version", "systemMetadata", "aspectVersion", "lastObserved"}
    assert not (forbidden & set(payload.keys()))
    assert not (forbidden & set(payload.get("upstreams", {}).keys()))


@pytest.mark.integration
def test_mismatched_payload_is_unbound_not_guessed():
    """Invariant 8: a payload belonging to no visible revision binds to nothing.

    This is the race the adapter exists for — metadata moving between the
    agent's read and ours. The honest answer is 'unbound', never the
    nearest-by-timestamp guess.
    """
    from dhdr.coordinate import bind_revision

    impossible = {
        "upstreams": [
            {"dataset": "urn:li:dataset:(urn:li:dataPlatform:hive,does_not_exist,PROD)"}
        ]
    }
    assert bind_revision(URN, "upstreamlineage", impossible, 9_999_999_999_999) is None


@pytest.mark.integration
def test_binding_matches_the_real_revision():
    """The positive case: facts that DO belong to a revision bind to it."""
    from dhdr.coordinate import bind_revision, history

    revisions = history(URN, "upstreamlineage")
    target = revisions[0]
    bound = bind_revision(
        URN, "upstreamlineage", target.value, target.last_observed_ms
    )
    assert bound is not None
    assert bound.version == target.version
