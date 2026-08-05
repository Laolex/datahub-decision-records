# dhdr — decision records for DataHub agents

**In plain terms, before any jargon.**

A company's data lives in thousands of tables. Some of those tables feed dashboards that people
make decisions from. An engineer wants to delete a column from one of them, and needs to know
first: is anything still using it?

An AI agent can answer that. It looks up what depends on the table, finds nothing, and says the
deletion is safe. It writes down its reasoning. So far so good.

Three weeks later a dashboard is broken and someone asks why the agent allowed it. They open the
note the agent wrote. It says *"nothing was using it."* But the answer to that question changes
over time — something may have started using the table an hour before the agent looked, or an
hour after. **The note doesn't say which version of the world it was describing.** So nobody can
tell whether the agent was wrong, or whether it was right about a world that had already changed.

That is the whole problem this project fixes. Every time the agent looks something up, we record
*exactly which version* of the company's records it saw — not just what it saw. Now the note
reads "nothing was using it, according to version 461, recorded at 22:24:56", and the question is
answerable. And when we can't establish which version the agent saw, we say so and refuse to
vouch for the decision, rather than issuing a clean-looking approval.

The demo shows one agent making the identical request twice, seconds apart, while someone changes
a data pipeline in between — and reaching opposite conclusions. The two notes look the same. Only
our record can tell you which world each was made in.

---

**The same thing, for a data engineer.** An agent that makes schema and access decisions
from DataHub context — lineage, ownership, glossary terms — and can prove **which version of that
context justified each decision**.

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

## Quickstart

**Three ways in, cheapest first.**

**1. Read the outputs — no setup at all.** [`examples/`](examples/) holds real artifacts from a
real run: both decision records, both certificates, the live MCP transcript, the SARIF the CI gate
uploads, the ablation table, and what a later reader inherits from `institutionalMemory`. The
[hosted walkthrough](https://laolex.github.io/datahub-decision-records/) shows the same with
commentary, and the certificate links on it resolve.

**2. Run the code — no DataHub needed, about a minute.** The unit tests cover the certifier, the
SARIF mapping, the change artifact and the ablation, none of which touch a live instance:

```bash
git clone https://github.com/Laolex/datahub-decision-records && cd datahub-decision-records
pip install -e '.[dev]'
pytest -q          # 22 passed, 32 skipped — the skipped ones need a live DataHub
```

The tests that *do* need DataHub skip by marker rather than failing, so a green run here means
something.

One caveat if you go on to run the integration tests: they **mutate lineage on the instance**,
because demonstrating that a decision flips requires the world to actually move. Two suites
running against the same DataHub at once will fight over that state and produce a spurious
failure. One suite per instance. This includes the ablation, which is the part that reports honestly on what is and is
not load-bearing in this design.

**3. The whole thing against a live DataHub.** From a running instance to a certified decision, in
one command:

```bash
pip install -e '.[dev]'
python scripts/quickstart.py
```

It checks the instance, ingests DataHub's `showcase-ecommerce` datasets if they are not already
there, verifies the one setting this depends on, and runs the demo. Safe to re-run.

**Starting DataHub is the one step it does not do for you** — that is `docker compose up` in
DataHub's own quickstart, and guessing at your compose file would be worse than asking. Copy
[`quickstart/docker-compose.override.yml`](quickstart/docker-compose.override.yml) next to it
first; it sets the one required setting and closes a security hole in the stock compose file
(every service, including an unauthenticated OpenSearch, is published on `0.0.0.0`).

The one required setting, if you would rather apply it by hand: **`CACHE_SEARCH_LINEAGE_TTL_SECONDS=0`**
on GMS. Its shipped default is a day, and MCP `get_lineage` reads through that cache — so a
lineage change reaches the graph index in seconds and stays invisible to the agent for hours,
and the demonstration times out rather than passing on stale context.

Expect the DataHub bring-up itself to dominate the wall clock on a cold machine; everything after
it is seconds.

## The design law

*A record that cannot name the revision it was made against is not a record of a decision.*

And its companion, which is why this ships as something a team installs rather than a demo:

*A record nobody keeps certifies nothing. Soundness that is not installed is not soundness.*

## How it works

Five units, each independently testable.

**The context proxy** (`src/dhdr/proxy.py`) sits between the agent and DataHub's MCP server.
It forwards every tool call over real MCP transport and returns *the MCP response itself* to
the agent — that response, and nothing else, is the decision input. A re-fetched value is
never substituted for it, however similar; between two fetches the metadata may have moved,
and then the revision on the record is not the revision that decided.

**Revision binding** (`src/dhdr/coordinate.py`) resolves the aspect version in force at the
instant the response was received, via `GET /openapi/v3/entity/{type}/{urn}/{aspect}?version=N`
and `systemMetadata.lastObserved`. Proximity in time only *proposes* a candidate. The deciding
facts extracted from the MCP response and from the aspect must then agree before a binding is
made. Zero matches means a write landed between the agent's read and ours; more than one means
the facts do not discriminate. Both are **unbound**, and an unbound deciding read collapses the
capability class to none — never "C2, but one read is unbound", which is exactly the phrasing a
hurried reader takes as certification.

**The change artifact.** A verdict nobody can act on is not much use, so each decision carries
the concrete change it is about: `ALTER TABLE … DROP COLUMN promo_code;` when the drop is
allowed, and a deprecation comment naming the consumer that still reads it when it is refused. A
refusal that proposes the safe alternative is the part that does real work. The artifact is
**proposed and never applied** — `dhdr` decides and records, it does not run migrations, and
there is deliberately no code here that would. The record commits to it by `params_digest`, so
the certificate names which change it certified without carrying a copy that could drift.

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

It also refuses a pairing it cannot justify. `certify` receives the record and the captured
reads as separate arguments, and nothing about the call obliges them to describe the same
decision — every individual piece can be honest while the assembly is wrong, which produces a
clean-looking certificate over a decision that never happened. So the record's revision must
match a revision some supplied read actually bound to, or the class collapses to none. That
check needs no extra capture: the record already names the revision it was decided against.

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

**A second scenario tests that claim rather than asserting it.**
`scenarios/access.py` decides whether to grant access to a dataset, flipping when a PII
glossary term is applied — a different aspect, a different predicate, a different question. It
required no change to `proxy.py` or `certify.py`, and the knowledge of which glossary terms
restrict access lives in the scenario, because the core takes an extractor as an argument
precisely so it never has to hold any.

It did force one change, and it is the reason a second domain was worth building: `read_aspect`
was reading through the openapi **v2** endpoint, which returns 400 for `glossaryTerms`,
`institutionalMemory` and `status` on Core v1.5.0.6 — it fails to deserialise its own
`SystemMetadata` — while handling `upstreamLineage` fine. A lineage-only suite reports a healthy
coordinate layer that cannot read three aspects at all, with `history()` coming back empty and
every read binding to nothing, silently. That is now a v3 read, with a regression test that
exercises a non-lineage aspect.

## Scenarios

Two, both deciding over real `showcase-ecommerce` entities:

| scenario | reads | flips when |
|---|---|---|
| `scenarios/schema_ops.py` — is dropping this column safe? | `upstreamLineage` | a pipeline wires a consumer to the table |
| `scenarios/access.py` — should this access request be granted? | `glossaryTerms` | a PII term is applied to the dataset |

A third was designed — incident triage over data-quality assertions — and is deliberately **not**
built. It needs `get_dataset_assertions`, which is not reachable on DataHub Core: the OSS server
registers eight tools and that is not among them, because the tool sits behind
`DATA_QUALITY_TOOLS_ENABLED` (default off) *and* a DataHub Cloud version gate. Building it anyway
would have meant reading assertions by a route the agent surface does not offer — the opposite of
this project's argument.

## Why the coordinate has to be recovered

DataHub the platform maintains this coordinate already — versioned aspects keyed by version
number, the Timeline API over entity change history, `If-Version-Match` on
`/v3/entity/{entityName}/batchGet`. What the agent-facing read tools return does not carry it
through, so a read silently resolves to *now*. The evidence needed to bind a decision is
therefore already stored and one API away; this project binds it to the decision rather than
adding anything new to the platform.

That is the reason the provenance layer had to exist, not the pitch. The pitch is the agent.

### What changes if the version coordinate ships upstream

Worth stating plainly, because a thesis that depends on a gap staying open is a fragile one, and
[#181](https://github.com/acryldata/mcp-server-datahub/issues/181) is a request for that gap to
close.

**Almost all of this survives, and the part that goes away is the part we would most like to
lose.** If `get_lineage` grew an `as_of` parameter tomorrow — or merely echoed
`systemMetadata.version` in its response — the *acquisition* of the coordinate would get simpler
and better: the fact-matching in `coordinate.py` exists only because the response cannot date
itself, and a read that carries its own version needs no matching at all. That is a workaround
retiring, which is what a workaround is for.

What does not change is everything downstream of having the coordinate: binding it to the
decision, refusing to certify when it cannot be bound, reporting a capability class rather than a
percentage, declaring the C3 boundary where the agent's own write couples it to future state, and
publishing the certificate somewhere the next reader inherits it. None of that follows from the
gap. It follows from the design law — *a record that cannot name the revision it was made against
is not a record of a decision* — which is true of any agent reading any versioned metadata,
including one whose platform hands it the version for free.

Two things get *easier* rather than harder in that world. The race this design has to guard
against — metadata moving between the agent's read and the resolver's — disappears, because the
coordinate arrives with the response instead of being recovered afterwards. And the honest
`unbound` outcome becomes rare rather than routine.

So the right reading if the parameter ships is **validation, not obsolescence**: the platform
agreed the coordinate belongs on the agent's surface. The workaround was always the cost of it not
being there yet, and the ablation already reports which half was load-bearing — the refusal, not
the annotation.

## Running the tests

Requires a live DataHub Core instance at `localhost:8080` for the integration tests.

```bash
pip install -e '.[dev]'
python scripts/preflight.py      # check the instance can demonstrate the flip
DATAHUB_GMS_URL=http://localhost:8080 python -m pytest -v
```

Run the preflight first. A stock DataHub quickstart serves lineage from a cache whose default
TTL is a day, and `get_lineage` reads through it — so the world changes, the graph index updates
within seconds, and the agent keeps seeing the old answer. The only symptom is a test that times
out, which looks like a bug here and is not one. The preflight measures it directly and prints
the one setting to change.

See the two decisions for yourself:

```bash
python -m dhdr.cli demo     # live MCP reads, two decisions, both written back
python scripts/demo.py      # the same run, paced to be read (or --fast)
```

Both go through the real MCP server and publish each certificate into DataHub. There is no time
travel in that path: MCP only ever answers about *now*, so the world genuinely moves between the
two reads and the command waits for MCP itself to report the change. `--no-publish` decides and
certifies without writing back.

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

54 tests currently pass. The ones worth knowing about:

- the agent calls `get_lineage` through the real MCP server, decides `admit`, and then — after a
  pipeline change wires a consumer to the table — makes the identical call and decides `reject`,
  with the two records naming different revisions;
- an MCP read binds with `value_source == "mcp"`, proving the decision input was the protocol
  response rather than a re-fetch;
- a mismatched payload is left unbound rather than guessed;
- history survives DataHub's retention pruning the oldest aspect versions;
- a second scenario (access/governance, a different aspect) rides the same core unchanged.

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

**This is not a description of what would happen.** It runs on
[pull request #1](https://github.com/Laolex/datahub-decision-records/pull/1) of this repository,
where the certificate arrives as a code-scanning annotation on `pipelines/orders.sql`:

```
dhdr/decision-certified | pipelines/orders.sql | Capability class: C2
```

The workflow is [`.github/workflows/dhdr-gate.yml`](.github/workflows/dhdr-gate.yml), and it
states its own limit at the top: producing a certificate needs a live DataHub to read revisions
from, which a hosted runner has none of. With `DATAHUB_GMS_URL` configured it generates one in
CI; otherwise it uploads `examples/decision.sarif.json`, produced against a live DataHub Core
v1.5.0.6 and committed. Either way the annotation on that PR is a real certificate from a real
decision — what the fallback does not prove is that CI reached DataHub.

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
- [datahub-project/datahub#18851](https://github.com/datahub-project/datahub/issues/18851), fixed by
  **[PR #18869](https://github.com/datahub-project/datahub/pull/18869)**
  — `institutionalMemory` has no registered patch template, so `PATCH` fails with a null-template
  `NullPointerException`. Eight other dataset aspects handle the same request, so it is a
  per-aspect gap. This is the reason write-back here is read-append-write rather than an atomic
  append — so rather than only report it, the PR adds `InstitutionalMemoryTemplate` following the
  existing `GlobalTagsTemplate` pattern, with a test for the two-writers case that motivated it.

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

Written during the window: the capture proxy over real MCP transport, revision binding and its
fact-matching, both scenario agents, the certifier and its pairing guard, write-back into
`institutionalMemory`, the SARIF emitter, the CLI, the ablation, and the two upstream reports.

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
