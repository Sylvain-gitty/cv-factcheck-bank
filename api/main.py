"""factbank-api: the deterministic half of the job engine.

n8n orchestrates; this service does the work that must be reproducible (discovery,
scoring, tailoring, letter gates, rendering) and, from step 6, serves the review app.

    GET  /health      no auth; liveness for Docker and the n8n heartbeat
    GET  /whoami      token check
    POST /discover    Stage 1: fetch, filter, dedupe, insert new jobs (state 'new')
    POST /score       Stage 2b: BM25 score everything waiting for Gate 1 ('new' -> 'scored')
    GET  /validate    fact-bank integrity (validate.py)

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

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

FACTBANK = Path(os.environ.get("FACTBANK_DIR", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(FACTBANK))      # the V1 stage modules live at the repo root

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
