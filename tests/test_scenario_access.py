import sys
from pathlib import Path

import pytest
from reckon import MemorySink, Recorder

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dhdr.certify import certify  # noqa: E402
from dhdr.proxy import CaptureProxy  # noqa: E402
from fixtures.seed import seed_access  # noqa: E402
from scenarios.access import decide_grant_access  # noqa: E402


@pytest.mark.integration
def test_access_flips_when_the_term_is_applied():
    world = seed_access()

    proxy_before = CaptureProxy()
    before = decide_grant_access(
        proxy_before,
        Recorder(sink=MemorySink(), run_id="before", emitter="dhdr/0.1.0"),
        world.dataset_urn,
        at_ms=world.decision_ms,
    )

    proxy_after = CaptureProxy()
    after = decide_grant_access(
        proxy_after,
        Recorder(sink=MemorySink(), run_id="after", emitter="dhdr/0.1.0"),
        world.dataset_urn,
        at_ms=world.after_ms,
    )

    assert before == "admit"
    assert after == "reject"
    assert proxy_before.reads[0].revision != proxy_after.reads[0].revision


@pytest.mark.integration
def test_access_decision_certifies_against_its_own_revision():
    """The second scenario must be certifiable by the *unmodified* certifier.

    If a new domain needs the core or the certifier changed to accommodate it,
    invariant 4 is broken and the change belongs in the core rather than the
    scenario. This asserts the second domain rides the same machinery.
    """
    world = seed_access()
    sink = MemorySink()
    proxy = CaptureProxy()
    decide_grant_access(
        proxy,
        Recorder(sink=sink, run_id="cert", emitter="dhdr/0.1.0"),
        world.dataset_urn,
        at_ms=world.after_ms,
    )

    cert = certify(sink.records[0], proxy.reads, requested="C2")
    assert cert.cls == "C2"
    assert cert.unbound_reads == 0
    assert "%" not in cert.render()


@pytest.mark.integration
def test_access_read_that_cannot_be_dated_certifies_nothing():
    """Same refusal as scenario 1, from the same code path."""
    world = seed_access()
    sink = MemorySink()
    proxy = CaptureProxy()
    decide_grant_access(
        proxy,
        Recorder(sink=sink, run_id="unbound", emitter="dhdr/0.1.0"),
        world.dataset_urn,
        at_ms=1,
    )

    cert = certify(sink.records[0], proxy.reads, requested="C2")
    assert cert.cls is None
    assert cert.unbound_reads == 1
