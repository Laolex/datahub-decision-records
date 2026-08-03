"""Seeds the Scenario 1 world on top of DataHub's own showcase-ecommerce datapack.

The story: an engineer wants to drop a column from the `orders` source table.
Before allowing it, the agent checks whether the analytics table that reads from
`orders` still depends on it. Early in the window it does not, and the drop is
safe. Then a pipeline change wires `order_history` to `orders`, and the same
drop becomes destructive.

Two deliberate choices.

**Real entities, not invented ones.** Both datasets ship in the
`showcase-ecommerce` datapack. MCP's `get_lineage` resolves upstreams that exist
*as entities*, so a fabricated URN would return nothing and the read would bind
to no revision — the adapter working correctly, but a demo showing nothing.

**The agent reads the consumer's aspect, not the target's.** The deciding fact —
does `order_history` read from `orders`? — lives in `order_history`'s
`upstreamLineage`, and that is also the aspect whose revision changes. Reading
downstream-of-`orders` instead would put the deciding fact in one entity and the
resolvable revision in another, and the binding would be incoherent.

`orders` is never mutated. Only `order_history`'s lineage moves.
"""

import time
from dataclasses import dataclass

import requests

from dhdr.coordinate import DEFAULT_BASE_URL

TARGET = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.order_entry.orders,PROD)"
CONSUMER = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_history,PROD)"


@dataclass(frozen=True)
class SeededWorld:
    target_urn: str
    consumer_urn: str
    before_ms: int
    after_ms: int
    decision_ms: int


def _emit_lineage(urn: str, upstreams: list[str], base_url: str) -> None:
    body = [
        {
            "urn": urn,
            "upstreamLineage": {
                "value": {
                    "upstreams": [
                        {"dataset": u, "type": "TRANSFORMED"} for u in upstreams
                    ]
                }
            },
        }
    ]
    response = requests.post(
        f"{base_url}/openapi/v3/entity/dataset",
        json=body,
        params={"async": "false"},
        timeout=30,
    )
    response.raise_for_status()


def seed_schema_ops(base_url: str = DEFAULT_BASE_URL) -> SeededWorld:
    """Write the two lineage states with a measurable gap between them.

    Returns the instants that matter: `decision_ms` sits inside the window when
    the consumer had no dependency, `after_ms` after the edge appeared.
    """
    _emit_lineage(CONSUMER, [], base_url)
    before_ms = int(time.time() * 1000)

    time.sleep(2)
    decision_ms = int(time.time() * 1000)
    time.sleep(2)

    # the pipeline change: order_history starts reading from orders
    _emit_lineage(CONSUMER, [TARGET], base_url)
    time.sleep(3)
    after_ms = int(time.time() * 1000)

    return SeededWorld(
        target_urn=TARGET,
        consumer_urn=CONSUMER,
        before_ms=before_ms,
        after_ms=after_ms,
        decision_ms=decision_ms,
    )
