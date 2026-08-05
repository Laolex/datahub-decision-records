#!/opt/datahub-probe-venv/bin/python
"""One command from a running DataHub to a certified decision.

    python scripts/quickstart.py

Checks the instance, ingests the `showcase-ecommerce` datasets if they are not
already there, verifies the one setting this demonstration depends on, and then
runs the demo. Safe to re-run: the ingest is skipped when the entities exist.

What it deliberately does *not* do is start DataHub for you. Bringing up the
stack is `docker compose up` in DataHub's own quickstart, and doing it from here
would mean guessing at your compose file. See `quickstart/docker-compose.override.yml`
for the two settings to apply when you do.
"""

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GMS = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
DATAPACK = "https://raw.githubusercontent.com/datahub-project/static-assets/main/datapacks/showcase-ecommerce"

# Aspects the DataHub Cloud datapack carries that Core's GMS rejects with a 422.
CLOUD_ONLY = {
    "testResults",
    "lineageFeatures",
    "entityInferenceMetadata",
    "usageFeatures",
    "documentation",
}


def step(n: int, text: str) -> None:
    print(f"\n[{n}/4] {text}")


def fail(msg: str) -> None:
    raise SystemExit(f"\n  ✗ {msg}\n")


def gms_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{GMS}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def dataset_exists(urn: str) -> bool:
    enc = urllib.parse.quote(urn, safe="")
    try:
        with urllib.request.urlopen(
            f"{GMS}/openapi/v3/entity/dataset/{enc}/datasetkey", timeout=15
        ) as r:
            return r.status == 200
    except Exception:
        return False


def ingest_datapack() -> None:
    work = REPO / "datapack"
    work.mkdir(exist_ok=True)

    # `datahub datapack load showcase-ecommerce` does NOT fetch the real pack —
    # it writes ~54 bundled records and reports success. Fetch it directly.
    raw = work / "02-data.json"
    if not raw.exists():
        print("      downloading the datapack …")
        urllib.request.urlretrieve(f"{DATAPACK}/02-data.json", raw)

    records = json.loads(raw.read_text())
    keep = [
        r
        for r in records
        if r.get("entityType") == "dataset" and r.get("aspectName") not in CLOUD_ONLY
    ]
    filtered = work / "02-datasets.json"
    filtered.write_text(json.dumps(keep))
    print(f"      {len(keep)} dataset records to ingest")

    recipe = work / "recipe-ds.yml"
    recipe.write_text(
        "source:\n"
        "  type: file\n"
        "  config:\n"
        f"    path: {filtered}\n"
        "sink:\n"
        "  type: datahub-rest\n"
        "  config:\n"
        f"    server: {GMS}\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "datahub", "ingest", "-c", str(recipe)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(
            "datapack ingest failed:\n"
            + (result.stderr or result.stdout)[-1500:]
            + "\n  Is `acryl-datahub` installed? `pip install -e '.[dev]'`"
        )


def main() -> int:
    print("dhdr quickstart — from a running DataHub to a certified decision")

    step(1, f"checking DataHub at {GMS}")
    if not gms_is_up():
        fail(
            f"no DataHub at {GMS}.\n"
            "  Start it with DataHub's quickstart, applying the two settings in\n"
            "  quickstart/docker-compose.override.yml (the lineage cache must be off).\n"
            "  Then re-run this."
        )
    print("      up")

    step(2, "seeding DataHub's showcase-ecommerce datasets")
    from fixtures.seed import CONSUMER, TARGET

    if dataset_exists(CONSUMER) and dataset_exists(TARGET):
        print("      already present — skipping ingest")
    else:
        ingest_datapack()
        if not (dataset_exists(CONSUMER) and dataset_exists(TARGET)):
            fail("ingest ran but the showcase datasets are still missing.")
        print("      ingested")

    step(3, "verifying the instance can actually demonstrate the flip")
    check = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "preflight.py")],
        capture_output=True,
        text=True,
    )
    print("      " + "\n      ".join(check.stdout.strip().splitlines()[-3:]))
    if check.returncode != 0:
        fail(
            "preflight failed — see above. Almost always the GMS lineage cache:\n"
            "  set CACHE_SEARCH_LINEAGE_TTL_SECONDS=0 and restart GMS."
        )

    step(4, "running the demo")
    print()
    demo = subprocess.run(
        [sys.executable, "-m", "dhdr.cli", "demo", "--reset"], cwd=REPO
    )
    if demo.returncode != 0:
        fail("the demo exited non-zero — see above.")

    print(
        "\nThat is the whole claim: the same call through the same MCP server, decided\n"
        "both ways, each bound to the revision that justified it and written back into\n"
        "DataHub. Sample artifacts without running anything: examples/\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
