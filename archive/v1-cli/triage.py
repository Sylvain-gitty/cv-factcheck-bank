#!/usr/bin/env python3
"""Stage 3a — rank everything you decided to pursue, by how well the bank answers it.

    python triage.py                  # build any missing CVs, then the table
    python triage.py --top 25         # size of the recommended shortlist
    python triage.py --rebuild        # re-tailor even where a CV already exists
    python triage.py --csv            # also write out/triage.csv

------------------------------------------------------------------------------
WHY THIS STAGE EXISTS

Gate 1 answers "is this job worth my time?" from the posting alone, in about thirty
seconds each. It is deliberately cheap and deliberately generous -- over-filtering
costs more than under-filtering, because a job wrongly dropped never appears again.

The result of being generous is a pursue list longer than any week. Fifty-nine of
them, on the run this was written for, against a realistic eight to ten
applications a week. Something has to cut that down, and the expensive option is to
find out during Stage 4 -- after you have written an opening by hand -- that the
bank could only answer half the posting.

tailor.py already computes exactly the signal needed, and computes it for free:
`keyword_coverage` is the share of the skills detected in a posting that some
confirmed fact actually evidences. It caught a real one in testing. A posting
listed as "remotewoman - Product Manager" failed at 50%, and reading it showed the
employer was Upsun, a platform-as-a-service whose stack -- Docker, CI/CD, testing
-- has no fact behind it anywhere in the bank. Thirty seconds of Gate 1 could not
see that. One tailor run could.

So this stage runs that check across every pursue and sorts by it. It is Stage 3
used as a filter rather than as a deliverable, placed before Stage 4 because
everything up to here is machine time and everything after here is yours.

------------------------------------------------------------------------------
WHAT THE RANKING IS, AND WHAT IT IS NOT

Sorted by how many of a posting's detected skills a confirmed fact evidences, then
by the share of them, then by uncovered requirements ascending.

The count leads and the percentage follows, because the percentage alone is not
rankable. Coverage is a ratio and a thin posting has a tiny denominator: a job
naming two skills you happen to hold scores 100%. Sorted on the share alone, the
first run of this stage floated sixteen such postings above GlassFlow at 7/8 and
N26 at 4/6 -- the two strongest fits in the batch by every other measure. 2/2 and
12/14 are both near-perfect shares and only one of them is a CV with twelve things
to say.

Coverage is LEXICAL. It counts detected skill tags, so it rewards a posting whose
vocabulary happens to match the bank and says nothing about whether you would be
good at the job, whether the team is any good, or whether they would hire you.
Treat a low number as "the CV this produces will argue weakly", not as "bad job".

The uncovered-requirement count is the weaker of the two columns and is reported
second for that reason: requirement extraction still lifts boilerplate out of
postings -- "We give you your time back.", "An additional day of annual leave for
each year of service." -- and every line of it inflates the count. Two postings are
only comparable on that column if they are written to a similar length.

No composite score is computed. Multiplying a lexical percentage by a
boilerplate-inflated count would produce a number that looks like a measurement and
is not, which is the one thing this repo consistently refuses to do.

NOTHING HERE DECIDES ANYTHING. It writes into out/ and prints. No verdict is
changed, nothing is reopened, no job is skipped on your behalf. Cutting the list is
Gate 1's job and Gate 1 is you.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

# Output-directory naming, variant selection and the freshness stamp all live in
# tailor.py and are imported, not reimplemented. They decide what this stage measures,
# and a second copy would drift from the first the moment either changed.
from tailor import cv_is_current, dest_for, variant_for, write_stamp

HERE = Path(__file__).parent
JOBS = HERE / "jobs"
OUT = HERE / "out"
DECISION_LOG = HERE / ".state" / "decisions.json"
SCORES = HERE / ".state" / "scores.json"

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                                # noqa: BLE001
    pass


def log(msg=""):
    print(msg, flush=True)


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def bank_skills() -> set[str]:
    """Every skill some CONFIRMED fact carries. The same test rank.py uses for its gaps."""
    try:
        import render as R
        bank = R.load_bank()
    except Exception:                                            # noqa: BLE001
        return set()
    out = set()
    for f in bank.get("facts", []):
        if f.get("status") == "confirmed":
            out |= set(f.get("skills") or [])
    return out


def pursued() -> list[str]:
    return sorted(s for s, r in load_json(DECISION_LOG, {}).items()
                  if r.get("verdict") == "pursue")


def build(slug: str, variant: str) -> tuple[bool, str]:
    """Run tailor.py for one job. Returns (ok, message)."""
    src = JOBS / f"{slug}.yaml"
    if not src.exists():
        return False, "job file gone"
    r = subprocess.run([sys.executable, "tailor.py", f"jobs/{slug}.yaml",
                        "--variant", variant],
                       cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, (tail[-1][:60] if tail else f"exit {r.returncode}")
    return True, ""


def parse_coverage(detail: str) -> tuple[int | None, int | None, list[str]]:
    """'88% of the job's 8 detected skills present; missing: [...]' -> (88, 8, [...]).

    The DENOMINATOR is the point. A percentage on its own is unrankable here: a posting
    naming two skills you happen to hold scores 100%, and sorting on that alone floats
    the thinnest postings in the batch to the top above jobs where the bank answers
    twelve requirements out of fourteen. Same number, entirely different bet.
    """
    pct = re.match(r"\s*(\d+)%", detail or "")
    det = re.search(r"job's\s+(\d+)\s+detected skills", detail or "")
    missing = re.search(r"missing:\s*\[(.*?)\]", detail or "", re.S)
    skills = []
    if missing and missing.group(1).strip():
        skills = [t.strip().strip("'\"") for t in missing.group(1).split(",")]
        skills = [t for t in skills if t]
    return (int(pct.group(1)) if pct else None,
            int(det.group(1)) if det else None,
            skills)


def read_result(job: dict) -> dict | None:
    """Everything tailor.py already wrote about this job, from a previous run."""
    d = dest_for(job)
    checks = load_json(d / "checks.json", None)
    sel = load_json(d / "selection.json", None)
    if checks is None or sel is None:
        return None

    by_name = {c.get("check"): c for c in checks}
    cov = by_name.get("keyword_coverage", {})
    pct, detected, missing = parse_coverage(cov.get("detail", ""))
    failed = [c["check"] for c in checks if not c.get("pass")]
    return {
        "dir": d,
        "coverage": pct,
        "detected": detected,
        "matched": (detected - len(missing)) if detected is not None else None,
        "coverage_ok": bool(cov.get("pass", True)),
        "missing_skills": missing,
        "uncovered": len(sel.get("uncovered_requirements") or []),
        "bullets": len(sel.get("chosen") or []),
        "failed_checks": failed,
    }


def load_jobs(slugs) -> tuple[dict, list]:
    jobs, missing = {}, []
    for slug in slugs:
        p = JOBS / f"{slug}.yaml"
        if not p.exists():
            missing.append((slug, "job file gone"))
            continue
        try:
            jobs[slug] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as e:                                   # noqa: BLE001
            missing.append((slug, f"unreadable: {str(e)[:40]}"))
    return jobs, missing


def collect(slugs, rebuild: bool):
    scores = load_json(SCORES, {})
    jobs, problems = load_jobs(slugs)

    rows = []
    variants = {s: variant_for(s, scores) for s in jobs}
    # cv_is_current compares the stamp tailor.py leaves against the variant Stage 2b
    # implies now, because a CV built last week with a different variant is otherwise
    # indistinguishable from a fresh one: Enpal read 8/8 from a fortnight-old directory
    # and 8/14 once rebuilt.
    todo = [s for s in jobs
            if rebuild or not cv_is_current(jobs[s], s, variants[s])]
    if todo:
        log(f"building {len(todo)} CV(s) — tailor.py, no API, roughly "
            f"{max(1, round(len(todo) * 3 / 60))} min")
        log(f"  variant per posting from Stage 2b: "
            + ", ".join(f"{v} {sum(1 for s in todo if variants[s] == v)}"
                        for v in sorted(set(variants[s] for s in todo))) + "\n")
    for i, slug in enumerate(todo, 1):
        ok, why = build(slug, variants[slug])
        if ok:
            write_stamp(dest_for(jobs[slug]), slug, variants[slug])
        mark = "ok " if ok else "-- "
        log(f"  {i:>3}/{len(todo)}  {mark}[{variants[slug]:<4}] {slug[:50]}"
            + (f"   {why}" if why else ""))
        if not ok:
            problems.append((slug, why))

    already = {s for s, _ in problems}
    for slug, job in jobs.items():
        res = read_result(job)
        if res is None:
            if slug not in already:
                problems.append((slug, "no tailored output"))
            continue
        rows.append({
            "slug": slug,
            "company": job.get("company") or "?",
            "title": job.get("title") or "",
            "location": job.get("location") or "",
            "url": job.get("url") or "",
            "variant": variants[slug],
            "batch_score": (scores.get(slug) or {}).get("relative", ""),
            "coverage": res["coverage"],
            "detected": res["detected"],
            "matched": res["matched"],
            "coverage_ok": res["coverage_ok"],
            "uncovered": res["uncovered"],
            "bullets": res["bullets"],
            "missing_skills": res["missing_skills"],
            "failed_checks": res["failed_checks"],
        })

    # Sort by how MANY of the posting's skills the bank answers, then by the share of
    # them. Matched-count first because it is the quantity that survives a thin posting:
    # 2/2 and 12/14 are both near-perfect shares, and only one of them is a CV with
    # twelve things to say.
    rows.sort(key=lambda r: (-(r["matched"] if r["matched"] is not None else -1),
                             -(r["coverage"] if r["coverage"] is not None else -1),
                             r["uncovered"]))
    return rows, problems


def render(rows, problems, top: int):
    if not rows:
        log("\nnothing to triage — no pursued job has a tailored CV yet")
        return 1

    log(f"\n{len(rows)} pursued job(s), sorted by skills answered (then by share)")
    log("=" * 78)
    log("  skills = of the skills detected in the posting, how many a confirmed fact")
    log("  evidences. Read 12/14 as a strong bet and 2/2 as a thin posting, not as a tie.")
    log("=" * 78)
    log(f"{'':4}{'skills':>8}{'':4}{'var':>5}{'unc':>4} {'batch':>6}  job")
    for i, r in enumerate(rows, 1):
        if i == top + 1:
            log("-" * 78 + f"   <- recommended cut at {top}")
        if r["matched"] is None:
            ratio, pct = "    ?", "     "
        else:
            ratio = f"{r['matched']}/{r['detected']}"
            pct = f"{r['coverage']}%"
        flag = " !" if not r["coverage_ok"] else "  "
        log(f"{i:>3}.{ratio:>8}{flag}{pct:>5}{r['variant']:>5}{r['uncovered']:>4} "
            f"{str(r['batch_score']):>6}  {r['company'][:16]:<16} {r['title'][:28]}")
        log(f"{'':>28}{r['slug'][:50]}")

    weak = [r for r in rows if not r["coverage_ok"]]
    if weak:
        log(f"\n{len(weak)} posting(s) FAIL the coverage check outright — the bank")
        log("answers less than half of what they ask for:")
        for r in weak:
            log(f"    {r['coverage']}%  {r['company'][:22]:<22} {r['slug'][:40]}")
            if r["missing_skills"]:
                log(f"         missing: {', '.join(r['missing_skills'][:6])}")

    other = [r for r in rows if r["failed_checks"] and
             r["failed_checks"] != ["keyword_coverage"]]
    if other:
        log(f"\n{len(other)} posting(s) fail a check other than coverage:")
        for r in other:
            rest = [c for c in r["failed_checks"] if c != "keyword_coverage"]
            log(f"    {r['slug'][:52]}  {', '.join(rest)}")

    gaps = Counter()
    for r in rows:
        gaps.update(r["missing_skills"])
    if gaps:
        # SPLIT THE LIST, because one word covers two different problems.
        # keyword_coverage reports a skill missing when no SELECTED bullet carries it,
        # and a CV selects about ten bullets out of the whole bank. So the raw list
        # mixes "you cannot evidence this at all" with "you can, but this posting's ten
        # bullets went elsewhere" -- which is why `sql` and `python` appeared in it.
        # Only the first is a curriculum. The second is a selection artefact and
        # learning Python again would not move it.
        have = bank_skills()
        absent = Counter({s: n for s, n in gaps.items() if s not in have})
        unselected = Counter({s: n for s, n in gaps.items() if s in have})

        if absent:
            log(f"\nSkill gaps across all {len(rows)} pursued postings")
            log("Asked for by the market, evidenced by no confirmed fact anywhere in the")
            log("bank. This is the curriculum, measured over everything you said yes to")
            log("rather than over one batch's top twenty.")
            for skill, n in absent.most_common(15):
                log(f"  {n:>3} x  {skill}")
        if unselected:
            log("\nIn the bank, but not in the bullets these CVs chose:")
            for skill, n in unselected.most_common(8):
                log(f"  {n:>3} x  {skill}")
            log("Not a gap. Either the posting wanted a different emphasis, or the")
            log("per-CV bullet cap pushed the evidencing fact off the page.")

    if problems:
        log(f"\n{len(problems)} job(s) produced nothing:")
        for slug, why in problems:
            log(f"    {slug[:56]}  — {why}")

    log(f"\nNothing above has been decided. To take the top {top} forward, start with")
    log("the letters: python letter.py jobs/<slug>.yaml")
    return 0


def write_csv(rows) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / "triage.csv"
    cols = ["slug", "company", "title", "location", "variant", "matched", "detected",
            "coverage", "coverage_ok", "uncovered", "bullets", "batch_score",
            "missing_skills", "url"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = dict(r)
            row["missing_skills"] = " ".join(r["missing_skills"])
            w.writerow(row)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25, help="size of the recommended shortlist")
    ap.add_argument("--rebuild", action="store_true", help="re-tailor even where a CV exists")
    ap.add_argument("--csv", action="store_true", help="also write out/triage.csv")
    args = ap.parse_args()

    slugs = pursued()
    if not slugs:
        log("nothing pursued yet — tick some jobs and run `python rank.py --decide`")
        return 0

    rows, problems = collect(slugs, args.rebuild)
    rc = render(rows, problems, args.top)
    if args.csv and rows:
        log(f"\n  -> {write_csv(rows)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
