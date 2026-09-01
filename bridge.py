#!/usr/bin/env python3
"""The bridge — a tiny local HTTP API over the pipeline stages, for n8n to drive.

    python bridge.py                 # start on 127.0.0.1:899
    python bridge.py --port 9000
    python bridge.py --print-token   # show the token n8n needs

------------------------------------------------------------------------------
WHY THIS EXISTS

n8n runs in Docker. The pipeline is Python on the Windows host. A container cannot execute
a program on its host, and the usual workarounds are worse than this: installing Python
into the n8n image breaks on every image update, and mounting the host filesystem into a
Node container to shell out is fragile and hard to reason about.

So the tools stay where they are and expose a narrow local API. n8n drives them with plain
HTTP Request nodes. Nothing about the workflow changes if you later move n8n to another
machine, or drop n8n entirely and call these endpoints from cron.

------------------------------------------------------------------------------
SECURITY — READ THIS, IT IS A SERVER THAT RUNS PROGRAMS

Three constraints, and none of them is optional:

1. BOUND TO 127.0.0.1. Not 0.0.0.0. It is not reachable from your network, let alone the
   internet. If you change this, you are publishing a remote code execution endpoint.
2. A FIXED ACTION ALLOWLIST. There is no endpoint that takes a command string. Each route
   maps to a hard-coded argv list; the only caller-supplied value is a slug, and that is
   validated against [a-z0-9-]{1,80} before it goes anywhere near a subprocess.
3. BEARER TOKEN. Generated on first run into .state/bridge-token, which is gitignored.
   Any other local process would otherwise be able to drive your job applications.

If n8n runs in Docker on the same machine, it reaches the host at
`http://host.docker.internal:899`. That is still a loopback path on the host side.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / ".state"
TOKEN_FILE = STATE / "bridge-token"
PY = sys.executable
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")

# The complete set of things this server can run. A route either appears here or does not
# exist; there is deliberately no way to pass an arbitrary command.
ACTIONS = {
    "discover": lambda b: [PY, "discover.py", "--limit", str(int(b.get("limit", 60)))],
    "rank": lambda b: [PY, "rank.py", "--top", str(int(b.get("top", 10)))]
                      + (["--llm"] if b.get("llm") else []),
    "decide": lambda b: [PY, "rank.py", "--decide"],
    "tailor": lambda b: [PY, "tailor.py", f"jobs/{slug(b)}.yaml",
                         "--variant", variant(b)],
    "letter": lambda b: [PY, "letter.py", f"jobs/{slug(b)}.yaml"]
                        + (["--llm"] if b.get("llm") else []),
    "letter_check": lambda b: [PY, "letter.py", "--check", slug(b)],
    "package": lambda b: [PY, "package.py", slug(b)],
    "queue": lambda b: [PY, "package.py", "--list"],
    "sent": lambda b: [PY, "package.py", "--sent", slug(b)],
    "report": lambda b: [PY, "track.py"],
    "open": lambda b: [PY, "track.py", "--open"],
    "validate": lambda b: [PY, "validate.py", "--quiet"],
}


def slug(body) -> str:
    s = str(body.get("slug", "")).strip()
    if not SLUG_RE.match(s):
        raise ValueError(f"bad slug: {s!r}")
    return s


def variant(body) -> str:
    v = str(body.get("variant", "ds")).strip()
    if not re.match(r"^[a-z0-9-]{1,20}$", v):
        raise ValueError(f"bad variant: {v!r}")
    return v


def token() -> str:
    STATE.mkdir(exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def run(argv, timeout=900) -> dict:
    started = datetime.now(timezone.utc)
    p = subprocess.run(argv, cwd=HERE, capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    return {
        "ok": p.returncode == 0,
        "exit_code": p.returncode,
        "stdout": p.stdout or "",
        "stderr": (p.stderr or "")[-4000:],
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
    }


def read_digest() -> dict:
    """The Gate 1 payload: the digest, plus the ranked jobs as structured data."""
    md = HERE / "out" / "digest.md"
    scores = HERE / ".state" / "scores.json"
    jobs = []
    if scores.exists():
        sc = json.loads(scores.read_text(encoding="utf-8"))
        import yaml
        for s in sorted(sc, key=lambda x: -sc[x]["relative"])[:15]:
            jp = HERE / "jobs" / f"{s}.yaml"
            if not jp.exists():
                continue
            j = yaml.safe_load(jp.read_text(encoding="utf-8")) or {}
            jobs.append({
                "slug": s, "title": j.get("title"), "company": j.get("company"),
                "location": j.get("location"), "url": j.get("url"),
                "source": j.get("source"), "score": sc[s]["relative"],
                "archetype": sc[s].get("archetype_label"),
                "archetype_confident": sc[s].get("archetype_confident"),
            })
    return {"markdown": md.read_text(encoding="utf-8") if md.exists() else "",
            "jobs": jobs, "count": len(jobs)}


class Handler(BaseHTTPRequestHandler):
    server_version = "cv-fact-bank-bridge"

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return secrets.compare_digest(got, self.token)

    def do_GET(self):
        route = self.path.split("?")[0].strip("/")
        if route == "health":
            return self._send(200, {"ok": True, "service": "cv-fact-bank-bridge",
                                    "actions": sorted(ACTIONS)})
        if not self._authed():
            return self._send(401, {"ok": False, "error": "bad or missing bearer token"})
        if route == "digest":
            return self._send(200, {"ok": True, **read_digest()})
        if route in ACTIONS:
            return self._send(200, run(ACTIONS[route]({})))
        self._send(404, {"ok": False, "error": f"no route {route!r}",
                         "actions": sorted(ACTIONS)})

    def do_POST(self):
        route = self.path.split("?")[0].strip("/")
        if not self._authed():
            return self._send(401, {"ok": False, "error": "bad or missing bearer token"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"ok": False, "error": "body is not JSON"})
        if not isinstance(body, dict):
            return self._send(400, {"ok": False, "error": "body must be an object"})
        if route not in ACTIONS:
            return self._send(404, {"ok": False, "error": f"no action {route!r}",
                                    "actions": sorted(ACTIONS)})
        try:
            argv = ACTIONS[route](body)
        except ValueError as e:
            return self._send(400, {"ok": False, "error": str(e)})
        except Exception as e:                                   # noqa: BLE001
            return self._send(400, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        try:
            self._send(200, run(argv))
        except subprocess.TimeoutExpired:
            self._send(504, {"ok": False, "error": "action timed out"})

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=899)
    ap.add_argument("--print-token", action="store_true")
    args = ap.parse_args()

    tok = token()
    if args.print_token:
        print(tok)
        return 0

    Handler.token = tok
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"bridge on http://127.0.0.1:{args.port}   (loopback only)")
    print(f"  from n8n in Docker:  http://host.docker.internal:{args.port}")
    print(f"  token:               {tok}")
    print(f"  actions:             {', '.join(sorted(ACTIONS))}")
    print("\nCtrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
