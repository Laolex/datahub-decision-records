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
