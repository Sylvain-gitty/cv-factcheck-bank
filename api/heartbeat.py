"""The heartbeat: catch the failures that produce no error message.

Born from the step-6 bug: every digest write was refused, the error workflow's write was
refused too, and so nothing ever told you. Silence looked exactly like a quiet day. These
checks compare what SHOULD have happened with what DID, from both sides of the boundary
(n8n's own execution log, read-only, and the engine's tables):

  n8n_down          n8n does not answer
  silent_pipeline   the pipeline workflow ran, but no digest was recorded for it
  unrecorded_fail   an n8n execution failed and no failed digest records it
  no_discovery      no successful discovery run for days while the stack was up
  stuck_drafting    a job has sat in 'drafting' (should take seconds)
  stuck_pdfs        PDFs queued for the desktop helper are not being printed
  drafts_given_up   pursued jobs whose drafting failed 3 times (needs you)
  backup_stale      the newest database backup is missing or old

Each issue has a stable code, so the desktop helper announces it once, not every minute.
"""
from __future__ import annotations

import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

PIPELINE_WF = "jeDailyDiscover1"
N8N_HEALTH = os.environ.get("N8N_HEALTH_URL", "http://n8n:5678/healthz")
BACKUP_MAX_AGE_H = 36
NO_DISCOVERY_DAYS = 3


def _n8n_dsn(dsn: str) -> str:
    # Same server and user, n8n's own database. Only ever read.
    return dsn.rsplit("/", 1)[0] + "/n8n"


def check(dsn: str, root: Path) -> dict:
    issues: list[dict] = []

    def add(code, msg, severity="warning"):
        issues.append({"code": code, "severity": severity, "message": msg})

    try:
        urllib.request.urlopen(N8N_HEALTH, timeout=4).close()
        n8n_up = True
    except Exception as e:  # noqa: BLE001
        n8n_up = False
        add("n8n_down", f"n8n is not answering ({type(e).__name__}); nothing will run. "
                        "Check: docker compose ps", "critical")

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        last_digest = conn.execute("select max(created_at) as t from digests").fetchone()["t"]
        recorded = {r["source_execution"] for r in conn.execute(
            "select source_execution from digests where source_execution is not null "
            "and created_at > now() - interval '3 days'").fetchall()}
        q = conn.execute(
            """select
                 (select max(finished_at) from runs where workflow='api:discover' and status='ok') as last_discover,
                 (select count(*) from jobs where state='drafting'
                    and state_changed_at < now() - interval '15 minutes') as stuck_drafting,
                 (select count(*) from pdf_jobs where status='pending'
                    and created_at < now() - interval '10 minutes') as stuck_pdfs,
                 (select count(*) from jobs where state='pursued' and draft_attempts >= 3) as given_up,
                 (select min(started_at) from runs) as first_run,
                 (select value from heartbeat_state where key='watch_since') as watch_since
            """).fetchone()

    if n8n_up:
        try:
            with psycopg.connect(_n8n_dsn(dsn), row_factory=dict_row) as n8n:
                execs = n8n.execute(
                    """select id::text as id, "workflowId" as wf, status, mode, "stoppedAt" as stopped
                       from execution_entity
                       where "startedAt" > greatest(now() - interval '3 days', %s)
                         and "stoppedAt" is not null
                       order by id desc limit 300""", (q["watch_since"],)).fetchall()
        except Exception as e:  # noqa: BLE001
            execs = []
            add("n8n_db", f"could not read n8n's execution log: {type(e).__name__}", "warning")
        now = datetime.now(timezone.utc)
        for ex in execs:
            age_min = (now - ex["stopped"]).total_seconds() / 60
            if age_min < 3:
                continue                       # still being recorded
            if ex["wf"] == PIPELINE_WF and ex["status"] == "success" and f"pipeline:{ex['id']}" not in recorded:
                add("silent_pipeline",
                    f"the pipeline ran (n8n execution {ex['id']}) but no digest was recorded for it: "
                    "the notification step is broken, so you would hear nothing", "critical")
                break
        for ex in execs:
            if ex["status"] in ("error", "crashed") and ex["mode"] != "error" \
                    and (now - ex["stopped"]).total_seconds() > 180 \
                    and f"failed:{ex['id']}" not in recorded:
                add("unrecorded_fail",
                    f"n8n execution {ex['id']} failed and the failure was not recorded either "
                    "(the error workflow could not report it). Open n8n -> Executions.", "critical")
                break

    up_since = q["first_run"]
    if q["last_discover"] is None or \
            (datetime.now(timezone.utc) - q["last_discover"]).days >= NO_DISCOVERY_DAYS:
        if up_since and (datetime.now(timezone.utc) - up_since).days >= NO_DISCOVERY_DAYS:
            add("no_discovery", f"no successful discovery for {NO_DISCOVERY_DAYS}+ days. Restart the "
                                "stack, or check the pipeline workflow in n8n")
    if q["stuck_drafting"]:
        add("stuck_drafting", f"{q['stuck_drafting']} job(s) stuck in drafting for 15+ minutes")
    if q["stuck_pdfs"]:
        add("stuck_pdfs", f"{q['stuck_pdfs']} PDF(s) waiting 10+ minutes: is the desktop helper "
                          "(JobEngineNotifier task) running?")
    if q["given_up"]:
        add("drafts_given_up", f"{q['given_up']} pursued job(s) could not be drafted after 3 tries: "
                               "see Review", "info")

    backups = sorted((root / "backups").glob("*-jobengine.dump"))
    if not backups:
        add("backup_stale", "no database backup found in backups/")
    else:
        age_h = (datetime.now().timestamp() - backups[-1].stat().st_mtime) / 3600
        if age_h > BACKUP_MAX_AGE_H:
            add("backup_stale", f"newest database backup is {age_h:.0f} h old ({backups[-1].name})")

    worst = "critical" if any(i["severity"] == "critical" for i in issues) else \
            "warning" if any(i["severity"] == "warning" for i in issues) else "ok"
    return {"status": worst, "issues": issues,
            "last_digest": last_digest.isoformat() if last_digest else None,
            "last_discover": q["last_discover"].isoformat() if q["last_discover"] else None,
            "newest_backup": backups[-1].name if backups else None}
