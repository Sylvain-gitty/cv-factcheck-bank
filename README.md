# cv-fact-bank

Your CV, motivation letters and portfolio claims are all **renderings** of the same
underlying data — so store the data, not the documents.

This is a small, dependency-light toolchain that keeps every claim you make about yourself
in one structured store, renders CVs from it, tailors one to a specific job posting, and
refuses to let you say things you cannot defend.

```bash
pip install pyyaml
for f in profile entities facts vocab; do cp $f.example.yaml $f.yaml; done

python validate.py                    # integrity + guardrails + coverage
python render.py                      # all CV variants -> out/
python tailor.py jobs/example-berlin-ds.yaml --explain
```

PyYAML is the only dependency. No LaTeX, no headless browser, no API key, no build step.
Output is self-contained HTML with print CSS — open it and Ctrl+P to PDF.

---

## The idea

An LLM asked to "tailor my CV to this job" from a PDF will, reliably and without warning,
invent: a job title that sounds better, a year of experience you do not have, a technology
you have never used. Not often. Often enough. And you will not catch it every time, because
you will be reading the twentieth CV that week.

Prompting against that does not work. **Structure does.** If the only permitted operation is
*select from and rephrase these records*, nothing can invent an employer, because no record
contains one. Generation becomes retrieval, and retrieval can be verified mechanically.

So:

- **`facts.yaml`** holds atomic claims. One claim per record.
- **`render.py`** selects, orders, caps and formats. **It never writes.** Every word of every
  bullet comes verbatim from the bank, and a `trace.json` proves it line by line.
- **`tailor.py`** decides *which* facts fit a job. Even with the optional LLM selector
  enabled, it returns **fact ids only** — the renderer still builds the document, so no
  generated text can reach the page.

## Two layers

An **entity** is a thing you did over a period (a job, a project, a degree). A **fact** is
one claim about it.

A CV renders entities in reverse-chronological order with selected bullets underneath;
retrieval works on individual facts. Splitting them means dates, employers and authorship
live in exactly one place and cannot drift apart — ordinary normalisation, applied to your
own history.

## Guardrails

Every one of these exists because it caught something real.

| Guardrail | Catches |
|---|---|
| `status: draft` → `confirmed` | Anything you have not personally asserted. Nothing renders until you flip it. |
| `contribution: led / joint / supported` | Team work quietly becoming solo work. **`supported` facts never render to a CV** — you do not put a teammate's work on your CV — but stay in the bank for context. |
| `scope: created / operated / contributed` | "I worked inside a good system" becoming "I built it". When set to `operated`, creator verbs are rejected. |
| `forbidden_verbs` per authorship | `led` / `owned` / `architected` appearing on team work. |
| `deny_list` | Technologies you cannot defend, checked again at render time. |
| Controlled skill vocabulary | `sklearn` / `scikit-learn` / `Scikit-Learn` drifting into three tags and silently halving your retrieval recall. |
| Derived skills section | A skills list that outruns the evidence. It is computed from the facts actually rendered, so it **cannot** contain a skill no bullet supports. |
| Numeric integrity | Any number in a rendered bullet that is not in its source fact. |

The design principle behind the two verb checks: **deny-lists, not allow-lists.** An
allow-list of permitted verbs fights you constantly and gets switched off. A narrow
deny-list of credit-claiming verbs fires rarely and only on the failure that matters.

A check that cries wolf is worse than no check.

## Tailoring to a job

`tailor.py` takes a job as a small YAML file and produces `cv.html`, `cv.md`, `trace.json`,
`selection.json` and `checks.json`.

**Retrieval is BM25, not embeddings.** For a bank of a few dozen facts, embedding
infrastructure is over-engineering: BM25 is instant, deterministic, needs no API key or
model download, and `--explain` shows you exactly why it ranked what it ranked. Switch when
the bank passes a few hundred facts, or when you start missing facts that are semantically
right but share no words with the requirement.

**Selection is greedy set cover, not top-N.** Taking the highest-scoring N facts produces a
redundant CV: five bullets answering the requirement you match best and nothing for the
other four. Two refinements, both forced by real runs rather than designed up front:

1. **Coverage credit per fact is capped at two requirements.** Uncapped, the winner was a
   generic keyword-dense line that lexically matched four requirements at once and was the
   weakest fact in the bank. A reader does not credit one bullet with satisfying four
   separate requirements, so neither should the objective.
2. **Skill backfill.** A posting's skills are detected across the whole description, but
   retrieval only queries the requirement lines — so a skill mentioned in prose ("our stack
   is Postgres and Docker") could never pull in the fact evidencing it, and the coverage
   check would report it missing while a perfectly good fact sat unselected. Backfill now
   prefers facts covering an uncovered job skill before falling back to strength.

**The LLM is a challenger, not the default.** `--llm` runs *after* the deterministic
selector and reports the diff (`+3 / -2, 13 agreed`). Ship the cheap thing, then measure
whether the expensive thing beats it. Without an API key it writes the prompt to a file for
you to paste anywhere.

### The most useful output is the uncovered list

When requirements go uncovered, `tailor.py` names them. That is not a tool failure — it is
**your skill gap for that job, stated precisely.** Aggregated over thirty applications it is
a curriculum written by the market rather than by a syllabus.

## Confirming facts

```bash
python confirm.py            # writes out/worksheet.md + confirm.txt
python confirm.py --apply    # flips every ticked fact to confirmed
```

Ticking a box asserts four things: it is true and at the right scope, the verb matches what
you did, **you can defend it under follow-up**, and the numbers are right. The third is the
one people skip, and it is the one that costs you — a fact you cannot survive a follow-up on
turns a good interview into a bad one at the worst moment.

The worksheet shows each bullet exactly as it will render, its evidence, every structured
metric, and a list of things worth a second look: team work where the bullet must not claim
sole credit, `operated` scope, missing outcomes, recall-only evidence, and every number
extracted for verification.

## Page length

Variants declare a `page_target` and the run warns when you exceed it. The estimator's
constants were **measured from a real browser render**, not guessed — an earlier version
counted bullet characters only and reported 1.1 pages where the truth was 1.76, because it
ignored the profile paragraph, the skills grid and the education block.

If you change the CSS, re-calibrate. Open a rendered variant and run:

```js
(() => { const w = document.body.getBoundingClientRect().width;
         const page = (297 - 26) * (w / 190);
         return document.documentElement.scrollHeight / page; })()
```

A length check that lies is worse than none: it tells you a two-page CV fits on one.

**The rule that matters is not "one page."** It is: never spill a little onto a second sheet.
Land at 1.8–2.0, or cut to a genuine single page. 1.4 is the bad number.

## Things only a screenshot caught

Three defects passed every validator, every character count and every traceability check,
and were invisible until the rendered page was actually looked at:

1. **The CV rendered dark-on-dark.** The CSS set a text colour but no background, so a
   browser in dark mode painted the page dark and the near-black text became unreadable. A
   CV is a print document; it is always light, whatever theme the reader is in.
2. **Entity headers wrapped and pushed the dates out of alignment**, because name,
   organisation and role all ran on one line.
3. **An entity heading rendered with no bullets under it** — `by_entity` is a `defaultdict`,
   so the per-entity cap check *created* an empty entry for entities whose facts were all
   dropped by the total cap.

**Look at the artefact.**

## Privacy

`.gitignore` excludes `profile.yaml`, `entities.yaml`, `facts.yaml`, `vocab.yaml`,
`confirm.txt`, `out/` and real job files. Those hold your phone number, your address, your full employment history
and your rendered CVs.

**Do not remove those lines.** If you need to share a bank, share the `.example.yaml` files.

## Files

```
profile.yaml        identity, role archetypes, deny-list, verb guardrails
entities.yaml       jobs, projects, degrees: dates and authorship live here
facts.yaml          atomic claims, each attached to an entity
vocab.yaml          controlled vocabulary for skill tags
render_config.yaml  CV variants: archetype, section order, page budget, language
validate.py         integrity, guardrails, coverage report
render.py           bank -> HTML / Markdown / traceability
tailor.py           tailor to one job posting, with checks
confirm.py          the draft -> confirmed human gate
```

MIT licensed.
