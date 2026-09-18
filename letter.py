#!/usr/bin/env python3
"""Stage 4 — motivation letter: evidence pack, draft skeleton, and the checks that matter.

    python letter.py jobs/<slug>.yaml            # build the draft
    python letter.py jobs/<slug>.yaml --llm      # have a model fill the middle
    python letter.py --check <slug>              # run the gates
    python letter.py --render <slug>             # HTML + PDF, refuses if checks fail
    python letter.py --list

Drafts live in letters/<slug>.md and are meant to be edited by hand.

------------------------------------------------------------------------------
THE ONE STRUCTURAL RULE

**You write the opening. The tool will not do it, and will not let you skip it.**

The draft ships with the first paragraph as a marked TODO block, and every gate fails
while that block is still present. This is not a nag -- it is the same mechanism as
`status: draft` on facts: the thing you must do by hand is enforced by the data, not by
your memory at 11pm.

The reason is narrow and worth stating. The first two sentences are the only part of a
motivation letter with a high probability of being read carefully, and they are where a
human voice is most detectable. A model writes competent, forgettable openings. That is
the one place in this pipeline where forgettable is fatal.

Automation gets a letter to roughly 70%. The last 30% is you, and it is the 30% that does
the work.

------------------------------------------------------------------------------
WHAT THE CHECKS ACTUALLY CATCH

  opening_is_yours   the TODO block is gone
  company_specific   a proper noun from THIS posting appears in the first two sentences
  no_dead_openers    not "I am writing to apply for..."
  genericness        lexical similarity against your previous letters is below 0.75
  numeric_integrity  every number in the letter appears in a cited fact
  deny_list          no forbidden claim survived into prose
  length             250-400 words

`genericness` is the interesting one, and it is your own TIRI instinct pointed at your
own output: if a machine cannot tell this letter apart from the last one, neither can the
reader. Below the threshold it is boilerplate with the company name swapped, which is
worse than no letter because it is evidence you did not care.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

import render as R
import tailor as T

HERE = Path(__file__).parent
LETTERS = HERE / "letters"
OUT = HERE / "out" / "letters"

# THE HUMAN GATE, MOVED RATHER THAN REMOVED.
#
# This pipeline used to refuse to write the opening at all, on the grounds that the
# first two sentences are the only part of a motivation letter reliably read closely,
# and a model writes competent forgettable ones. That held while the alternative was
# writing three letters a week. It does not survive fifty-seven.
#
# So the gate moves from "you wrote it" to "you read it and said yes". The line below
# sits in every draft and every fatal check fails while it reads `no`. Same mechanism
# as `status: draft` on a fact: the thing you must do by hand is enforced by the data
# rather than by your memory at 11pm. What is NOT preserved is the guarantee that the
# voice is yours -- only that you had to look at it before it could go anywhere.
APPROVAL_LINE = "<!-- APPROVED: no -->"
APPROVAL_RE = r"<!--\s*APPROVED:\s*(yes|no)\s*-->"

TODO_BLOCK = """<!-- OPENING: WRITE THIS YOURSELF. The checks fail while this block is here.
     Two or three sentences. Name something specific about THIS company that you
     actually noticed, and say plainly why it made you look twice. Not "I am excited
     by your mission" -- something you could only write about them.
     Candidate hooks pulled from the posting are listed at the bottom of this file. -->"""

DEAD_OPENERS = [
    "i am writing to apply", "i am writing to express", "i would like to apply",
    "i am excited to apply", "i am thrilled to apply", "please accept this letter",
    "i am reaching out regarding", "with great interest i", "i am very interested in the",
]

STOP = set("""a an the and or but of to in for on with at by from as is are was were be been
this that these those it its i my me we our you your they their he she his her not no if
then than so such very more most much many some any all can could will would shall should
may might must have has had do does did been being am""".split())


def log(msg=""):
    print(msg, flush=True)


try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                                # noqa: BLE001
    pass


# --------------------------------------------------------------------------- helpers

def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Zäöüßéèà]+", (text or "").lower())
            if len(w) > 2 and w not in STOP]


def cosine(a: str, b: str) -> float:
    ca, cb = Counter(words(a)), Counter(words(b))
    if not ca or not cb:
        return 0.0
    common = set(ca) & set(cb)
    num = sum(ca[t] * cb[t] for t in common)
    den = math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values()))
    return num / den if den else 0.0


def generic_tech_terms(bank) -> set[str]:
    """Every label and alias in the controlled vocabulary.

    A proper noun that is just a technology name is not a company signal. "Machine
    Learning" and "PostgreSQL" say nothing about who you are writing to, and an opening
    built on one is exactly the generic letter this stage exists to prevent. Reusing
    vocab.yaml means the exclusion list maintains itself.
    """
    out = set()
    for sk in bank["vocab"].get("skills", []):
        out.add(sk["id"].replace("-", " ").lower())
        out.add(str(sk.get("label", "")).lower())
        for a in sk.get("aliases") or []:
            out.add(str(a).replace("-", " ").lower())
    return {t for t in out if t}


DE_MARKERS = set("""der die das und mit für von zu ist sind wir unser unsere sie ihre bei
auf im in den dem des eine einen einer werden wird haben hat als auch nicht oder aber wenn
dass durch über unter nach vor zwischen sowie bereits sowohl""".split())


def is_german(text: str) -> bool:
    """Crude language check, and crude is enough for the decision it drives."""
    w = re.findall(r"[a-zA-ZäöüßÄÖÜ]+", (text or "").lower())
    if len(w) < 40:
        return False
    return sum(1 for x in w if x in DE_MARKERS) / len(w) > 0.06


# Brand-shaped tokens: internal capital (Enpal.One), a dot, or a trailing registered mark.
# These survive in any language because their shape, not their capitalisation, marks them.
BRANDISH = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]+|[a-z][A-Z][A-Za-z0-9]*)\b")


# Posting furniture. None of these is ever a company signal, however it is capitalised:
# section headers, HR vocabulary, benefit-provider names, difficulty labels. The
# lowercase test below catches most noise on its own, but only when the word happens to
# recur in lowercase -- on a short posting it does not, which is how WORK and OFFER
# reached a hook list.
NOISE = {
    "work", "offer", "offers", "looking for", "experience", "experiences",
    "opportunity", "opportunities", "commitment", "diversity", "inclusion",
    "inclusive hiring", "disclosure", "execution", "ownership", "value", "values",
    "members", "member", "policy", "security", "legal", "benefits", "requirements",
    "responsibilities", "tasks", "things", "thing", "type", "make", "translate",
    "verification", "easy", "hard", "very hard", "senior", "junior", "lead",
    "manager", "engineer", "engineering", "sales", "transparency", "growth",
    "impact", "mission", "vision", "culture", "perks", "salary", "compensation",
    "equity", "stock option grant", "virtual stock option", "enrolment",
    "corporate", "startups", "services gmbh", "gmbh", "learning", "development",
    "flexibility", "wellbeing", "note", "urban sports club", "own", "deliver",
    "betriebliche altersvorsorge", "build", "ensure", "drive", "support",
    "collaborate", "partner", "next steps", "application", "interview",
}


def is_ordinary_word(span: str, desc: str) -> bool:
    """Does this span also appear in lowercase in the posting?

    A NAME IS NOT ALSO AN ORDINARY WORD. "Sequoia", "Terminal-Bench" and "GLS" never
    appear lowercase in the text that names them; "Work", "Engineer", "Execution" and
    "Diversity" almost always do, because the posting also uses them as plain words.
    That asymmetry separates a name from a shouted heading or a capitalised bullet verb
    far more reliably than counting capitals does.

    Single-word spans only. "Deutsche Telekom" would never match anyway, and testing
    each word separately would discard real names containing a common word.
    """
    if " " in span:
        return False
    # Case-SENSITIVE: only a genuine lowercase occurrence counts as evidence.
    return bool(re.search(rf"{re.escape(span.lower())}", desc))


def company_signals(job: dict, bank=None) -> list[str]:
    """Proper nouns and product names from the posting itself.

    Deliberately NOT a web fetch. Guessing a homepage from a company name is fragile, and
    a wrong page produces a letter that is specific about the wrong company -- the single
    most damaging failure this stage has. The posting is the one source you know is theirs.
    """
    company = str(job.get("company") or "")
    title_words = set(words(str(job.get("title") or "")))
    banned = generic_tech_terms(bank) if bank else set()
    desc = str(job.get("description") or "")

    # GERMAN CAPITALISES EVERY NOUN, so a capitalised-span heuristic returns ordinary
    # vocabulary -- "Dach", "Haus", "Garage" -- and presents it as company identity. That
    # is worse than returning nothing, because it looks like a usable hook. On a German
    # posting, fall back to brand-shaped tokens only and let the caller say so.
    if is_german(desc):
        out, seen = [], set()
        for m in BRANDISH.finditer(desc):
            c = m.group(0).strip(". ")
            if len(c) < 4 or c.lower() in banned or c.lower() == company.lower():
                continue
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out[:10]
    generic = {"we", "you", "our", "the", "this", "it", "as", "in", "at", "for", "and",
               "about", "your", "their", "job", "role", "team", "what", "who", "why",
               "how", "please", "apply", "position", "company", "ready", "join",
               "we are", "you will", "our team", "the role", "german", "english",
               "remote", "berlin", "germany", "europe"}
    seen, out = set(), []
    # Sentence by sentence, so a capitalised span cannot run across a full stop and glue
    # the tail of one sentence to the head of the next.
    for sentence in re.split(r"(?<=[.!?\n])\s+", str(job.get("description") or "")):
        for m in re.finditer(
                r"\b[A-Z][A-Za-z0-9&.\-]{2,}(?:\s+[A-Z][A-Za-z0-9&.\-]{2,}){0,2}", sentence):
            # SKIP SENTENCE-INITIAL SPANS. Every sentence starts with a capital, so
            # matching them harvests "Instead", "Have" and "Some" as if they were company
            # names. A real proper noun recurs mid-sentence; a sentence-starter does not.
            if m.start() == 0:
                continue
            # SKIP BULLET-INITIAL SPANS, for the same reason. Responsibility lists read
            # "- Partner with stakeholders", "- Build and maintain", "- Ensure data
            # quality", and once whitespace is collapsed those are not line starts, so the
            # rule above misses them. They are the job's verbs, not the company's name.
            before = sentence[:m.start()].rstrip()
            if not before or before[-1] in "-*\u2022\u2013\u00b7:;":
                continue
            c = m.group(0).strip(". ")
            low = c.lower()
            if len(c) < 3 or low in generic or low in banned or low == company.lower():
                continue
            if low in NOISE:
                continue
            # A MULTI-WORD ALL-CAPS SPAN IS A SECTION HEADER, always: "LOOKING FOR",
            # "INCLUSIVE HIRING", "WHAT WE OFFER". A single short all-caps token is the
            # opposite -- GLS, IOP, OOH, RWTH, FACS are exactly the hooks worth having --
            # so only the multi-word form goes.
            if c.isupper() and " " in c:
                continue
            # And the general case: a name does not also appear as a plain lowercase word.
            if is_ordinary_word(c, desc):
                continue
            cw = words(c)
            # A span built only from words already in the job title says nothing about the
            # company -- it is the role restated back at you.
            if cw and all(w in title_words for w in cw):
                continue
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out[:14]


def sibling_signals(job: dict, bank, jobs_dir: Path) -> list[str]:
    """Hooks from OTHER postings by the same company in this batch.

    Some postings carry no "About us" section at all -- this one opened straight into
    "About the role" -- so there is nothing company-specific to extract. Sibling postings
    from the same employer usually carry the boilerplate that names the products.

    This stays inside the rule that matters: it is the same company's own text, already
    fetched, from a source we know is theirs. It is not a web fetch and cannot land on
    the wrong company.
    """
    import yaml as _yaml
    company = str(job.get("company") or "").strip().lower()
    if not company:
        return []
    out, seen = [], set()
    for p in sorted(jobs_dir.glob("*.yaml")):
        try:
            other = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:                                        # noqa: BLE001
            continue
        if str(other.get("company") or "").strip().lower() != company:
            continue
        if other.get("url") == job.get("url"):
            continue
        # Do not mix languages: German hooks in an English letter read as pasted-in.
        if is_german(str(other.get("description") or "")) != is_german(
                str(job.get("description") or "")):
            continue
        for sig in company_signals(other, bank):
            if sig not in seen:
                seen.add(sig)
                out.append(sig)
    return out[:10]


def all_signals(job, bank) -> list[str]:
    """The hook set the draft offers AND the check validates against.

    These must be the same list. They were not: the draft borrowed hooks from sibling
    postings when a job carried no company section, while run_checks looked only at the
    posting's own text -- so the tool proposed "Enpal.One", the writer used it, and the
    gate rejected it as not company-specific.
    """
    own = company_signals(job, bank)
    if not any(BRANDISH.search(x) for x in own):
        borrowed = [x for x in sibling_signals(job, bank, HERE / "jobs") if x not in own]
        borrowed.sort(key=lambda x: (not bool(BRANDISH.search(x)), x))
        return borrowed + own
    return own


def select_facts(bank, job, variant_id="ds", top=6):
    """Reuse Stage 3's retrieval so the letter and the CV argue from the same evidence."""
    rc = R.load("render_config.yaml")
    variant = next(v for v in rc["variants"] if v["id"] == variant_id)
    cfg = R.resolve_variant(variant, rc["defaults"])
    cfg["max_total_facts"] = top
    _, _, covers = T.retrieve(bank, cfg, job, 6)
    if not covers:
        return []
    job_skills = T.detect_job_skills(job, bank["vocab"])
    chosen, _, _ = T.greedy_cover(covers, bank, cfg, job["requirements"], job_skills)
    return [bank["facts_by_id"][f] for f in chosen[:top]]


# --------------------------------------------------------------------------- draft

def build_draft(job, facts, signals, llm_body=None) -> str:
    owner = R.load_bank()["profile"].get("owner", {})
    lines = [
        f"# {job.get('title')} — {job.get('company') or ''}".rstrip(" —"),
        "",
        f"<!-- job: {job.get('url')} -->",
        f"<!-- generated: {date.today().isoformat()} -->",
        APPROVAL_LINE,
        "<!--   ^ change to `yes` when this letter is ready to send. Every fatal",
        "        check fails until you do. Edit the text first if it needs it. -->",
        "",
        TODO_BLOCK,
        "",
    ]
    if llm_body:
        lines += [llm_body.strip(), ""]
    else:
        lines += [
            "<!-- MIDDLE: two proof points. Each cites the fact it comes from, so the",
            "     numeric check can verify it. Rephrase freely; do not invent. -->",
            "",
        ]
        for f in facts[:2]:
            claim = R.clean(f.get("claim_short") or f.get("claim"))
            out = R.clean(f.get("outcome_short") or f.get("outcome") or "")
            lines += [f"{claim} {out}".strip() + f"  <!-- {f['id']} -->", ""]
        lines += [
            "<!-- CLOSE: what you want, and what you bring. Two sentences. -->",
            "",
            "",
        ]
    lines += [
        "---",
        "",
        f"<!-- EVIDENCE AVAILABLE ({len(facts)} facts retrieved for this posting) -->",
    ]
    for f in facts:
        lines.append(f"<!--   {f['id']}: {R.clean(f.get('claim_short') or f.get('claim'))[:96]} -->")
    lines += ["", "<!-- HOOKS: proper nouns from the posting. Use one in your opening. -->",
              "<!--   " + " · ".join(signals[:10]) + " -->"]
    return "\n".join(lines) + "\n"


PROMPT = """Draft the MIDDLE and CLOSE of a motivation letter. Do NOT write the opening --
the candidate writes that themselves.

Rules:
- Use ONLY the facts listed. Do not invent achievements, numbers, employers or dates.
- Two short paragraphs of evidence, then a two-sentence close.
- After each evidence paragraph, put the fact id in an HTML comment: <!-- fact-id -->
- Plain, direct, no marketing language. No "passionate", "excited", "leverage".
- 180-260 words total.

JOB: {title} at {company}
REQUIREMENTS:
{requirements}

FACTS AVAILABLE (id | claim | outcome):
{facts}

Return the prose only, no preamble.
"""


def call_llm(prompt: str):
    import urllib.request
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    if os.environ.get("OPENROUTER_API_KEY"):
        url = "https://openrouter.ai/api/v1/chat/completions"
        model = os.environ.get("LETTER_MODEL", "anthropic/claude-sonnet-4.5")
    else:
        url = "https://api.openai.com/v1/chat/completions"
        model = os.environ.get("LETTER_MODEL", "gpt-4o-mini")
    body = json.dumps({"model": model, "temperature": 0.3,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- checks

# A pack is scaffolding for writing a letter, not a letter. It quotes the posting and
# the facts verbatim, so leaving packs in these globs makes every letter look similar
# to its own brief and pollutes the one measurement that is supposed to catch
# boilerplate.
def letter_files(exclude: str | None = None):
    return [p for p in sorted(LETTERS.glob("*.md"))
            if not p.name.endswith(".pack.md") and p.stem != exclude]


def prose_of(text: str) -> str:
    """The letter without comments, headings or rules -- what a reader actually sees."""
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    body = "\n".join(l for l in body.splitlines()
                     if not l.startswith("#") and l.strip() != "---")
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def cited_facts(text: str, bank) -> list[dict]:
    ids = re.findall(r"<!--\s*(f-[a-z0-9-]+)\s*-->", text)
    return [bank["facts_by_id"][i] for i in ids if i in bank["facts_by_id"]]


def run_checks(slug, text, job, bank):
    prose = prose_of(text)
    body_words = len(prose.split())
    first_two = " ".join(re.split(r"(?<=[.!?])\s+", prose)[:2])
    checks = []

    def add(name, ok, detail, fatal=True):
        checks.append({"check": name, "pass": ok, "detail": detail, "fatal": fatal})

    m = re.search(APPROVAL_RE, text)
    approved = bool(m) and m.group(1).lower() == "yes"
    add("approved", approved,
        "you approved this letter" if approved
        else ("no APPROVED line -- add `<!-- APPROVED: yes -->` once you have read it"
              if not m else
              "APPROVED is still `no` -- read the letter, edit if needed, then flip it"))

    # Approving a letter that still contains the placeholder is not a decision, it is
    # a slip. Kept fatal so the two cannot be confused.
    add("opening_written", "OPENING: WRITE THIS YOURSELF" not in text,
        "clean" if "OPENING: WRITE THIS YOURSELF" not in text
        else "the placeholder block is still in the file")

    sigs = all_signals(job, bank)
    hit = next((s for s in sigs if s.lower() in first_two.lower()), None)
    add("company_specific", bool(hit),
        f"opening names '{hit}'" if hit
        else "nothing specific to this company in the first two sentences")

    dead = next((d for d in DEAD_OPENERS if d in prose[:220].lower()), None)
    add("no_dead_openers", not dead, "clean" if not dead else f"opens with '{dead}'")

    prev = [(p.stem, prose_of(p.read_text(encoding="utf-8")))
            for p in letter_files(exclude=slug)]
    worst = max(((cosine(prose, t), s) for s, t in prev), default=(0.0, None))
    add("genericness", worst[0] < 0.75,
        f"most similar previous letter: {worst[1] or 'none yet'} at {worst[0]:.2f}"
        + ("" if worst[0] < 0.75 else " -- this is boilerplate with the name swapped"))

    facts = cited_facts(text, bank)
    src = " ".join(
        f"{f.get('claim','')} {f.get('claim_short') or ''} {f.get('outcome') or ''} "
        f"{f.get('outcome_short') or ''} "
        + " ".join(str(m.get('value')) for m in (f.get('metrics') or []))
        for f in facts)
    # Strip trailing punctuation before comparing. The pattern is greedy over "." and
    # "," so it swallows the full stop that ends a sentence: "0.610." never matches the
    # "0.610" in its fact, and a correctly sourced number fails the check. A gate that
    # fires on correct input is worse than no gate, because the habit it teaches is
    # overriding it.
    nums = [n.rstrip(".,") for n in re.findall(r"\d[\d,.]*", prose)]
    unsourced = [n for n in nums if n and n not in src]
    add("numeric_integrity", not unsourced,
        f"{len(facts)} fact(s) cited, every number traced" if not unsourced
        else f"numbers with no cited source: {unsourced[:5]}")

    deny = [t.lower() for t in bank["profile"].get("deny_list", {}).get("terms", [])]
    hits = sorted({t for t in deny if t in prose.lower()})
    add("deny_list", not hits, "clean" if not hits else f"found: {hits}")

    add("length", 250 <= body_words <= 400, f"{body_words} words (target 250-400)",
        fatal=False)
    return checks


# --------------------------------------------------------------------------- render

# The letterhead is render.CSS_BASE -- the same typeface, name size, contact styling and
# rule the CV uses. A CV and its covering letter arrive together and read as one document;
# when these were two independent stylesheets they drifted into different type sizes and a
# rule on one but not the other. Only the rules a letter needs and a CV does not live here:
# a letter is one page of prose, so it wants wider margins and looser leading than a CV
# packing two pages of bullets.
CSS = R.CSS_BASE + """
@page { size: A4; margin: 18mm 18mm; }
body { line-height: 1.5; max-width: 175mm; margin: 0 auto; padding: 6mm; }
.to { margin: 9mm 0 7mm; font-size: 9.8pt; color: #333; }
.to b { color: #000; }
p { margin: 0 0 3.4mm; text-align: justify; }
.sig { margin-top: 9mm; }
"""


def render_letter(slug, text, job, bank):
    owner = bank["profile"].get("owner", {})
    prose = prose_of(text)
    paras = "".join(f"<p>{R.esc(p.strip())}</p>"
                     for p in re.split(r"\n\s*\n", prose) if p.strip())
    # Same header markup as render.render_html, so CSS_BASE styles both identically:
    # <header> with an h1, an optional headline, and contact items as <span>s the
    # stylesheet separates. Building it differently here is how the two drifted before.
    bits = [owner.get("phone"), owner.get("email"), owner.get("location"),
            owner.get("linkedin"), owner.get("github")]
    contact = "".join(f"<span>{R.esc(b)}</span>" for b in bits if b)
    headline = owner.get("headline_en") or ""
    html = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>{R.esc(owner.get('name'))} — "
            f"{R.esc(job.get('company') or '')}</title>"
            f"<style>{CSS}</style></head><body>"
            f"<header><h1>{R.esc(owner.get('name'))}</h1>"
            + (f"<div class='headline'>{R.esc(headline)}</div>" if headline else "")
            + f"<div class='contact'>{contact}</div></header>"
            f"<div class='to'>{R.esc(job.get('company') or '')}<br>"
            f"<b>Re: {R.esc(job.get('title'))}</b><br>"
            f"{date.today().strftime('%d %B %Y')}</div>"
            f"{paras}<div class='sig'>{R.esc(owner.get('name'))}</div>"
            f"</body></html>")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.html").write_text(html, encoding="utf-8")
    pdf = OUT / f"{slug}.pdf"
    ok = R.to_pdf(OUT / f"{slug}.html", pdf)
    return OUT / f"{slug}.html", (pdf if ok else None)


# --------------------------------------------------------------------------- driver

PACK_RULES = """\
## What to produce

Write the COMPLETE letter into `letters/{slug}.md`, replacing the placeholder block.
Keep the HTML comments that are already there (the job line, the generated date, the
APPROVED line). Leave `APPROVED: no` -- flipping it is the reader's decision, not
yours.

Structure: an opening of two or three sentences, two or three proof paragraphs, a
close of two sentences. 250-400 words of prose, not counting comments.

THE SHAPE THAT WORKS, from the two letters in the first batch that read best
(glassflow-ai-engineer and n26-technical-product-manager-applied-machine-learning):

  - Open on a STRUCTURAL CHOICE the company made -- something they built or decided,
    not something they claim about themselves. "Rius keeps every trace rather than
    capping at thirty days." "IOP builds the capability once, horizontally, rather
    than shipping a model per team." Then say what that choice implies about how
    they think. Then claim the resulting problem: that is the problem I would want
    to own.
  - End every evidence paragraph by bending back to THEIR situation. Not "here is
    what I did" but "here is the version of that you have." A paragraph that stops
    at the achievement is a CV bullet with more words around it.
  - Short declarative sentences. One memorable clause closing each paragraph. A
    two-sentence close, concrete, no flourish.
  - The company fact in the opening must be checkable on their own site, and the
    first two sentences must contain a proper noun from the posting -- the
    company_specific gate reads only those two.

## Hard rules

1. EVERY claim about the candidate must come from the facts listed below. No
   achievement, number, employer, date or technology that is not in them. This is the
   whole premise of the fact bank: generation is retrieval, and retrieval is checkable.
2. Cite the fact behind each proof paragraph with a trailing `<!-- f-id -->`. The
   numeric_integrity check reads those comments to verify every number in the prose,
   and a number with no cited source fails the build.
3. Numbers must match their fact EXACTLY. Not rounded, not "over", not "nearly".
4. MOST METRICS DO NOT BELONG IN THE PROSE. A reader who does not know the project
   cannot tell whether 0.693 against 0.610 is a large gap or a rounding error, and
   the letter has no room to explain what was being ranked. So state what the result
   MEANT and let the cited fact carry the number:

     not  "reached 0.693 ROC-AUC and beat every supervised model at 0.610"
     but  "the simplest method, with no training at all, beat every model we
           trained -- which changed what was worth building"

   The test is whether a stranger can tell why the sentence matters. Numbers for
   SCALE, COST, DURATION or TEAM SIZE pass it -- 62,229 papers, $16.10, four months,
   twenty-five people all mean something immediately. Numbers for MODEL PERFORMANCE
   -- ROC-AUC, F2, precision, recall -- almost never do. At most one performance
   figure per letter, and only where the sentence around it makes the scale obvious.

   This does not weaken the guarantee. The claim still comes from a cited fact and
   still has to be defensible in the interview; it is the presentation that changes.
   The point of the fact bank was never that the letter is quantitative.
5. Nothing from the deny list, in any form.
6. The opening must name something specific and true about THIS company, verified
   against a source you actually read -- not inferred from the company name. Being
   confidently specific about the wrong company is the worst failure available here.
   If you could not verify anything, say so in the pack rather than inventing.
7. Do not open with "I am writing to apply" or any of its relatives.
8. Do not resemble the previous openings quoted at the end; the genericness check
   fails above 0.75 cosine against any earlier letter.
"""


def build_pack(slug, job, facts, signals, bank) -> str:
    """Everything needed to write this letter, in one file.

    The pack exists so the writing step is separable from who does it. Today that is
    an assistant in a session; with an API key it is the same text as a prompt. The
    one thing it deliberately does NOT contain is company research -- that has to come
    from actually reading the company's own pages, and a pack that pre-filled it from
    the posting would quietly reintroduce the guesswork it is meant to replace.
    """
    deny = bank["profile"].get("deny_list", {}).get("terms", [])
    L = [f"# Briefing — {job.get('title')} at {job.get('company') or '?'}", "",
         f"- slug: `{slug}`",
         f"- location: {job.get('location') or 'unstated'}",
         f"- posting: {job.get('url')}",
         f"- language: {job.get('language') or 'en'}", "",
         PACK_RULES.replace("{slug}", slug), "",
         "## Research to do first", "",
         "Find the company's own site and read what they say about themselves. Confirm",
         "it is the right company -- match it against the posting's own details before",
         "using anything from it. Look for what makes them specific: what they build,",
         "who for, how they talk about it, anything recent and concrete.", "",
         "## Facts you may use (and nothing else)", ""]
    for f in facts:
        claim = R.clean(f.get("claim") or "")
        out = R.clean(f.get("outcome") or "")
        L.append(f"### `{f['id']}`")
        L.append(claim + (f" {out}" if out else ""))
        bits = []
        if f.get("skills"):
            bits.append("skills: " + ", ".join(f["skills"]))
        if f.get("contribution"):
            bits.append(f"contribution: {f['contribution']}")
        if f.get("scope"):
            bits.append(f"scope: {f['scope']}")
        if bits:
            L.append("")
            L.append("_" + " · ".join(bits) + "_")
        L.append("")
    L += ["## Never write these", "", ", ".join(f"`{t}`" for t in deny), "",
          "## Proper nouns found in the posting", "",
          (" · ".join(signals[:14]) if signals else "_none found — read the posting_"),
          "", "## The posting", "", "```",
          str(job.get("description") or "").strip(), "```", ""]

    prev = []
    for p in letter_files(exclude=slug):
        txt = p.read_text(encoding="utf-8")
        if "OPENING: WRITE THIS YOURSELF" in txt:
            continue                       # still a stub; nothing to be generic against
        opening = " ".join(re.split(r"(?<=[.!?])\s+", prose_of(txt))[:2])
        if opening.strip():
            prev.append(f"- **{p.stem}** — {opening.strip()[:220]}")
    if prev:
        L += ["## Openings already used — do not resemble these", ""] + prev + [""]
    return "\n".join(L)


def write_pack(slug, bank, variant=None) -> int:
    """variant=None means: ask Stage 2b, the same way tailor.py and triage.py do.

    Defaulting to `ds` here silently built every pack from the data-scientist half of
    the bank. On a product-operations posting that left the Katapult leadership facts
    out of the brief entirely, so the letter argued from model evaluation for a job
    about roadmaps and stakeholder loops -- the same class of mistake as running the
    wrong CV variant, one stage later.
    """
    path = HERE / "jobs" / f"{slug}.yaml"
    if not path.exists():
        log(f"no job file for {slug}")
        return 1
    if variant is None:
        scores = T._load_json(T.SCORES_PATH, {})
        variant = T.variant_for(slug, scores)
    # load_job, not yaml.safe_load: it derives `requirements` from the description
    # when the posting has none, and select_facts retrieves against exactly that.
    job = T.load_job(path)
    facts = select_facts(bank, job, variant, top=8)
    signals = all_signals(job, bank)
    LETTERS.mkdir(exist_ok=True)
    dest = LETTERS / f"{slug}.pack.md"
    dest.write_text(build_pack(slug, job, facts, signals, bank), encoding="utf-8")
    log(f"  {dest.relative_to(HERE)}   [{variant}]  {len(facts)} fact(s), "
        f"{len(signals)} hook(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job", nargs="?", help="path to a job YAML")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--variant", default="ds")
    ap.add_argument("--check", metavar="SLUG")
    ap.add_argument("--render", metavar="SLUG")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pack", nargs="+", metavar="SLUG",
                    help="write a briefing pack per slug for whoever writes the letter")
    args = ap.parse_args()

    bank = R.load_bank()
    LETTERS.mkdir(exist_ok=True)

    if args.pack:
        rc = 0
        for slug in args.pack:
            # only override the Stage 2b choice if the caller actually asked
            rc |= write_pack(slug, bank,
                             args.variant if "--variant" in sys.argv else None)
        return rc

    if args.list:
        for p in letter_files():
            done = "OPENING: WRITE THIS YOURSELF" not in p.read_text(encoding="utf-8")
            log(f"  [{'ready ' if done else 'needs opening'}] {p.stem}")
        return 0

    slug = args.check or args.render
    if slug:
        path = LETTERS / f"{slug}.md"
        if not path.exists():
            sys.exit(f"no draft at {path}")
        job_path = next((p for p in (HERE / "jobs").glob("*.yaml") if p.stem == slug), None)
        if not job_path:
            sys.exit(f"no job file for '{slug}'")
        job = T.load_job(job_path)
        text = path.read_text(encoding="utf-8")
        checks = run_checks(slug, text, job, bank)
        log(f"\nCHECKS — {slug}")
        for c in checks:
            mark = "ok  " if c["pass"] else ("FAIL" if c["fatal"] else "warn")
            # Truncating at a fixed width cut the score off the end of the
            # genericness line whenever the compared slug was long -- hiding the one
            # number that check exists to report. Wrap instead of clipping.
            detail = c["detail"]
            log(f"  [{mark}] {c['check']:<18} {detail[:74]}")
            for i in range(74, len(detail), 74):
                log(f"  {'':<7} {'':<18} {detail[i:i + 74]}")
        blocked = [c for c in checks if not c["pass"] and c["fatal"]]
        if args.render:
            if blocked:
                log(f"\n  NOT RENDERED — {len(blocked)} gate(s) failed.")
                return 1
            h, pdf = render_letter(slug, text, job, bank)
            log(f"\n  -> {h}" + (f"\n  -> {pdf}" if pdf else ""))
        elif blocked:
            return 1
        return 0

    if not args.job:
        sys.exit("give a job file, or use --check / --render / --list")
    job_path = Path(args.job)
    if not job_path.is_absolute():
        job_path = HERE / job_path
    job = T.load_job(job_path)
    slug = job_path.stem

    facts = select_facts(bank, job, args.variant)
    if not facts:
        sys.exit("no confirmed facts matched this posting — run validate.py")
    own = company_signals(job, bank)
    signals = all_signals(job, bank)
    borrowed = [x for x in signals if x not in own]

    body = None
    if args.llm:
        prompt = PROMPT.format(
            title=job.get("title"), company=job.get("company"),
            requirements="\n".join(f"- {r}" for r in job["requirements"][:10]),
            facts="\n".join(
                f"{f['id']} | {R.clean(f.get('claim_short') or f.get('claim'))} | "
                f"{R.clean(f.get('outcome_short') or f.get('outcome') or '')}" for f in facts))
        try:
            body = call_llm(prompt)
        except Exception as e:                                   # noqa: BLE001
            log(f"  LLM call failed ({e})")
        if body is None:
            (LETTERS / f"{slug}.prompt.txt").write_text(prompt, encoding="utf-8")
            log(f"  no API key — prompt written to letters/{slug}.prompt.txt")

    path = LETTERS / f"{slug}.md"
    if path.exists():
        log(f"  {path.name} already exists — not overwriting your edits")
    else:
        path.write_text(build_draft(job, facts, signals, body), encoding="utf-8")

    log(f"\nDRAFT  letters/{slug}.md")
    log(f"  {len(facts)} fact(s) retrieved · {len(signals)} company hook(s) found")
    if is_german(str(job.get("description") or "")):
        log("  posting is in German — capitalisation carries no signal there, so only")
        log("  brand-shaped names were extracted. Read the posting for your hook.")
    log(f"  hooks: {' · '.join(signals[:8]) if signals else '(none found — read the posting)'}")
    if borrowed:
        log(f"  ({len(borrowed)} borrowed from other {job.get('company')} postings in this"
            f" batch — this one carried no company section of its own)")
    log("\nGATE 3 — write the opening yourself. Every check fails until you do.")
    log(f"  then:  python letter.py --check {slug}")
    log(f"  then:  python letter.py --render {slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
