# Submission images

Upload to the Devpost gallery in this order. The first image is the one Devpost uses as the
project thumbnail. All are 1500×1000 (3:2), which is the ratio Devpost crops to.

| file | what it shows | source |
|---|---|---|
| `thumbnail.png` | The flip, as a cover: same agent, same call, opposite outcomes, different revisions. | designed |
| `02-the-flip.png` | The headline result in full, including the concrete change proposed each way. | `examples/demo-transcript.txt` |
| `03-capability-classes.png` | What a certificate reports — `none`, C0, C1, C2, and the hard cliff at C3. | `examples/README.md` |
| `04-ablation.png` | Which captured field is load-bearing, including the row that goes against us. | `examples/ablation.txt` |
| `05-how-it-works.png` | The five units and where the certificate lands. | `README.md` |
| `06-certificate-in-datahub.png` | The certificates on the dataset's own Documentation tab. | live DataHub Core v1.5.0.6 |
| `07-decision-gate-on-a-pull-request.png` | The same certificate as a code-scanning annotation on PR #1. | github.com |

`06` and `07` are unretouched screenshots of the running system, cropped and captioned. The
others are drawn, but every number on them is copied from a file in `examples/` — the revisions
`v941` and `v942` are the pair in `demo-transcript.txt`.

`og.png` (1200×630) is not part of the gallery. It is the social preview card for the hosted
walkthrough, referenced from `docs/index.html`.

The `.svg` beside each drawn image is its source. To re-render after an edit:

```bash
chromium --headless=old --window-size=1500,1000 --screenshot=out.png page.html   # page.html wraps the svg in an <img>
```

Colours and type match `docs/index.html`: `#fbfbfa` ground, `#1a1a18` text, `#5c5c56` muted,
`#7a4d1e` accent, `#2f6b3a` admit, `#9a3324` reject; DejaVu Serif for prose, DejaVu Sans Mono
for anything the machine produced.
