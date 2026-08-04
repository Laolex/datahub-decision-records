import json
import sys

sys.path.insert(0, "/opt/datahub-decision-records")

from dhdr.certify import Certificate  # noqa: E402
from dhdr.sarif import to_sarif  # noqa: E402


def _result(cert, **kw):
    return to_sarif(cert, path="a.py", **kw)["runs"][0]["results"][0]


def test_levels_are_ordinal_not_scores():
    assert _result(Certificate("C0", True))["level"] == "note"
    assert _result(Certificate("C2", True))["level"] == "warning"


def test_unsound_fails_open_by_default_and_closed_under_strict():
    unsound = Certificate(None, False, unbound_reads=1)
    assert _result(unsound)["level"] == "warning"
    assert _result(unsound, strict=True)["level"] == "error"


def test_no_percentage_anywhere():
    assert "%" not in json.dumps(to_sarif(Certificate("C2", True), path="a.py"))


def test_output_is_valid_sarif_210_shape():
    """A gate nobody can ingest is a gate nobody installs."""
    doc = to_sarif(Certificate("C2", True), path="src/pipeline.py")
    assert doc["version"] == "2.1.0"
    assert doc["$schema"].startswith("https://")
    run = doc["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "dhdr"
    assert driver["rules"], "results must be traceable to a declared rule"

    result = run["results"][0]
    assert result["ruleId"] in {rule["id"] for rule in driver["rules"]}
    location = result["locations"][0]["physicalLocation"]["artifactLocation"]
    assert location["uri"] == "src/pipeline.py"


def test_the_unsound_result_says_unsound_in_the_message():
    """GitHub shows the message and hides everything else behind a click. If the
    word does not survive into the message text, the annotation reads like an
    ordinary warning."""
    text = _result(Certificate(None, False, unbound_reads=1))["message"]["text"]
    assert "UNSOUND" in text
    assert "Capability class: none" in text


def test_c3_boundary_reaches_the_annotation():
    cert = Certificate("C2", False, c3_boundary="evidence ends here")
    assert "evidence ends here" in _result(cert)["message"]["text"]
