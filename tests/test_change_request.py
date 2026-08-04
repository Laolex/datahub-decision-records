import sys

import pytest
from reckon import MemorySink, Recorder

sys.path.insert(0, "/opt/datahub-decision-records")

from dhdr.proxy import CaptureProxy  # noqa: E402
from fixtures.seed import CONSUMER, TARGET, seed_schema_ops  # noqa: E402
from scenarios.schema_ops import (  # noqa: E402
    ChangeRequest,
    decide_drop_column,
    proposed_change,
)


def test_admitted_decision_proposes_the_drop():
    change = proposed_change(TARGET, "promo_code", outcome="admit", consumers=())
    assert change.kind == "drop_column"
    assert "ALTER TABLE" in change.statement
    assert "b2fd91.order_entry_db.order_entry.orders" in change.statement
    assert "DROP COLUMN promo_code" in change.statement


def test_rejected_decision_proposes_deprecation_instead_of_a_drop():
    """A refusal still has to do work. Returning "no" and stopping leaves the
    engineer exactly where they started."""
    change = proposed_change(
        TARGET, "promo_code", outcome="reject", consumers=(CONSUMER,)
    )
    assert change.kind == "deprecate_column"
    assert "DROP COLUMN" not in change.statement
    assert "order_history" in change.render()


def test_the_artifact_is_proposed_and_never_applied():
    """Invariant of scope, not of soundness: `dhdr` decides and records. It does
    not run migrations, and the artifact must not be mistakable for one that ran."""
    change = proposed_change(TARGET, "promo_code", outcome="admit", consumers=())
    assert change.applied is False
    assert "proposed" in change.render().lower()
    assert not hasattr(change, "apply")
    assert not hasattr(change, "execute")


def test_change_request_is_a_value_not_a_side_effect():
    change = proposed_change(TARGET, "promo_code", outcome="admit", consumers=())
    assert isinstance(change, ChangeRequest)


@pytest.mark.integration
def test_the_record_binds_the_change_it_decided_about():
    """RCDR commits to the action's params by digest rather than copying them.

    That is the better arrangement: the record proves *which* change it decided
    about without duplicating a payload that could then drift from it. So the
    assertion is that the binding exists and moves when the change moves — not
    that the record carries the DDL, which it deliberately does not.
    """
    world = seed_schema_ops()

    def digest_for(column: str) -> str:
        sink = MemorySink()
        decide_drop_column(
            CaptureProxy(),
            Recorder(sink=sink, run_id=f"change-{column}", emitter="dhdr/0.1.0"),
            world.target_urn,
            world.consumer_urn,
            at_ms=world.decision_ms,
            column=column,
        )
        return sink.records[0]["action"]["params_digest"]

    promo = digest_for("promo_code")
    assert promo.startswith("sha256:")
    # A different proposed change is a different decision, and the record says so.
    assert promo != digest_for("customer_email")
    # The same proposed change is the same commitment.
    assert promo == digest_for("promo_code")
