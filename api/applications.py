"""Stage 5 + Gate 4 + the start of Stage 6: package, you send, follow up, record the outcome.

    approved --(package, automatic)--> packaged --(you: "I sent it")--> sent
    sent --(outcome)--> replied | interview | offer | rejected | closed

Packaging reuses V1's package.assemble (CV, letter, CHECKLIST.md with your screening
answers, follow-up.ics) with record=False: applications live in Postgres now. PDFs are
queued for the Windows notifier to print with Edge (see 006_applications.sql for why).

THERE IS STILL NO SUBMIT. "I sent it" records something you did on the employer's site.
"""
from __future__ import annotations

import contextlib
import io
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import package as P
import render as R
import tailor as T

FOLLOW_UP_DAYS = P.FOLLOW_UP_DAYS            # (7, 14), V1's
OUTCOMES = {"replied": "replied", "interview": "interview", "offer": "offer",
            "rejected": "rejected", "closed": "closed", "withdrawn": "closed"}
LIST_STATES = ("approved", "packaged", "sent", "replied", "interview", "offer", "rejected", "closed")
PACKAGE_FILES = {".html", ".pdf", ".md", ".ics"}


class Refused(Exception):
    pass


def _job(conn, job_id: int) -> dict:
    j = conn.execute("select id, slug, title, company, url, source, state from jobs where id=%s",
                     (job_id,)).fetchone()
    if j is None:
        raise KeyError(job_id)
    return j


def _event(conn, job_id, kind, data=None, actor="user"):
    conn.execute("insert into events (job_id, kind, actor, data) values (%s,%s,%s,%s)",
                 (job_id, kind, actor, Jsonb(data) if data is not None else None))


def _set_state(conn, job_id, state):
    conn.execute("update jobs set state=%s, state_changed_at=now(), updated_at=now() where id=%s",
                 (state, job_id))


# --------------------------------------------------------------------------- package

def package(dsn: str, root: Path, job_id: int) -> dict:
    """Assemble the application folder for an approved job and queue its PDFs."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        j = _job(conn, job_id)
        if j["state"] not in ("approved", "packaged"):
            raise Refused(f"only an approved job can be packaged (it is '{j['state']}')")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = P.assemble(j["slug"], record=False)
        if rc != 0:
            msg = " ".join(ln.strip() for ln in buf.getvalue().splitlines() if "FAIL" in ln)[:900]
            conn.execute("update applications set package_error=%s, updated_at=now() where job_id=%s",
                         (msg or "package.py refused", job_id))
            _event(conn, job_id, "package_failed", {"detail": msg}, actor="system")
            conn.commit()
            raise Refused(f"not packaged: {msg or 'package.py refused'}")

        dest = root / "out" / "applications" / j["slug"]
        job_yaml = T.load_job(root / "jobs" / f"{j['slug']}.yaml")
        bank = R.load_bank()
        name = (bank["profile"].get("owner", {}).get("name") or "cv").replace(" ", "_")
        rel = lambda p: str(p.relative_to(root)).replace("\\", "/")   # noqa: E731
        score = conn.execute("select archetype, relative from scores where job_id=%s "
                             "order by scored_at desc, id desc limit 1", (job_id,)).fetchone() or {}
        with conn.transaction():
            conn.execute(
                """insert into applications (job_id, archetype, batch_score, cv_variant, has_letter,
                       status, package_path, package_error)
                   values (%s,%s,%s,%s,true,'ready',%s,null)
                   on conflict (job_id) do update set package_path=excluded.package_path,
                       package_error=null, cv_variant=excluded.cv_variant, updated_at=now()""",
                (job_id, score.get("archetype"), score.get("relative"),
                 T.built_variant(job_yaml), rel(dest)))
            for kind in ("CV", "Letter"):
                html, pdf = dest / f"{name}_{kind}.html", dest / f"{name}_{kind}.pdf"
                if html.exists() and not pdf.exists():
                    conn.execute("insert into pdf_jobs (job_id, html_path, pdf_path) values (%s,%s,%s)",
                                 (job_id, rel(html), rel(pdf)))
            v = conn.execute("select coalesce(max(version),0)+1 as v from documents "
                             "where job_id=%s and kind='package'", (job_id,)).fetchone()["v"]
            conn.execute("insert into documents (job_id, kind, version, path, status) "
                         "values (%s,'package',%s,%s,'passed')", (job_id, v, rel(dest)))
            _set_state(conn, job_id, "packaged")
            _event(conn, job_id, "packaged", {"path": rel(dest)}, actor="system")
    return {"state": "packaged", "path": rel(dest)}


def files(root: Path, slug: str) -> list[dict]:
    d = root / "out" / "applications" / slug
    if not d.is_dir():
        return []
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(d.iterdir())
            if p.is_file() and p.suffix in PACKAGE_FILES]


def file_path(dsn: str, root: Path, job_id: int, name: str) -> Path | None:
    """A file inside this job's package folder, by exact name. Nothing else."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        j = _job(conn, job_id)
    d = (root / "out" / "applications" / j["slug"]).resolve()
    p = (d / name).resolve()
    if p.parent != d or p.suffix not in PACKAGE_FILES or not p.is_file():
        return None
    return p


# --------------------------------------------------------------------------- send + outcome

def mark_sent(dsn: str, job_id: int, sent: date | None) -> dict:
    sent = sent or date.today()
    if sent > date.today():
        raise Refused("the sent date cannot be in the future")
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        j = _job(conn, job_id)
        if j["state"] != "packaged":
            raise Refused(f"only a packaged application can be marked sent (it is '{j['state']}')")
        a = conn.execute("update applications set status='sent', sent_date=%s, updated_at=now() "
                         "where job_id=%s returning id", (sent, job_id)).fetchone()
        for n in FOLLOW_UP_DAYS:
            conn.execute("insert into follow_ups (application_id, kind, due_date) values (%s,%s,%s) "
                         "on conflict (application_id, kind) do update set due_date=excluded.due_date, "
                         "shown_at=null, done_at=null, closed_reason=null",
                         (a["id"], f"day-{n}", sent + timedelta(days=n)))
        _set_state(conn, job_id, "sent")
        _event(conn, job_id, "sent", {"sent_date": sent.isoformat()})
    return {"state": "sent", "sent_date": sent.isoformat(),
            "follow_ups": [(sent + timedelta(days=n)).isoformat() for n in FOLLOW_UP_DAYS]}


def unsend(dsn: str, job_id: int) -> dict:
    """Undo a mistaken "I sent it", before any outcome was recorded."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        j = _job(conn, job_id)
        if j["state"] != "sent":
            raise Refused("only an application marked sent, with no outcome yet, can be un-sent")
        a = conn.execute("update applications set status='ready', sent_date=null, updated_at=now() "
                         "where job_id=%s returning id", (job_id,)).fetchone()
        conn.execute("delete from follow_ups where application_id=%s", (a["id"],))
        _set_state(conn, job_id, "packaged")
        _event(conn, job_id, "unsent")
    return {"state": "packaged"}


def record_outcome(dsn: str, job_id: int, outcome: str, when: date | None, notes: str | None) -> dict:
    if outcome not in OUTCOMES:
        raise Refused(f"unknown outcome '{outcome}'")
    when = when or date.today()
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        j = _job(conn, job_id)
        if j["state"] not in ("sent", "replied", "interview", "offer", "rejected", "closed"):
            raise Refused("record an outcome once the application is sent")
        a = conn.execute("select id, sent_date, first_reply_date from applications where job_id=%s",
                         (job_id,)).fetchone()
        if a["sent_date"] and when < a["sent_date"]:
            raise Refused("the outcome date is before the sent date")
        # A reply of any kind sets first_reply_date once. "closed" (no reply, given up)
        # and "withdrawn" are not replies: track.py must keep them apart.
        is_reply = outcome in ("replied", "interview", "offer", "rejected")
        conn.execute(
            """update applications set status=%s, updated_at=now(),
                   first_reply_date = case when %s and first_reply_date is null then %s
                                           else first_reply_date end,
                   notes = case when %s::text is null then notes
                                else concat_ws(E'\n', notes, %s::text) end
               where id=%s""",
            (outcome, is_reply, when, notes, f"{when.isoformat()} {outcome}: {notes}" if notes else None,
             a["id"]))
        conn.execute("update follow_ups set done_at=now(), closed_reason=%s "
                     "where application_id=%s and done_at is null", (outcome, a["id"]))
        _set_state(conn, job_id, OUTCOMES[outcome])
        _event(conn, job_id, "outcome", {"outcome": outcome, "date": when.isoformat(), "notes": notes})
    return {"state": OUTCOMES[outcome], "outcome": outcome}


def close_follow_up(dsn: str, follow_up_id: int, action: str) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        f = conn.execute("select id, due_date from follow_ups where id=%s and done_at is null",
                         (follow_up_id,)).fetchone()
        if not f:
            raise Refused("no open follow-up with that id")
        if action == "done":
            conn.execute("update follow_ups set done_at=now(), closed_reason='done' where id=%s",
                         (follow_up_id,))
        elif action == "snooze":
            conn.execute("update follow_ups set due_date=greatest(due_date, current_date) + 3, "
                         "shown_at=null where id=%s", (follow_up_id,))
        else:
            raise Refused("action must be done or snooze")
    return {"ok": True}


# --------------------------------------------------------------------------- reads

def list_applications(dsn: str, root: Path) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute(
            """select j.id, j.slug, j.title, j.company, j.url, j.source, j.state,
                      j.state_changed_at, a.status, a.sent_date, a.first_reply_date, a.cv_variant,
                      a.notes, a.package_error, a.package_path,
                      (current_date - a.sent_date) as days_since_sent,
                      (select count(*) from pdf_jobs p where p.job_id=j.id and p.status='pending') as pdf_pending,
                      (select string_agg(p.error, '; ') from pdf_jobs p where p.job_id=j.id and p.status='failed') as pdf_error
               from jobs j left join applications a on a.job_id=j.id
               where j.state = any(%s)
               order by case j.state when 'approved' then 0 when 'packaged' then 1 when 'sent' then 2
                                     else 3 end, j.state_changed_at desc""",
            (list(LIST_STATES),)).fetchall()
        due = conn.execute(
            """select f.id, f.kind, f.due_date, j.id as job_id, j.company, j.title
               from follow_ups f join applications a on a.id=f.application_id join jobs j on j.id=a.job_id
               where f.done_at is null and f.due_date <= current_date order by f.due_date""").fetchall()
        upcoming = {r["job_id"]: r for r in conn.execute(
            """select distinct on (a.job_id) a.job_id, f.id, f.kind, f.due_date
               from follow_ups f join applications a on a.id=f.application_id
               where f.done_at is null order by a.job_id, f.due_date""").fetchall()}
    for r in rows:
        r["files"] = files(root, r["slug"])
        r["next_follow_up"] = upcoming.get(r["id"])
    return {"applications": rows, "due": due}


def checklist(root: Path, slug: str) -> str | None:
    p = root / "out" / "applications" / slug / "CHECKLIST.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


# --------------------------------------------------------------------------- host helpers

def pdf_pending(dsn: str) -> list[dict]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return conn.execute("select id, html_path, pdf_path from pdf_jobs where status='pending' "
                            "order by id limit 20").fetchall()


def pdf_done(dsn: str, pdf_id: int, ok: bool, error: str | None) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        r = conn.execute("update pdf_jobs set status=%s, error=%s, done_at=now() "
                         "where id=%s and status='pending' returning job_id",
                         ("done" if ok else "failed", None if ok else (error or "failed")[:500], pdf_id)
                         ).fetchone()
        if r:
            _event(conn, r["job_id"], "pdf_" + ("done" if ok else "failed"),
                   {"pdf_job": pdf_id, "error": error}, actor="system")
    return {"ok": bool(r)}


def reminders_due(dsn: str) -> list[dict]:
    """Follow-ups due today or earlier that the notifier has not announced yet."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return conn.execute(
            """select f.id, f.kind, f.due_date, j.company, j.title, a.sent_date
               from follow_ups f join applications a on a.id=f.application_id join jobs j on j.id=a.job_id
               where f.done_at is null and f.shown_at is null and f.due_date <= current_date
               order by f.due_date""").fetchall()


def reminders_shown(dsn: str, ids: list[int]) -> int:
    with psycopg.connect(dsn) as conn:
        return conn.execute("update follow_ups set shown_at=now() where id = any(%s) and shown_at is null",
                            (ids,)).rowcount
