import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@pytest.mark.integration
def test_demo_shows_the_same_call_deciding_both_ways(capsys):
    from dhdr.cli import main

    assert main([]) == 0
    out = capsys.readouterr().out

    assert "admit" in out
    assert "reject" in out
    # two certificates, and the revisions they name must differ
    revisions = re.findall(r"^revision: v(\S+)", out, re.MULTILINE)
    assert len(revisions) == 2
    assert revisions[0] != revisions[1]
    assert "Capability class: C2" in out
    assert "%" not in out


@pytest.mark.integration
def test_sarif_subcommand_emits_an_ingestible_document(capsys):
    """The CI gate has to be reachable from a shell, not just importable."""
    import json

    from dhdr.cli import main

    assert main(["sarif", "--path", "pipelines/orders.sql"]) == 0
    doc = json.loads(capsys.readouterr().out)

    assert doc["version"] == "2.1.0"
    result = doc["runs"][0]["results"][0]
    assert result["level"] in {"note", "warning", "error"}
    assert (
        result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == "pipelines/orders.sql"
    )


@pytest.mark.integration
def test_demo_runs_from_any_working_directory():
    """The CLI must not depend on being launched from the repo.

    A judge running this from their own checkout is the whole point, and a
    hardcoded absolute path would work perfectly on the machine that built it
    and nowhere else.
    """
    result = subprocess.run(
        [sys.executable, "-m", "dhdr.cli"],
        cwd="/",
        capture_output=True,
        text=True,
        timeout=300,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src")},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "admit" in result.stdout
    assert "reject" in result.stdout
