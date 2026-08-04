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
