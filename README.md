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

> **Status: in progress.** The capture core, revision binding and the schema-ops agent are
> built and tested against a live DataHub Core v1.5.0.6 instance. The certifier, write-back to
> DataHub, and the CLI are landing over the next few days. Sections below marked *(pending)*
> describe work not yet in the repository. Nothing here claims a result it has not produced.

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

**The certifier** *(pending)* reports a capability class — C0 identity, C1 tightening, C2
loosening, C3 state-coupled — never a percentage. A score over incommensurable kinds of
missing evidence manufactures false confidence. C3 is certified as a *boundary*: where a
decision mutates metadata a later decision reads, the certificate states where deductive
evidence ends and counterfactual inference begins, and claims nothing past that line.

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

17 tests currently pass. The ones worth knowing about:

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

## Reproduce

*(pending)* — the exact DataHub Core version, the datapack ingest recipe, and the commands to
regenerate every committed artifact in `examples/` will land with the CLI.

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
