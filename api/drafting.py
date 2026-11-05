"""Stages 3 + 4 as a service: for each pursued job, tailor the CV and build the letter draft.

    pursued -> drafting -> ready_for_review        (or back to pursued, with the error)

The work itself is V1's, unchanged: tailor.py and letter.py run as subprocesses with fixed
argv lists (they print, write files, and keep module-level state, so a subprocess per job
is the clean boundary). The rules come from tailor.run_batch:

- The CV variant comes from the job's score: the archetype when the label is confident,
  `span` when two profiles were nearly tied (tailor.variant_for).
- A letter draft whose opening you have written is NEVER touched. A draft whose opening is
  still the TODO block is rebuilt when the CV is rebuilt (the old one is moved to
  letters/.superseded/, not deleted), because it argues from facts that may no longer be
  on the page.

Nothing here writes prose. The opening stays a TODO block, and the letter's checks fail
until you write it (Gate 3, step 8).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import letter as L
import render as R
import tailor as T

MAX_ATTEMPTS = 3
STUCK_MINUTES = 15
CV_FATAL = {"traceability", "confirmed_only", "deny_list", "numeric_integrity"}


def _run(root: Path, args: list[str]) -> None:
    r = subprocess.run([sys.executable, *args], cwd=root, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(f"{args[0]} failed: {tail[-1][:300] if tail else f'exit {r.returncode}'}")


def _rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root)).replace("\\", "/")


def _next_version(conn, job_id: int, kind: str) -> int:
    return conn.execute("select coalesce(max(version), 0) + 1 as v from documents "
                        "where job_id=%s and kind=%s", (job_id, kind)).fetchone()["v"]


def draft_one(root: Path, slug: str, score: dict, variant: str | None = None) -> dict:
    """Build CV + letter draft for one job. Returns what was produced; raises on failure.
    `variant` overrides the score-based choice (the review app's variant switch)."""
    job_path = root / "jobs" / f"{slug}.yaml"
    if not job_path.exists():
        raise RuntimeError(f"no job file jobs/{slug}.yaml")
    job = yaml.safe_load(job_path.read_text(encoding="utf-8")) or {}
    variant = variant or T.variant_for(slug, {slug: score or {}})

    _run(root, ["tailor.py", f"jobs/{slug}.yaml", "--variant", variant])
    cv_dir = T.dest_for(job)
    T.write_stamp(cv_dir, slug, variant)
    cv_checks = T._load_json(cv_dir / "checks.json", [])
    for c in cv_checks:
        c["fatal"] = c.get("check") in CV_FATAL

    draft = root / "letters" / f"{slug}.md"
    letter_note = "built"
    if draft.exists():
        if T.opening_written(draft):
            letter_note = "kept: you had written the opening (re-check its proof points)"
        else:
            T.supersede(draft)
            letter_note = "rebuilt from the new CV"
    if not draft.exists():
        _run(root, ["letter.py", f"jobs/{slug}.yaml"])

    letter_checks = L.run_checks(slug, draft.read_text(encoding="utf-8"), T.load_job(job_path),
                                 R.load_bank())
    return {
        "variant": variant,
        "cv": {"path": _rel(root, cv_dir / "cv.md"), "render_path": _rel(root, cv_dir / "cv.html"),
               "checks": cv_checks,
               "status": "passed" if all(c["pass"] for c in cv_checks if c["fatal"]) else "failed"},
        "letter": {"path": _rel(root, draft), "checks": letter_checks, "note": letter_note,
                   "status": "passed" if all(c["pass"] for c in letter_checks if c.get("fatal", True))
                   else "draft"},
        "uncovered": next((c["detail"] for c in cv_checks if c["check"] == "keyword_coverage"), None),
    }


def run_drafting(dsn: str, root: Path, max_jobs: int) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        run_id = conn.execute("insert into runs (workflow) values ('api:draft') returning id"
                              ).fetchone()["id"]
        # A crash mid-draft leaves a job in 'drafting'; hand it back after a while.
        conn.execute("update jobs set state='pursued', state_changed_at=now() where state='drafting' "
                     "and state_changed_at < now() - make_interval(mins => %s)", (STUCK_MINUTES,))
        conn.commit()
        # Claim ONE job at a time, until none is left or max_jobs is reached. Claiming a
        # whole batch up front would leave a job pursued during this run waiting for the
        # next scheduled run: its webhook ping arrives while this run is busy.
        done, failed = [], []
        tried: list[int] = [0]      # one attempt per job per run; retries come from later runs
        while len(done) + len(failed) < max_jobs:
            job = conn.execute(
                """update jobs set state='drafting', state_changed_at=now(), updated_at=now(),
                       draft_attempts = draft_attempts + 1
                   where id = (select id from jobs where state='pursued' and draft_attempts < %s
                               and id <> all(%s)
                               order by state_changed_at limit 1 for update skip locked)
                   returning id, slug""", (MAX_ATTEMPTS, tried)).fetchone()
            conn.commit()
            if job is None:
                break
            tried.append(job["id"])
            score = conn.execute(
                "select per_archetype, archetype, archetype_confident, archetype_label, margin, "
                "relative from scores where job_id=%s order by scored_at desc, id desc limit 1",
                (job["id"],)).fetchone() or {}
            try:
                out = draft_one(root, job["slug"], score)
            except Exception as e:  # one bad posting must not stop the batch
                msg = f"{type(e).__name__}: {e}"[:1000]
                with conn.transaction():
                    conn.execute("update jobs set state='pursued', state_changed_at=now(), "
                                 "updated_at=now(), draft_error=%s where id=%s", (msg, job["id"]))
                    conn.execute("insert into events (job_id, kind, actor, data) values "
                                 "(%s, 'draft_failed', 'system', %s)",
                                 (job["id"], Jsonb({"error": msg, "run_id": run_id})))
                failed.append({"id": job["id"], "slug": job["slug"], "error": msg})
                continue
            with conn.transaction():
                for kind in ("cv", "letter"):
                    d = out[kind]
                    conn.execute(
                        "insert into documents (job_id, kind, version, variant, path, render_path, "
                        "checks, status) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (job["id"], kind, _next_version(conn, job["id"], kind),
                         out["variant"] if kind == "cv" else None, d["path"],
                         d.get("render_path"), Jsonb(d["checks"]), d["status"]))
                conn.execute("update jobs set state='ready_for_review', state_changed_at=now(), "
                             "updated_at=now(), draft_error=null where id=%s", (job["id"],))
                conn.execute("insert into events (job_id, kind, actor, data) values "
                             "(%s, 'drafted', 'system', %s)",
                             (job["id"], Jsonb({"variant": out["variant"], "cv": out["cv"]["status"],
                                                "letter": out["letter"]["note"], "run_id": run_id})))
            done.append({"id": job["id"], "slug": job["slug"], "variant": out["variant"],
                         "cv": out["cv"]["status"], "letter": out["letter"]["note"],
                         "coverage": out["uncovered"]})

        remaining = conn.execute("select count(*) as n from jobs where state='pursued' "
                                 "and draft_attempts < %s", (MAX_ATTEMPTS,)).fetchone()["n"]
        given_up = conn.execute("select count(*) as n from jobs where state='pursued' "
                                "and draft_attempts >= %s", (MAX_ATTEMPTS,)).fetchone()["n"]
        result = {"run_id": run_id, "drafted": done, "failed": failed,
                  "remaining": remaining, "given_up": given_up}
        conn.execute("update runs set finished_at=clock_timestamp(), status=%s, stats=%s where id=%s",
                     ("failed" if failed and not done else "ok",
                      Jsonb({k: v for k, v in result.items() if k != "run_id"}), run_id))
        conn.commit()
        return result
