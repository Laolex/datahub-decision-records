"""Scenario 2 — access and governance.

The agent decides whether to grant access to a dataset. The deciding input is
governance metadata: while the dataset carries no restricted term, access is
allowed; once a PII term is applied, the same request is refused.

The point of a second scenario is not a second feature. It is evidence for
invariant 4 — that the capture core is domain-ignorant. This module reads a
different aspect, applies a different predicate, and decides about a different
thing, and it does so **without a single change to `coordinate.py`, `proxy.py`
or `certify.py`**. If a new domain had required the core to learn about glossary
terms, the core would have been wrong.

Note what is deliberately not claimed. This is a governance *signal* check, not
an authorization system: it asks whether the metadata that justified a grant has
moved since, which is a different and smaller question than whether the grant
was correct.
"""

from dhdr.proxy import CaptureProxy, CapturedRead

MAX_RESTRICTED_TERMS = 0
RESTRICTED_TERMS = frozenset(
    {"urn:li:glossaryTerm:b2fd91.1598cf93-c199-43a1-8833-fce96faa9a1a"}  # "PII"
)


def restricted_terms(payload: dict) -> frozenset[str]:
    """The restricted glossary terms carried by a `glossaryTerms` payload.

    Lives here rather than in `coordinate.py` on purpose. Knowing what a
    glossary term is, and which ones restrict access, is domain knowledge; the
    core takes an extractor as an argument precisely so it never has to hold
    any.
    """
    terms = (payload or {}).get("terms") or []
    urns = {t.get("urn") for t in terms if isinstance(t, dict) and t.get("urn")}
    return frozenset(urns & RESTRICTED_TERMS)


def decide_grant_access(
    proxy: CaptureProxy,
    recorder,
    dataset_urn: str,
    at_ms: int | None = None,
) -> str:
    """Decide whether to grant access, recording which revision justified it."""
    read = proxy.call("get_entities", dataset_urn, "glossaryterms", at_ms=at_ms)
    return _record_decision(read, recorder, dataset_urn)


def _record_decision(read: CapturedRead, recorder, dataset_urn: str) -> str:
    found = restricted_terms(read.value)
    restricted_count = len(found)
    source = f"datahub:{dataset_urn}#glossaryterms"

    with recorder.decision(
        action="grant_access", params={"dataset": dataset_urn}, pure=True
    ) as decision:
        decision.policy(
            "max_restricted_terms",
            value=MAX_RESTRICTED_TERMS,
            provenance="bundled" if read.resolved else "unknown",
            source=source,
            revision=str(read.revision) if read.resolved else None,
        )
        decision.read(
            "restricted_terms",
            restricted_count,
            f"{source}@v{read.revision}" if read.resolved else f"{source}@unbound",
        )

        allowed = decision.check(
            "lte",
            left="restricted_terms",
            value=restricted_count,
            right="max_restricted_terms",
        )
        predicate_id = decision.predicate.id

        decision.candidate(
            "grant_access",
            compared_value=restricted_count,
            outcome="admit" if allowed else "reject",
            predicate=predicate_id,
        )
        decision.candidate(
            "require_review",
            compared_value=restricted_count,
            outcome="reject" if allowed else "admit",
            predicate=predicate_id,
        )
        decision.candidates_exhaustive()

        if allowed:
            decision.admit()
        else:
            decision.reject()

        return decision.outcome
