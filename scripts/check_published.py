#!/opt/datahub-probe-venv/bin/python
"""Every certificate link on the Documentation tab must open. Check, don't assume.

Invariant 10 says the published artifact must resolve — institutional memory a
later human cannot open is not memory. The code enforces the *shape* of that
(an HTTPS URL, never a `dhdr://` scheme) but nothing enforces the *fact*, because
the artifact is served by GitHub Pages and reaching it needs a commit and a push
that happen outside this process.

So the invariant has been met, three times now, by someone remembering. Every
run that publishes — the demo, and the integration suite, which writes to the
same dataset — mints a URL whose artifact sits untracked in `docs/certs/` until
pushed. In between, the Documentation tab a reader opens contains dead links:
exactly the failure this project exists to name, on the screen that demonstrates
it.

This turns remembering into a check.

    python scripts/check_published.py            # the demo dataset
    python scripts/check_published.py <urn> …    # any entity

Exit 0 means every published link resolves. Non-zero lists the dead ones and
what to do, which is almost always: commit `docs/certs/` and push.
"""

import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/datahub-decision-records")

from dhdr.coordinate import DEFAULT_BASE_URL  # noqa: E402
from dhdr.publish import read_published  # noqa: E402

TIMEOUT_S = 20


def resolves(url: str) -> tuple[bool, str]:
    """Whether the artifact is actually fetchable, and what happened if not.

    A GET, not a HEAD: a static host can answer HEAD from a route that a GET
    then 404s, and the reader in the failure this checks for is doing a GET.
    """
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
            if response.status == 200:
                return True, "200"
            return False, str(response.status)
    except urllib.error.HTTPError as exc:
        return False, str(exc.code)
    except Exception as exc:  # network down, DNS, TLS — all mean "cannot open"
        return False, type(exc).__name__


def check(urn: str) -> list[tuple[str, str]]:
    published = read_published(urn) or {}
    elements = published.get("elements") or []
    if not elements:
        print(f"  no certificates published on {urn}")
        return []

    dead: list[tuple[str, str]] = []
    for element in elements:
        url = element.get("url", "")
        ok, why = resolves(url)
        if not ok:
            dead.append((url, why))
    print(f"  {len(elements) - len(dead)}/{len(elements)} resolve — {urn}")
    return dead


def main(argv: list[str]) -> int:
    from fixtures.seed import CONSUMER

    urns = argv[1:] or [CONSUMER]
    print(f"Checking published certificates against {DEFAULT_BASE_URL}")

    dead: list[tuple[str, str]] = []
    for urn in urns:
        dead.extend(check(urn))

    if not dead:
        print("\nevery published certificate resolves")
        return 0

    print(f"\n{len(dead)} DEAD LINK(S) — invariant 10 is not holding right now:")
    for url, why in dead:
        print(f"  {why}  {url}")
    print(
        "\nThese were published to DataHub but their artifacts are not reachable.\n"
        "Almost always this is an unpushed run:\n\n"
        "    git add docs/certs && git commit -m 'docs: publish certificate artifacts' && git push\n\n"
        "then wait for the Pages build and re-run this check."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
