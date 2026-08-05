#!/usr/bin/env python3
"""Negative control: prove the refusal holds, and that it is not vacuous.

A demo that only shows the certifier succeeding is not evidence. Every entry in
this category can show a green path. What distinguishes a record that means
something is whether the system *declines* when it should — and whether that
decline is a real discrimination rather than a machine that says no to
everything.

This script asserts five invariants and exits non-zero if any of them breaks,
so it can gate CI:

  1. REFUSAL. A read that could not be bound to a revision certifies as no
     class at all. A decision whose world cannot be named is not certifiable.
  2. NOT VACUOUS. The control case — a fully bound, complete record — must
     still certify at C2. A certifier that refuses everything satisfies (1)
     trivially and is worth nothing; this is the arm that catches it.
  3. ABSENCE IS RECORDED. An unbound read carries revision=None and
     resolved=False. It is never silently resolved to the present, which is the
     failure the whole project exists to oppose.
  4. LOAD-BEARING FIELDS. Each of the four captured fields the README claims is
     necessary must cost a class when removed. A field that costs nothing is
     documentation, not evidence, and must not be described as evidence.
  5. THE PUBLISHED NEGATIVE RESULT. Deleting the revision from the record must
     cost *nothing*. This is the finding the submission reports against its own
     pitch, and it is pinned here so it cannot quietly stop being true. If this
     invariant fails, the certifier has started reading the revision and the
     README's ablation section has become false.

Invariants 4 and 5 point in opposite directions on purpose. Together they are
the claim: the binding is load-bearing, the annotation is not.

Run:  python scripts/negative_control.py
"""

import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from dhdr.certify import certify  # noqa: E402
from dhdr.proxy import CapturedRead  # noqa: E402

BOUND = CapturedRead(
    "get_lineage", "urn:x", "upstreamlineage", 2, 1785762999915, {}, True
)
UNBOUND = CapturedRead("get_lineage", "urn:x", "upstreamlineage", None, None, {}, False)

COMPLETE_RECORD = {
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

LOAD_BEARING = [
    ("execution.pure", ("execution", "pure")),
    ("predicate.id", ("predicate", "id")),
    ("policy.resolved_value", ("policy", "resolved_value")),
    ("candidates.completeness", ("candidates", "completeness")),
]

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


def main() -> int:
    violations: list[str] = []

    def check(ok: bool, invariant: str, detail: str) -> None:
        status = "ok  " if ok else "FAIL"
        print(f"  [{status}] {invariant}: {detail}")
        if not ok:
            violations.append(f"{invariant} — {detail}")

    print("\nNEGATIVE CONTROL — the refusal, and proof it discriminates\n")

    # 1. The refusal itself.
    unbound_cls = _cls(COMPLETE_RECORD, [UNBOUND])
    check(
        unbound_cls == "none",
        "1 REFUSAL",
        f"unbound read certifies as {unbound_cls!r} (must be 'none')",
    )

    # 2. The control case, which stops (1) being satisfied by refusing everything.
    bound_cls = _cls(COMPLETE_RECORD, [BOUND])
    check(
        bound_cls == "C2",
        "2 NOT VACUOUS",
        f"complete bound record certifies as {bound_cls!r} (must be 'C2')",
    )

    # 3. Absence is recorded as absence.
    check(
        UNBOUND.revision is None and UNBOUND.resolved is False,
        "3 ABSENCE RECORDED",
        f"revision={UNBOUND.revision!r} resolved={UNBOUND.resolved!r} "
        "(must be None / False, never resolved to the present)",
    )

    # 4. Every field claimed load-bearing must actually cost a class.
    for label, path in LOAD_BEARING:
        cls = _cls(_without(COMPLETE_RECORD, path), [BOUND])
        check(
            cls != "C2",
            "4 LOAD-BEARING",
            f"removing {label} leaves class {cls!r} (must not stay 'C2')",
        )

    # 5. The published negative result, pinned against silent drift.
    revision_cls = _cls(_without(COMPLETE_RECORD, REVISION_PATH), [BOUND])
    check(
        revision_cls == "C2",
        "5 REVISION INERT",
        f"removing the revision leaves class {revision_cls!r} (must stay 'C2' — "
        "the README reports this field as not load-bearing)",
    )

    print()
    if violations:
        print(f"{len(violations)} invariant(s) violated:\n")
        for violation in violations:
            print(f"  - {violation}")
        print("\nThe refusal no longer holds as described. Do not ship this.\n")
        return 1

    print("All invariants hold. The binding is load-bearing; the annotation is not.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
