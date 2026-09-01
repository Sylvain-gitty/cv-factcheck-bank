#!/usr/bin/env python3
"""Stage 6 — application tracking and the weekly report.

    python track.py --add <job-slug>       # log an application (snapshots its features)
    python track.py                        # the report
    python track.py --open                 # what needs chasing
    python track.py --csv                  # path to the sheet

The log is `applications.csv`. Open it in a spreadsheet and edit the outcome columns by
hand -- `sent_date`, `first_reply_date`, `status`, `notes`. Nothing here overwrites them.

------------------------------------------------------------------------------
WHY THIS STAGE EXISTS

Your job search is a product with one metric -- interviews per week -- and a four-stage
funnel. Instrumented, you will make better decisions than someone applying to twice as
many jobs on instinct. Uninstrumented, you will remember the rejections and forget the
pattern.

------------------------------------------------------------------------------
THREE WAYS THIS REPORT REFUSES TO MISLEAD YOU

1. SMALL n IS NOT A RATE. Twelve applications and one reply is not evidence about your
   CV; it is one reply. Every proportion here carries a Wilson 95% interval, and below
   MIN_N the report says so instead of printing a number that looks like a finding.
   This is the same instinct as declining to report an F2 gain whose interval crossed
   zero -- pointed at your own job search.

2. NO REPLY IS NOT A NO. It is not-yet-observed. An application sent four days ago has
   not been rejected; it has not been answered. Counting it as a failure biases every
   rate downwards, and the bias is worst exactly when you are most active. Applications
   inside the response window are held out as CENSORED and excluded from the
   denominators.

3. ONE VARIABLE AT A TIME. If you change the CV variant, the sources and the letter tone
   in the same fortnight, no breakdown below can attribute anything. The report warns
   when a dimension has churned too fast to read.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

import render as R

HERE = Path(__file__).parent
JOBS = HERE / "jobs"
STATE = HERE / ".state"
CSV_PATH = HERE / "applications.csv"
DECISIONS = STATE / "decisions.json"

FIELDS = ["slug", "company", "title", "source", "archetype", "batch_score",
          "cv_variant", "letter", "sent_date", "first_reply_date", "status", "notes"]

# An application younger than this with no reply is not a rejection -- it is unanswered.
RESPONSE_WINDOW_DAYS = 21
# Below this, a proportion is an anecdote. 25 is where a Wilson interval on a ~15% rate
# stops spanning most of the possible range.
MIN_N = 25

OPEN = {"", "sent", "open"}
POSITIVE = {"replied", "screen", "interview", "offer"}


def log(msg=""):
    print(msg, flush=True)


try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                                # noqa: BLE001
    pass


# --------------------------------------------------------------------------- stats

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval. Correct at small n, where the normal approximation is not.

    Returns (point, low, high) as proportions.
    """
    if n == 0:
        return 0.0, 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def classify(row) -> str:
    """replied | rejected | censored | unsent."""
    status = (row.get("status") or "").strip().lower()
    sent = parse_date(row.get("sent_date"))
    if not sent:
        return "unsent"
    if status in POSITIVE or parse_date(row.get("first_reply_date")):
        return "replied"
    if status in ("rejected", "no", "closed"):
        return "rejected"
    age = (date.today() - sent).days
    return "censored" if age < RESPONSE_WINDOW_DAYS else "rejected"


# --------------------------------------------------------------------------- io

def read_rows() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_rows(rows):
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def add(slug: str) -> int:
    rows = read_rows()
    if any(r["slug"] == slug for r in rows):
        sys.exit(f"{slug} is already logged — edit applications.csv directly")
    job_path = JOBS / f"{slug}.yaml"
    if not job_path.exists():
        sys.exit(f"no job file at {job_path}")
    job = yaml.safe_load(job_path.read_text(encoding="utf-8")) or {}

    # Snapshot the score AS IT WAS. Re-deriving it later would score against a corpus
    # that no longer exists, and the whole point of the log is what you knew at the time.
    scores = {}
    sp = STATE / "scores.json"
    if sp.exists():
        scores = json.loads(sp.read_text(encoding="utf-8")).get(slug, {})

    rows.append({
        "slug": slug, "company": job.get("company") or "", "title": job.get("title") or "",
        "source": job.get("source") or "", "archetype": scores.get("archetype") or "",
        "batch_score": scores.get("relative", ""), "cv_variant": "ds", "letter": "",
        "sent_date": date.today().isoformat(), "first_reply_date": "",
        "status": "sent", "notes": "",
    })
    write_rows(rows)
    log(f"logged {slug}  ({len(rows)} application(s) total)")
    log(f"edit outcomes in {CSV_PATH.name} — status, first_reply_date, notes")
    return 0


# --------------------------------------------------------------------------- report

def rate_line(label, k, n, width=22):
    p, lo, hi = wilson(k, n)
    if n == 0:
        return f"  {label:<{width}} —"
    bar = "" if n < 5 else f"  [{lo:.0%}–{hi:.0%}]"
    warn = "   too few to read" if n < 8 else ""
    return f"  {label:<{width}} {k:>3}/{n:<3} {p:>5.0%}{bar}{warn}"


def breakdown(rows, key, label):
    groups = defaultdict(lambda: [0, 0])
    for r in rows:
        c = classify(r)
        if c == "censored" or c == "unsent":
            continue
        g = (r.get(key) or "—").strip() or "—"
        groups[g][1] += 1
        if c == "replied":
            groups[g][0] += 1
    if not groups:
        return
    log(f"\n  by {label}")
    for g, (k, n) in sorted(groups.items(), key=lambda kv: -kv[1][1]):
        log(rate_line(g, k, n))
    if len(groups) > 1 and all(n < 8 for _, (_, n) in groups.items()):
        log(f"    every {label} bucket is under 8 — this split cannot support a comparison yet")
        return

    # THE COMPARISON, NOT JUST THE NUMBERS. Two point estimates can look decisive while
    # their intervals overlap completely, which means the data cannot distinguish them.
    # Saying so is the whole difference between a report and a rationalisation.
    ranked = sorted(((k / n if n else 0, k, n, g) for g, (k, n) in groups.items()
                     if n >= 5), reverse=True)
    if len(ranked) >= 2:
        (_, k1, n1, g1), (_, k2, n2, g2) = ranked[0], ranked[-1]
        _, lo1, hi1 = wilson(k1, n1)
        _, lo2, hi2 = wilson(k2, n2)
        if lo1 <= hi2:
            log(f"    {g1} looks better than {g2}, but the intervals overlap"
                f" — not yet a difference you can act on")
        else:
            log(f"    {g1} beats {g2} with no interval overlap — the first real signal here")


def report() -> int:
    rows = read_rows()
    counts = Counter(classify(r) for r in rows)
    sent = [r for r in rows if classify(r) != "unsent"]
    decided = [r for r in sent if classify(r) != "censored"]
    replied = [r for r in sent if classify(r) == "replied"]

    surfaced = pursued = 0
    if DECISIONS.exists():
        d = json.loads(DECISIONS.read_text(encoding="utf-8"))
        surfaced = len(d)
        pursued = sum(1 for v in d.values() if v.get("verdict") == "pursue")

    log("\n" + "=" * 68)
    log(f"APPLICATION REPORT — {date.today().isoformat()}")
    log("=" * 68)

    log("\nFUNNEL")
    for label, n, of in (("surfaced (decided at Gate 1)", surfaced, None),
                         ("pursued", pursued, surfaced),
                         ("sent", len(sent), pursued),
                         ("replied", len(replied), len(decided))):
        if not of:
            pct = ""
        elif n > of:
            # More sent than pursued means applications were logged here that never went
            # through Gate 1. Not an error, but the funnel no longer nests, and printing
            # "1600% of previous" would be arithmetic pretending to be a statistic.
            pct = "   (exceeds previous stage — some were logged without a Gate 1 decision)"
        else:
            pct = f"   {n / of:.0%} of previous"
        log(f"  {label:<30} {n:>4}{pct}")
    if counts["censored"]:
        log(f"  {'awaiting reply (censored)':<30} {counts['censored']:>4}"
            f"   sent < {RESPONSE_WINDOW_DAYS}d ago — not counted as rejections")

    log("\nRESPONSE RATE")
    if len(decided) < MIN_N:
        log(f"  {len(replied)}/{len(decided)} — NOT REPORTED AS A RATE.")
        log(f"  {MIN_N - len(decided)} more resolved application(s) needed before a")
        log("  proportion here means anything. A number now would look like a finding")
        log("  and be an anecdote.")
        if decided:
            p, lo, hi = wilson(len(replied), len(decided))
            log(f"  For scale, the 95% interval at this n is {lo:.0%}–{hi:.0%}: it spans")
            log("  almost every value it could take, which is the point.")
    else:
        log(rate_line("overall", len(replied), len(decided)))
        for key, label in (("source", "source"), ("archetype", "archetype"),
                           ("cv_variant", "CV variant")):
            breakdown(decided, key, label)

        buckets = defaultdict(lambda: [0, 0])
        for r in decided:
            try:
                s = int(float(r.get("batch_score") or 0))
            except ValueError:
                s = 0
            b = f"{s // 25 * 25}-{s // 25 * 25 + 24}"
            buckets[b][1] += 1
            if classify(r) == "replied":
                buckets[b][0] += 1
        log("\n  by batch score")
        for b in sorted(buckets):
            log(rate_line(b, *buckets[b]))

    if replied:
        days = [(parse_date(r.get("first_reply_date")) - parse_date(r.get("sent_date"))).days
                for r in replied
                if parse_date(r.get("first_reply_date")) and parse_date(r.get("sent_date"))]
        if days:
            days.sort()
            log(f"\nTIME TO FIRST REPLY   median {days[len(days) // 2]}d   "
                f"range {days[0]}–{days[-1]}d   n={len(days)}")

    variants = Counter(r.get("cv_variant") or "—" for r in sent)
    if len(variants) > 1 and len(sent) < 25:
        log(f"\nWARNING — {len(variants)} CV variants across only {len(sent)} applications.")
        log("  Hold one variant fixed for 25 applications before changing it. Otherwise no")
        log("  breakdown above can attribute a difference to anything you did.")

    log("\n" + "-" * 68)
    log("Read this like a data scientist, not a gambler:")
    log("  · no reply is not a rejection, it is not-yet-observed")
    log("  · a rate without an interval is a guess with a decimal point")
    log("  · you are the annotator; keep the labels honest and the data stays useful")
    return 0


def open_items() -> int:
    rows = [r for r in read_rows() if classify(r) in ("censored", "unsent")]
    if not rows:
        log("nothing outstanding")
        return 0
    log(f"\n{len(rows)} outstanding")
    for r in sorted(rows, key=lambda x: x.get("sent_date") or ""):
        sent = parse_date(r.get("sent_date"))
        age = (date.today() - sent).days if sent else None
        chase = "  <- chase" if age is not None and age >= 7 else ""
        log(f"  {(str(age) + 'd') if age is not None else 'unsent':>6}  "
            f"{(r.get('company') or '?')[:24]:<24} {r.get('title', '')[:38]}{chase}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", metavar="SLUG")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    if args.csv:
        log(str(CSV_PATH))
        return 0
    if args.add:
        return add(args.add)
    if not CSV_PATH.exists():
        write_rows([])
        log(f"created {CSV_PATH.name}")
    if args.open:
        return open_items()
    return report()


if __name__ == "__main__":
    sys.exit(main())
