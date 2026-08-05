#!/opt/datahub-probe-venv/bin/python
"""Check that this DataHub instance can actually demonstrate the flip.

Run this before the test suite. The integration tests need two things that a
stock DataHub quickstart does not give you, and when either is missing the
symptom is a timeout that looks like a bug in `dhdr` rather than a setting on
the server. This turns that into a sentence you can act on.

    python scripts/preflight.py

Exit code 0 means the suite should pass. Non-zero prints what to change.
"""

import asyncio
import logging
import sys
import time

sys.path.insert(0, "/opt/datahub-decision-records")

# The MCP server logs every GraphQL query it sends at DEBUG. Useful when
# debugging the adapter, actively unhelpful in a preflight whose entire job is
# to print one clear line about what is wrong.
logging.disable(logging.INFO)

# The DataHub SDK's ExperimentalWarning goes straight to stderr on import and
# would otherwise land in the middle of a preflight whose whole job is to print
# one clear line.
import warnings  # noqa: E402

try:
    from datahub.errors import ExperimentalWarning

    warnings.filterwarnings("ignore", category=ExperimentalWarning)
except ImportError:
    warnings.filterwarnings("ignore", message=r".*[Ee]xperimental.*")

try:
    from loguru import logger as _loguru_logger

    _loguru_logger.remove()
except ImportError:
    pass

from dhdr.coordinate import DEFAULT_BASE_URL, history, lineage_facts  # noqa: E402

CACHE_HELP = """\
  GMS is serving lineage from cache. `get_lineage` reads through it, so a lineage
  change reaches the graph index within seconds and stays invisible to the agent
  for as long as the TTL — which ships as a day.

  Set this on the GMS container and restart it:

      CACHE_SEARCH_LINEAGE_TTL_SECONDS=0

  With it off, MCP reflects a lineage change in about 3 seconds in both
  directions. Without it, `test_agent_decides_through_real_mcp_and_flips` times
  out and every other MCP-path result is read from a stale world."""


async def _mcp_lineage(urn: str) -> set[str]:
    from dhdr.proxy import McpCaptureProxy

    async with McpCaptureProxy() as proxy:
        return set(lineage_facts((await proxy.call_lineage(urn)).value))


async def check_lineage_cache(consumer: str, target: str, timeout_s: float = 30.0) -> bool:
    """Move the world and see how long MCP takes to admit it."""
    from fixtures.seed import set_consumer_lineage

    start = await _mcp_lineage(consumer)
    want = set() if target in start else {target}
    set_consumer_lineage(sorted(want))

    began = time.time()
    while time.time() - began < timeout_s:
        if await _mcp_lineage(consumer) == want:
            print(f"  lineage change visible to MCP in {time.time() - began:.1f}s — cache is off")
            return True
        await asyncio.sleep(2)
    return False


def check_aspect_history(urn: str) -> bool:
    """The coordinate layer needs more than one revision to resolve against."""
    revisions = history(urn, "upstreamlineage")
    if len(revisions) >= 2:
        print(f"  {len(revisions)} readable aspect revisions — history is resolvable")
        return True
    print(
        f"  only {len(revisions)} readable revision(s) of upstreamLineage.\n"
        "  Run the seeder at least once (the test suite does this itself), or check that\n"
        f"  {DEFAULT_BASE_URL} is the instance holding the showcase-ecommerce datapack."
    )
    return False


async def main() -> int:
    from fixtures.seed import CONSUMER, TARGET

    print(f"Checking {DEFAULT_BASE_URL} …")
    ok = True

    if not check_aspect_history(CONSUMER):
        ok = False

    if not await check_lineage_cache(CONSUMER, TARGET):
        print("\nLINEAGE CACHE IS ON\n")
        print(CACHE_HELP)
        ok = False

    print("\nready" if ok else "\nnot ready — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
