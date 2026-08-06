import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dhdr.certify import certify  # noqa: E402
from dhdr.proxy import CapturedRead  # noqa: E402

BOUND = CapturedRead(
    "get_lineage", "urn:x", "upstreamlineage", 2, 1785762999915, {"upstreams": []}, True
)
UNBOUND = CapturedRead("get_lineage", "urn:x", "upstreamlineage", None, None, {}, False)


def _record(**over):
    base = {
        "execution": {
            "runtime": "cpython-3.12",
            "deps_digest": "d",
            "path_digest": "p",
            "pure": True,
        },
        "predicate": {"id": "pred-1"},
        "compared": {"value": 0},
        "policy": {
            "resolved_value": 0,
            "resolution": {"provenance": "bundled", "revision": "2"},
        },
        "candidates": {
            "completeness": "exhaustive",
            "items": [{"compared_value": 0}, {"compared_value": 1}],
        },
    }
    base.update(over)
    return base


def test_full_record_certifies_c2():
    cert = certify(_record(), [BOUND], requested="C2")
    assert cert.cls == "C2"
    assert cert.satisfied is True
    assert cert.unbound_reads == 0


def test_unbound_read_collapses_the_class_entirely():
    """Not 'C2 with a warning' — no class at all. A hurried reader must not be
    able to mistake a degraded certificate for a passing one."""
    cert = certify(_record(), [BOUND, UNBOUND], requested="C2")
    assert cert.unbound_reads == 1
    assert cert.cls is None
    assert cert.satisfied is False
    rendered = cert.render()
    assert "Capability class: none" in rendered
    assert "UNSOUND" in rendered
    assert "C2" not in rendered.splitlines()[0]


def test_c3_is_a_boundary_never_a_pass():
    cert = certify(_record(), [BOUND], requested="C3")
    assert cert.satisfied is False
    assert cert.c3_boundary is not None


def test_certificate_never_reports_a_percentage():
    rendered = certify(_record(), [BOUND], requested="C2").render()
    assert "%" not in rendered


OTHER_DECISIONS_READ = CapturedRead(
    "get_lineage", "urn:x", "upstreamlineage", 99, 1785762999999, {"upstreams": []}, True
)


def test_reads_from_another_decision_are_refused_not_certified():
    """The record names the revision it was decided against. If no read supplied
    that revision, these two arguments did not come from the same decision, and
    certifying them would produce a clean-looking certificate over a pairing
    that never happened.

    This is the one way the whole design can be defeated from the caller's side:
    every individual piece is honest, and the assembly is wrong.
    """
    from dhdr.certify import MISPAIRED_READS

    cert = certify(_record(), [OTHER_DECISIONS_READ], requested="C2")
    assert cert.cls is None
    assert cert.satisfied is False
    assert MISPAIRED_READS in cert.missing
    assert "Capability class: none" in cert.render()


def test_a_matching_revision_still_certifies():
    """The guard must not reject the ordinary case: the record's revision is v2
    and one of the reads bound to v2."""
    cert = certify(_record(), [BOUND, OTHER_DECISIONS_READ], requested="C2")
    assert cert.cls == "C2"


def test_a_record_with_no_revision_is_not_checked_for_pairing():
    """An unbound decision omits the revision key entirely. There is nothing to
    match against, and the unbound read has already collapsed the class — this
    must not be reported as a *second*, different failure."""
    from dhdr.certify import MISPAIRED_READS

    record = _record(policy={"resolved_value": 0, "resolution": {"provenance": "unknown"}})
    cert = certify(record, [UNBOUND], requested="C2")
    assert cert.cls is None
    assert MISPAIRED_READS not in cert.missing


def test_self_write_boundary_comes_from_evidence_not_assertion():
    """The agent publishing its own certificate is a state mutation a later
    decision may read. That boundary must follow from a write that demonstrably
    happened — a `published=True` flag from the caller is an assertion about the
    world, not evidence from it (invariant 11)."""
    from dhdr.certify import SELF_WRITE_BOUNDARY

    # no publish event -> no boundary claimed
    assert SELF_WRITE_BOUNDARY not in certify(_record(), [BOUND], requested="C2").missing

    event = {
        "urn": "urn:x",
        "aspect": "institutionalMemory",
        "url": "https://example.org/cert/1",
        "at_ms": 1,
    }
    cert = certify(_record(), [BOUND], requested="C2", publish_events=[event])
    assert SELF_WRITE_BOUNDARY in cert.missing
    assert SELF_WRITE_BOUNDARY in cert.render()


def test_an_empty_publish_event_list_claims_no_boundary():
    """An empty list is evidence that nothing was written, not evidence of a
    write. Treating "the parameter was passed" as the trigger would reintroduce
    exactly the caller-assertion this is meant to exclude."""
    from dhdr.certify import SELF_WRITE_BOUNDARY

    cert = certify(_record(), [BOUND], requested="C2", publish_events=[])
    assert SELF_WRITE_BOUNDARY not in cert.missing


@pytest.mark.integration
def test_certifies_a_record_the_agent_actually_produced():
    """The handcrafted records above fix the certifier's contract. This one
    checks the contract is the same shape the agent emits — a certifier that
    only ever certifies its own fixtures has proven nothing."""
    from reckon import MemorySink, Recorder

    from dhdr.proxy import CaptureProxy
    from fixtures.seed import seed_schema_ops
    from scenarios.schema_ops import decide_drop_column

    world = seed_schema_ops()
    sink = MemorySink()
    proxy = CaptureProxy()
    decide_drop_column(
        proxy,
        Recorder(sink=sink, run_id="cert", emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=world.decision_ms,
    )

    cert = certify(sink.records[0], proxy.reads, requested="C2")
    assert cert.unbound_reads == 0
    assert cert.cls == "C2"
    assert "%" not in cert.render()
