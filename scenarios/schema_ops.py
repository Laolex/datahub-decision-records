"""Scenario 1 — destructive schema operations.

The agent decides whether dropping a column from a source table is safe. The
deciding input is downstream lineage read from DataHub: while nothing reads from
the table the drop is allowed, and once a pipeline wires a consumer to it the
same drop is refused.

Two entry points, one decision. `decide_drop_column` reads through the aspect
API and can therefore be pointed at a past instant; `decide_drop_column_mcp`
reads through the real MCP server, which only ever answers about now. They share
`_record_decision`, so the record is identical whichever way the context
arrived — the scenario is not written twice and cannot drift.

The consumer count is derived with `lineage_facts` rather than by indexing the
payload. MCP returns a search result and the aspect API returns a list of
declared upstreams; the deciding fact is the same either way, and the scenario
has no business knowing which shape it was handed.
"""

from dataclasses import dataclass

from dhdr.coordinate import lineage_facts
from dhdr.proxy import CaptureProxy, CapturedRead, McpCaptureProxy

MAX_SAFE_CONSUMERS = 0
DEFAULT_COLUMN = "promo_code"


@dataclass(frozen=True)
class ChangeRequest:
    """The concrete change the agent is proposing, alongside the record.

    A decision record with no subject is a verdict nobody can act on, so the
    agent emits the actual DDL it wants run. It is **proposed and never
    applied** — `dhdr` decides and records; it does not execute migrations, and
    there is deliberately no method here that would.

    A refusal carries a change request too. Returning "no" and stopping leaves
    the engineer exactly where they started; refusing the drop and proposing
    deprecation instead is the part that is actually useful.
    """

    kind: str
    statement: str
    rationale: str
    applied: bool = False

    def render(self) -> str:
        status = "applied" if self.applied else "proposed — not applied by dhdr"
        return f"-- {self.rationale}\n-- {status}\n{self.statement}"


def _table_name(dataset_urn: str) -> str:
    """The table out of a dataset URN, for rendering DDL a human recognises."""
    try:
        return dataset_urn.split(",")[1]
    except IndexError:  # pragma: no cover - malformed urn
        return dataset_urn


def proposed_change(
    target_urn: str,
    column: str,
    *,
    outcome: str,
    consumers: tuple[str, ...],
) -> ChangeRequest:
    """Render the change the decision implies. Pure: no I/O, no execution."""
    table = _table_name(target_urn)
    if outcome == "admit":
        return ChangeRequest(
            kind="drop_column",
            statement=f"ALTER TABLE {table} DROP COLUMN {column};",
            rationale=(
                f"No downstream consumer reads {table}.{column} at the bound revision."
            ),
        )

    readers = ", ".join(_table_name(c) for c in consumers) or "a downstream consumer"
    return ChangeRequest(
        kind="deprecate_column",
        statement=(
            f"COMMENT ON COLUMN {table}.{column} IS "
            f"'deprecated: still read by {readers}; do not drop until that dependency is removed';"
        ),
        rationale=(
            f"{readers} still reads {table} at the bound revision, so the drop is "
            "refused and deprecation proposed instead."
        ),
    )


def _record_decision(
    read: CapturedRead,
    recorder,
    target_urn: str,
    consumer_urn: str,
    column: str = DEFAULT_COLUMN,
) -> str:
    """Turn one captured lineage read into one recorded decision."""
    upstreams = lineage_facts(read.value)
    consumer_count = 1 if target_urn in upstreams else 0
    source = f"datahub:{consumer_urn}#upstreamlineage"

    # Rendered from the same consumer count the predicate uses, so the artifact
    # and the verdict cannot disagree about the world they were made in.
    likely = "reject" if consumer_count > MAX_SAFE_CONSUMERS else "admit"
    change = proposed_change(
        target_urn, column, outcome=likely, consumers=(consumer_urn,)
    )

    with recorder.decision(
        action="drop_column",
        params={
            "target": target_urn,
            "column": column,
            "proposed_change": change.statement,
            "change_kind": change.kind,
        },
        pure=True,
    ) as decision:
        # The revision rides in RCDR's existing Policy.revision field. The
        # threshold is the policy; the revision is what dates the world it was
        # applied to. An unbound read claims neither — a threshold applied to a
        # world we cannot date is not a bundled policy, it is an unknown one.
        decision.policy(
            "max_safe_consumers",
            value=MAX_SAFE_CONSUMERS,
            provenance="bundled" if read.resolved else "unknown",
            source=source,
            revision=str(read.revision) if read.resolved else None,
        )
        decision.read(
            "downstream_consumers",
            consumer_count,
            f"{source}@v{read.revision}" if read.resolved else f"{source}@unbound",
        )

        safe = decision.check(
            "lte",
            left="downstream_consumers",
            value=consumer_count,
            right="max_safe_consumers",
        )
        predicate_id = decision.predicate.id

        decision.candidate(
            "drop_column",
            compared_value=consumer_count,
            outcome="admit" if safe else "reject",
            predicate=predicate_id,
        )
        decision.candidate(
            "deprecate_instead",
            compared_value=consumer_count,
            outcome="reject" if safe else "admit",
            predicate=predicate_id,
        )
        decision.candidates_exhaustive()

        if safe:
            decision.admit()
        else:
            decision.reject()

        return decision.outcome


def decide_drop_column(
    proxy: CaptureProxy,
    recorder,
    target_urn: str,
    consumer_urn: str,
    at_ms: int | None = None,
    column: str = DEFAULT_COLUMN,
) -> str:
    """Decide whether to drop a column, recording why. Reads the aspect API."""
    read = proxy.call("get_lineage", consumer_urn, "upstreamlineage", at_ms=at_ms)
    return _record_decision(read, recorder, target_urn, consumer_urn, column)


async def decide_drop_column_mcp(
    proxy: McpCaptureProxy,
    recorder,
    target_urn: str,
    consumer_urn: str,
    column: str = DEFAULT_COLUMN,
) -> str:
    """The same decision, with the live MCP response as the decision input."""
    read = await proxy.call_lineage(consumer_urn)
    return _record_decision(read, recorder, target_urn, consumer_urn, column)
