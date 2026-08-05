"""Certificate -> SARIF 2.1.0.

SARIF is the right carrier because its `level` is ordinal — none / note / warning
/ error — so capability classes map onto it without anyone inventing a
percentage along the way (invariant 2).

The reason this exists at all is the second design law: *a record nobody keeps
certifies nothing.* A certificate printed by a CLI is read once by the person who
ran it. A certificate that arrives as an annotation on a pull request is read by
whoever is about to merge, which is the moment it can still change something.

Note the default. A gate that blocks a merge because of a gap in its own
instrumentation gets uninstalled inside a week, and an uninstalled gate certifies
nothing at all. So unsoundness fails **open**, loudly, by default; `strict=True`
fails closed for teams that have decided they want that.
"""

from .certify import Certificate

SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"

LEVELS = {"C0": "note", "C1": "note", "C2": "warning", "C3": "error"}

RULE_CERTIFIED = "dhdr/decision-certified"
RULE_UNSOUND = "dhdr/decision-unsound"

RULES = [
    {
        "id": RULE_CERTIFIED,
        "name": "DecisionCertified",
        "shortDescription": {"text": "Agent decision bound to a metadata revision"},
        "fullDescription": {
            "text": (
                "Every context read behind this decision was bound to the DataHub aspect "
                "revision in force when the read happened. The level reflects the capability "
                "class, which is ordinal and is never a score."
            )
        },
        "defaultConfiguration": {"level": "warning"},
    },
    {
        "id": RULE_UNSOUND,
        "name": "DecisionUnsound",
        "shortDescription": {"text": "Agent decision could not be bound to a revision"},
        "fullDescription": {
            "text": (
                "At least one deciding read could not be tied to an aspect revision, so no "
                "capability class is certifiable — the record cannot name the world it was "
                "made in. Reported at warning by default so a gap in instrumentation does "
                "not block a merge; run strict to fail the build instead."
            )
        },
        "defaultConfiguration": {"level": "warning"},
    },
]


def _message(
    cert: Certificate,
    outcome: str | None,
    revision: int | None,
    dataset: str | None,
    change: str | None,
) -> str:
    """The certificate, led by the decision it is about when that is known."""
    if outcome is None and revision is None and dataset is None and change is None:
        return cert.render()

    head = []
    if outcome is not None:
        table = dataset.split(",")[1] if dataset and "," in dataset else dataset
        against = f" against {table}" if table else ""
        at = f" at revision v{revision}" if revision is not None else ""
        head.append(f"Decision: {outcome}{against}{at}")
    elif revision is not None:
        head.append(f"Revision: v{revision}")
    if change:
        head.append(f"Proposed: {change}")

    return "\n".join([*head, "", cert.render()])


def to_sarif(
    cert: Certificate,
    *,
    path: str,
    strict: bool = False,
    outcome: str | None = None,
    revision: int | None = None,
    dataset: str | None = None,
    change: str | None = None,
) -> dict:
    """Render one certificate as a SARIF 2.1.0 document.

    The optional decision context is what makes the annotation actionable. A
    reader on a pull request has the diff and nothing else; a bare capability
    class is a grade with no subject. When supplied, the message leads with what
    was decided, about which dataset, against which revision, and the change
    being proposed.
    """
    unsound = cert.cls is None or bool(cert.unbound_reads)

    if unsound:
        rule_id = RULE_UNSOUND
        level = "error" if strict else "warning"
    else:
        rule_id = RULE_CERTIFIED
        level = LEVELS.get(cert.cls, "warning")

    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "dhdr",
                        "informationUri": "https://github.com/Laolex/datahub-decision-records",
                        "rules": RULES,
                    }
                },
                "results": [
                    {
                        "ruleId": rule_id,
                        "level": level,
                        # The rendered certificate is the message. It already leads
                        # with the class or with UNSOUND, and carries the C3
                        # boundary and every missing item — which is exactly what a
                        # reviewer needs in the one line a code host shows them.
                        "message": {"text": _message(cert, outcome, revision, dataset, change)},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": path},
                                    "region": {"startLine": 1},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }
