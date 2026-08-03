"""Resolution of DataHub aspect revisions.

DataHub's MCP surface exposes no version coordinate: every read resolves to
"now". The platform stores one regardless. Version 0 is the sentinel for
latest; 1..N are the archived revisions, 1 being the oldest.

`If-Version-Match` on the v3 batchGet is an HTTP precondition for *writes*
(optimistic concurrency), NOT a version selector for reads. Version selection
is a query parameter on the v2 single-aspect GET. Conflating the two produces a
false negative — it did once, during the probe that established this module.
"""

import urllib.parse
from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "http://localhost:8080"


@dataclass(frozen=True)
class AspectVersion:
    """One revision of one aspect, with the stamp that dates it."""

    version: int
    last_observed_ms: int
    value: dict


def read_aspect(
    urn: str,
    aspect: str,
    *,
    version: int = 0,
    base_url: str = DEFAULT_BASE_URL,
) -> AspectVersion:
    """Read one aspect pinned to one revision. version=0 means latest."""
    enc = urllib.parse.quote(urn, safe="")
    response = requests.get(
        f"{base_url}/openapi/v2/entity/dataset/{enc}/{aspect.lower()}",
        params={"version": version, "systemMetadata": "true"},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    system = body.get("systemMetadata") or {}
    raw_version = system.get("version")
    return AspectVersion(
        version=int(raw_version) if raw_version is not None else version,
        last_observed_ms=int(system.get("lastObserved") or 0),
        value=body.get("value", body),
    )


def history(
    urn: str,
    aspect: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    max_versions: int = 500,
) -> list[AspectVersion]:
    """Every readable revision of an aspect, oldest first.

    Version 0 is skipped as a probe target: it is an alias for the newest
    numbered revision, and including it would double-count the present. It is
    read once to learn where the numbering currently ends.

    The walk descends from that newest version rather than ascending from 1,
    because DataHub's retention deletes the oldest revisions of a busy aspect.
    Ascending from 1 and stopping at the first gap reports a long-lived aspect
    as having no history whatsoever — the reads then bind to nothing, and the
    adapter fails silently on exactly the instances that have been running long
    enough for any of this to matter. Descending, the first gap is the retention
    floor and everything above it is real.
    """
    try:
        newest = read_aspect(urn, aspect, version=0, base_url=base_url)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (400, 404):
            return []
        raise

    revisions: list[AspectVersion] = []
    for candidate in range(newest.version, max(newest.version - max_versions, 0), -1):
        try:
            revisions.append(read_aspect(urn, aspect, version=candidate, base_url=base_url))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (400, 404):
                break
            raise
    revisions.reverse()
    return revisions


def lineage_facts(payload: dict) -> frozenset[str]:
    """The deciding facts of a lineage payload, canonicalised to a set of URNs.

    Two shapes reduce to the same facts:

    - the aspect API returns ``{"upstreams": [{"dataset": urn, ...}, ...]}``
    - MCP ``get_lineage`` returns
      ``{"upstreams": {"searchResults": [{"entity": {"urn": ...}}], "total": N}}``

    One caveat is deliberate. MCP resolves upstreams that exist *as entities*;
    the aspect lists upstreams that were *declared*. A dangling declared
    upstream appears in one and not the other, the fact sets disagree, and the
    read is correctly reported unbound — we genuinely cannot prove which
    revision the agent saw. Conservative, and honest about why.
    """
    upstreams = payload.get("upstreams")
    if upstreams is None:
        return frozenset()

    items: list = []
    if isinstance(upstreams, dict):
        items = upstreams.get("searchResults") or []
    elif isinstance(upstreams, list):
        items = upstreams

    urns: set[str] = set()
    for item in items:
        if isinstance(item, str):
            urns.add(item)
        elif isinstance(item, dict):
            entity = item.get("entity")
            if isinstance(entity, dict) and entity.get("urn"):
                urns.add(entity["urn"])
            else:
                candidate = item.get("dataset") or item.get("urn")
                if candidate:
                    urns.add(candidate)
    return frozenset(urns)


def resolve_at(
    urn: str,
    aspect: str,
    at_ms: int,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> AspectVersion | None:
    """The revision in force at `at_ms`.

    Returns None when the aspect had no revision at that instant. That is a real
    answer, not a failure: the record must be able to say the metadata did not
    yet exist rather than silently resolving to the present.
    """
    in_force = [
        revision
        for revision in history(urn, aspect, base_url=base_url)
        if revision.last_observed_ms <= at_ms
    ]
    if not in_force:
        return None
    return max(in_force, key=lambda revision: revision.last_observed_ms)


def bind_revision(
    urn: str,
    aspect: str,
    observed_payload: dict,
    at_ms: int,
    *,
    base_url: str = DEFAULT_BASE_URL,
    extract=lineage_facts,
) -> AspectVersion | None:
    """Bind an observed payload to the revision that produced it, or to nothing.

    Exactly one revision is in force at any instant: the newest at or before
    `at_ms`. That revision is the only candidate. The facts must then confirm
    it — if they disagree, a write landed between the agent's read and ours and
    the nearest revision by timestamp is not the revision that decided
    (invariant 8).

    Note what is deliberately *not* treated as ambiguity. A world that returns
    to an earlier state produces several revisions carrying identical facts —
    ``[orders] -> [] -> [orders]`` is an ordinary pipeline change followed by a
    revert. Only one of them was in force when the agent read, so there is
    nothing to disambiguate. Rejecting such a read would refuse to certify the
    most common shape of metadata change there is.
    """
    observed = extract(observed_payload)
    in_force = resolve_at(urn, aspect, at_ms, base_url=base_url)
    if in_force is None:
        return None
    if extract(in_force.value) != observed:
        # The agent saw something the revision in force does not account for.
        return None
    return in_force
