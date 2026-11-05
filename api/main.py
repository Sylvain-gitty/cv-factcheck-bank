"""factbank-api: the deterministic half of the job engine.

n8n orchestrates; this service does the work that must be reproducible (discovery,
scoring, tailoring, letter gates, rendering) and, from step 6, serves the review app.

    GET  /health      no auth; liveness for Docker and the n8n heartbeat
    GET  /whoami      token check
    POST /discover    Stage 1: fetch, filter, dedupe, insert new jobs (state 'new')
    POST /score       Stage 2b: BM25 score everything waiting for Gate 1 ('new' -> 'scored')
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
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

FACTBANK = Path(os.environ.get("FACTBANK_DIR", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(FACTBANK))      # the V1 stage modules live at the repo root

import digests                        # noqa: E402
import inbox                          # noqa: E402
from discovery import run_discovery    # noqa: E402
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
UI_PREFIXES = ("/ui", "/digest", "/static")


@app.middleware("http")
async def browser_guard(request: Request, call_next):
    """Localhost-only Host for the app; same-origin + custom header for its writes."""
    path = request.url.path
    if path == "/" or path.startswith(UI_PREFIXES):
        if request.headers.get("host", "") not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "app is served on localhost only"}, status_code=421)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if (request.headers.get("origin") not in ALLOWED_ORIGINS
                    or request.headers.get("x-job-engine") != "1"):
                return JSONResponse({"detail": "cross-origin write refused"}, status_code=403)
    response = await call_next(request)
    if path == "/" or path.startswith(UI_PREFIXES):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    return response


@app.get("/", include_in_schema=False)
def home():
    """The review app. The desktop notification opens this."""
    return FileResponse(STATIC / "app.html", headers={"Cache-Control": "no-store"})


@app.get("/static/{name}", include_in_schema=False)
def static(name: str):
    if name not in {"app.js", "app.css"}:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})


@app.get("/digest", response_class=HTMLResponse)
def digest_page() -> str:
    """The latest digest as a plain page, no JavaScript."""
    return digests.page(digests.latest(DATABASE_URL))


@app.get("/ui/api/summary")
def ui_summary() -> dict:
    return {"digest": digests.latest(DATABASE_URL), **inbox.counts(DATABASE_URL)}


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


@app.post("/ui/api/decisions")
def ui_decide(body: DecisionIn) -> dict:
    return inbox.decide(DATABASE_URL, body.job_ids, body.verdict)


class UndoIn(BaseModel):
    decision_ids: list[int] = Field(..., min_length=1, max_length=500)


@app.post("/ui/api/decisions/undo")
def ui_undo(body: UndoIn) -> dict:
    return inbox.undo(DATABASE_URL, body.decision_ids)
