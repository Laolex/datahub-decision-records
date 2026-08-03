import pytest

from dhdr.coordinate import AspectVersion, history, read_aspect, resolve_at

URN = "urn:li:dataset:(urn:li:dataPlatform:hive,probe_orders2,PROD)"


@pytest.mark.integration
def test_read_aspect_returns_version_and_stamp():
    av = read_aspect(URN, "upstreamlineage", version=1)
    assert isinstance(av, AspectVersion)
    assert av.version == 1
    assert av.last_observed_ms > 0
    assert "upstreams" in av.value


@pytest.mark.integration
def test_history_is_ascending_and_stamped():
    revisions = history(URN, "upstreamlineage")
    assert len(revisions) >= 2
    assert [r.version for r in revisions] == sorted(r.version for r in revisions)
    stamps = [r.last_observed_ms for r in revisions]
    assert stamps == sorted(stamps)


@pytest.mark.integration
def test_resolve_at_returns_the_world_as_it_stood():
    revisions = history(URN, "upstreamlineage")
    first, second = revisions[0], revisions[1]
    midpoint = (first.last_observed_ms + second.last_observed_ms) // 2

    at_midpoint = resolve_at(URN, "upstreamlineage", midpoint)
    assert at_midpoint is not None
    assert at_midpoint.version == first.version
    # the decisive property: fewer upstreams before the edge was added
    assert len(at_midpoint.value["upstreams"]) < len(second.value["upstreams"])


@pytest.mark.integration
def test_resolve_before_existence_is_none():
    """Absence is a real answer, not a failure (invariant 5)."""
    revisions = history(URN, "upstreamlineage")
    assert resolve_at(URN, "upstreamlineage", revisions[0].last_observed_ms - 1) is None
