# dhdr — decision records for DataHub agents

An agent that makes schema, access and triage decisions from DataHub context — lineage,
ownership, glossary terms — and can prove **which version of that context justified each
decision**.

Reading metadata to decide something is the easy half. The hard half arrives later, when
someone asks why the agent allowed a column drop that broke a dashboard. The lineage has
moved since. The log says "no consumers found", and there is nothing in it that says whether
that was true at the time or merely true of a stale read. `dhdr` closes that: every context
read an agent performs is bound to the metadata revision in force when the read happened, and
a decision whose reads cannot be bound is reported as certifying nothing rather than as
passing.

Built for **Build with DataHub — The Agent Hackathon**, track *Agents That Do Real Work*.

**Walkthrough with real output: https://laolex.github.io/datahub-decision-records/** — every
block on that page was produced by the code here, against a live DataHub Core instance.

> **Status.** The capture core, revision binding, the schema-ops agent, the certifier,
> write-back and the demo CLI are built and tested against a live DataHub Core v1.5.0.6
> instance, and everything in `examples/` was produced by running them. Nothing here claims a
> result it has not produced.

## The design law

*A record that cannot name the revision it was made against is not a record of a decision.*

And its companion, which is why this ships as something a team installs rather than a demo:

*A record nobody keeps certifies nothing. Soundness that is not installed is not soundness.*

## How it works

Four units, each independently testable.

**The context proxy** (`src/dhdr/proxy.py`) sits between the agent and DataHub's MCP server.
It forwards every tool call over real MCP transport and returns *the MCP response itself* to
the agent — that response, and nothing else, is the decision input. A re-fetched value is
never substituted for it, however similar; between two fetches the metadata may have moved,
and then the revision on the record is not the revision that decided.

**Revision binding** (`src/dhdr/coordinate.py`) resolves the aspect version in force at the
instant the response was received, via `GET /openapi/v2/entity/{type}/{urn}/{aspect}?version=N`
and `systemMetadata.lastObserved`. Proximity in time only *proposes* a candidate. The deciding
facts extracted from the MCP response and from the aspect must then agree before a binding is
made. Zero matches means a write landed between the agent's read and ours; more than one means
the facts do not discriminate. Both are **unbound**, and an unbound deciding read collapses the
capability class to none — never "C2, but one read is unbound", which is exactly the phrasing a
hurried reader takes as certification.

**The recorded agent** (`scenarios/schema_ops.py`) decides whether dropping a column is safe,
over real datasets from DataHub's `showcase-ecommerce` datapack, emitting a
[Reckon](https://pypi.org/project/reckon-rcdr/) decision record as it goes. It reads the same
lineage either through MCP or through the aspect API and records the decision identically, so
the scenario is not written twice and cannot drift between the two.

**The certifier** (`src/dhdr/certify.py`) reports a capability class — C0 identity, C1 tightening, C2
loosening, C3 state-coupled — never a percentage. A score over incommensurable kinds of
missing evidence manufactures false confidence. C3 is certified as a *boundary*: where a
decision mutates metadata a later decision reads, the certificate states where deductive
evidence ends and counterfactual inference begins, and claims nothing past that line.

**Write-back** (`src/dhdr/publish.py`) puts the certificate into the dataset's
`institutionalMemory`, so the next agent or engineer inherits what was decided, against which
revision, and how far the evidence went — without rerunning anything. The description is a
summary; the URL is the artifact, and it must be resolvable HTTPS, because institutional memory
a later human cannot open is not memory. The agent's own write is itself state a later decision
may read, so it is surfaced as a C3 boundary — derived from a recorded publish event, never from
a flag the caller passed.

One limitation stated plainly, because the alternative would be the failure this project is
about. The write is **not atomic**. On DataHub Core v1.5.0.6 neither available mechanism works
for this aspect: `If-Version-Match` is documented as an optimistic-concurrency precondition but
is not enforced on the write endpoint — a stale-version write returns 200 and overwrites — and
server-side JSON patch has no template registered for `institutionalMemory`, though it does for
`globalTags` and `upstreamLineage`. What this module does is read-append-write with a verified
read-back: it carries forward every element it saw and retries if its own element did not land.
That preserves anything written before it read, and detects being overwritten. It does not close
the race where another writer lands between our read and our write. Both facts are pinned by
tests that fail if the platform starts supporting either mechanism.

The capture core is domain-ignorant by construction. It knows about reads, versions,
predicates and candidate sets. It does not know what a schema, an owner or a pipeline is. If a
scenario requires a change to the core, the core is wrong.

## Why the coordinate has to be recovered

DataHub the platform maintains this coordinate already — versioned aspects keyed by version
number, the Timeline API over entity change history, `If-Version-Match` on
`/v3/entity/{entityName}/batchGet`. What the agent-facing read tools return does not carry it
through, so a read silently resolves to *now*. The evidence needed to bind a decision is
therefore already stored and one API away; this project binds it to the decision rather than
adding anything new to the platform.

That is the reason the provenance layer had to exist, not the pitch. The pitch is the agent.

## Running the tests

Requires a live DataHub Core instance at `localhost:8080` for the integration tests.

```bash
pip install -e '.[dev]'
DATAHUB_GMS_URL=http://localhost:8080 python -m pytest -v
```

See the two decisions for yourself:

```bash
python -m dhdr.cli
```

```
=== as the agent saw it ===
outcome:  admit
revision: v131  (lastObserved=1785837756441)
Capability class: C2

=== as it actually was ===
outcome:  reject
revision: v132  (lastObserved=1785837761548)
Capability class: C2

Same agent. Same call. Opposite decisions.
The log cannot tell you which world it was made in. The certificate can.
```

42 tests currently pass. The ones worth knowing about:

- the agent calls `get_lineage` through the real MCP server, decides `admit`, and then — after a
  pipeline change wires a consumer to the table — makes the identical call and decides `reject`,
  with the two records naming different revisions;
- an MCP read binds with `value_source == "mcp"`, proving the decision input was the protocol
  response rather than a re-fetch;
- a mismatched payload is left unbound rather than guessed;
- history survives DataHub's retention pruning the oldest aspect versions.

Note that the flip test needs GMS's lineage cache disabled
(`CACHE_SEARCH_LINEAGE_TTL_SECONDS=0`). With the shipped default a lineage change reaches the
graph index in seconds but stays invisible to `get_lineage` for hours, and the test times out
rather than passing on stale context.

## As a CI gate, not only a CLI

A certificate printed by a CLI is read once, by the person who ran it. A certificate that arrives
as an annotation on a pull request is read by whoever is about to merge — the moment it can still
change something. That is the second design law doing work: *a record nobody keeps certifies
nothing.*

```bash
python -m dhdr.cli sarif --path pipelines/orders.sql > dhdr.sarif
```

The output is SARIF 2.1.0 ([`examples/decision.sarif.json`](examples/decision.sarif.json)), which
any code host ingests. SARIF's `level` is ordinal — `none`, `note`, `warning`, `error` — so the
capability classes map onto it directly and nobody has to invent a percentage on the way:

| class | level |
|---|---|
| C0, C1 | `note` |
| C2 | `warning` |
| C3 | `error` |
| unsound (any unbound read) | `warning`, or `error` under `--strict` |

Note that last row. **Unsoundness fails open by default.** A gate that blocks a merge because of
a gap in its own instrumentation gets uninstalled inside a week, and an uninstalled gate
certifies nothing at all. `--strict` fails closed for teams that have decided they want that, and
only then does the command exit non-zero.

## Ablation

Remove one captured field at a time and see what the certifier can still claim. An entry that
cannot show which part of its own record is load-bearing has not demonstrated that the record is
necessary. Reproduce with `pytest tests/test_ablation.py -s`.

```
removed                        class still available
(none — full record)           C2
execution.pure                 none
predicate.id                   C0
policy.resolved_value          C0
candidates.completeness        C1
policy.resolution.revision     C2
read binding (unbound read)    none
```

The fifth row is the one worth reporting, and it is not flattering: **deleting the revision from
the record costs nothing.** The underlying verifier has no concept of a DataHub aspect version,
so a record carrying a revision and a record missing one certify identically. The revision in the
record is documentation for whoever reads it later. It is not evidence, and it does not defend
itself.

What is load-bearing is the last row — the binding. A read that could not be tied to a revision
collapses the class to none. So this project's contribution to soundness is the *refusal*: the
value is in declining to certify a decision whose world cannot be named, not in annotating a
record with a version string. Both results are pinned by tests, so if the upstream verifier ever
starts checking the revision, this section is what breaks.

## Upstream

Two findings from this build were filed back, both reproducible on DataHub Core v1.5.0.6:

- [acryldata/mcp-server-datahub#181](https://github.com/acryldata/mcp-server-datahub/issues/181)
  — an optional point-in-time parameter for context reads. No read tool accepts a version or
  timestamp, and no shipped GraphQL selection requests `systemMetadata`, so a read resolves to
  *now* and the response carries nothing that dates it. The proposal defaults to current so
  nothing breaks, with a smaller fallback (echo the resolved version in responses) that needs no
  time travel at all. This is the gap the whole project works around.
- [datahub-project/datahub#18851](https://github.com/datahub-project/datahub/issues/18851)
  — `institutionalMemory` has no registered patch template, so `PATCH` fails with a null-template
  `NullPointerException`. Eight other dataset aspects handle the same request, so it is a
  per-aspect gap. This is the reason write-back here is read-append-write rather than an atomic
  append.

## Reproduce

Everything in [`examples/`](examples/) is a real artifact produced by the code in this repo, not
a description of one — two decision records, their certificates, the demo transcript, the live
MCP flip, the ablation table, and what a later reader inherits from `institutionalMemory`.
Regenerate all of it with one command against a live instance:

```bash
python scripts/generate_examples.py
```

### The world

Verified against **DataHub Core v1.5.0.6**, `mcp-server-datahub` 0.6.0, `acryl-datahub` 1.6.0.17.

The scenario decides over real datasets from DataHub's own `showcase-ecommerce` datapack, not
invented URNs — MCP resolves upstreams that exist *as entities*, so a fabricated URN produces a
demo that silently binds to nothing. Note that `datahub datapack load showcase-ecommerce` does
**not** fetch the real pack (it writes ~54 bundled records and reports success), so fetch it
directly and filter the DataHub Cloud aspects that Core's GMS rejects with a 422:

```bash
mkdir -p datapack && cd datapack
for f in 01-definitions 02-data 03-context; do
  curl -sL "https://raw.githubusercontent.com/datahub-project/static-assets/main/datapacks/showcase-ecommerce/$f.json" -o "$f.json"
done

python - <<'PY'
import json
CLOUD_ONLY = {"testResults", "lineageFeatures", "entityInferenceMetadata",
              "usageFeatures", "documentation"}
records = json.load(open("02-data.json"))
keep = [r for r in records
        if r.get("entityType") == "dataset" and r.get("aspectName") not in CLOUD_ONLY]
json.dump(keep, open("02-datasets.json", "w"))
print(f"dataset records kept: {len(keep)}")
PY

cat > recipe-ds.yml <<'YML'
source:
  type: file
  config:
    path: ./02-datasets.json
sink:
  type: datahub-rest
  config:
    server: http://localhost:8080
YML
datahub ingest -c recipe-ds.yml
```

### One required setting

GMS caches lineage search results with a shipped default TTL of a day, and MCP `get_lineage`
reads through that cache — so a lineage change reaches the graph index within seconds and stays
invisible to the agent for hours. The flip depends on the world moving between two reads, so set
`CACHE_SEARCH_LINEAGE_TTL_SECONDS=0` on GMS. With it off, MCP reflects a change in about three
seconds; with it on, the flip test times out rather than passing on stale context.

## Pre-existing work

Per the hackathon rules, what was not built during the submission window:

- **[`reckon-rcdr`](https://pypi.org/project/reckon-rcdr/) 0.1.1** — my own decision-record
  format and verifier, published before this event. It supplies the record schema and the
  capability classes (C0–C3). It knows nothing about DataHub. Everything that binds a record to
  a metadata revision is new here, and the [ablation](#ablation) reports honestly that the
  revision field is inert to the upstream verifier — the binding check in this repo is what
  carries the soundness.
- **`acryl-datahub` 1.6.0.17** and **`mcp-server-datahub` 0.6.0** — DataHub's own SDK and MCP
  server, unmodified dependencies.

Written during the window: the capture proxy, revision binding, the schema-ops agent, the
certifier, write-back, the ablation, the CLI, and the two upstream issues.

## Invariants

The full set of eleven invariants — the properties that must hold when every line of this
implementation has been replaced — are enumerated in the design document and summarised above.
The two that constrain the most code: the decision input is the response the agent received,
and absence of evidence is recorded as absence (a field that was not captured is
distinguishable in the ledger from a field captured as empty).

## Non-goals

Not a data quality product, not a lineage product, not a policy engine. `dhdr` does not decide
whether an agent's action was correct — only whether the record supports asking.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
