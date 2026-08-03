import pytest
import requests

DEFAULT_BASE_URL = "http://localhost:8080"


@pytest.fixture(scope="session", autouse=True)
def require_datahub():
    """Skip the integration suite rather than fail it when GMS is not up."""
    try:
        requests.get(f"{DEFAULT_BASE_URL}/health", timeout=5).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DataHub not reachable at {DEFAULT_BASE_URL}: {exc}")
