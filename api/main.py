"""factbank-api: the deterministic half of the job engine.

n8n orchestrates; this service does the work that must be reproducible (discovery,
scoring, tailoring, letter gates, rendering) and, from step 6, serves the review app.

    GET  /health      no auth; liveness for Docker
    GET  /heartbeat   the silent-failure checks (api/heartbeat.py); the desktop helper polls it
    GET  /whoami      token check
    POST /discover    Stage 1: fetch, filter, dedupe, insert new jobs (state 'new')
    POST /score       Stage 2b: BM25 score everything waiting for Gate 1 ('new' -> 'scored')
    POST /draft       Stages 3+4: CV + letter draft for pursued jobs ('pursued' -> 'ready_for_review')
    GET  /pdf/pending · POST /pdf/{id}/done        the Windows notifier prints PDFs with Edge
    GET  /reminders/due · POST /reminders/shown    the Windows notifier announces follow-ups
    POST /report/snapshot                          weekly report snapshot (n8n), if one is due
    GET  /report/pending · POST /report/notified   the Windows notifier announces it
    GET  /validate    fact-bank integrity (validate.py)
    POST /digests     n8n records the result of a pipeline run (ok or failed)
    GET  /digests/latest · GET /digests/pending · POST /digests/notified
    GET  /            the review app (static page; talks to /ui/api/*)
    GET  /digest      the latest digest as a plain page (no JavaScript needed)
    /ui/api/*         the review app's JSON endpoints (inbox, decisions, undo, summary)

THE REVIEW APP HAS NO LOGIN, ON PURPOSE (step 6). Two threats were weighed:
- Another program on this PC: it can read .env and the token anyway, so a login would
  add friction without adding protection.
- A web page open in your browser trying to reach localhost: that is the real one, and
  it is blocked without a login. Every /, /digest and /ui request must carry a localhost
  Host header (defeats DNS rebinding), and every /ui write must come from this app's own
  Origin AND carry the X-Job-Engine header, which a foreign page cannot add without a
  CORS grant this server never gives.
The bearer-token API above (used by n8n) is unchanged.

Security, carried over from bridge.py:
- The container port is published on 127.0.0.1 only (docker-compose.yml).
- Every endpoint except /health requires `Authorization: Bearer $API_TOKEN`.
- No endpoint accepts a command string. Inputs are typed, bounded fields; source ids are
  checked against sources.yaml before anything runs.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.request
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

FACTBANK = Path(os.environ.get("FACTBANK_DIR", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(FACTBANK))      # the V1 stage modules live at the repo root

import applications as apps           # noqa: E402
import digests                        # noqa: E402
import heartbeat                      # noqa: E402
import inbox                          # noqa: E402
import report                         # noqa: E402
import review                         # noqa: E402
from discovery import run_discovery    # noqa: E402
from drafting import run_drafting      # noqa: E402
from migrate import migrate            # noqa: E402
from scoring import run_scoring        # noqa: E402

DATABASE_URL = os.environ["DATABASE_URL"]
API_TOKEN = os.environ["API_TOKEN"]

BANK_FILES = ["profile.yaml", "entities.yaml", "facts.yaml", "vocab.yaml",
              "render_config.yaml", "sources.yaml", "answers.yaml"]

# One discovery or scoring run at a time: two overlapping runs would race on dedupe.
_work_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app):
    migrate(DATABASE_URL)       # schema is always current after `docker compose up`
    yield


app = FastAPI(title="factbank-api", version="0.2.0", lifespan=lifespan)


def require_token(authorization: str = Header(default="")) -> None:
    """Bearer-token check for every non-health endpoint."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, API_TOKEN):
        raise HTTPException(status_code=401, detail="missing or bad token")


def exclusive(fn, *args):
    if not _work_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another discover/score run is in progress")
    try:
        return fn(*args)
    finally:
        _work_lock.release()


@app.get("/health")
def health() -> dict:
    """Liveness for Docker and the n8n heartbeat. No secrets, no personal data."""
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            conn.execute("select 1")
        db = "ok"
    except Exception as e:  # report, don't crash: health must always answer
        db = f"error: {type(e).__name__}"
    missing = [f for f in BANK_FILES if not (FACTBANK / f).exists()]
    status = "ok" if db == "ok" and not missing else "degraded"
    return {"status": status, "db": db, "fact_bank_missing": missing}


@app.get("/whoami", dependencies=[Depends(require_token)])
def whoami() -> dict:
    """Authenticated no-op, so n8n can verify its token."""
    return {"ok": True, "service": "factbank-api", "version": app.version}


class DiscoverIn(BaseModel):
    limit: int = Field(60, ge=1, le=200, description="max new jobs kept this run")
    sources: list[str] | None = Field(None, max_length=100,
                                      description="only these source ids (default: all enabled)")


@app.post("/discover", dependencies=[Depends(require_token)])
def discover(body: DiscoverIn | None = None) -> dict:
    """Stage 1. Slow (every source is fetched; ~1-2 min). Give the caller a long timeout."""
    body = body or DiscoverIn()
    if body.sources and not all(re.fullmatch(r"[a-z0-9._-]{1,80}", s) for s in body.sources):
        raise HTTPException(status_code=400, detail="bad source id")
    try:
        return exclusive(run_discovery, DATABASE_URL, FACTBANK, body.limit, body.sources)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class ScoreIn(BaseModel):
    top: int = Field(10, ge=1, le=100, description="how many inbox jobs to return")


@app.post("/score", dependencies=[Depends(require_token)])
def score(body: ScoreIn | None = None) -> dict:
    """Stage 2b over the whole corpus; stores scores for jobs waiting at Gate 1."""
    return exclusive(run_scoring, DATABASE_URL, FACTBANK, (body or ScoreIn()).top)


class DraftIn(BaseModel):
    max_jobs: int = Field(10, ge=1, le=50, description="jobs drafted per call")


_draft_lock = threading.Lock()


@app.post("/draft", dependencies=[Depends(require_token)])
def draft(body: DraftIn | None = None) -> dict:
    """Stages 3+4 for up to max_jobs pursued jobs. ~2-5 s per job."""
    if not _draft_lock.acquire(blocking=False):
        # Not an error: the run in progress claims jobs one at a time until none is left,
        # so it will pick up whatever this call was asked to do.
        return {"busy": True, "drafted": [], "failed": [], "remaining": None, "given_up": None}
    try:
        return run_drafting(DATABASE_URL, FACTBANK, (body or DraftIn()).max_jobs)
    finally:
        _draft_lock.release()


@app.get("/validate", dependencies=[Depends(require_token)])
def validate() -> dict:
    """Run validate.py (fixed argv) and return its errors and warnings as lists.

    A subprocess rather than an import: validate.py collects findings in module-level
    lists, which would accumulate across calls in a long-running server.
    """
    p = subprocess.run([sys.executable, "validate.py"], cwd=FACTBANK, capture_output=True,
                       text=True, timeout=120, encoding="utf-8", errors="replace")
    lines = p.stdout.splitlines()
    return {
        "ok": p.returncode == 0,
        "exit_code": p.returncode,
        "errors": [ln.strip()[2:] for ln in lines if ln.startswith("  x ")],
        "warnings": [ln.strip()[2:] for ln in lines if ln.startswith("  ! ")],
        "summary": next((ln for ln in reversed(lines) if ln.strip()), ""),
    }


# --------------------------------------------------------------------------- digests

class TopJob(BaseModel):
    id: int | None = None
    slug: str | None = Field(None, max_length=200)
    title: str | None = Field(None, max_length=500)
    company: str | None = Field(None, max_length=300)
    url: str | None = Field(None, max_length=2000)
    relative: int | None = None
    archetype: str | None = Field(None, max_length=100)


class DigestIn(BaseModel):
    status: Literal["ok", "failed"]
    trigger: str | None = Field(None, max_length=40)
    new_count: int = Field(0, ge=0)
    inbox_size: int | None = Field(None, ge=0)
    fetched: int | None = Field(None, ge=0)
    sources_run: int | None = Field(None, ge=0)
    sources_failed: list[str] = Field(default_factory=list, max_length=200)
    top: list[TopJob] = Field(default_factory=list, max_length=50)
    discover_run_id: int | None = None
    score_run_id: int | None = None
    workflow: str | None = Field(None, max_length=300)
    failed_node: str | None = Field(None, max_length=300)
    error: str | None = Field(None, max_length=5000)
    execution_url: str | None = Field(None, max_length=2000)
    source_execution: str | None = Field(None, max_length=100,
                                         description="idempotency key: the n8n execution reported")


@app.post("/digests", dependencies=[Depends(require_token)])
def post_digest(body: DigestIn) -> dict:
    """Returns only {id, status, duplicate} -- deliberately NOT the stored row.

    n8n treats any output item with a top-level `error` field as a failed item and retries
    the node. Echoing a failed digest (which has `error: "..."`) made every alert retry
    three times, 5 s apart, although each POST had already succeeded.
    """
    row = digests.record(DATABASE_URL, body.model_dump())
    return {"id": row["id"], "status": row["status"], "duplicate": bool(row.get("duplicate"))}


@app.get("/digests/latest", dependencies=[Depends(require_token)])
def get_latest() -> dict:
    return {"digest": digests.latest(DATABASE_URL)}


@app.get("/digests/pending", dependencies=[Depends(require_token)])
def get_pending() -> dict:
    return {"digests": digests.pending(DATABASE_URL)}


class NotifiedIn(BaseModel):
    up_to_id: int = Field(..., ge=1)


@app.post("/digests/notified", dependencies=[Depends(require_token)])
def post_notified(body: NotifiedIn) -> dict:
    return {"marked": digests.mark_notified(DATABASE_URL, body.up_to_id)}


# --------------------------------------------------------------------------- review app

STATIC = Path(__file__).resolve().parent / "static"
APP_PORT = os.environ.get("APP_PORT", "8000")
ALLOWED_HOSTS = {f"localhost:{APP_PORT}", f"127.0.0.1:{APP_PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
# Exact paths and "/"-terminated prefixes only. A bare startswith("/digest") also matched
# the bearer API's /digests, and refused every digest n8n tried to record (step 6 bug).
UI_EXACT = {"/", "/review", "/applications", "/report", "/digest"}
UI_PREFIXES = ("/ui/", "/static/")


def is_ui_path(path: str) -> bool:
    return path in UI_EXACT or path.startswith(UI_PREFIXES)


@app.middleware("http")
async def browser_guard(request: Request, call_next):
    """Localhost-only Host for the app; same-origin + custom header for its writes."""
    path = request.url.path
    if is_ui_path(path):
        if request.headers.get("host", "") not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "app is served on localhost only"}, status_code=421)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if (request.headers.get("origin") not in ALLOWED_ORIGINS
                    or request.headers.get("x-job-engine") != "1"):
                return JSONResponse({"detail": "cross-origin write refused"}, status_code=403)
    response = await call_next(request)
    if is_ui_path(path):
        # setdefault: a route may set its own (the CV preview needs inline styles + framing)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"))
    return response


@app.get("/", include_in_schema=False)
def home():
    """The review app. The desktop notification opens this."""
    return FileResponse(STATIC / "app.html", headers={"Cache-Control": "no-store"})


@app.get("/static/{name}", include_in_schema=False)
def static(name: str):
    if name not in {"app.js", "app.css", "review.js", "applications.js", "report.js"}:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})


@app.get("/digest", response_class=HTMLResponse)
def digest_page() -> str:
    """The latest digest as a plain page, no JavaScript."""
    return digests.page(digests.latest(DATABASE_URL))


@app.get("/ui/api/summary")
def ui_summary() -> dict:
    return {"digest": digests.latest(DATABASE_URL), **inbox.counts(DATABASE_URL),
            "heartbeat": heartbeat.check(DATABASE_URL, FACTBANK)}


@app.get("/heartbeat", dependencies=[Depends(require_token)])
def get_heartbeat() -> dict:
    return heartbeat.check(DATABASE_URL, FACTBANK)


@app.get("/ui/api/inbox")
def ui_inbox(source: str | None = None, archetype: str | None = None, q: str | None = None,
             limit: int = 200) -> dict:
    if q is not None and len(q) > 200:
        raise HTTPException(status_code=400, detail="search too long")
    return inbox.list_inbox(DATABASE_URL, source, archetype, q or None, max(1, min(limit, 500)))


@app.get("/ui/api/jobs/{job_id}")
def ui_job(job_id: int) -> dict:
    job = inbox.job_detail(DATABASE_URL, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return job


class DecisionIn(BaseModel):
    job_ids: list[int] = Field(..., min_length=1, max_length=500)
    verdict: Literal["pursue", "skip"]


N8N_WEBHOOK_BASE = os.environ.get("N8N_WEBHOOK_BASE", "http://n8n:5678/webhook")


def _ping_drafting() -> None:
    """Tell n8n there is drafting to do. Fire-and-forget: if n8n is down or slow, the
    drafting workflow's own schedule picks the job up later, so nothing is lost."""
    def go():
        try:
            req = urllib.request.Request(f"{N8N_WEBHOOK_BASE}/job-engine/draft", data=b"{}",
                                         method="POST", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as e:  # noqa: BLE001 -- logged, never raised into the UI
            print(f"drafting ping failed (schedule will catch up): {type(e).__name__}: {e}")
    threading.Thread(target=go, daemon=True).start()


@app.post("/ui/api/decisions")
def ui_decide(body: DecisionIn) -> dict:
    res = inbox.decide(DATABASE_URL, body.job_ids, body.verdict)
    if body.verdict == "pursue" and res["decided"]:
        _ping_drafting()
    return res


class UndoIn(BaseModel):
    decision_ids: list[int] = Field(..., min_length=1, max_length=500)


@app.post("/ui/api/decisions/undo")
def ui_undo(body: UndoIn) -> dict:
    return inbox.undo(DATABASE_URL, body.decision_ids)



# --------------------------------------------------------------------------- review (Gates 2+3)

@app.get("/review", include_in_schema=False)
def review_page():
    return FileResponse(STATIC / "review.html", headers={"Cache-Control": "no-store"})


def _review_call(fn, *args):
    try:
        return fn(*args)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="no such job") from e
    except review.Conflict as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except review.Refused as e:
        return JSONResponse({"detail": str(e), "checks": e.checks}, status_code=400)


@app.get("/ui/api/review")
def ui_review_list() -> dict:
    return {"jobs": review.list_review(DATABASE_URL, FACTBANK)}


@app.get("/ui/api/review/{job_id}")
def ui_review_load(job_id: int):
    return _review_call(review.load, DATABASE_URL, FACTBANK, job_id)


class LetterIn(BaseModel):
    text: str = Field(..., max_length=60_000)
    base_hash: str = Field(..., pattern=r"^[0-9a-f]{16}$")


class CheckIn(BaseModel):
    text: str = Field(..., max_length=60_000)


class ApproveIn(LetterIn):
    cv_read: bool = False


class VariantIn(BaseModel):
    variant: str = Field(..., pattern=r"^[a-z0-9-]{1,20}$")


def _slug_of(job_id: int) -> str:
    with psycopg.connect(DATABASE_URL) as conn:
        r = conn.execute("select slug from jobs where id=%s", (job_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such job")
    return r[0]


@app.post("/ui/api/review/{job_id}/check")
def ui_review_check(job_id: int, body: CheckIn):
    return review.check(FACTBANK, _slug_of(job_id), body.text)


@app.post("/ui/api/review/{job_id}/letter")
def ui_review_save(job_id: int, body: LetterIn):
    return _review_call(review.save, DATABASE_URL, FACTBANK, job_id, body.text, body.base_hash)


@app.post("/ui/api/review/{job_id}/approve")
def ui_review_approve(job_id: int, body: ApproveIn):
    res = _review_call(review.approve, DATABASE_URL, FACTBANK, job_id, body.text,
                       body.base_hash, body.cv_read)
    if isinstance(res, dict):
        # Stage 5 follows approval directly. A packaging failure does not undo the
        # approval: the job stays 'approved' and the Applications screen offers a retry.
        try:
            res["package"] = apps.package(DATABASE_URL, FACTBANK, job_id)
        except apps.Refused as e:
            res["package_error"] = str(e)
    return res


@app.post("/ui/api/review/{job_id}/reopen")
def ui_review_reopen(job_id: int):
    return _review_call(review.reopen, DATABASE_URL, FACTBANK, job_id)


@app.post("/ui/api/review/{job_id}/drop")
def ui_review_drop(job_id: int):
    return _review_call(review.drop, DATABASE_URL, job_id)


@app.post("/ui/api/review/{job_id}/retry")
def ui_review_retry(job_id: int):
    res = _review_call(review.retry, DATABASE_URL, job_id)
    if isinstance(res, dict):
        _ping_drafting()
    return res


@app.post("/ui/api/review/{job_id}/cv")
def ui_review_cv(job_id: int, body: VariantIn):
    return _review_call(review.rebuild_cv, DATABASE_URL, FACTBANK, job_id, body.variant)


@app.get("/ui/files/cv/{job_id}", include_in_schema=False)
def ui_cv_file(job_id: int):
    """The tailored CV, for the preview frame. Only a path the database recorded, inside out/.
    V1's CV is self-contained HTML with inline styles: no scripts allowed, framable by the app only."""
    p = review.cv_html_path(DATABASE_URL, FACTBANK, job_id)
    if p is None:
        raise HTTPException(status_code=404, detail="no CV for this job")
    return FileResponse(p, media_type="text/html", headers={
        "Cache-Control": "no-store",
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                                   "font-src data:; frame-ancestors 'self'; base-uri 'none'",
    })



# --------------------------------------------------------------------------- applications (Stage 5, Gate 4)

def _apps_call(fn, *args):
    try:
        return fn(*args)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="no such job") from e
    except apps.Refused as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/applications", include_in_schema=False)
def applications_page():
    return FileResponse(STATIC / "applications.html", headers={"Cache-Control": "no-store"})


@app.get("/ui/api/applications")
def ui_apps_list() -> dict:
    return apps.list_applications(DATABASE_URL, FACTBANK)


@app.get("/ui/api/applications/{job_id}/checklist")
def ui_apps_checklist(job_id: int) -> dict:
    return {"text": apps.checklist(FACTBANK, _slug_of(job_id))}


@app.post("/ui/api/applications/{job_id}/package")
def ui_apps_package(job_id: int):
    return _apps_call(apps.package, DATABASE_URL, FACTBANK, job_id)


class SentIn(BaseModel):
    sent_date: date | None = None


@app.post("/ui/api/applications/{job_id}/sent")
def ui_apps_sent(job_id: int, body: SentIn | None = None):
    return _apps_call(apps.mark_sent, DATABASE_URL, job_id, (body or SentIn()).sent_date)


@app.post("/ui/api/applications/{job_id}/unsend")
def ui_apps_unsend(job_id: int):
    return _apps_call(apps.unsend, DATABASE_URL, job_id)


class OutcomeIn(BaseModel):
    outcome: Literal["replied", "interview", "offer", "rejected", "closed", "withdrawn"]
    outcome_date: date | None = None
    notes: str | None = Field(None, max_length=2000)


@app.post("/ui/api/applications/{job_id}/outcome")
def ui_apps_outcome(job_id: int, body: OutcomeIn):
    return _apps_call(apps.record_outcome, DATABASE_URL, job_id, body.outcome, body.outcome_date, body.notes)


class FollowUpIn(BaseModel):
    action: Literal["done", "snooze"]


@app.post("/ui/api/follow-ups/{follow_up_id}")
def ui_follow_up(follow_up_id: int, body: FollowUpIn):
    return _apps_call(apps.close_follow_up, DATABASE_URL, follow_up_id, body.action)


@app.get("/ui/files/package/{job_id}/{name}", include_in_schema=False)
def ui_package_file(job_id: int, name: str):
    """A file from this job's application folder, by exact name (html/pdf/md/ics)."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name):
        raise HTTPException(status_code=400, detail="bad file name")
    try:
        p = apps.file_path(DATABASE_URL, FACTBANK, job_id, name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="no such job") from e
    if p is None:
        raise HTTPException(status_code=404, detail="no such file")
    media = {".html": "text/html", ".pdf": "application/pdf", ".md": "text/plain; charset=utf-8",
             ".ics": "text/calendar"}[p.suffix]
    headers = {"Cache-Control": "no-store",
               "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                                          "font-src data:; frame-ancestors 'self'; base-uri 'none'",
               "X-Frame-Options": "SAMEORIGIN"}
    if p.suffix == ".ics":
        headers["Content-Disposition"] = f'attachment; filename="{p.name}"'
    return FileResponse(p, media_type=media, headers=headers)


# host-side helpers (bearer token): PDFs and follow-up announcements

@app.get("/pdf/pending", dependencies=[Depends(require_token)])
def pdf_pending() -> dict:
    return {"jobs": apps.pdf_pending(DATABASE_URL)}


class PdfDoneIn(BaseModel):
    ok: bool
    error: str | None = Field(None, max_length=500)


@app.post("/pdf/{pdf_id}/done", dependencies=[Depends(require_token)])
def pdf_done(pdf_id: int, body: PdfDoneIn) -> dict:
    return apps.pdf_done(DATABASE_URL, pdf_id, body.ok, body.error)


@app.get("/reminders/due", dependencies=[Depends(require_token)])
def reminders_due() -> dict:
    return {"reminders": apps.reminders_due(DATABASE_URL)}


class ShownIn(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=200)


@app.post("/reminders/shown", dependencies=[Depends(require_token)])
def reminders_shown(body: ShownIn) -> dict:
    return {"marked": apps.reminders_shown(DATABASE_URL, body.ids)}



# --------------------------------------------------------------------------- report (Stage 6)

@app.get("/report", include_in_schema=False)
def report_page():
    return FileResponse(STATIC / "report.html", headers={"Cache-Control": "no-store"})


@app.get("/ui/api/report")
def ui_report() -> dict:
    return report.compute(DATABASE_URL)


@app.post("/report/snapshot", dependencies=[Depends(require_token)])
def report_snapshot() -> dict:
    return report.snapshot_if_due(DATABASE_URL)


@app.get("/report/pending", dependencies=[Depends(require_token)])
def report_pending() -> dict:
    return {"reports": report.pending(DATABASE_URL)}


@app.post("/report/notified", dependencies=[Depends(require_token)])
def report_notified(body: ShownIn) -> dict:
    return {"marked": report.mark_notified(DATABASE_URL, body.ids)}
