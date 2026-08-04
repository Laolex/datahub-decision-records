"""The demo, paced for recording.

`dhdr demo` prints the result. This prints the *story*, at a speed a viewer can
read, so recording the submission video is one command and no editing.

The staging is deliberate and it is not decoration. The real finding — two runs,
identical apparent input, identical logged reasoning, opposite outcomes — is
close to illegible in three minutes to someone who has not read the design
document, because appreciating it means holding aspect versioning and
counterfactual classes in your head at once. So it arrives through something the
viewer already fears: a schema change that broke a dashboard, and a log that
cannot tell you whether the agent was wrong or merely reading stale metadata.

Blast radius is the illustration. Revision-binding is the product.

Nothing here is staged in the dishonest sense: every number below is produced by
the real agent reading a real DataHub instance during the recording.

    python scripts/demo.py            # paced for video
    python scripts/demo.py --fast     # no pauses, for a quick check
"""

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from reckon import MemorySink, Recorder  # noqa: E402

from dhdr.certify import certify  # noqa: E402
from dhdr.proxy import CaptureProxy  # noqa: E402

PACE = 1.0


def say(text: str = "", pause: float = 0.6) -> None:
    print(text)
    time.sleep(pause * PACE)


def beat(pause: float = 1.4) -> None:
    time.sleep(pause * PACE)


def rule(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 62 - len(title)))
    print()
    time.sleep(0.8 * PACE)


def decide(world, decide_drop_column, at_ms: int, run_id: str):
    sink = MemorySink()
    proxy = CaptureProxy()
    outcome = decide_drop_column(
        proxy,
        Recorder(sink=sink, run_id=run_id, emitter="dhdr/0.1.0"),
        world.target_urn,
        world.consumer_urn,
        at_ms=at_ms,
    )
    return outcome, sink.records[0], proxy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="no pauses")
    args = parser.parse_args()

    global PACE
    if args.fast:
        PACE = 0.0

    from fixtures.seed import seed_schema_ops
    from scenarios.schema_ops import decide_drop_column

    rule("the change")
    say("An engineer proposes dropping a column from a Snowflake table.")
    say("Before allowing it, an agent checks DataHub: does anything still read from it?")
    beat()

    say("Setting up the world on a live DataHub instance …", pause=0.2)
    world = seed_schema_ops()
    say(f"  target:   {world.target_urn.split(',')[1]}")
    say(f"  consumer: {world.consumer_urn.split(',')[1]}")
    beat()

    rule("what the agent decided")
    outcome_then, record_then, proxy_then = decide(
        world, decide_drop_column, world.decision_ms, "demo-then"
    )
    read_then = proxy_then.reads[0]
    say(f"  downstream consumers found: {0 if outcome_then == 'admit' else 1}")
    say(f"  decision: {outcome_then.upper()}")
    beat()
    say("The reasoning is legible and it looks correct. The drop goes ahead.")
    beat()

    rule("three weeks later, a dashboard is broken")
    say("Someone asks why the agent allowed it. They open the log.")
    say('It says "no consumers found".')
    beat()
    say("But the lineage has moved since. So the log cannot answer the question")
    say("it is being asked: was that true when the decision was made, or was the")
    say("agent reading a world that had already changed?")
    beat(2.0)

    rule("the same call, against the world as it actually was")
    outcome_now, record_now, proxy_now = decide(
        world, decide_drop_column, world.after_ms, "demo-now"
    )
    read_now = proxy_now.reads[0]
    say(f"  downstream consumers found: {0 if outcome_now == 'admit' else 1}")
    say(f"  decision: {outcome_now.upper()}")
    beat()
    say("Same agent. Same call. Opposite decisions.")
    say("A pipeline wired a consumer to that table between the two.")
    beat(2.0)

    rule("what the certificate adds")
    say("Each decision is bound to the metadata revision that justified it:")
    print()
    say(f"  {outcome_then:>6}  ←  aspect revision v{read_then.revision}"
        f"   (lastObserved={read_then.last_observed_ms})")
    say(f"  {outcome_now:>6}  ←  aspect revision v{read_now.revision}"
        f"   (lastObserved={read_now.last_observed_ms})")
    print()
    beat()
    say("Two different revisions. The record can now name the world it was made in.")
    beat()

    cert = certify(record_then, proxy_then.reads, requested="C2")
    say("Certifier output for the first decision:")
    print()
    for line in cert.render().splitlines():
        say(f"  {line}", pause=0.3)
    print()
    say("A capability class, never a percentage — a score over incommensurable")
    say("kinds of missing evidence manufactures exactly the false confidence")
    say("this exists to prevent.")
    beat()

    rule("and when it cannot prove which world")
    _outcome, record_unbound, proxy_unbound = decide(
        world, decide_drop_column, 1, "demo-unbound"
    )
    unbound = certify(record_unbound, proxy_unbound.reads, requested="C2")
    for line in unbound.render().splitlines():
        say(f"  {line}", pause=0.3)
    print()
    say("It refuses. Not 'C2 with a warning' — no class at all. That phrasing is")
    say("exactly what a hurried reader takes as certification.")
    beat(2.0)

    rule("where it ends up")
    say("The certificate is written back into the dataset's institutionalMemory,")
    say("so the next agent or engineer inherits it — and it arrives as an")
    say("annotation on the pull request, where it can still change the outcome.")
    beat()
    say("A record nobody keeps certifies nothing.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
