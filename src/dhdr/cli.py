"""`dhdr` — run the scenario and print the certificates.

The demo needs `fixtures/` and `scenarios/`, which live at the repository root
rather than inside the installed package: they are the world and the agent, not
the library. The root is resolved from this file's location so the command works
from any working directory and from anyone's checkout.
"""

import argparse
import json
import sys
from pathlib import Path

from reckon import MemorySink, Recorder

from .certify import certify
from .proxy import CaptureProxy
from .sarif import to_sarif

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


def _decide_once(at_ms: int, world, decide_drop_column, run_id: str):
    """One decision, returning the record, the outcome and the proxy that read."""
    sink = MemorySink()
    proxy = CaptureProxy()
    outcome = decide_drop_column(
        proxy,
        Recorder(sink=sink, run_id=run_id, emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=at_ms,
    )
    return sink.records[0], outcome, proxy


def _sarif(args: argparse.Namespace) -> int:
    """Emit the current decision as a SARIF annotation for a CI gate."""
    seed_schema_ops, decide_drop_column = _load_scenario()
    world = seed_schema_ops()
    record, _outcome, proxy = _decide_once(
        world.after_ms, world, decide_drop_column, "sarif"
    )
    cert = certify(record, proxy.reads, requested="C2")
    json.dump(to_sarif(cert, path=args.path, strict=args.strict), sys.stdout, indent=2)
    print()
    # Exit non-zero only under --strict, and only when nothing is certifiable.
    # A gate that blocks a merge over a gap in its own instrumentation gets
    # uninstalled, and an uninstalled gate certifies nothing.
    return 1 if (args.strict and cert.cls is None) else 0


def _demo(_args: argparse.Namespace) -> int:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dhdr", description="Decision records for DataHub agents."
    )
    sub = parser.add_subparsers(dest="command")

    demo = sub.add_parser("demo", help="run the scenario and print both certificates")
    demo.set_defaults(func=_demo)

    sarif = sub.add_parser("sarif", help="emit the certificate as SARIF 2.1.0")
    sarif.add_argument(
        "--path", default="scenarios/schema_ops.py", help="artifact URI to annotate"
    )
    sarif.add_argument(
        "--strict",
        action="store_true",
        help="fail closed: exit non-zero when nothing is certifiable",
    )
    sarif.set_defaults(func=_sarif)

    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        return _demo(args)          # bare `dhdr` runs the demo
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
