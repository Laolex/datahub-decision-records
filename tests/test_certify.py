import sys

import pytest

sys.path.insert(0, "/opt/datahub-decision-records")

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
