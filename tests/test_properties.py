"""Property-based tests: search for the counterexample I did not think of.

The rest of the suite checks examples I chose. Choosing examples is exactly
where an author's blind spot lives — you test the cases your model predicts, so
a wrong model produces confidently passing tests. Hypothesis generates the
inputs instead, and shrinks any failure to its smallest form.

These target the pure logic — fact extraction, class assignment, the pairing
guard, change rendering — because that is where an invariant can be stated
crisply and checked over thousands of inputs. Nothing here touches DataHub, so
it runs anywhere in well under a second.
"""

import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dhdr.certify import MISPAIRED_READS, UNSOUND_UNBOUND, certify  # noqa: E402
from dhdr.coordinate import lineage_facts  # noqa: E402
from dhdr.proxy import CapturedRead  # noqa: E402
from dhdr.sarif import to_sarif  # noqa: E402
from scenarios.schema_ops import proposed_change  # noqa: E402

urns = st.text(min_size=1, max_size=40).map(lambda s: f"urn:li:dataset:({s},PROD)")


def _record(revision: str | None = "2", **over):
    resolution = {"provenance": "bundled"}
    if revision is not None:
        resolution["revision"] = revision
    base = {
        "execution": {"runtime": "cpython-3.12", "deps_digest": "d",
                      "path_digest": "p", "pure": True},
        "predicate": {"id": "pred-1"},
        "compared": {"value": 0},
        "policy": {"resolved_value": 0, "resolution": resolution},
        "candidates": {"completeness": "exhaustive",
                       "items": [{"compared_value": 0}, {"compared_value": 1}]},
    }
    base.update(over)
    return base


def _read(revision: int | None, resolved: bool = True) -> CapturedRead:
    return CapturedRead("get_lineage", "urn:x", "upstreamlineage", revision,
                        1 if resolved else None, {"upstreams": []}, resolved)


# ---------------------------------------------------------------- fact extraction


@given(st.lists(urns, max_size=8))
def test_lineage_facts_round_trips_the_aspect_shape(dataset_urns):
    """Whatever set of upstreams goes in comes back out, deduplicated."""
    payload = {"upstreams": [{"dataset": u, "type": "TRANSFORMED"} for u in dataset_urns]}
    assert lineage_facts(payload) == frozenset(dataset_urns)


@given(st.lists(urns, max_size=8))
def test_both_payload_shapes_yield_identical_facts(dataset_urns):
    """The MCP shape and the aspect shape must be indistinguishable downstream.

    This is the property the whole two-path design rests on: if these ever
    disagree, the same world produces different decisions depending on which
    API answered, and the scenario would silently depend on the transport.
    """
    aspect = {"upstreams": [{"dataset": u} for u in dataset_urns]}
    mcp = {"upstreams": {"total": len(dataset_urns),
                         "searchResults": [{"entity": {"urn": u}} for u in dataset_urns]}}
    assert lineage_facts(aspect) == lineage_facts(mcp)


@given(st.dictionaries(st.text(max_size=5), st.text(max_size=5), max_size=4))
def test_fact_extraction_never_raises_on_junk(junk):
    """A malformed payload must produce empty facts, never an exception.

    An extractor that throws turns an unusual response into a crash rather than
    an honest 'unbound'.
    """
    assert isinstance(lineage_facts(junk), frozenset)


# ---------------------------------------------------------------- certification


@given(st.integers(min_value=1, max_value=6), st.integers(min_value=0, max_value=6))
@settings(max_examples=60)
def test_any_unbound_read_collapses_the_class(unbound_count, bound_count):
    """Invariant 9, over every mix: one unbound read is enough to refuse.

    No combination of bound reads can outvote an unbound one.
    """
    reads = [_read(2) for _ in range(bound_count)] + [_read(None, False) for _ in range(unbound_count)]
    cert = certify(_record(), reads, requested="C2")
    assert cert.cls is None
    assert cert.satisfied is False
    assert cert.unbound_reads == unbound_count
    assert UNSOUND_UNBOUND in cert.missing


@given(st.integers(min_value=1, max_value=200), st.integers(min_value=1, max_value=200))
@settings(max_examples=60)
def test_a_record_never_certifies_against_reads_from_another_decision(record_rev, read_rev):
    """The pairing guard, over arbitrary revision pairs.

    Equal revisions may certify; different ones must never.
    """
    cert = certify(_record(revision=str(record_rev)), [_read(read_rev)], requested="C2")
    if record_rev == read_rev:
        assert MISPAIRED_READS not in cert.missing
    else:
        assert cert.cls is None
        assert MISPAIRED_READS in cert.missing


@given(st.sampled_from(["C0", "C1", "C2", "C3", None]), st.booleans())
@settings(max_examples=40)
def test_a_certificate_never_renders_a_percentage(cls, strict):
    """Invariant 2 as a property rather than one example."""
    from dhdr.certify import Certificate

    cert = Certificate(cls, cls is not None)
    assert "%" not in cert.render()
    import json

    assert "%" not in json.dumps(to_sarif(cert, path="a.sql", strict=strict))


# ---------------------------------------------------------------- change artifact


@given(st.text(min_size=1, max_size=30).filter(lambda s: s.strip()),
       st.sampled_from(["admit", "reject"]))
@settings(max_examples=60)
def test_the_proposed_change_never_claims_to_have_been_applied(column, outcome):
    """The scope invariant: dhdr proposes, never applies.

    Whatever the column name or outcome, the artifact must say so and must not
    grow an execution path.
    """
    change = proposed_change("urn:li:dataset:(x,tbl,PROD)", column,
                             outcome=outcome, consumers=("urn:li:dataset:(x,c,PROD)",))
    assert change.applied is False
    assert "proposed" in change.render().lower()
    assert not hasattr(change, "apply") and not hasattr(change, "execute")


@given(st.text(min_size=1, max_size=30).filter(lambda s: s.strip()))
@settings(max_examples=60)
def test_a_refusal_never_proposes_a_destructive_change(column):
    """If the drop is refused, the artifact must not contain a DROP.

    The one way the change artifact could actively cause harm is by emitting
    destructive DDL on the path that exists to prevent it.
    """
    change = proposed_change("urn:li:dataset:(x,tbl,PROD)", column,
                             outcome="reject", consumers=("urn:li:dataset:(x,c,PROD)",))
    assert "DROP COLUMN" not in change.statement.upper()
