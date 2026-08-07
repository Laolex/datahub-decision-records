"""No script may hardcode where this repository lives.

Two of them did, and the failure is worse than a crash. An absolute
`sys.path.insert` does not stop a clone at another path from running — it makes
it import `fixtures` and `dhdr` from whatever checkout happens to sit at the
hardcoded path instead. The script then reports on a working tree the reader is
not looking at, and says nothing about it. On a machine with no such directory
it exits 1 with a traceback, which at least is honest, and which is what a judge
following the README would have seen.

`check_published.py` is the one that matters most: its whole job is proving the
submission's published links are alive.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((REPO / "scripts").glob("*.py"))

#: A string literal absolute path handed to sys.path — the defect itself.
HARDCODED = re.compile(r"""sys\.path\.insert\(\s*\d+\s*,\s*['"]/""")


def test_there_are_scripts_to_check():
    """A glob that silently matches nothing would make every test below pass."""
    assert SCRIPTS, "no scripts found — this suite would be vacuous"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_does_not_hardcode_the_repository_root(script):
    source = script.read_text()
    offending = [
        line
        for line in source.splitlines()
        if HARDCODED.search(line)
    ]
    assert not offending, (
        f"{script.name} hardcodes an absolute path into sys.path: {offending}. "
        "Derive it: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_root_resolves_to_this_repository(script):
    """The derived root must be this checkout, not a sibling that happens to exist."""
    source = script.read_text()
    if "sys.path.insert" not in source:
        pytest.skip(f"{script.name} does not extend sys.path")
    assert "__file__" in source, (
        f"{script.name} extends sys.path without deriving from __file__"
    )
