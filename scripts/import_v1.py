"""One-off import of the V1 file-based state into Postgres.

    docker compose exec factbank-api python scripts/import_v1.py --dry-run
    docker compose exec factbank-api python scripts/import_v1.py
    docker compose exec factbank-api python scripts/import_v1.py --replace   # wipe + redo

Reads, never writes, the V1 files:
    jobs/*.yaml              -> jobs
    .state/seen.json         -> job_keys (dedupe history)
    .state/scores.json       -> scores   (the last V1 batch)
    .state/decisions.json    -> decisions (with the feature snapshot taken at decision time)
    applications.csv         -> applications
    out/jobs/, letters/, out/letters/, out/applications/  -> documents (paths only)

Each job's state is derived with status.py's own rule (stage_of), so the database agrees
with the V1 board. Everything runs in one transaction: it imports all or nothing, and the
script ends by checking that the row counts match the source files.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import psycopg
import yaml
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import status as v1_status  # noqa: E402  (V1 modules live at the repo root)
import tailor as v1_tailor  # noqa: E402

FIXTURES = {"example-berlin-ds"}   # decisions on the old job.example.yaml fixture
ENGINE_TABLES = ["events", "applications", "documents", "decisions", "scores",
                 "job_keys", "jobs", "runs"]
STAGE_TO_STATE = {"pursued": "pursued", "drafted": "ready_for_review", "applied": "sent"}


def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def parse_posted(v) -> datetime | None:
    s = str(v or "").strip()
    if not s or s == "None":
        return None
    try:
        if re.fullmatch(r"\d{9,13}", s):
            n = int(s)
            return datetime.fromtimestamp(n / 1000 if n > 10**11 else n, tz=timezone.utc)
        if re.match(r"\d{4}-\d\d-\d\d", s):
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return parsedate_to_datetime(s)
    except (ValueError, TypeError, OverflowError):
        return None


def nz(v):
    """'None', '' and None all mean missing."""
    return None if v is None or str(v).strip() in ("", "None") else str(v)


def as_date(s) -> date | None:
    s = nz(s)
    return date.fromisoformat(s) if s else None


def derive_state(slug: str, job: dict, verdict: str | None, sent: dict) -> str:
    if verdict is None:
        return "scored"
    if verdict == "skip":
        return "skipped"
    stage, _next = v1_status.stage_of(slug, job, sent)
    if stage == "tailored":   # V1 lumps rendered and packaged together
        return "packaged" if (ROOT / "out" / "applications" / slug).exists() else "approved"
    return STAGE_TO_STATE[stage]


def run(conn, dry: bool) -> dict:
    jobs_dir = ROOT / "jobs"
    seen = load_json(ROOT / ".state" / "seen.json", {})
    scores = load_json(ROOT / ".state" / "scores.json", {})
    decisions = load_json(ROOT / ".state" / "decisions.json", {})
    apps = list(csv.DictReader((ROOT / "applications.csv").open(encoding="utf-8")))
    sent = {r["slug"]: r["sent_date"] for r in apps if nz(r.get("sent_date"))}
    key_of = {v["slug"]: k for k, v in seen.items()}
    files = {f.stem: f for f in sorted(jobs_dir.glob("*.yaml"))}

    skipped = {"decisions_without_job": sorted(set(decisions) - set(files))}
    unexpected = set(skipped["decisions_without_job"]) - FIXTURES
    if unexpected:
        raise SystemExit(f"decisions for unknown jobs (not fixtures): {sorted(unexpected)}")

    # The V1 scores came from one batch: record it as a run so scores keep their context.
    v1_run = conn.execute(
        "insert into runs (workflow, started_at, finished_at, status, stats) "
        "values ('v1-import', now(), now(), 'ok', %s) returning id",
        (Jsonb({"note": "scores and decisions from the V1 file-based pipeline"}),),
    ).fetchone()[0]

    ids: dict[str, int] = {}
    for slug, f in files.items():
        job = yaml.safe_load(f.read_text(encoding="utf-8"))
        verdict = (decisions.get(slug) or {}).get("verdict")
        state = derive_state(slug, job, verdict, sent)
        seen_rec = seen.get(key_of.get(slug), {})
        first_seen = seen_rec.get("first_seen") or datetime.now(timezone.utc).isoformat()
        reqs = job.get("requirements")
        jid = conn.execute(
            """insert into jobs (slug, job_key, title, company, location, url, source,
                   language, posted_at, posted_raw, salary_raw, tags, description,
                   requirements, state, first_seen, raw)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
            (slug, key_of.get(slug), job["title"], nz(job.get("company")),
             nz(job.get("location")), job.get("url"), job["source"], job.get("language"),
             parse_posted(job.get("posted")), nz(job.get("posted")),
             nz(job.get("salary_raw")), nz(job.get("tags")), job.get("description"),
             Jsonb(reqs) if reqs else None, state, first_seen,
             Jsonb(json.loads(json.dumps(job, default=str)))),
        ).fetchone()[0]
        ids[slug] = jid
        conn.execute("insert into events (job_id, kind, actor, data) values (%s,'imported','import',%s)",
                     (jid, Jsonb({"state": state, "file": f"jobs/{f.name}"})))

        # documents: CV (dir named after the posting), letter draft, rendered letter, package
        cv_dir = v1_tailor.dest_for(job)
        if (cv_dir / "cv.html").exists():
            checks = load_json(cv_dir / "checks.json", None)
            conn.execute(
                "insert into documents (job_id, kind, variant, path, render_path, checks, status) "
                "values (%s,'cv',%s,%s,%s,%s,'rendered')",
                (jid, v1_tailor.built_variant(job), str((cv_dir / "cv.md").relative_to(ROOT)),
                 str((cv_dir / "cv.html").relative_to(ROOT)), Jsonb(checks) if checks else None))
        draft = ROOT / "letters" / f"{slug}.md"
        if draft.exists():
            html = ROOT / "out" / "letters" / f"{slug}.html"
            fresh = html.exists() and html.stat().st_mtime >= draft.stat().st_mtime
            conn.execute(
                "insert into documents (job_id, kind, path, render_path, status) "
                "values (%s,'letter',%s,%s,%s)",
                (jid, str(draft.relative_to(ROOT)),
                 str(html.relative_to(ROOT)) if fresh else None,
                 "rendered" if fresh else "draft"))
        pkg = ROOT / "out" / "applications" / slug
        if pkg.exists():
            conn.execute("insert into documents (job_id, kind, path, status) "
                         "values (%s,'package',%s,'passed')", (jid, str(pkg.relative_to(ROOT))))

    # dedupe history: every key ever seen, linked to its job where the job file exists
    for key, rec in seen.items():
        conn.execute("insert into job_keys (job_key, slug, source, first_seen, job_id) "
                     "values (%s,%s,%s,%s,%s)",
                     (key, rec.get("slug"), rec.get("source"), rec.get("first_seen"),
                      ids.get(rec.get("slug"))))

    for slug, s in scores.items():
        if slug not in ids:
            continue
        conn.execute(
            """insert into scores (job_id, run_id, method, per_archetype, archetype,
                   archetype_confident, archetype_label, margin, raw, relative)
               values (%s,%s,'bm25',%s,%s,%s,%s,%s,%s,%s)""",
            (ids[slug], v1_run, Jsonb(s.get("per_archetype")), s.get("archetype"),
             s.get("archetype_confident"), s.get("archetype_label"), s.get("margin"),
             s.get("raw"), s.get("relative")))

    for slug, d in decisions.items():
        if slug not in ids:
            continue
        conn.execute(
            "insert into decisions (job_id, verdict, decided_at, features, origin) "
            "values (%s,%s,%s,%s,'v1-import')",
            (ids[slug], d["verdict"], d["decided_at"], Jsonb(d.get("features"))))
        conn.execute("insert into events (job_id, at, kind, actor, data) "
                     "values (%s,%s,'decision','import',%s)",
                     (ids[slug], d["decided_at"], Jsonb({"verdict": d["verdict"]})))

    for r in apps:
        if r["slug"] not in ids:
            raise SystemExit(f"application for unknown job: {r['slug']}")
        bs = nz(r.get("batch_score"))
        conn.execute(
            """insert into applications (job_id, archetype, batch_score, cv_variant, has_letter,
                   status, sent_date, first_reply_date, notes)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ids[r["slug"]], nz(r.get("archetype")), int(float(bs)) if bs else None,
             nz(r.get("cv_variant")), (r.get("letter") or "").lower() == "yes",
             r["status"], as_date(r.get("sent_date")), as_date(r.get("first_reply_date")),
             nz(r.get("notes"))))

    # ---- reconcile: source counts vs. what landed --------------------------------------
    def q(sql):
        return conn.execute(sql).fetchone()[0]

    expect = {
        "jobs": len(files),
        "job_keys": len(seen),
        "scores": sum(1 for s in scores if s in ids),
        "decisions": sum(1 for s in decisions if s in ids),
        "decisions_pursue": sum(1 for s, d in decisions.items() if s in ids and d["verdict"] == "pursue"),
        "applications": len(apps),
        "applications_sent": sum(1 for r in apps if r["status"] == "sent"),
    }
    got = {
        "jobs": q("select count(*) from jobs"),
        "job_keys": q("select count(*) from job_keys"),
        "scores": q("select count(*) from scores"),
        "decisions": q("select count(*) from decisions"),
        "decisions_pursue": q("select count(*) from decisions where verdict='pursue'"),
        "applications": q("select count(*) from applications"),
        "applications_sent": q("select count(*) from applications where status='sent'"),
    }
    states = dict(conn.execute("select state, count(*) from jobs group by 1 order by 2 desc").fetchall())
    docs = dict(conn.execute("select kind || ':' || status, count(*) from documents group by 1 order by 1").fetchall())
    mismatch = {k: (expect[k], got[k]) for k in expect if expect[k] != got[k]}
    return {"expect": expect, "got": got, "mismatch": mismatch, "states": states,
            "documents": docs, "skipped": skipped, "dry_run": dry}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="import, report, then roll back")
    ap.add_argument("--replace", action="store_true", help="wipe engine tables first")
    a = ap.parse_args()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        existing = conn.execute("select count(*) from jobs").fetchone()[0]
        if existing and not a.replace:
            print(f"jobs table already has {existing} rows; use --replace to wipe and re-import.")
            return 1
        try:
            with conn.transaction():
                if a.replace:
                    conn.execute(f"truncate {', '.join(ENGINE_TABLES)} restart identity cascade")
                report = run(conn, a.dry_run)
                if report["mismatch"]:
                    raise RuntimeError(f"count mismatch: {report['mismatch']}")
                if a.dry_run:
                    raise _Rollback(report)
        except _Rollback as rb:
            report = rb.report
    print(json.dumps(report, indent=2, default=str))
    print("\nDRY RUN: rolled back, nothing written." if a.dry_run else "\nImported and committed.")
    return 0


class _Rollback(Exception):
    def __init__(self, report):
        self.report = report


if __name__ == "__main__":
    sys.exit(main())
