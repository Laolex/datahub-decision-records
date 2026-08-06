import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dhdr.certify import Certificate  # noqa: E402
from dhdr.publish import (  # noqa: E402
    _read_with_version,
    publish_certificate,
    read_published,
)

URN = "urn:li:dataset:(urn:li:dataPlatform:hive,probe_orders2,PROD)"
BASE = "http://localhost:8080"


@pytest.mark.integration
def test_certificate_is_inherited_by_the_next_reader():
    cert = Certificate("C2", True)
    url = publish_certificate(
        URN,
        cert,
        outcome="reject",
        revision=2,
        decided_at_ms=1785762999915,
        certificate_url="https://example.org/cert/1785762999915.json",
    )
    assert url.startswith("https://")

    published = read_published(URN)
    assert published is not None
    descriptions = [e["description"] for e in published["elements"]]
    assert any("C2" in d and "reject" in d and "v2" in d for d in descriptions)
    # the artifact itself is reachable, not just summarised
    assert any(e["url"].startswith("https://") for e in published["elements"])


@pytest.mark.integration
def test_unsound_certificate_says_so_in_what_it_publishes():
    """Invariant 5 survives the round trip: absence stays visible."""
    cert = Certificate(None, False, unbound_reads=1)
    publish_certificate(
        URN,
        cert,
        outcome="reject",
        revision=None,
        decided_at_ms=1,
        certificate_url="https://example.org/cert/1.json",
    )
    published = read_published(URN)
    assert any("unsound" in e["description"].lower() for e in published["elements"])


@pytest.mark.integration
def test_unresolvable_scheme_is_refused():
    """dhdr:// resolves for nobody. Memory a human cannot open is not memory."""
    with pytest.raises(ValueError, match="resolvable HTTPS"):
        publish_certificate(
            URN,
            Certificate("C2", True),
            outcome="admit",
            revision=1,
            decided_at_ms=1,
            certificate_url="dhdr://decision/1",
        )


@pytest.mark.integration
def test_publish_preserves_an_element_written_before_it():
    """An entry already in institutional memory must survive our append.

    Note what this does and does not prove. It writes the other element
    *before* `publish_certificate` reads, so the read-append-write cycle sees it
    and carries it forward. It does not prove atomicity: see
    `test_datahub_offers_no_atomic_append_for_institutional_memory` for the race
    that remains open on this DataHub version.
    """
    baseline = len((read_published(URN) or {}).get("elements", []))

    other = {
        "url": "https://example.invalid/other",
        "description": "other writer",
        "createStamp": {"time": 1, "actor": "urn:li:corpuser:datahub"},
    }
    existing = list((read_published(URN) or {}).get("elements", []))
    requests.post(
        f"{BASE}/openapi/v3/entity/dataset",
        json=[
            {
                "urn": URN,
                "institutionalMemory": {"value": {"elements": existing + [other]}},
            }
        ],
        params={"async": "false"},
        timeout=30,
    ).raise_for_status()

    publish_certificate(
        URN,
        Certificate("C2", True),
        outcome="admit",
        revision=2,
        decided_at_ms=2,
        certificate_url="https://example.org/cert/2",
    )

    urls = [e["url"] for e in read_published(URN)["elements"]]
    assert "https://example.invalid/other" in urls, "concurrent writer's element was lost"
    assert "https://example.org/cert/2" in urls
    assert len(urls) >= baseline + 2


@pytest.mark.integration
def test_publish_records_an_event_only_when_the_write_succeeded():
    """The certifier derives the C3 self-write boundary from this event, so it
    has to be produced by a successful write and by nothing else."""
    events: list[dict] = []
    publish_certificate(
        URN,
        Certificate("C2", True),
        outcome="admit",
        revision=3,
        decided_at_ms=3,
        certificate_url="https://example.org/cert/3",
        events=events,
    )
    assert len(events) == 1
    assert events[0]["aspect"] == "institutionalMemory"
    assert events[0]["url"] == "https://example.org/cert/3"
    assert events[0]["urn"] == URN
    assert events[0]["at_ms"] > 0

    refused: list[dict] = []
    with pytest.raises(ValueError):
        publish_certificate(
            URN,
            Certificate("C2", True),
            outcome="admit",
            revision=3,
            decided_at_ms=3,
            certificate_url="dhdr://nope",
            events=refused,
        )
    assert refused == [], "a refused publish must not leave evidence of a write"


@pytest.mark.integration
def test_datahub_offers_no_atomic_append_for_institutional_memory():
    """Pins the platform gap this module has to work around.

    Two mechanisms could make the append atomic, and on DataHub Core v1.5.0.6
    neither is available for this aspect:

    1. `If-Version-Match` is documented as an optimistic-concurrency
       precondition, but the write endpoint does not enforce it — a write
       carrying a stale version succeeds and overwrites.
    2. Server-side JSON patch has no template registered for
       `institutionalMemory`, so a patch request fails with a null template.
       Templates *do* exist for `globalTags` and `upstreamLineage`, so this is a
       per-aspect gap rather than the feature being absent.

    When either of these starts working, this test fails — and
    `publish_certificate` should be simplified to use it.
    """
    import urllib.parse

    enc = urllib.parse.quote(URN, safe="")

    stale = _read_with_version(URN)["version"]
    element = {
        "url": "https://example.invalid/precondition-probe",
        "description": "probe",
        "createStamp": {"time": 1, "actor": "urn:li:corpuser:datahub"},
    }
    body = [{"urn": URN, "institutionalMemory": {"value": {"elements": [element]}}}]

    # bump the version so `stale` really is stale
    requests.post(
        f"{BASE}/openapi/v3/entity/dataset", json=body, params={"async": "false"}, timeout=30
    ).raise_for_status()

    clobber = requests.post(
        f"{BASE}/openapi/v3/entity/dataset",
        json=[
            {
                "urn": URN,
                "institutionalMemory": {
                    "value": {"elements": [dict(element, description="clobbered")]}
                },
            }
        ],
        params={"async": "false"},
        headers={"If-Version-Match": str(stale)},
        timeout=30,
    )
    assert clobber.status_code == 200, (
        "If-Version-Match is now enforced — publish_certificate can become atomic"
    )

    patched = requests.patch(
        f"{BASE}/openapi/v3/entity/dataset/{enc}/institutionalMemory",
        json={"patch": [{"op": "add", "path": "/elements/x", "value": {}}]},
        params={"async": "false"},
        timeout=30,
    )
    assert patched.status_code == 500, (
        "institutionalMemory now has a patch template — use it instead of read-modify-write"
    )
