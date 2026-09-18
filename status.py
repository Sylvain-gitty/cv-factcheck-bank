#!/usr/bin/env python3
"""Where every pursued job has got to.

    python status.py              # the board
    python status.py --stage drafted
    python status.py --csv        # also write out/pipeline.csv

Four stages, in order:

    pursued    you decided to go for it; nothing built yet
    drafted    tailor.py has produced a CV and letter.py a letter draft
    tailored   you wrote the opening, the gates pass, the letter rendered
    applied    you sent it

------------------------------------------------------------------------------
THE STAGE IS DERIVED, NOT DECLARED

There is no status column here to keep up to date, because a status column is a
second copy of the truth and the copy is always the one that is wrong. You do not
forget to write a CV -- tailor.py writes it, or it does not exist. So every stage
below is read off the artefacts themselves:

    drafted    the posting's CV directory  AND  letters/<slug>.md
               (that directory is named after the POSTING, not the job file, so the
               path comes from tailor.dest_for rather than from the slug)
    tailored   out/letters/<slug>.html, NEWER than letters/<slug>.md -- --render
               refuses to produce it while a fatal gate is failing, so it proves
               the checks passed; the freshness test is because out/ survives
               edits to the draft, and a render from a previous week is not a
               render of what the draft now says
    applied    a sent_date in applications.csv

Exactly one of those cannot be derived, and it is the last one. Sending is an act
outside this machine: nothing here can observe it, which is why package.py --sent
exists and why that is the only stage you have to assert by hand. Everything the
tooling does itself, the tooling reports itself.

The board also names the next command for each job, because "where is everything"
and "what do I do next" are the same question asked twice.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Same rule tailor.py uses to name the directory it writes, imported so the
# board cannot drift from the thing it is reporting on.
from tailor import dest_for

HERE = Path(__file__).parent
JOBS = HERE / "jobs"
OUT = HERE / "out"
LETTERS = HERE / "letters"
DECISION_LOG = HERE / ".state" / "decisions.json"
APPLICATIONS = HERE / "applications.csv"

# The marker letter.py leaves in a fresh draft. While it is there the opening is
# unwritten and every gate fails, so it is the single most useful thing to report
# about a job sitting at `drafted`.
OPENING_TODO = "OPENING: WRITE THIS YOURSELF"

STAGES = ["pursued", "drafted", "tailored", "applied"]

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


def sent_dates() -> dict[str, str]:
    """slug -> sent_date, for rows that actually carry one."""
    if not APPLICATIONS.exists():
        return {}
    out = {}
    with APPLICATIONS.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            slug, when = (row.get("slug") or "").strip(), (row.get("sent_date") or "").strip()
            if slug and when:
                out[slug] = when
    return out


def stage_of(slug: str, job: dict, sent: dict[str, str]) -> tuple[str, str]:
    """(stage, the next command to run). Derived entirely from what is on disk."""
    if slug in sent:
        return "applied", ""

    # The CV directory is named after the POSTING, not the job file, and the two are
    # only usually the same string. Where they diverge -- a long title truncated in the
    # filename, say -- assuming the slug reports a built CV as missing and parks the job
    # at `pursued` forever. Two jobs sat there until this used tailor's own rule.
    cv = (dest_for(job) / "cv.html").exists()
    draft = LETTERS / f"{slug}.md"
    # A RENDER OLDER THAN ITS SOURCE IS NOT A RENDER. out/letters/ survives edits to
    # letters/*.md, so a stale HTML/PDF from a previous week keeps reporting `tailored`
    # while the draft underneath has been rewritten -- or, as happened here, replaced
    # by an unwritten stub whose .md source had been lost entirely. package.py copies
    # the rendered file, so the stale one would have been the one that got sent.
    rendered = False
    if draft.exists():
        for _ext in ("html", "pdf"):
            _out = OUT / "letters" / f"{slug}.{_ext}"
            if _out.exists() and _out.stat().st_mtime >= draft.stat().st_mtime:
                rendered = True
                break
    packaged = (OUT / "applications" / slug).exists()

    if packaged:
        return "tailored", f"python package.py --sent {slug}"
    if rendered:
        return "tailored", f"python package.py {slug}"

    if cv and draft.exists():
        try:
            unwritten = OPENING_TODO in draft.read_text(encoding="utf-8")
        except OSError:
            unwritten = False
        if unwritten:
            return "drafted", f"write the opening in letters/{slug}.md"
        return "drafted", f"python letter.py --check {slug}"

    if cv:
        return "pursued", f"python letter.py jobs/{slug}.yaml"
    return "pursued", f"python tailor.py jobs/{slug}.yaml --explain"


def in_flight() -> tuple[set[str], dict]:
    """Every slug that is actually being worked on, and the decision log.

    A logged pursue is the usual way in, but it is not the only one. Work that
    predates the decision log, or was started from a URL by hand, leaves exactly the
    same artefacts behind and is exactly as easy to forget -- an assembled,
    unsent application sitting in out/applications/ is the most expensive thing
    this board can fail to mention. So anything with a packaged folder or a row in
    applications.csv counts as in flight whether Gate 1 logged it or not.

    A letter draft alone does not qualify: drafts exist for jobs later skipped, and
    reviving those on the board would argue with a decision already made.
    """
    log_data = load_json(DECISION_LOG, {})
    slugs = {s for s, r in log_data.items() if r.get("verdict") == "pursue"}
    if (OUT / "applications").exists():
        slugs |= {p.name for p in (OUT / "applications").iterdir() if p.is_dir()}
    if APPLICATIONS.exists():
        with APPLICATIONS.open(newline="", encoding="utf-8") as fh:
            slugs |= {(r.get("slug") or "").strip() for r in csv.DictReader(fh)
                      if (r.get("slug") or "").strip()}
    return slugs, log_data


def collect():
    slugs, log_data = in_flight()
    sent = sent_dates()
    jobs = {p.stem: p for p in JOBS.glob("*.yaml")}

    rows = []
    for slug in slugs:
        row = log_data.get(slug, {})
        job = {}
        if slug in jobs:
            try:
                import yaml
                job = yaml.safe_load(jobs[slug].read_text(encoding="utf-8")) or {}
            except Exception:                                    # noqa: BLE001
                job = {}
        stage, nxt = stage_of(slug, job, sent)
        rows.append({
            "stage": stage,
            "slug": slug,
            "company": (job.get("company") or "?"),
            "title": (job.get("title") or ""),
            "decided": str(row.get("decided_at", ""))[:10],
            "sent": sent.get(slug, ""),
            "next": nxt,
            "orphan": slug not in jobs,
            "undecided": slug not in log_data,
        })
    rows.sort(key=lambda r: (STAGES.index(r["stage"]), r["decided"]))
    return rows


def render(rows, only=None) -> int:
    if not rows:
        log("\nnothing pursued yet — tick some jobs and run `python rank.py --decide`")
        return 0

    counts = {st: sum(1 for r in rows if r["stage"] == st) for st in STAGES}
    log("\n" + "  ".join(f"{st} {counts[st]}" for st in STAGES))
    log("-" * 74)

    shown = 0
    for st in STAGES:
        group = [r for r in rows if r["stage"] == st and (only in (None, st))]
        if not group:
            continue
        log(f"\n{st.upper()}  ({len(group)})")
        for r in group:
            flag = "  [job file gone]" if r["orphan"] else ""
            if r["undecided"]:
                flag += "  [not in the decision log]"
            head = f"{r['company'][:22]:<22} {r['title'][:40]}"
            log(f"  {head}{flag}")
            log(f"    {r['slug'][:66]}")
            if r["sent"]:
                log(f"    sent {r['sent']}")
            elif r["next"]:
                log(f"    next: {r['next']}")
            shown += 1

    if only and not shown:
        log(f"\nnothing at stage '{only}'")
        return 0

    stuck = [r for r in rows if r["stage"] == "pursued"]
    if stuck:
        log(f"\n{len(stuck)} pursued job(s) with nothing built yet. A pursue you never")
        log("assemble is the same as a skip, except it also cost you the decision.")
    return 0


def write_csv(rows) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / "pipeline.csv"
    cols = ["stage", "slug", "company", "title", "decided", "sent", "next"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=STAGES, help="show only this stage")
    ap.add_argument("--csv", action="store_true", help="also write out/pipeline.csv")
    args = ap.parse_args()

    rows = collect()
    rc = render(rows, args.stage)
    if args.csv:
        log(f"\n  -> {write_csv(rows)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
