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
        requests.get(f"{DEFAULT_BASE_URL}/health", timeout=5).raise_for_status()
        _SKIP_REASON = None
    except Exception as exc:  # noqa: BLE001
        _SKIP_REASON = f"DataHub not reachable at {DEFAULT_BASE_URL}: {exc}"
    return _SKIP_REASON


def pytest_collection_modifyitems(config, items):
    reason = _datahub_unavailable()
    if reason is None:
        return
    skip_integration = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
