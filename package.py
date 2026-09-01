#!/usr/bin/env python3
"""Stage 5 — assemble a ready-to-send application, then stop.

    python package.py <job-slug>          # assemble; refuses if any gate is failing
    python package.py --list              # the queue: what is ready, what is blocked
    python package.py --sent <job-slug>   # you submitted it; log it and start the clock

Produces out/applications/<slug>/ containing the CV, the letter, a submission checklist
with your screening answers filled in, and a follow-up calendar file.

------------------------------------------------------------------------------
GATE 4 — YOU SUBMIT. THIS TOOL DOES NOT, AND WILL NOT.

There is no --submit flag and there is not going to be one. Four independent reasons, any
one of which is sufficient:

1. TERMS OF SERVICE. Automated submission is prohibited on most job platforms. The
   downside is losing the account you are job-searching with, mid-search.
2. IRREVERSIBILITY. A letter with the wrong company name cannot be recalled, and it is the
   single most common catastrophic failure in automated applications. Everyone has done it
   once by hand. Now imagine it firing eight times before you notice.
3. CREDENTIALS AND PERSONAL DATA. Portal logins, CAPTCHAs, address and salary fields.
   Automating credential entry on your behalf is exactly the category of action that stays
   in human hands.
4. SCREENING QUESTIONS. "Why us?", "Notice period?", "Salary expectation?" are answered by
   a person or answered badly.

What this stage removes is the twenty minutes of assembly around the submission, not the
submission. That is the whole trade, and it is a good one.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

import letter as L
import render as R
import tailor as T
import track as TR

HERE = Path(__file__).parent
JOBS = HERE / "jobs"
LETTERS = HERE / "letters"
OUT = HERE / "out" / "applications"
FOLLOW_UP_DAYS = (7, 14)


def log(msg=""):
    print(msg, flush=True)


try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                                # noqa: BLE001
    pass


# --------------------------------------------------------------------------- readiness

def readiness(slug, bank):
    """What is done, what is not. Returns (list of (name, ok, detail), job or None)."""
    out = []
    job_path = JOBS / f"{slug}.yaml"
    if not job_path.exists():
        return [("job file", False, f"no {job_path.name} — run discover.py")], None
    job = T.load_job(job_path)
    out.append(("job file", True, job.get("title") or slug))

    cv_dir = HERE / "out" / "jobs" / T.slugify(f"{job.get('company','')}-{job.get('title','')}")
    cv_pdf = cv_dir / "cv.pdf"
    cv_html = cv_dir / "cv.html"
    out.append(("tailored CV", cv_html.exists(),
                str(cv_html) if cv_html.exists() else f"run: python tailor.py jobs/{slug}.yaml"))

    lp = LETTERS / f"{slug}.md"
    if not lp.exists():
        out.append(("letter draft", False, f"run: python letter.py jobs/{slug}.yaml"))
        return out, job
    text = lp.read_text(encoding="utf-8")
    checks = L.run_checks(slug, text, job, bank)
    failed = [c for c in checks if not c["pass"] and c["fatal"]]
    out.append(("letter gates", not failed,
                "all gates pass" if not failed
                else f"{len(failed)} failing: " + ", ".join(c["check"] for c in failed)))
    return out, job


def load_answers():
    p = HERE / "answers.yaml"
    if not p.exists():
        return []
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("answers", [])


# --------------------------------------------------------------------------- artefacts

def checklist(slug, job, bank, answers) -> str:
    owner = bank["profile"].get("owner", {})
    unanswered = [a for a in answers if a.get("answer") in (None, "")]
    L_ = [
        f"# {job.get('title')} — {job.get('company') or ''}".rstrip(" —"), "",
        f"**Apply at:** {job.get('url')}", "",
        f"Prepared {date.today().isoformat()} · {job.get('location') or 'location unstated'}"
        f" · via {job.get('source')}", "",
        "---", "", "## Before you submit", "",
        "- [ ] Open `cv.pdf` and read it. Not the HTML — the PDF.",
        "- [ ] Read the letter aloud once. Cut anything you would not say.",
        "- [ ] Check the company name in the letter. Out loud. This is the one that ends careers.",
        "- [ ] Confirm the posting is still live and the deadline has not passed.",
        "- [ ] Attach both files. Check you attached the *tailored* CV, not the master.",
        "", "## Screening answers", "",
        "Paste these; do not retype them. `PER_JOB` means write it fresh for this posting.",
        "",
    ]
    for a in answers:
        ans = a.get("answer")
        if ans == "PER_JOB":
            body = "_write this one fresh — a stored answer to \"why us\" is the generic "
            body += "letter problem wearing a different hat_"
        elif ans in (None, ""):
            body = "**UNANSWERED** — fill this in `answers.yaml` before you need it"
        else:
            body = R.clean(str(ans))
        L_ += [f"**{a['question']}**", "", body, ""]

    L_ += ["---", "", "## After you submit", "",
           f"- [ ] `python package.py --sent {slug}`",
           f"- [ ] Follow up on {(date.today() + timedelta(days=FOLLOW_UP_DAYS[0])).isoformat()}"
           f" if no reply (see follow-up.ics)",
           "", "## Gate 4", "",
           "This package is complete. **Submitting it is yours** — no tool here does it, and",
           "none will. Automated submission breaks most platforms' terms, a wrong-company",
           "letter cannot be recalled, and the screening questions above are answered by a",
           "person or answered badly.", ""]
    if unanswered:
        L_ += [f"> {len(unanswered)} screening answer(s) are still blank: "
               + ", ".join(a["id"] for a in unanswered) + ".", ""]
    return "\n".join(L_)


def follow_up_ics(slug, job) -> str:
    """Two reminders. Plain iCalendar text — no dependency, imports anywhere."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//cv-fact-bank//EN"]
    for n in FOLLOW_UP_DAYS:
        d = (date.today() + timedelta(days=n)).strftime("%Y%m%d")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{slug}-followup-{n}@cv-fact-bank",
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}",
            f"DTSTART;VALUE=DATE:{d}",
            f"SUMMARY:Follow up — {job.get('company') or ''} · {job.get('title') or ''}",
            f"DESCRIPTION:Day {n}. No reply yet? A short polite nudge.\\n{job.get('url')}",
            "END:VEVENT",
        ]
    return "\n".join(lines + ["END:VCALENDAR"])


# --------------------------------------------------------------------------- commands

def assemble(slug) -> int:
    bank = R.load_bank()
    checks, job = readiness(slug, bank)
    log(f"\nREADINESS — {slug}")
    for name, ok, detail in checks:
        log(f"  [{'ok  ' if ok else 'FAIL'}] {name:<14} {detail[:70]}")
    if not all(ok for _, ok, _ in checks):
        log("\n  NOT ASSEMBLED — finish the failing steps above first.")
        return 1

    dest = OUT / slug
    dest.mkdir(parents=True, exist_ok=True)

    cv_dir = HERE / "out" / "jobs" / T.slugify(f"{job.get('company','')}-{job.get('title','')}")
    name = (bank["profile"].get("owner", {}).get("name") or "cv").replace(" ", "_")
    for src, tgt in ((cv_dir / "cv.pdf", f"{name}_CV.pdf"),
                     (cv_dir / "cv.html", f"{name}_CV.html")):
        if src.exists():
            shutil.copy2(src, dest / tgt)
    if not (dest / f"{name}_CV.pdf").exists() and (cv_dir / "cv.html").exists():
        R.to_pdf(cv_dir / "cv.html", dest / f"{name}_CV.pdf")

    lh, lpdf = L.render_letter(slug, (LETTERS / f"{slug}.md").read_text(encoding="utf-8"),
                               job, bank)
    shutil.copy2(lh, dest / f"{name}_Letter.html")
    if lpdf and lpdf.exists():
        shutil.copy2(lpdf, dest / f"{name}_Letter.pdf")

    answers = load_answers()
    (dest / "CHECKLIST.md").write_text(checklist(slug, job, bank, answers), encoding="utf-8")
    (dest / "follow-up.ics").write_text(follow_up_ics(slug, job), encoding="utf-8")

    rows = TR.read_rows()
    if not any(r["slug"] == slug for r in rows):
        scores = {}
        sp = HERE / ".state" / "scores.json"
        if sp.exists():
            import json
            scores = json.loads(sp.read_text(encoding="utf-8")).get(slug, {})
        rows.append({"slug": slug, "company": job.get("company") or "",
                     "title": job.get("title") or "", "source": job.get("source") or "",
                     "archetype": scores.get("archetype") or "",
                     "batch_score": scores.get("relative", ""), "cv_variant": "ds",
                     "letter": "yes", "sent_date": "", "first_reply_date": "",
                     "status": "ready", "notes": ""})
        TR.write_rows(rows)

    blank = [a["id"] for a in answers if a.get("answer") in (None, "")]
    log(f"\n  -> {dest}")
    for f in sorted(p.name for p in dest.iterdir()):
        log(f"     {f}")
    if blank:
        log(f"\n  {len(blank)} screening answer(s) still blank: {', '.join(blank)}")
        log("  Fill them in answers.yaml once and they are done for every application.")
    log("\nGATE 4 — read CHECKLIST.md, then submit it yourself.")
    log(f"  afterwards:  python package.py --sent {slug}")
    return 0


def queue() -> int:
    bank = R.load_bank()
    rows = {r["slug"]: r for r in TR.read_rows()}
    slugs = sorted({p.stem for p in LETTERS.glob("*.md")} | set(rows))
    if not slugs:
        log("nothing in the queue — start with: python letter.py jobs/<slug>.yaml")
        return 0
    log(f"\n{'slug':<44} {'status':<10} blockers")
    log("-" * 92)
    for slug in slugs:
        row = rows.get(slug, {})
        status = (row.get("status") or "draft").strip()
        if status == "sent" or row.get("sent_date"):
            log(f"{slug[:44]:<44} {'sent':<10} —")
            continue
        checks, _ = readiness(slug, bank)
        bad = [n for n, ok, _ in checks if not ok]
        log(f"{slug[:44]:<44} {status:<10} "
            + ("ready to assemble" if not bad else ", ".join(bad)))
    return 0


def mark_sent(slug) -> int:
    rows = TR.read_rows()
    row = next((r for r in rows if r["slug"] == slug), None)
    if not row:
        sys.exit(f"{slug} is not in applications.csv — assemble it first")
    if row.get("sent_date"):
        sys.exit(f"{slug} was already marked sent on {row['sent_date']}")
    row["sent_date"] = date.today().isoformat()
    row["status"] = "sent"
    TR.write_rows(rows)
    log(f"{slug} marked sent {row['sent_date']} — the response clock starts now.")
    log(f"  no reply is not a rejection for {TR.RESPONSE_WINDOW_DAYS} days; track.py holds it "
        f"as censored until then")
    log("  python track.py --open   to see what needs chasing")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--sent", metavar="SLUG")
    args = ap.parse_args()
    if args.sent:
        return mark_sent(args.sent)
    if args.list or not args.slug:
        return queue()
    return assemble(args.slug)


if __name__ == "__main__":
    sys.exit(main())
