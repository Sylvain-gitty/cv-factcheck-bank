#!/usr/bin/env python3
"""Stage 3 — tailor a CV to a job, or to every job you decided to pursue.

    python tailor.py                              # every pursue: CV + letter draft
    python tailor.py --force                      # ... rebuilding what is current
    python tailor.py job.example.yaml
    python tailor.py job.example.yaml --variant pm
    python tailor.py job.example.yaml --llm       # optional selector
    python tailor.py job.example.yaml --explain   # show the retrieval working

Output: out/jobs/<slug>/  ->  cv.html, cv.md, trace.json, selection.json, checks.json

------------------------------------------------------------------------------
HOW THIS WORKS, AND THE TWO CALLS WORTH UNDERSTANDING

1. RETRIEVAL IS LEXICAL (BM25), NOT EMBEDDINGS.

   Plan 01 says "embed each fact and retrieve by cosine". For 38 facts that is
   over-engineering. BM25 over 38 short documents is instant, deterministic, needs no
   API key and no model download, and -- crucially -- you can read why it ranked what it
   ranked. Job requirements and CV facts share a technical vocabulary, which is the
   regime lexical matching is strongest in.

   Revisit this when the bank passes a few hundred facts, or when you start missing
   facts that are semantically right but share no words with the requirement. Until
   then, the simple thing is not a compromise; it is the correct thing. Your own TIRI
   work is the precedent: a zero-label cosine baseline beat every supervised
   cross-question model. Always find out what the cheap method does first.

2. SELECTION MAXIMISES REQUIREMENT COVERAGE, NOT TOTAL SCORE.

   The obvious objective -- take the top N facts by score -- produces a redundant CV:
   five bullets all answering the requirement you match best, and nothing at all for the
   other four. Greedy set cover instead asks, at each step, which fact adds the most
   *new* requirement coverage. That is what a reader is actually checking.

THE LLM IS OPTIONAL AND IT IS THE CHALLENGER, NOT THE DEFAULT.
The deterministic selector runs first and always. --llm asks a model to re-select from
the same candidates and reports how much it changed. Ship the baseline, measure the
challenger against it: the discipline is the point.

In every mode the selector returns FACT IDS ONLY. render.py builds the document, so no
generated text can reach the page.

------------------------------------------------------------------------------
BATCH MODE

With no job named, this runs the whole pursue list -- a CV and a letter draft for
everything Gate 1 said yes to -- and skips whatever is already current. Fifty-nine
jobs is not a list you re-run by hand, and the point of skipping is not speed: it is
that a command safe to re-run is one you will actually re-run after each Gate 1 pass.

"Current" means a CV whose recorded variant still matches the one Stage 2b implies,
and a letter draft that exists. Neither is inferable from the output directory alone,
which is named after the posting, so the variant is stamped into it.

A rebuilt CV can leave a letter citing facts no longer on the page. Where the opening
is still the generated TODO, nothing in that file is yours and it is rebuilt -- the
old one moved to letters/.superseded/ rather than deleted, because "nothing of yours
is in it" is a claim about a string match. Where you have written the opening, the
draft is never touched and the run says which ones to re-check.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

import render as R

HERE = Path(__file__).parent
OUT = HERE / "out" / "jobs"

# A posting is not obliged to be ASCII, and --explain prints it back verbatim. On a
# cp1252 console one emoji in a job description killed the run mid-report and wrote
# nothing. Same guard as rank.py, letter.py and package.py.
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                                # noqa: BLE001
    pass

STOP = set("""a an and are as at be but by for from has have how if in into is it its of on or
that the their this to was were what when where which who will with you your we our us they
role position company team work working experience years year job apply application ideally
plus strong good great excellent ability able knowledge understanding familiar familiarity
skills skill required requirement requirements responsibilities responsibility offer offers
looking seeking join candidate candidates ideal must should would like well also more most
using use used help support new well-being benefits salary contract remote hybrid office""".split())


# --------------------------------------------------------------------------- text

def norm(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


def tokens(text: str) -> list[str]:
    text = norm(text).lower()
    raw = re.findall(r"[a-z0-9][a-z0-9+#._\-]*", text)
    out = []
    for t in raw:
        t = t.strip("._-")
        if len(t) >= 2 and t not in STOP:
            out.append(t)
    return out


# --------------------------------------------------------------------------- BM25

class BM25:
    """Textbook BM25. ~40 lines, no dependencies, fully inspectable."""

    def __init__(self, docs: dict[str, list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids = list(docs)
        self.docs = docs
        self.len = {i: len(d) for i, d in docs.items()}
        self.avglen = (sum(self.len.values()) / len(self.len)) if self.len else 0.0
        self.tf = {i: Counter(d) for i, d in docs.items()}
        df = Counter()
        for d in docs.values():
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query: list[str], doc_id: str) -> float:
        tf, dl, total = self.tf[doc_id], self.len[doc_id], 0.0
        for t in query:
            f = tf.get(t, 0)
            if not f:
                continue
            denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avglen or 1))
            total += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
        return total

    def top(self, query: list[str], k: int) -> list[tuple[str, float]]:
        scored = [(i, self.score(query, i)) for i in self.ids]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]


# --------------------------------------------------------------------------- job

def load_job(path: Path) -> dict:
    job = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not job.get("requirements"):
        job["requirements"] = extract_requirements(job.get("description", ""))
    return job


def extract_requirements(description: str) -> list[str]:
    """Heuristic requirement extraction: bullets first, else sentences.

    Deliberately dumb, and good enough. Plan 01 Stage 2c already produces a clean
    `matched_requirements` list from the job posting; when you wire that up, drop these
    straight into the job file's `requirements:` and this function stops being used.
    """
    lines, out = description.splitlines(), []
    for ln in lines:
        s = ln.strip()
        if re.match(r"^[-*•–·]\s+", s):
            s = re.sub(r"^[-*•–·]\s+", "", s)
            if len(s.split()) >= 3:
                out.append(s)
    if out:
        return out
    for sent in re.split(r"(?<=[.!?])\s+", description):
        s = sent.strip()
        if len(s.split()) >= 5:
            out.append(s)
    return out[:20]


def detect_job_skills(job: dict, vocab: dict) -> list[str]:
    """Which controlled-vocabulary skills does this posting actually ask for?

    Using the vocabulary rather than a bag of words is what makes the keyword check below
    meaningful: it compares like with like, and it is the same list the CV's skills
    section is derived from.
    """
    blob = " " + " ".join(tokens(
        f"{job.get('title','')} {job.get('description','')} {' '.join(job.get('requirements') or [])}")) + " "
    found = []
    for s in vocab.get("skills", []):
        needles = [s["id"], s.get("label", "")] + (s.get("aliases") or [])
        for n in needles:
            n_tokens = tokens(n)
            if n_tokens and all(f" {t} " in blob for t in n_tokens):
                found.append(s["id"])
                break
    return found


# --------------------------------------------------------------------------- retrieval

def fact_document(f: dict, bank: dict) -> list[str]:
    """Field expansion: what text represents this fact for matching purposes."""
    labels = {s["id"]: s.get("label", s["id"]) for s in bank["vocab"].get("skills", [])}
    e = bank["entities_by_id"].get(f.get("entity"), {})
    parts = [f.get("claim", ""), f.get("claim_short", ""), f.get("outcome") or "",
             e.get("name", ""), e.get("summary", "") or "",
             " ".join(labels.get(s, s) for s in (f.get("skills") or []))]
    for m in f.get("metrics") or []:
        parts.append(str(m.get("name", "")))
    return tokens(" ".join(str(p) for p in parts))


def retrieve(bank, cfg, job, top_k: int):
    """Score every eligible fact against every requirement."""
    eligible = []
    for f in bank["facts"]:
        if f.get("status") != "confirmed" and not cfg["include_drafts"]:
            continue
        if cfg["archetype"] and cfg["archetype"] not in (f.get("archetypes") or []):
            continue
        if f.get("contribution") == "supported":
            continue          # a teammate's work is not a candidate for your CV
        eligible.append(f)
    if not eligible:
        return None, {}, {}

    docs = {f["id"]: fact_document(f, bank) for f in eligible}
    bm = BM25(docs)

    per_req: dict[str, list[tuple[str, float]]] = {}
    covers: dict[str, dict[str, float]] = defaultdict(dict)
    for req in job["requirements"]:
        hits = bm.top(tokens(req), top_k)
        per_req[req] = hits
        for fid, score in hits:
            covers[fid][req] = score
    return bm, per_req, covers


def greedy_cover(covers, bank, cfg, requirements, job_skills=(), cap=2):
    """Greedy set cover, weighted by fact strength, with per-fact coverage capped.

    THE CAP IS THE INTERESTING PART, and it exists because the naive version failed on the
    very first real job.

    Uncapped, the winner of round one was `f-bootcamp-programme` -- "Python, SQL,
    statistics, machine learning, deep learning" -- which lexically matched four
    requirements at once and is the least impressive fact in the bank. It displaced
    `f-tiri-bootstrap-discipline`, a strength-3 fact that answers "rigorous approach to
    model validation" almost word for word.

    Two fixes, both principled rather than fudged:

      1. Cap each fact's coverage credit at its best `cap` requirements. A reader does not
         credit one bullet with satisfying four separate requirements, so the model should
         not either. This removes the advantage keyword-soup facts had by construction.
      2. Weight the gain by strength. Between two facts covering the same ground, the
         stronger evidence wins.

    Ties break on strength then id, so runs stay reproducible.
    """
    chosen, picked, per_entity = [], set(), Counter()
    remaining = set(requirements)
    rationale = {}

    def weight(fid):
        return 0.5 + 0.5 * (bank["facts_by_id"][fid].get("strength") or 1)

    def eligible(fid):
        f = bank["facts_by_id"][fid]
        if fid in picked:
            return False
        if per_entity[f["entity"]] >= cfg["max_facts_per_entity"]:
            return False
        if f.get("status") != "confirmed" and not cfg["include_drafts"]:
            return False
        return True

    while len(chosen) < cfg["max_total_facts"]:
        best, best_gain, best_new = None, 0.0, set()
        for fid, reqmap in covers.items():
            if not eligible(fid):
                continue
            new = set(reqmap) & remaining
            if not new:
                continue
            top = sorted(new, key=lambda r: -reqmap[r])[:cap]
            gain = sum(reqmap[r] for r in top) * weight(fid)
            key = (gain, bank["facts_by_id"][fid].get("strength") or 0, fid)
            best_key = (best_gain, bank["facts_by_id"][best].get("strength") or 0, best)                 if best else (0.0, 0, "")
            if key > best_key:
                best, best_gain, best_new = fid, gain, set(top)
        if best is None or best_gain <= 0:
            break
        chosen.append(best)
        picked.add(best)
        per_entity[bank["facts_by_id"][best]["entity"]] += 1
        rationale[best] = {"covers": sorted(best_new), "gain": round(best_gain, 3),
                           "strength": bank["facts_by_id"][best].get("strength")}
        remaining -= best_new

    # Coverage exhausted but space left. Backfill in two tiers.
    #
    # Tier 1 -- SKILL BACKFILL. The posting's skills are detected across the whole
    # description, but retrieval only queries the requirement lines, so a skill mentioned
    # in prose ("our stack is Postgres and Docker") can never pull in the fact that
    # evidences it. The keyword_coverage check would then report it missing while a
    # perfectly good fact sat unselected. Close that loop here: prefer facts carrying a
    # job skill nothing chosen so far covers, even when they are weak.
    #
    # Tier 2 -- plain strength, so a short posting does not yield a three-bullet CV.
    def covered_skills():
        out = set()
        for fid in chosen:
            out |= set(bank["facts_by_id"][fid].get("skills") or [])
        return out

    def candidates():
        return [f for f in bank["facts"] if eligible(f["id"])
                and (not cfg["archetype"] or cfg["archetype"] in (f.get("archetypes") or []))]

    while len(chosen) < cfg["max_total_facts"]:
        gap = set(job_skills) - covered_skills()
        pool = candidates()
        if not pool:
            break
        scored = []
        for f in pool:
            fills = set(f.get("skills") or []) & gap
            scored.append((len(fills), f.get("strength") or 0, f["id"], f, sorted(fills)))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        n_fills, _, fid, f, fills = scored[0]
        chosen.append(fid)
        picked.add(fid)
        per_entity[f["entity"]] += 1
        rationale[fid] = {
            "covers": [], "gain": 0.0, "strength": f.get("strength"),
            "note": (f"skill backfill: {', '.join(fills)}" if n_fills
                     else "backfill by strength"),
        }
    return chosen, sorted(remaining), rationale


# --------------------------------------------------------------------------- LLM (optional)

PROMPT = """You are selecting which CV bullet points to include for one specific job.

You may ONLY return fact ids from the candidate list. You may not write, rephrase, merge or
invent any text. Selection and ordering are your entire job.

JOB TITLE: {title}
COMPANY: {company}

REQUIREMENTS:
{requirements}

CANDIDATE FACTS (id | strength 1-3 | text):
{candidates}

Select at most {max_facts} facts, at most {max_per_entity} from any single entity.
Prefer covering every requirement at least once over piling up bullets on one requirement.
Prefer higher-strength facts when coverage is equal.

Return ONLY this JSON, no prose:
{{"selected": ["fact-id", ...], "reasoning": "two sentences at most",
  "uncovered_requirements": ["..."]}}
"""


def build_prompt(job, covers, bank, cfg):
    cands = []
    for fid in sorted(covers):
        f = bank["facts_by_id"][fid]
        text = R.clean(f.get("claim_short") or f.get("claim"))
        cands.append(f"{fid} | {f.get('strength')} | {text}")
    return PROMPT.format(
        title=job.get("title", ""), company=job.get("company", ""),
        requirements="\n".join(f"- {r}" for r in job["requirements"]),
        candidates="\n".join(cands),
        max_facts=cfg["max_total_facts"], max_per_entity=cfg["max_facts_per_entity"])


def call_llm(prompt: str) -> dict | None:
    """OpenAI-compatible chat completion via stdlib. Returns None if no key is set."""
    import urllib.request

    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    if os.environ.get("OPENROUTER_API_KEY"):
        url = "https://openrouter.ai/api/v1/chat/completions"
        model = os.environ.get("TAILOR_MODEL", "anthropic/claude-sonnet-4.5")
    else:
        url = "https://api.openai.com/v1/chat/completions"
        model = os.environ.get("TAILOR_MODEL", "gpt-4o-mini")
    body = json.dumps({"model": model, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    text = data["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


# --------------------------------------------------------------------------- checks

def run_checks(chosen, sel, bank, cfg, job, job_skills, est_pages):
    checks, hard_fail = [], False

    def add(name, ok, detail, fatal=False):
        nonlocal hard_fail
        checks.append({"check": name, "pass": ok, "detail": detail})
        if not ok and fatal:
            hard_fail = True

    # 1. Traceability -- every rendered bullet maps to a real fact.
    bad = [b["fact_id"] for b in sel.trace if b["fact_id"] not in bank["facts_by_id"]]
    add("traceability", not bad, f"{len(sel.trace)} bullets, all traced" if not bad
        else f"untraceable: {bad}", fatal=True)

    # 2. Confirmed status.
    drafts = [fid for fid in chosen if bank["facts_by_id"][fid].get("status") != "confirmed"]
    add("confirmed_only", not drafts,
        "all confirmed" if not drafts else f"{len(drafts)} draft fact(s) included -- DO NOT SEND",
        fatal=not cfg["include_drafts"])

    # 3. Deny-list, re-checked on the rendered text.
    deny = [t.lower() for t in bank["profile"].get("deny_list", {}).get("terms", [])]
    hits = sorted({t for b in sel.trace for t in deny if t in b["text"].lower()})
    add("deny_list", not hits, "clean" if not hits else f"found: {hits}", fatal=True)

    # 4. Numeric integrity. The renderer is verbatim so this should always pass -- it is a
    #    regression guard for the day a phrasing step is added to this path.
    num_bad = []
    for b in sel.trace:
        f = bank["facts_by_id"].get(b["fact_id"], {})
        src = " ".join([str(f.get("claim", "")), str(f.get("claim_short") or ""),
                        str(f.get("claim_de") or ""), str(f.get("claim_short_de") or ""),
                        str(f.get("outcome") or ""),
                        " ".join(str(m.get("value")) for m in (f.get("metrics") or []))])
        for n in re.findall(r"\d[\d,.]*", b["text"]):
            if n not in src:
                num_bad.append(f"{b['fact_id']}: '{n}'")
    add("numeric_integrity", not num_bad,
        "every number traced to its fact" if not num_bad else f"unsourced: {num_bad[:5]}",
        fatal=True)

    # 5. Keyword coverage -- ATS parsers match literally, so this is not superstition.
    cv_skills = {s for fid in chosen for s in (bank["facts_by_id"][fid].get("skills") or [])}
    missing = [s for s in job_skills if s not in cv_skills]
    pct = 100 * (len(job_skills) - len(missing)) / len(job_skills) if job_skills else 100.0
    add("keyword_coverage", pct >= 60,
        f"{pct:.0f}% of the job's {len(job_skills)} detected skills present"
        + (f"; missing: {missing}" if missing else ""))

    # 6. Length.
    add("length", est_pages <= cfg["page_target"] + 0.25,
        f"~{est_pages:.1f} page(s) against a target of {cfg['page_target']}")

    return checks, hard_fail


# --------------------------------------------------------------------------- driver

def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", norm(s).lower())).strip("-") or "job"


# --------------------------------------------------------------------------- batch
#
# `python tailor.py` with no job runs the whole pursue list: a CV and a letter draft
# for every job Gate 1 said yes to, skipping whatever is already current.
#
# These helpers live here rather than in triage.py because triage.py imports from this
# module, and a second copy of the variant rule would drift away from this one the
# first time either changed. One definition, imported.

JOBS_DIR = HERE / "jobs"
LETTERS_DIR = HERE / "letters"
DECISION_LOG = HERE / ".state" / "decisions.json"
SCORES_PATH = HERE / ".state" / "scores.json"

# Recorded inside each output directory, because tailor.py names that directory after
# the POSTING alone -- so a CV argued from a different half of the bank, or built
# against an older copy of the posting, is otherwise indistinguishable from a fresh one.
STAMP = ".triage.json"

# The marker letter.py leaves in a fresh draft. While it is present the opening is
# unwritten, every gate fails, and nothing in the file is yours.
OPENING_TODO = "OPENING: WRITE THIS YOURSELF"

VARIANT_FOR = {"data-scientist": "ds", "ai-engineer": "ai", "technical-pm": "pm"}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def variant_for(slug: str, scores: dict) -> str:
    """Which CV variant to argue this posting with.

    Not cosmetic: a variant filters the bank by archetype and keyword_coverage measures
    the SELECTED bullets, so running `ds` against a product posting makes every
    technical-pm fact ineligible and reports skills as missing that a confirmed fact
    evidences. Stage 2b has already labelled each posting, so take the label; give the
    ambiguous ones `span`, which drops the filter and exists for exactly that case.
    """
    sc = scores.get(slug) or {}
    if not sc.get("archetype_confident", False):
        return "span"
    return VARIANT_FOR.get(sc.get("archetype"), "span")


def dest_for(job: dict) -> Path:
    return OUT / slugify(f"{job.get('company', '')}-{job.get('title', '')}")


def stamp_of(d: Path) -> dict:
    return _load_json(d / STAMP, {})


def write_stamp(d: Path, slug: str, variant: str):
    if d.exists():
        (d / STAMP).write_text(json.dumps({"slug": slug, "variant": variant}, indent=2),
                               encoding="utf-8")


def cv_is_current(job: dict, slug: str, variant: str) -> bool:
    d = dest_for(job)
    if not (d / "checks.json").exists():
        return False
    st = stamp_of(d)
    return st.get("slug") == slug and st.get("variant") == variant


def opening_written(path: Path) -> bool:
    """True if anything in this draft is the author's.

    Errs towards True. A false positive costs a stale letter you were told about; a
    false negative would overwrite something you wrote, and this pipeline does not
    trade those at par.
    """
    try:
        return OPENING_TODO not in path.read_text(encoding="utf-8")
    except OSError:
        return True


def supersede(path: Path) -> Path:
    """Move a draft aside instead of deleting it. Regeneration only ever discards
    machine-written text, but 'only ever' is a claim about a string match, so the old
    file is kept where it can be read back rather than destroyed on the strength of it.
    """
    keep = LETTERS_DIR / ".superseded"
    keep.mkdir(parents=True, exist_ok=True)
    dest = keep / f"{path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    path.replace(dest)
    return dest


def _run(args: list[str]) -> tuple[bool, str]:
    r = subprocess.run([sys.executable, *args], cwd=HERE, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, (tail[-1][:70] if tail else f"exit {r.returncode}")
    return True, ""


def run_batch(force: bool) -> int:
    """CV + letter draft for every pursued job, skipping what is already current."""
    log = print
    decisions = _load_json(DECISION_LOG, {})
    scores = _load_json(SCORES_PATH, {})
    slugs = sorted(s for s, r in decisions.items() if r.get("verdict") == "pursue")
    if not slugs:
        log("nothing pursued yet — tick some jobs and run `python rank.py --decide`")
        return 0

    jobs, missing = {}, []
    for slug in slugs:
        p = JOBS_DIR / f"{slug}.yaml"
        if not p.exists():
            missing.append(slug)
            continue
        try:
            jobs[slug] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as e:                                   # noqa: BLE001
            missing.append(f"{slug} ({str(e)[:30]})")

    log(f"\n{len(slugs)} pursued job(s)\n")
    built_cv, built_letter, kept, regen, failed = 0, 0, [], [], []

    for i, (slug, job) in enumerate(sorted(jobs.items()), 1):
        variant = variant_for(slug, scores)
        draft = LETTERS_DIR / f"{slug}.md"
        need_cv = force or not cv_is_current(job, slug, variant)
        note = []

        if need_cv:
            ok, why = _run(["tailor.py", f"jobs/{slug}.yaml", "--variant", variant])
            if not ok:
                failed.append((slug, f"cv: {why}"))
                log(f"  {i:>3}/{len(jobs)}  -- [{variant:<4}] {slug[:48]}   {why}")
                continue
            write_stamp(dest_for(job), slug, variant)
            built_cv += 1
            note.append("cv")
            # The letter argues from the facts the CV selected, so a rebuilt CV leaves
            # an existing draft citing evidence that may no longer be on the page.
            if draft.exists():
                if opening_written(draft):
                    kept.append(slug)                # yours. never touched.
                else:
                    supersede(draft)
                    regen.append(slug)

        if not draft.exists():
            ok, why = _run(["letter.py", f"jobs/{slug}.yaml"])
            if ok:
                built_letter += 1
                note.append("letter")
            else:
                failed.append((slug, f"letter: {why}"))
                note.append(f"letter FAILED: {why}")

        mark = ", ".join(note) if note else "up to date"
        log(f"  {i:>3}/{len(jobs)}  ok [{variant:<4}] {slug[:48]}   {mark}")

    log(f"\n{built_cv} CV(s) built, {built_letter} letter draft(s) written")
    if regen:
        log(f"\n{len(regen)} draft(s) had an unwritten opening and were rebuilt from the")
        log(f"new CV's facts. The previous files are in letters/.superseded/ :")
        for slug in regen[:10]:
            log(f"    {slug[:60]}")
    if kept:
        log(f"\n{len(kept)} letter(s) KEPT because you had written the opening — but the")
        log("CV underneath was rebuilt, so the proof points they cite may no longer be")
        log("on the page. Re-check these before sending:")
        for slug in kept:
            log(f"    letters/{slug[:56]}.md")
    if missing:
        log(f"\n{len(missing)} pursued job(s) have no job file:")
        for slug in missing[:10]:
            log(f"    {slug[:60]}")
    if failed:
        log(f"\n{len(failed)} failure(s):")
        for slug, why in failed:
            log(f"    {slug[:48]}  {why}")
        return 1
    log("\nGATE 3 is yours: every letter above needs its opening written by hand.")
    log("  python status.py            # what is where")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job", nargs="?",
                    help="path to a job YAML file; omit to do every pursued job")
    ap.add_argument("--variant", default="ds")
    ap.add_argument("--llm", action="store_true", help="add the LLM selector as challenger")
    ap.add_argument("--explain", action="store_true", help="show per-requirement retrieval")
    ap.add_argument("--include-drafts", action="store_true")
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--force", action="store_true",
                    help="batch mode: rebuild even what is already current")
    args = ap.parse_args()

    # No job named means the whole pursue list. Single-job use is unchanged.
    if not args.job:
        return run_batch(args.force)

    bank = R.load_bank()
    rc = R.load("render_config.yaml")
    variant = next((v for v in rc["variants"] if v["id"] == args.variant), None)
    if not variant:
        sys.exit(f"unknown variant '{args.variant}'. Try: "
                 + ", ".join(v["id"] for v in rc["variants"]))
    cfg = R.resolve_variant(variant, rc["defaults"])
    if args.include_drafts:
        cfg["include_drafts"] = True

    job_path = Path(args.job)
    if not job_path.is_absolute():
        job_path = HERE / job_path
    job = load_job(job_path)
    slug = slugify(f"{job.get('company','')}-{job.get('title','')}")
    dest = OUT / slug
    dest.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"{job.get('title')} - {job.get('company')}")
    print(f"variant: {cfg['label']}  |  requirements: {len(job['requirements'])}")
    print("=" * 70)

    bm, per_req, covers = retrieve(bank, cfg, job, args.top_k)
    if not covers:
        print("\n  No eligible facts.")
        if not cfg["include_drafts"]:
            print("  Every fact is still status: draft. Confirm some, or pass --include-drafts.")
        return 1

    if args.explain:
        print("\nRETRIEVAL (top 3 per requirement)")
        for req, hits in per_req.items():
            print(f"\n  {req[:76]}")
            for fid, score in hits[:3]:
                txt = R.clean(bank["facts_by_id"][fid].get("claim_short")
                              or bank["facts_by_id"][fid].get("claim"))
                print(f"    {score:5.2f}  {fid:<38} {txt[:60]}")

    job_skills = detect_job_skills(job, bank["vocab"])
    chosen, uncovered, rationale = greedy_cover(
        covers, bank, cfg, job["requirements"], job_skills)
    selector = "bm25-greedy-cover"

    if args.llm:
        prompt = build_prompt(job, covers, bank, cfg)
        (dest / "prompt.txt").write_text(prompt, encoding="utf-8")
        try:
            result = call_llm(prompt)
        except Exception as e:                                  # noqa: BLE001
            print(f"\n  LLM call failed ({e}). Keeping the deterministic selection.")
            result = None
        if result is None:
            print(f"\n  No API key set (OPENROUTER_API_KEY / OPENAI_API_KEY).")
            print(f"  Wrote the prompt to {dest / 'prompt.txt'} — paste it into any chat,")
            print("  save the JSON as llm_selection.json here, and re-run.")
            manual = dest / "llm_selection.json"
            if manual.exists():
                result = json.loads(manual.read_text(encoding="utf-8"))
                print("  Found llm_selection.json — using it.")
        if result:
            valid = [f for f in result.get("selected", []) if f in covers]
            dropped = [f for f in result.get("selected", []) if f not in covers]
            if dropped:
                print(f"\n  ! LLM returned {len(dropped)} id(s) outside the candidate set "
                      f"-- ignored: {dropped}")
            if valid:
                added = set(valid) - set(chosen)
                removed = set(chosen) - set(valid)
                print(f"\n  LLM vs baseline: +{len(added)} / -{len(removed)} "
                      f"({len(set(valid) & set(chosen))} agreed)")
                if added:
                    print(f"    added:   {sorted(added)}")
                if removed:
                    print(f"    dropped: {sorted(removed)}")
                chosen, selector = valid, "llm"

    sel = R.selection_from_ids(chosen, bank)
    html_doc = R.render_html(bank, sel, cfg, rc["section_labels"], rc["skill_group_labels"])
    (dest / "cv.html").write_text(html_doc, encoding="utf-8")
    (dest / "cv.md").write_text(
        R.render_markdown(bank, sel, cfg, rc["section_labels"]), encoding="utf-8")
    (dest / "trace.json").write_text(json.dumps(
        {"job": job.get("title"), "company": job.get("company"), "variant": cfg["label"],
         "selector": selector, "bullets": sel.trace}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (dest / "selection.json").write_text(json.dumps(
        {"selector": selector, "chosen": chosen, "rationale": rationale,
         "uncovered_requirements": uncovered}, indent=2, ensure_ascii=False), encoding="utf-8")

    est = R.page_estimate(bank, sel, cfg)
    checks, fatal = run_checks(chosen, sel, bank, cfg, job, job_skills, est)
    (dest / "checks.json").write_text(json.dumps(checks, indent=2, ensure_ascii=False),
                                      encoding="utf-8")

    print(f"\nSELECTION  [{selector}]  {len(chosen)} bullets across {len(sel.by_entity)} entities")
    for fid in chosen:
        r = rationale.get(fid, {})
        mark = "+" if r.get("covers") else "."
        print(f"  {mark} {fid:<40} covers {len(r.get('covers', []))} req")
    if uncovered:
        print(f"\n  {len(uncovered)} requirement(s) NOT covered by any fact:")
        for r in uncovered:
            print(f"    - {r[:74]}")
        print("    ^ this is the most useful output here. It is your skill gap for this job,")
        print("      and aggregated across jobs it is a curriculum.")

    print("\nCHECKS")
    for c in checks:
        print(f"  [{'ok ' if c['pass'] else 'FAIL'}] {c['check']:<20} {c['detail'][:78]}")

    print(f"\n  -> {dest}")
    if fatal:
        print("\n  BLOCKED: a fatal check failed. Do not send this.")
        return 1
    print("\n  Read trace.json before sending. Gate 2 is you, not this script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
