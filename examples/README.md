# Sample outputs

Every file here was produced by running the code against a live DataHub Core v1.5.0.6 instance —
regenerate the lot with `python scripts/generate_examples.py`. Nothing here was written by hand.

**Start with these two:**

| file | what it shows |
|---|---|
| [`mcp-flip.txt`](mcp-flip.txt) | **The headline result.** The identical `get_lineage` call through DataHub's real MCP server, made twice while a pipeline change lands in between, deciding `admit` then `reject` — each bound to a different aspect revision. `value_source: mcp` proves the agent decided on the protocol response, not on a re-fetch. |
| [`demo-transcript.txt`](demo-transcript.txt) | The same run as a reader sees it, including the concrete change the agent proposes each way: `ALTER TABLE … DROP COLUMN promo_code` when the drop is safe, a deprecation comment naming the consumer when it is not. |

**Then, if you want the detail:**

| file | what it shows |
|---|---|
| [`published-institutional-memory.json`](published-institutional-memory.json) | What the *next* reader inherits. The certificate written back into the dataset's `institutionalMemory`; the URLs resolve. |
| [`certificate-then.txt`](certificate-then.txt) / [`certificate-now.txt`](certificate-now.txt) | The rendered certificate for each of the two decisions. |
| [`record-then.json`](record-then.json) / [`record-now.json`](record-now.json) | The full decision records the certificates are derived from — predicate, policy resolution, candidate set, execution fingerprint. |
| [`ablation.txt`](ablation.txt) | Which captured field is load-bearing, including the result that goes against us: deleting the revision from the record costs nothing. What carries the soundness is the *refusal*, not the annotation. |
| [`decision.sarif.json`](decision.sarif.json) | What the CI gate uploads, so the certificate lands as an annotation on a pull request rather than in a terminal. |

## Reading a certificate

The certificates report a **capability class**, never a score:

| class | means |
|---|---|
| **C0** | The record can reproduce *this* decision identically. Identity replay. |
| **C1** | It also supports asking whether a *stricter* policy would have changed the outcome. |
| **C2** | It also supports asking whether a *looser* policy would have. This is what a bound, complete record earns. |
| **C3** | Would extend to decisions whose own writes change what later decisions read. **Never certified** — reported as a boundary where deductive evidence stops and inference begins. |
| **none** | A deciding read could not be tied to a revision, so nothing is certifiable. Not "C2 with a warning". |

A percentage is deliberately never produced: a score averaged over incommensurable kinds of
missing evidence manufactures exactly the false confidence this project exists to prevent.
