"""The token has to reach every call, and the entity type has to come from the URN.

Both of these are failures that do not announce themselves.

Without the token, an auth-enabled instance 401s. That is loud on the read path
and silent on the write path, because `publish_certificate` retries and the
retry re-reads — so a missing header turns into "could not publish after 5
attempts under contention", naming a race that never happened.

With `dataset` hardcoded, a dashboard or a dataJob 404s on the aspect GET,
`history()` reads a 404 as "no revisions", every read binds to nothing, and the
certificate reports `none`. That is the correct refusal for the wrong reason,
and indistinguishable from metadata that genuinely could not be dated. Neither
failure raises, which is why they are pinned here rather than left to the
integration suite.
"""

import pytest

from dhdr import coordinate


@pytest.fixture(autouse=True)
def _clear_session():
    """The session caches its token, so a leaked one crosses tests."""
    coordinate._session = None
    coordinate._session_token = None
    yield
    coordinate._session = None
    coordinate._session_token = None


def test_no_token_configured_sends_no_authorization_header(monkeypatch):
    monkeypatch.delenv(coordinate.GMS_TOKEN_ENV_VAR, raising=False)
    assert coordinate.default_token() is None
    assert "Authorization" not in coordinate.session().headers


def test_token_reaches_the_session(monkeypatch):
    monkeypatch.setenv(coordinate.GMS_TOKEN_ENV_VAR, "pat-abc123")
    assert coordinate.session().headers["Authorization"] == "Bearer pat-abc123"


def test_token_set_after_import_still_takes_effect(monkeypatch):
    """Binding the token at import is how the knob comes loose."""
    monkeypatch.delenv(coordinate.GMS_TOKEN_ENV_VAR, raising=False)
    assert "Authorization" not in coordinate.session().headers

    monkeypatch.setenv(coordinate.GMS_TOKEN_ENV_VAR, "pat-later")
    assert coordinate.session().headers["Authorization"] == "Bearer pat-later"


def test_session_is_reused_while_the_token_is_unchanged(monkeypatch):
    """One connection across the revision walk, not one per revision."""
    monkeypatch.setenv(coordinate.GMS_TOKEN_ENV_VAR, "pat-stable")
    assert coordinate.session() is coordinate.session()


@pytest.mark.parametrize(
    "urn, expected",
    [
        ("urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.t,PROD)", "dataset"),
        ("urn:li:dashboard:(looker,dashboards.1)", "dashboard"),
        ("urn:li:chart:(looker,charts.1)", "chart"),
        ("urn:li:dataJob:(urn:li:dataFlow:(airflow,dag,PROD),task)", "dataJob"),
        ("urn:li:mlModel:(urn:li:dataPlatform:science,model,PROD)", "mlModel"),
        ("urn:li:glossaryTerm:PII", "glossaryTerm"),
    ],
)
def test_entity_type_comes_from_the_urn(urn, expected):
    assert coordinate.entity_type_of(urn) == expected


@pytest.mark.parametrize("urn", ["", "nonsense", "urn:li:", "urn:li"])
def test_unparseable_urn_falls_back_to_dataset(urn):
    """A malformed URN is not the place to start guessing at endpoints."""
    assert coordinate.entity_type_of(urn) == coordinate.DEFAULT_ENTITY_TYPE


def test_aspect_url_follows_the_urn_not_a_constant():
    from dhdr.publish import _aspect_url

    url = _aspect_url("urn:li:dashboard:(looker,dashboards.1)", base_url="http://gms")
    assert "/entity/dashboard/" in url
    assert "/entity/dataset/" not in url
