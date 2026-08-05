"""The documented configuration knob has to actually move the endpoint.

The README has always told readers to set `DATAHUB_GMS_URL`. Until this module
existed, that variable was read in exactly one place — the test gate in
`conftest.py` — while `src/`, `scripts/` and `fixtures/` all resolved
`http://localhost:8080` from an import-time constant and offered no way to
override it. Anyone whose DataHub was on another host followed the documented
command, got connection errors, and had no reason to suspect the documentation
rather than the project.

A documented knob that does nothing is worse than an undocumented one: it costs
the reader the time they spend trusting it. These tests fail if the knob comes
loose again.
"""

import dataclasses

import pytest

from dhdr import coordinate, proxy, publish

MODULES_WITH_A_DEFAULT = (coordinate, publish)


@pytest.fixture
def gms(monkeypatch):
    """Point the whole project at an arbitrary endpoint."""

    def _set(url: str) -> str:
        monkeypatch.setenv("DATAHUB_GMS_URL", url)
        return url

    return _set


def test_default_is_localhost_when_unset(monkeypatch):
    monkeypatch.delenv("DATAHUB_GMS_URL", raising=False)
    assert coordinate.default_base_url() == "http://localhost:8080"


def test_environment_overrides_the_default(gms):
    url = gms("http://datahub.internal:9002")
    assert coordinate.default_base_url() == url


def test_override_is_read_at_call_time_not_import_time(gms):
    """The bug this module exists for.

    `base_url: str = DEFAULT_BASE_URL` binds the value when Python imports the
    module, which is before any test — or any CLI flag — can change it. The
    default has to be resolved when the function runs.
    """
    first = gms("http://one.example:8080")
    assert coordinate.default_base_url() == first
    second = gms("http://two.example:8080")
    assert coordinate.default_base_url() == second


@pytest.mark.parametrize("module", MODULES_WITH_A_DEFAULT, ids=lambda m: m.__name__)
def test_no_module_binds_the_endpoint_at_import(module, gms):
    """No signature may carry a hardcoded endpoint as its default value."""
    gms("http://elsewhere.example:8080")
    import inspect

    for name, obj in vars(module).items():
        if not inspect.isfunction(obj):
            continue
        signature = inspect.signature(obj)
        parameter = signature.parameters.get("base_url")
        if parameter is None:
            continue
        assert parameter.default in (None, inspect.Parameter.empty), (
            f"{module.__name__}.{name} binds base_url at import time "
            f"({parameter.default!r}); it must default to None and resolve "
            "through default_base_url() when it runs"
        )


def test_proxy_dataclass_resolves_per_instance(gms):
    """A dataclass default is bound at class creation, which is even earlier."""
    first = gms("http://first.example:8080")
    assert proxy.CaptureProxy().base_url == first
    second = gms("http://second.example:8080")
    assert proxy.CaptureProxy().base_url == second


def test_proxy_dataclass_uses_a_factory_not_a_constant():
    field = next(f for f in dataclasses.fields(proxy.CaptureProxy) if f.name == "base_url")
    assert field.default is dataclasses.MISSING, (
        "base_url is a frozen constant on the dataclass; it needs "
        "field(default_factory=default_base_url) to track the environment"
    )


def test_explicit_argument_still_wins(gms):
    """Passing the endpoint directly must override the environment."""
    gms("http://ignored.example:8080")
    explicit = "http://explicit.example:8080"
    assert proxy.CaptureProxy(base_url=explicit).base_url == explicit


def test_publish_module_shares_one_resolver(gms):
    """One resolver, so the endpoint cannot drift between modules."""
    url = gms("http://shared.example:8080")
    assert publish.default_base_url() == coordinate.default_base_url() == url
