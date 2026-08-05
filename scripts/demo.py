#!/opt/datahub-probe-venv/bin/python
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
import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dhdr.cli import live_flow, quiet_mcp_logging  # noqa: E402

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


async def run() -> int:
    quiet_mcp_logging()

    rule("the change")
    say("An engineer proposes dropping a column from a Snowflake table.")
    say("Before allowing it, an agent checks DataHub: does anything still read from it?")
    say("Every read goes through DataHub's own MCP server — the live one, not a stub.")
    beat()

    decisions = []
    async for kind, payload in live_flow():
        if kind == "settling":
            if not payload:
                say("Setting the world to its starting state on a live instance …", pause=0.2)
            else:
                rule("meanwhile, a pipeline changes")
                say("A dbt model is wired to read from that table. The world moves.")
                say("Waiting until MCP itself reports the change …", pause=0.2)
            continue

        decisions.append(payload)
        if len(decisions) == 1:
            rule("what the agent decided")
            say(f"  downstream consumers found: 0")
            say(f"  decision: {payload.outcome.upper()}")
            print()
            say("and the change it is proposing:")
            for line in payload.change.render().splitlines():
                say(f"  {line}", pause=0.3)
            print()
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
        else:
            rule("the same call, now")
            say(f"  downstream consumers found: 1")
            say(f"  decision: {payload.outcome.upper()}")
            print()
            say("and a different change — it refuses the drop and proposes")
            say("deprecation instead, naming the consumer that still reads it:")
            for line in payload.change.render().splitlines():
                say(f"  {line}", pause=0.3)
            print()
            beat()
            say("Same agent. Same call, through the same MCP server. Opposite decisions.")
            say("Two different proposed changes, each bound to the revision behind it.")
            beat(2.0)

    before, after = decisions

    rule("what the certificate adds")
    say("Each decision is bound to the metadata revision that justified it:")
    print()
    say(f"  {before.outcome:>6}  ←  aspect revision v{before.revision}"
        f"   (lastObserved={before.last_observed_ms})")
    say(f"  {after.outcome:>6}  ←  aspect revision v{after.revision}"
        f"   (lastObserved={after.last_observed_ms})")
    print()
    beat()
    say("Two different revisions. The record can now name the world it was made in.")
    say("The MCP response carries no version at all — that coordinate is recovered")
    say("and matched back to the response by its facts, never by a re-fetch.")
    beat()

    say("Certificate for the first decision:")
    print()
    for line in before.certificate.render().splitlines():
        say(f"  {line}", pause=0.3)
    print()
    say("A capability class, never a percentage — a score over incommensurable")
    say("kinds of missing evidence manufactures exactly the false confidence")
    say("this exists to prevent. And note the boundary it declares about its own")
    say("write: past that point, replay becomes inference.")
    beat(2.0)

    rule("and when it cannot prove which world")
    unbound = unbound_refusal()
    for line in unbound.render().splitlines():
        say(f"  {line}", pause=0.3)
    print()
    say("It refuses. Not 'C2 with a warning' — no class at all. That phrasing is")
    say("exactly what a hurried reader takes as certification.")
    beat(2.0)

    rule("where it ends up")
    say("Both certificates were written back into the dataset's institutionalMemory")
    say("during this run, so the next agent or engineer inherits them:")
    print()
    for d in decisions:
        say(f"  {d.outcome:>6}  →  {d.published_url}", pause=0.3)
    print()
    beat()
    say("And the same certificate arrives as an annotation on the pull request,")
    say("where it can still change the outcome.")
    beat()
    say("A record nobody keeps certifies nothing.")
    print()
    return 0


def unbound_refusal():
    """A real unbound read: ask about an instant before the metadata existed.

    The aspect API is used here rather than MCP because MCP cannot be pointed at
    a past instant at all — which is the gap this project exists to close. The
    read is genuine and so is the refusal.
    """
    from reckon import MemorySink, Recorder

    from dhdr.certify import certify
    from dhdr.proxy import CaptureProxy
    from fixtures.seed import CONSUMER, TARGET
    from scenarios.schema_ops import decide_drop_column

    sink = MemorySink()
    proxy = CaptureProxy()
    decide_drop_column(
        proxy,
        Recorder(sink=sink, run_id="demo-unbound", emitter="dhdr/0.1.0"),
        TARGET,
        CONSUMER,
        at_ms=1,
    )
    return certify(sink.records[0], proxy.reads, requested="C2")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="no pauses")
    args = parser.parse_args()

    global PACE
    if args.fast:
        PACE = 0.0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
