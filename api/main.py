"""factbank-api: the deterministic half of the job engine.

n8n orchestrates; this service does the work that must be reproducible (discovery,
scoring, tailoring, letter gates, rendering) and, from step 6, serves the review app.

Step 2 ships only the skeleton: /health, and the token check every later endpoint uses.
Endpoints are added in step 4 (see docs/ARCHITECTURE-V2.md).

Security, carried over from bridge.py:
- The container port is published on 127.0.0.1 only (docker-compose.yml).
- Every endpoint except /health requires `Authorization: Bearer $API_TOKEN`.
- No endpoint will ever accept a command string; actions are fixed functions.
"""
from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException

from migrate import migrate

FACTBANK = Path(os.environ.get("FACTBANK_DIR", Path(__file__).resolve().parent.parent))
DATABASE_URL = os.environ["DATABASE_URL"]
API_TOKEN = os.environ["API_TOKEN"]

BANK_FILES = ["profile.yaml", "entities.yaml", "facts.yaml", "vocab.yaml",
              "render_config.yaml", "sources.yaml", "answers.yaml"]

@asynccontextmanager
async def lifespan(_app):
    migrate(DATABASE_URL)       # schema is always current after `docker compose up`
    yield


app = FastAPI(title="factbank-api", version="0.1.0", lifespan=lifespan)


def require_token(authorization: str = Header(default="")) -> None:
    """Bearer-token check for every non-health endpoint."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, API_TOKEN):
        raise HTTPException(status_code=401, detail="missing or bad token")


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
    """Authenticated no-op, so n8n can verify its token before real endpoints exist."""
    return {"ok": True, "service": "factbank-api", "version": app.version}
