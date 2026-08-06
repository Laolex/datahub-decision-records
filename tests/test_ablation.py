"""Ablation: remove one captured field at a time, observe the class collapse.

An entry that cannot show which part of its own record is load-bearing has not
demonstrated that the record is necessary.

The last two rows matter most here, and they do not say the same thing. The
first four ablate fields RCDR already captures, and each one costs a class.

The result worth reporting is the fifth: **deleting the revision from the record
costs nothing.** RCDR's verifier has no concept of a DataHub aspect version, so
a record carrying a revision string and a record missing one certify
identically. The revision in the record is documentation for whoever reads it
later; it is not evidence, and it does not defend itself.

What is load-bearing is the sixth row — the *binding*. A read that could not be
tied to a revision collapses the class to none. So this project's contribution
to soundness is the refusal, not the annotation: the value is in declining to
certify a decision whose world cannot be named, and a reader who takes the
revision field as proof of anything has taken it too far.
"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dhdr.certify import certify  # noqa: E402
from dhdr.proxy import CapturedRead  # noqa: E402

BOUND = CapturedRead(
    "get_lineage", "urn:x", "upstreamlineage", 2, 1785762999915, {}, True
)
UNBOUND = CapturedRead("get_lineage", "urn:x", "upstreamlineage", None, None, {}, False)

FULL = {
    "execution": {
        "runtime": "cpython-3.12",
        "deps_digest": "d",
        "path_digest": "p",
        "pure": True,
    },
    "predicate": {"id": "pred-1"},
    "compared": {"value": 0},
    "policy": {
        "resolved_value": 0,
        "resolution": {"provenance": "bundled", "revision": "2"},
    },
    "candidates": {"completeness": "exhaustive", "items": [{"compared_value": 0}]},
}

# (label, path to the key to remove) — each of these must cost a class
ABLATIONS = [
    ("execution.pure", ("execution", "pure")),
    ("predicate.id", ("predicate", "id")),
    ("policy.resolved_value", ("policy", "resolved_value")),
    ("candidates.completeness", ("candidates", "completeness")),
]

# Ablated too, but asserted separately, because it costs nothing.
REVISION_PATH = ("policy", "resolution", "revision")


def _without(record: dict, path: tuple[str, ...]) -> dict:
    damaged = copy.deepcopy(record)
    node = damaged
    for key in path[:-1]:
        node = node[key]
    node.pop(path[-1], None)
    return damaged


def _cls(record: dict, reads: list[CapturedRead]) -> str:
    return certify(record, reads, requested="C2").cls or "none"


def test_ablation_table():
    baseline = certify(FULL, [BOUND], requested="C2")
    assert baseline.cls == "C2"

    rows = [("(none — full record)", baseline.cls)]
    for label, path in ABLATIONS:
        rows.append((label, _cls(_without(FULL, path), [BOUND])))
    rows.append(("policy.resolution.revision", _cls(_without(FULL, REVISION_PATH), [BOUND])))
    rows.append(("read binding (unbound read)", _cls(FULL, [UNBOUND])))

    print("\n\nABLATION — which captured field is load-bearing\n")
    print(f"{'removed':<30} {'class still available'}")
    for label, cls in rows:
        print(f"{label:<30} {cls}")
    print()

    for label, _path in ABLATIONS:
        cls = dict(rows)[label]
        assert cls != "C2", f"removing {label} cost nothing — it is not load-bearing"


def test_the_revision_field_alone_is_not_evidence():
    """The negative result, pinned so it cannot quietly change.

    A record with the revision deleted certifies exactly as well as one that
    carries it. The upstream verifier does not model DataHub versions, so the
    field is inert to it. If this ever starts failing, RCDR has begun checking
    the revision and the README's ablation section is out of date.
    """
    assert _cls(_without(FULL, REVISION_PATH), [BOUND]) == "C2"
    assert _cls(FULL, [BOUND]) == "C2"


def test_the_binding_is_what_carries_the_soundness():
    """And the positive result: the refusal is the contribution."""
    assert _cls(FULL, [UNBOUND]) == "none"
    assert certify(FULL, [UNBOUND], requested="C2").satisfied is False
