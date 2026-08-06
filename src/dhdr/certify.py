"""The certifier.

Turns an RCDR record plus its captured reads into a capability class. It never
produces a score: a percentage over incommensurable kinds of missing evidence
manufactures exactly the false confidence this exists to prevent (invariant 2).
"""

from dataclasses import dataclass, field

from reckon import verify

from .proxy import CapturedRead

C3_BOUNDARY = (
    "C3 (State-Coupled Replay) is not certifiable. This decision mutates metadata "
    "a later decision reads; past the first flip this is counterfactual inference, "
    "not replay. Deductive evidence ends here."
)

SELF_WRITE_BOUNDARY = (
    "This agent published its own certificate to institutionalMemory. That write is state a "
    "later decision may read, so replay past this point is counterfactual inference, not "
    "replay. Deductive evidence ends at the publish step."
)

MISPAIRED_READS = (
    "the record names a revision that none of the supplied reads bound to; the record and the "
    "reads are not from the same decision and no capability class is certifiable"
)

UNSOUND_UNBOUND = (
    "a deciding read could not be bound to an aspect revision; "
    "no capability class is certifiable"
)


@dataclass
class Certificate:
    cls: str | None
    satisfied: bool
    missing: list[str] = field(default_factory=list)
    c3_boundary: str | None = None
    unbound_reads: int = 0

    def render(self) -> str:
        if self.unbound_reads:
            noun = "read" if self.unbound_reads == 1 else "reads"
            lines = [
                "Capability class: none",
                f"UNSOUND: {self.unbound_reads} deciding {noun} could not be bound to a "
                "revision. No class is certifiable — the record cannot name the world it "
                "was made in.",
            ]
        else:
            lines = [f"Capability class: {self.cls or 'none'}"]
        for item in self.missing:
            lines.append(f"Missing: {item}")
        if self.c3_boundary:
            lines.append(self.c3_boundary)
        return "\n".join(lines)


def _is_mispaired(record: dict, reads: list[CapturedRead]) -> bool:
    """True when the record was decided against a revision no supplied read saw.

    `certify` takes the record and the reads as two separate arguments, and
    nothing about the call obliges them to describe the same decision. Every
    individual piece can be honest while the assembly is wrong — which is the
    one way this design can be defeated from the caller's side, and it produces
    a certificate that looks clean.

    The record already names its revision, so the check needs no new capture:
    if `policy.resolution.revision` is present, some bound read must have
    resolved to it. A record with no revision is not checked — there is nothing
    to match, and the unbound read that caused it has already collapsed the
    class on its own.
    """
    revision = (record.get("policy") or {}).get("resolution", {}).get("revision")
    if revision is None:
        return False
    return not any(
        read.resolved and str(read.revision) == str(revision) for read in reads
    )


def certify(
    record: dict,
    reads: list[CapturedRead],
    *,
    requested: str = "C2",
    publish_events: list[dict] | None = None,
) -> Certificate:
    """Turn a record and its reads into a class — or into an explicit refusal.

    An unbound deciding read collapses the class to None rather than reporting a
    class alongside a warning (invariant 9). "C2, but one read is unbound" is
    precisely the phrasing a hurried reader takes as certification, and
    manufacturing that impression is the failure this exists to prevent.

    `publish_events` are the events emitted by `publish_certificate` on a
    successful write. A non-empty list means the agent mutated metadata a later
    decision may read, so the self-write boundary is appended (invariant 11).
    The boundary follows from a write that demonstrably happened; an empty list
    is evidence that nothing was written, and claims nothing.
    """
    report = verify(record, requested=requested)
    unbound = sum(1 for read in reads if not read.resolved)
    boundary = C3_BOUNDARY if requested == "C3" else None

    missing = list(report.missing)
    if publish_events:
        missing.append(SELF_WRITE_BOUNDARY)

    # Order matters, and property-based testing is what surfaced it. An unbound
    # read can never match the record's revision, so the pairing check fires on
    # it and reports "not from the same decision" when the truth is "the read
    # could not be dated at all". Both refuse, but only one of them is an honest
    # explanation — and a misleading reason on a refusal is its own small
    # version of the failure this project exists to prevent. Unbound wins.
    if not unbound and _is_mispaired(record, reads):
        return Certificate(
            cls=None,
            satisfied=False,
            missing=[MISPAIRED_READS, *missing],
            c3_boundary=boundary,
            unbound_reads=unbound,
        )

    if unbound:
        return Certificate(
            cls=None,
            satisfied=False,
            missing=[UNSOUND_UNBOUND, *missing],
            c3_boundary=boundary,
            unbound_reads=unbound,
        )

    return Certificate(
        cls=report.available,
        satisfied=report.satisfied,
        missing=missing,
        c3_boundary=boundary,
        unbound_reads=0,
    )
