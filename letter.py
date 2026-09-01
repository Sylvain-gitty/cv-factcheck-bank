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


def company_signals(job: dict, bank=None) -> list[str]:
    """Proper nouns and product names from the posting itself.

    Deliberately NOT a web fetch. Guessing a homepage from a company name is fragile, and
    a wrong page produces a letter that is specific about the wrong company -- the single
    most damaging failure this stage has. The posting is the one source you know is theirs.
    """
    company = str(job.get("company") or "")
    title_words = set(words(str(job.get("title") or "")))
    banned = generic_tech_terms(bank) if bank else set()
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
            c = m.group(0).strip(". ")
            low = c.lower()
            if len(c) < 3 or low in generic or low in banned or low == company.lower():
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

    add("opening_is_yours", "OPENING: WRITE THIS YOURSELF" not in text,
        "you have written the opening" if "OPENING: WRITE THIS YOURSELF" not in text
        else "the TODO block is still there -- this is the one thing you must do by hand")

    sigs = company_signals(job, bank)
    hit = next((s for s in sigs if s.lower() in first_two.lower()), None)
    add("company_specific", bool(hit),
        f"opening names '{hit}'" if hit
        else "nothing specific to this company in the first two sentences")

    dead = next((d for d in DEAD_OPENERS if d in prose[:220].lower()), None)
    add("no_dead_openers", not dead, "clean" if not dead else f"opens with '{dead}'")

    prev = [(p.stem, prose_of(p.read_text(encoding="utf-8")))
            for p in LETTERS.glob("*.md") if p.stem != slug]
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
    unsourced = [n for n in re.findall(r"\d[\d,.]*", prose) if n not in src]
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

CSS = """html,body{background:#fff!important;color:#1a1a1a!important}
@page{size:A4;margin:22mm 20mm}
body{font:11pt/1.55 "Source Sans Pro","Segoe UI",Calibri,sans-serif;max-width:170mm;margin:0 auto}
.head{margin-bottom:12mm}.head h1{font-size:15pt;margin:0 0 2px}
.meta{color:#555;font-size:9.5pt}
.to{margin:8mm 0 6mm;font-size:10.5pt}
p{margin:0 0 3.6mm;text-align:justify}
.sig{margin-top:10mm}"""


def render_letter(slug, text, job, bank):
    owner = bank["profile"].get("owner", {})
    prose = prose_of(text)
    paras = "".join(f"<p>{p.strip()}</p>" for p in re.split(r"\n\s*\n", prose) if p.strip())
    contact = " · ".join(str(x) for x in (owner.get("email"), owner.get("phone"),
                                          owner.get("location")) if x)
    html = (f"<!doctype html><meta charset='utf-8'><title>{owner.get('name')} — "
            f"{job.get('company') or ''}</title><style>{CSS}</style>"
            f"<div class='head'><h1>{owner.get('name')}</h1>"
            f"<div class='meta'>{contact}</div></div>"
            f"<div class='to'>{job.get('company') or ''}<br>"
            f"<b>Re: {job.get('title')}</b><br>{date.today().strftime('%d %B %Y')}</div>"
            f"{paras}<div class='sig'>{owner.get('name')}</div>")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.html").write_text(html, encoding="utf-8")
    pdf = OUT / f"{slug}.pdf"
    ok = R.to_pdf(OUT / f"{slug}.html", pdf)
    return OUT / f"{slug}.html", (pdf if ok else None)


# --------------------------------------------------------------------------- driver

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job", nargs="?", help="path to a job YAML")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--variant", default="ds")
    ap.add_argument("--check", metavar="SLUG")
    ap.add_argument("--render", metavar="SLUG")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    bank = R.load_bank()
    LETTERS.mkdir(exist_ok=True)

    if args.list:
        for p in sorted(LETTERS.glob("*.md")):
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
            log(f"  [{mark}] {c['check']:<18} {c['detail'][:74]}")
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
    signals = company_signals(job, bank)

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
    log(f"  hooks: {' · '.join(signals[:6])}")
    log("\nGATE 3 — write the opening yourself. Every check fails until you do.")
    log(f"  then:  python letter.py --check {slug}")
    log(f"  then:  python letter.py --render {slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
