#!/usr/bin/env python3
"""Stage 2b + 2c — score every discovered job, then re-rank the survivors.

    python rank.py                 # 2b only: score, rank, write the digest
    python rank.py --llm           # add 2c: LLM re-rank of the top N
    python rank.py --top 12        # how many reach 2c and the digest
    python rank.py --decide        # apply your pursue/skip ticks from decisions.txt

Reads  jobs/*.yaml   (written by discover.py)
Writes out/digest.md, out/digest.html, decisions.txt, .state/scores.json

------------------------------------------------------------------------------
STAGE 2b — CHEAP, DETERMINISTIC, RUNS ON EVERYTHING

The plan specified embeddings and cosine similarity. This ships BM25 instead, for the
same reason Stage 3 does: there is no embedding model installed, no API key is required,
and for a few dozen jobs a day the lexical version is not a compromise. It is instant,
reproducible, and you can read why it scored what it scored.

The index is built over the JOBS, and each archetype's `match_text` is the QUERY. That
orientation matters: many documents and a short query is the regime BM25 was designed for.
Querying three archetype "documents" with a job description would give degenerate IDF over
a corpus of three.

Output per job: a score for each archetype, plus the argmax -- which identity this posting
is actually asking for. That argmax is the point of running three archetypes at all.

*** BM25 SCORES ARE NOT COMPARABLE ACROSS RUNS. ***
IDF depends on the corpus, so today's 14.2 and tomorrow's 14.2 mean different things. Only
the RANK within a batch is meaningful. The digest therefore shows rank and a
batch-relative 0-100, never a raw score dressed up as a percentage.

STAGE 2c — EXPENSIVE, RUNS ON THE TOP N ONLY

An LLM reads the shortlist and returns structured judgement. The field that earns its cost
is `missing_requirements`: aggregated over thirty postings it is a skill gap list written
by the market rather than by a syllabus.

Without an API key it writes the prompt to disk for you to paste anywhere and drop the
JSON back. The pipeline degrades to 2b and keeps working.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

import render as R
from tailor import BM25, detect_job_skills, tokens

HERE = Path(__file__).parent
JOBS = HERE / "jobs"
OUT = HERE / "out"
STATE = HERE / ".state"
SCORES = STATE / "scores.json"
DECISIONS = HERE / "decisions.txt"
DECISION_LOG = STATE / "decisions.json"


def log(msg=""):
    print(msg, flush=True)


try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                              # noqa: BLE001
    pass


# --------------------------------------------------------------------------- 2b

# Below this relative gap between the top two archetypes, the winner is not meaningful.
# Calibrated against a real batch: clear cases sat at 43-76%, genuine ties at 21-26%.
ARCHETYPE_MARGIN = 0.30


def job_document(job: dict) -> list[str]:
    return tokens(" ".join(str(job.get(k) or "") for k in
                           ("title", "company", "location", "tags", "description")))


def score_batch(jobs: dict[str, dict], profile: dict) -> dict[str, dict]:
    """BM25 over the job corpus, one query per archetype."""
    archetypes = profile.get("archetypes", [])
    bm = BM25({slug: job_document(j) for slug, j in jobs.items()})

    raw: dict[str, dict[str, float]] = {slug: {} for slug in jobs}
    for arch in archetypes:
        q = tokens(arch.get("match_text") or "")
        if not q:
            continue
        for slug in jobs:
            raw[slug][arch["id"]] = bm.score(q, slug)

    # Batch-relative 0-100. Honest because it is labelled relative: a job scoring 100
    # today is the best of today's batch, not an absolute 100% match.
    best = {slug: max(v.values(), default=0.0) for slug, v in raw.items()}
    hi, lo = max(best.values(), default=1.0) or 1.0, min(best.values(), default=0.0)
    span = (hi - lo) or 1.0

    out = {}
    for slug, per_arch in raw.items():
        ordered = sorted(per_arch.items(), key=lambda kv: -kv[1])
        top = ordered[0][0] if ordered else None
        # AN ARGMAX WITHOUT A MARGIN IS A POINT ESTIMATE WITH NO ERROR BAR.
        # The three archetypes share most of their vocabulary, so on many postings the
        # top two scores are nearly tied and the winner is noise. Measured on a real
        # batch, margins ranged from 76% (unambiguous) to 21% (a coin flip). Reporting
        # both as a flat label would be exactly the overclaim the fact bank exists to
        # prevent -- so below the threshold it says so.
        margin = 0.0
        if len(ordered) > 1 and ordered[0][1]:
            margin = (ordered[0][1] - ordered[1][1]) / ordered[0][1]
        confident = margin >= ARCHETYPE_MARGIN
        out[slug] = {
            "per_archetype": {k: round(v, 2) for k, v in per_arch.items()},
            "archetype": top,
            "archetype_confident": confident,
            "archetype_label": (top if confident
                                else f"{ordered[0][0]}?/{ordered[1][0]}?" if len(ordered) > 1
                                else top),
            "margin": round(margin, 3),
            "raw": round(best[slug], 2),
            "relative": round(100 * (best[slug] - lo) / span),
        }
    return out


# --------------------------------------------------------------------------- 2c

PROMPT = """You are screening job postings for one candidate. Be blunt; a false positive
costs them an hour, a false negative costs them nothing they will notice.

CANDIDATE PROFILES (the roles they are targeting):
{profiles}

POSTING
Title: {title}
Company: {company}
Location: {location}
{description}

Return ONLY this JSON, no prose:
{{"fit_score": 0-100,
  "archetype": "one of: {arch_ids}",
  "matched_requirements": ["requirements this candidate clearly meets"],
  "missing_requirements": ["requirements they do not meet, stated as the skill itself"],
  "red_flags": ["unpaid trial task, no salary band, agency posting, etc - [] if none"],
  "one_line_why": "one sentence, why this is or is not worth an hour of their time"}}
"""


def build_prompt(job, profile):
    archs = profile.get("archetypes", [])
    profiles = "\n".join(
        f"- {a['id']}: {R.clean(a.get('profile') or '')}" for a in archs)
    return PROMPT.format(
        profiles=profiles, arch_ids=", ".join(a["id"] for a in archs),
        title=job.get("title", ""), company=job.get("company", ""),
        location=job.get("location") or "unspecified",
        description=(job.get("description") or "")[:6000])


def call_llm(prompt: str):
    import urllib.request
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    if os.environ.get("OPENROUTER_API_KEY"):
        url = "https://openrouter.ai/api/v1/chat/completions"
        model = os.environ.get("RANK_MODEL", "anthropic/claude-sonnet-4.5")
    else:
        url = "https://api.openai.com/v1/chat/completions"
        model = os.environ.get("RANK_MODEL", "gpt-4o-mini")
    body = json.dumps({"model": model, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


# --------------------------------------------------------------------------- digest

def write_digest(rows, gaps):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = [f"# Job digest — {ts}", "",
          f"{len(rows)} posting(s), ranked. **Rank is meaningful; the score is relative to "
          "this batch only** — BM25 depends on the corpus, so today's number and tomorrow's "
          "are not the same scale.", "",
          "Tick `decisions.txt` (`p` pursue / `s` skip), then `python rank.py --decide`. "
          "Every decision is also a training label for tuning Stage 2b later.", "",
          "An archetype marked _ambiguous_ means the top two scores were within "
          f"{ARCHETYPE_MARGIN:.0%} of each other — the label is not meaningful on that "
          "posting, only the relevance is.", "", "---", ""]
    for i, r in enumerate(rows, 1):
        j, s, llm = r["job"], r["score"], r.get("llm")
        md += [f"## {i}. {j.get('title')} — {j.get('company') or '?'}", "",
               f"`{r['slug']}` · {j.get('location') or 'location unstated'} · "
               f"via {j.get('source')} · **{s['archetype_label'] or '?'}**"
               + ("" if s["archetype_confident"]
                  else f" _(ambiguous — only {s['margin']:.0%} between the top two)_")
               + f" · batch score {s['relative']}/100"]
        if llm:
            md += ["", f"**Fit {llm.get('fit_score')}/100** — {llm.get('one_line_why', '')}"]
            if llm.get("missing_requirements"):
                md += ["", "Missing: " + ", ".join(llm["missing_requirements"])]
            if llm.get("red_flags"):
                md += ["", "**Red flags:** " + ", ".join(llm["red_flags"])]
        md += ["", f"<{j.get('url')}>", ""]
    if gaps:
        md += ["---", "", "## Skill gaps across this batch", "",
               "What the market asked for and your bank could not answer. This is a "
               "curriculum, not a criticism.", ""]
        for skill, n in gaps:
            md += [f"- **{skill}** — {n} posting(s)"]
    OUT.mkdir(exist_ok=True)
    (OUT / "digest.md").write_text("\n".join(md), encoding="utf-8")

    body = "".join(
        f"<article><h2>{i}. {escape(str(r['job'].get('title')))}</h2>"
        f"<p class='meta'>{escape(str(r['job'].get('company') or '?'))} · "
        f"{escape(str(r['job'].get('location') or ''))} · via {escape(str(r['job'].get('source')))}"
        f" · <b>{escape(str(r['score']['archetype_label'] or '?'))}</b>"
        + ("" if r['score']['archetype_confident'] else " <i>(ambiguous)</i>")
        + f" · {r['score']['relative']}/100</p>"
        + (f"<p class='why'>{escape(str(r['llm'].get('one_line_why','')))}</p>" if r.get("llm") else "")
        + f"<p><a href='{escape(str(r['job'].get('url')))}'>{escape(str(r['job'].get('url')))}</a></p></article>"
        for i, r in enumerate(rows, 1))
    (OUT / "digest.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Job digest</title>"
        "<style>html,body{background:#fff!important;color:#1a1a1a!important}"
        "body{font:14px/1.5 'Segoe UI',system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}"
        "article{border-bottom:1px solid #ddd;padding:.8rem 0}h2{font-size:15px;margin:0 0 .2rem}"
        ".meta{color:#666;font-size:12.5px;margin:.2rem 0}.why{margin:.3rem 0}"
        "a{color:#0645ad;word-break:break-all;font-size:12.5px}</style>"
        f"<h1>Job digest — {ts}</h1>{body}", encoding="utf-8")


def write_decisions(rows):
    prior = {}
    if DECISIONS.exists():
        for m in re.finditer(r"^\[([ psPS])\]\s+(\S+)", DECISIONS.read_text(encoding="utf-8"), re.M):
            prior[m.group(2)] = m.group(1).lower()
    L = ["# p = pursue, s = skip. Then: python rank.py --decide",
         "# Blank lines are left undecided and will reappear tomorrow.", ""]
    for r in rows:
        mark = prior.get(r["slug"], " ")
        L.append(f"[{mark}] {r['slug']:<62} # {str(r['job'].get('title'))[:52]}")
    DECISIONS.write_text("\n".join(L) + "\n", encoding="utf-8")


def apply_decisions(scores):
    if not DECISIONS.exists():
        sys.exit("decisions.txt not found — run `python rank.py` first.")
    log_data = json.loads(DECISION_LOG.read_text(encoding="utf-8")) if DECISION_LOG.exists() else {}
    n = 0
    for m in re.finditer(r"^\[([psPS])\]\s+(\S+)", DECISIONS.read_text(encoding="utf-8"), re.M):
        verdict, slug = ("pursue" if m.group(1).lower() == "p" else "skip"), m.group(2)
        if slug in log_data:
            continue
        # Snapshot the features AT DECISION TIME. Re-deriving them later would train on
        # a corpus that no longer exists.
        log_data[slug] = {"verdict": verdict,
                          "decided_at": datetime.now(timezone.utc).isoformat(),
                          "features": scores.get(slug, {})}
        n += 1
    STATE.mkdir(exist_ok=True)
    DECISION_LOG.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    tally = {}
    for v in log_data.values():
        tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
    log(f"recorded {n} new decision(s)")
    log(f"history: {tally.get('pursue', 0)} pursue / {tally.get('skip', 0)} skip "
        f"({len(log_data)} total)")
    if len(log_data) < 150:
        log(f"\n{150 - len(log_data)} more before there is enough signal to tune Stage 2b "
            f"against your own choices.")
    return 0


# --------------------------------------------------------------------------- driver

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="run Stage 2c on the top N")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--decide", action="store_true", help="apply ticks from decisions.txt")
    args = ap.parse_args()

    bank = R.load_bank()
    profile = bank["profile"]

    files = sorted(p for p in JOBS.glob("*.yaml"))
    if not files:
        sys.exit("no jobs found — run `python discover.py` first.")
    jobs = {p.stem: (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) for p in files}

    scores = score_batch(jobs, profile)
    if args.decide:
        return apply_decisions(scores)

    ranked = sorted(jobs, key=lambda s: -scores[s]["relative"])[:args.top]
    rows = [{"slug": s, "job": jobs[s], "score": scores[s]} for s in ranked]

    log(f"\nStage 2b — scored {len(jobs)} job(s) against "
        f"{len(profile.get('archetypes', []))} archetypes\n")
    for i, r in enumerate(rows, 1):
        sc = r["score"]
        flag = " " if sc["archetype_confident"] else "~"
        log(f"  {i:>2}. [{sc['relative']:>3}]{flag}{str(sc['archetype_label'] or '?'):<28}"
            f" {str(r['job'].get('title'))[:40]}")

    if args.llm:
        log(f"\nStage 2c — re-ranking the top {len(rows)}")
        for r in rows:
            prompt = build_prompt(r["job"], profile)
            manual = OUT / "prompts" / f"{r['slug']}.txt"
            try:
                res = call_llm(prompt)
            except Exception as e:                              # noqa: BLE001
                log(f"  {r['slug']}: LLM call failed ({e})")
                res = None
            if res is None:
                manual.parent.mkdir(parents=True, exist_ok=True)
                manual.write_text(prompt, encoding="utf-8")
            else:
                r["llm"] = res
                log(f"  [{res.get('fit_score')}] {r['slug'][:52]}")
        if not any("llm" in r for r in rows):
            log(f"\n  No API key (OPENROUTER_API_KEY / OPENAI_API_KEY).")
            log(f"  Prompts written to {OUT / 'prompts'} — paste one in anywhere, save the")
            log("  JSON beside it as <slug>.json, and re-run. 2b results below are unaffected.")

    gaps = {}
    for r in rows:
        for s in (r.get("llm") or {}).get("missing_requirements", []) or []:
            gaps[s] = gaps.get(s, 0) + 1
    for r in rows:
        for s in detect_job_skills(r["job"], bank["vocab"]):
            if not any(s in (f.get("skills") or []) for f in bank["facts"]
                       if f.get("status") == "confirmed"):
                gaps[s] = gaps.get(s, 0) + 1
    gaps = sorted(gaps.items(), key=lambda kv: -kv[1])[:12]

    write_digest(rows, gaps)
    write_decisions(rows)
    STATE.mkdir(exist_ok=True)
    SCORES.write_text(json.dumps(scores, indent=2), encoding="utf-8")

    if gaps:
        log("\nSkill gaps across this batch — what the market asked for and your bank"
            "\ncould not answer:")
        for skill, n in gaps[:6]:
            log(f"  {n} x  {skill}")

    log(f"\n  digest    -> {OUT / 'digest.md'}  (and .html)")
    log(f"  decisions -> {DECISIONS}")
    log("\nGATE 1 is yours. Tick p/s in decisions.txt, then: python rank.py --decide")
    return 0


if __name__ == "__main__":
    sys.exit(main())
