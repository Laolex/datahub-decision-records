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
    """Every archived revision of an aspect, oldest first.

    Version 0 is skipped: it is an alias for the newest numbered revision, and
    including it would double-count the present.
    """
    revisions: list[AspectVersion] = []
    for candidate in range(1, max_versions + 1):
        try:
            revisions.append(read_aspect(urn, aspect, version=candidate, base_url=base_url))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (400, 404):
                break
            raise
    return revisions


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
