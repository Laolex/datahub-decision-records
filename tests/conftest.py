"""Skip only what actually needs DataHub.

The earlier version was a session-scoped autouse fixture calling `pytest.skip`,
which skips the *whole session* when GMS is down — including the certifier, the
SARIF emitter and the ablation, none of which touch DataHub at all. That hides
real breakage behind a green-looking "skipped" summary on any machine without an
instance, which is exactly the kind of comfortable non-answer this project is
supposed to be against.

Now the reachability check runs once, and only tests marked `integration` are
skipped when it fails. Everything else runs and fails loudly.
"""

import os

import pytest
import requests

DEFAULT_BASE_URL = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")

_SKIP_REASON: str | None = None
_CHECKED = False


def _datahub_unavailable() -> str | None:
    """The reason DataHub cannot be used, or None when it can. Checked once."""
    global _SKIP_REASON, _CHECKED
    if _CHECKED:
        return _SKIP_REASON
    _CHECKED = True
    try:
        # `/health` is an empty 200 that any server can produce, and port 8080 is
        # the most contended port in software — Tomcat, Jenkins, any dev server.
        # Trusting a bare 200 there makes the integration tests *run* against
        # something that is not DataHub and fail confusingly, on the exact path
        # the README calls "no DataHub needed". `/config` identifies itself.
        response = requests.get(f"{DEFAULT_BASE_URL}/config", timeout=5)
        response.raise_for_status()
        body = response.json()
        if "datahub" not in body and "managedIngestion" not in body:
            raise RuntimeError(
                "something answered but it does not look like DataHub "
                "(no 'datahub' key in /config)"
            )
        # `/config` is served by GMS alone, so it stays 200 while the search
        # backend is missing — the containers report healthy and every
        # search-backed read then 500s with "Failed to generate PointInTime
        # Identifier". The integration tests un-skip and fail, and the failure
        # looks like this project rather than a half-started stack. A degraded
        # instance is not a usable instance; say so and skip.
        probe = requests.post(
            f"{DEFAULT_BASE_URL}/api/graphql",
            json={"query": "{ search(input: {type: DATASET, query: \"*\", count: 1}) { total } }"},
            timeout=10,
        )
        errors = (probe.json() or {}).get("errors") if probe.ok else None
        if not probe.ok or errors:
            if errors:
                # GMS returns the whole Java stack in one string; the first
                # sentence is the part a reader needs.
                detail = str(errors[0].get("message", errors[0])).split(".")[0][:120]
            else:
                detail = f"HTTP {probe.status_code}"
            raise RuntimeError(
                f"DataHub answered /config but its search backend is not serving ({detail}). "
                "The stack is still starting, or its Elasticsearch/OpenSearch container is down."
            )
        _SKIP_REASON = None
    except Exception as exc:  # noqa: BLE001
        _SKIP_REASON = f"DataHub not usable at {DEFAULT_BASE_URL}: {exc}"
    return _SKIP_REASON


def pytest_collection_modifyitems(config, items):
    reason = _datahub_unavailable()
    if reason is None:
        return
    skip_integration = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
