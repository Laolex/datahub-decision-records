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
def test_history_survives_retention_pruning_of_early_versions():
    """DataHub's retention deletes the oldest versions of a busy aspect.

    An aspect at version 42 whose versions 1..21 have been pruned still has 21
    readable revisions. Scanning upward from 1 and stopping at the first gap
    reports that aspect as having no history at all, and every decision made
    against it then binds to nothing — the adapter silently failing exactly when
    the instance has been alive long enough to matter.
    """
    urn = (
        "urn:li:dataset:(urn:li:dataPlatform:snowflake,"
        "b2fd91.order_entry_db.analytics.order_history,PROD)"
    )
    latest = read_aspect(urn, "upstreamlineage", version=0)
    assert latest.version > 1, "fixture requires an aspect with several revisions"

    with pytest.raises(Exception):
        read_aspect(urn, "upstreamlineage", version=1)

    revisions = history(urn, "upstreamlineage")
    assert revisions, "pruned early versions must not erase the whole history"
    assert max(r.version for r in revisions) == latest.version


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
