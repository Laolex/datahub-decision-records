import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def test_the_annotation_can_be_placed_on_the_line_being_decided():
    """An annotation only renders inline if it sits on a line the diff touches.

    Code hosts show code-scanning results against changed lines. Pinning every
    result to line 1 means that on any pull request whose change is further down
    the file — which is most of them — the certificate exists but is invisible
    where the merge decision is made. That is the one place this project claims
    it belongs.
    """
    region = to_sarif(Certificate("C2", True), path="pipelines/orders.sql", line=15)
    region = region["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 15


def test_the_annotation_defaults_to_the_top_of_the_file():
    doc = to_sarif(Certificate("C2", True), path="a.py")
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 1


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


def test_annotation_carries_what_a_reviewer_needs_to_act():
    """`Capability class: C2` alone tells a reviewer nothing actionable.

    The annotation lands on a pull request, where the reader has the diff and
    nothing else. It has to say which decision, about which dataset, against
    which revision — otherwise it is a grade with no subject.
    """
    doc = to_sarif(
        Certificate("C2", True),
        path="pipelines/orders.sql",
        outcome="reject",
        revision=462,
        dataset="urn:li:dataset:(urn:li:dataPlatform:snowflake,orders,PROD)",
        change="COMMENT ON COLUMN orders.promo_code IS 'deprecated';",
    )
    text = doc["runs"][0]["results"][0]["message"]["text"]
    assert "reject" in text
    assert "v462" in text
    assert "orders" in text
    assert "COMMENT ON COLUMN" in text
    assert "Capability class: C2" in text


def test_annotation_without_context_is_unchanged():
    """The context is optional; omitting it must not change the old output."""
    text = to_sarif(Certificate("C2", True), path="a.py")["runs"][0]["results"][0][
        "message"
    ]["text"]
    assert text == Certificate("C2", True).render()
