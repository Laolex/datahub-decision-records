import sys

import pytest

sys.path.insert(0, "/opt/datahub-decision-records")

from dhdr.coordinate import resolve_at  # noqa: E402
from fixtures.seed import seed_schema_ops  # noqa: E402


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
