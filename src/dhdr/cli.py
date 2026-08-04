"""`dhdr` — run the scenario and print the certificates.

The demo needs `fixtures/` and `scenarios/`, which live at the repository root
rather than inside the installed package: they are the world and the agent, not
the library. The root is resolved from this file's location so the command works
from any working directory and from anyone's checkout.
"""

import sys
from pathlib import Path

from reckon import MemorySink, Recorder

from .certify import certify
from .proxy import CaptureProxy

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_scenario():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from fixtures.seed import seed_schema_ops
        from scenarios.schema_ops import decide_drop_column
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            f"could not import the scenario from {REPO_ROOT}: {exc}. "
            "Run `dhdr demo` from a checkout of the repository — the fixtures and "
            "scenarios are not shipped inside the installed package."
        ) from exc
    return seed_schema_ops, decide_drop_column


def main() -> int:
    seed_schema_ops, decide_drop_column = _load_scenario()

    world = seed_schema_ops()

    for label, at_ms in (
        ("as the agent saw it", world.decision_ms),
        ("as it actually was", world.after_ms),
    ):
        sink = MemorySink()
        proxy = CaptureProxy()
        outcome = decide_drop_column(
            proxy,
            Recorder(sink=sink, run_id=f"cli-{at_ms}", emitter="dhdr/0.1.0"),
            world.target_urn,
            world.consumer_urn,
            at_ms=at_ms,
        )
        read = proxy.reads[0]
        print(f"\n=== {label} ===")
        print(f"outcome:  {outcome}")
        print(f"revision: v{read.revision}  (lastObserved={read.last_observed_ms})")
        print(certify(sink.records[0], proxy.reads, requested="C2").render())

    print("\nSame agent. Same call. Opposite decisions.")
    print("The log cannot tell you which world it was made in. The certificate can.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
