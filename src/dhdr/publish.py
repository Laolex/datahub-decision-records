"""Write the decision certificate back into DataHub.

Invariant 6: a decision that is not published is not inherited. The next agent
or engineer to touch this dataset should find what was decided, against which
revision, and how far the evidence went — without rerunning anything.

`institutionalMemory` is used because it exists on every dataset in OSS Core and
needs no custom aspect model.

**On atomicity, plainly.** Invariant 10 asks for a version-checked write so a
concurrent writer's entry is never lost. On DataHub Core v1.5.0.6 that is not
achievable for this aspect, and pretending otherwise would be the exact failure
this project exists to avoid. Two mechanisms were tried and both are closed:

- `If-Version-Match` is documented as an optimistic-concurrency precondition on
  writes, but the write endpoint does not enforce it. A write carrying a stale
  version returns 200 and overwrites. A retry loop built on it would look
  careful and do nothing.
- Server-side JSON patch has no template registered for `institutionalMemory`
  (the request fails with a null template). Templates exist for `globalTags` and
  `upstreamLineage`, so this is a per-aspect gap, not a missing feature.

What this module does instead is read-append-write with a verified read-back: it
carries forward every element it saw, and retries if its own element did not
land. That preserves any entry written *before* our read, and detects being
clobbered ourselves. It does **not** close the true race — an element written by
someone else between our read and our write is still lost, and no code on this
side of the API can prevent that. The honest scope is "last write wins, with the
loser detected and repaired", not "atomic append".

Registering an `institutionalMemory` patch template upstream is what would
actually fix it, which is why it is the upstream contribution in Task 7b.
"""

import time
import urllib.parse

from .certify import Certificate
from .coordinate import default_base_url, entity_type_of, session

ACTOR = "urn:li:corpuser:datahub"
MAX_ATTEMPTS = 5
#: Base for the exponential backoff between attempts. Retrying a contended write
#: immediately is how a retry loop becomes the contention it is retrying past:
#: every loser re-reads and re-writes in lockstep with every other loser.
RETRY_BACKOFF_S = 0.1


def _certificate_line(cert: Certificate, outcome: str, revision: int | None) -> str:
    revision_text = f"v{revision}" if revision is not None else "unbound revision"
    if cert.cls is None or cert.unbound_reads:
        first_line = cert.render().splitlines()[0]
        return f"decision={outcome} against {revision_text} — UNSOUND: {first_line}"
    return f"decision={outcome} against {revision_text} — class {cert.cls}"


def _aspect_url(urn: str, base_url: str | None = None) -> str:
    base_url = base_url or default_base_url()
    enc = urllib.parse.quote(urn, safe="")
    return f"{base_url}/openapi/v3/entity/{entity_type_of(urn)}/{enc}/institutionalMemory"


def _read_with_version(urn: str, *, base_url: str | None = None) -> dict:
    """Current institutional memory plus the aspect version it was read at.

    The v3 endpoint is used deliberately. The v2 single-aspect GET returns 400
    for this aspect on Core v1.5.0.6 — it fails to deserialise its own
    `SystemMetadata` — and code that treats a 4xx here as "nothing published"
    would drop every existing element on the next write.
    """
    response = session().get(
        _aspect_url(urn, base_url), params={"systemMetadata": "true"}, timeout=30
    )
    if response.status_code == 404:
        return {"value": {}, "version": None}
    response.raise_for_status()
    body = response.json()
    raw = (body.get("systemMetadata") or {}).get("version")
    return {"value": body.get("value") or {}, "version": int(raw) if raw else None}


def read_published(urn: str, *, base_url: str | None = None) -> dict | None:
    """What a later reader inherits. None when nothing was ever published."""
    response = session().get(_aspect_url(urn, base_url), timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("value")


def publish_certificate(
    urn: str,
    cert: Certificate,
    *,
    outcome: str,
    revision: int | None,
    decided_at_ms: int,
    certificate_url: str,
    base_url: str | None = None,
    events: list[dict] | None = None,
) -> str:
    """Append the certificate to institutional memory, preserving what was there.

    `certificate_url` must be a resolvable HTTPS URL to the published artifact. A
    `dhdr://` scheme resolves for nobody, and institutional memory a later human
    cannot open is not memory (invariant 10). The description is a summary; the
    URL is the certificate.

    If `events` is given, one event is appended to it per successful write, and
    nothing is appended on refusal or failure. The certifier derives the C3
    self-write boundary from those events rather than from a flag the caller
    passed, so they have to be produced by the write itself (invariant 11).

    See the module docstring for what this does and does not guarantee about
    concurrent writers.
    """
    if not certificate_url.startswith("https://"):
        raise ValueError(
            f"certificate_url must be resolvable HTTPS, got {certificate_url!r}. "
            "A later reader must be able to open the certificate, not just read a summary."
        )

    base_url = base_url or default_base_url()
    element = {
        "url": certificate_url,
        "description": _certificate_line(cert, outcome, revision),
        "createStamp": {"time": decided_at_ms, "actor": ACTOR},
    }

    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_BACKOFF_S * 2 ** (attempt - 1))
        current = _read_with_version(urn, base_url=base_url)
        elements = [
            e
            for e in (current["value"] or {}).get("elements", [])
            if e.get("url") != certificate_url
        ]
        elements.append(element)

        response = session().post(
            f"{base_url}/openapi/v3/entity/{entity_type_of(urn)}",
            json=[{"urn": urn, "institutionalMemory": {"value": {"elements": elements}}}],
            params={"async": "false"},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()

        # Read back rather than trusting the 200. A concurrent writer that
        # overwrote us between our write and this read is the case worth
        # catching, and it is the only side of the race we can observe.
        landed = (read_published(urn, base_url=base_url) or {}).get("elements", [])
        if any(e.get("url") == certificate_url for e in landed):
            if events is not None:
                events.append(
                    {
                        "urn": urn,
                        "aspect": "institutionalMemory",
                        "url": certificate_url,
                        "at_ms": decided_at_ms,
                    }
                )
            return certificate_url

    raise RuntimeError(
        f"could not publish to {urn} after {MAX_ATTEMPTS} attempts under contention"
    )
