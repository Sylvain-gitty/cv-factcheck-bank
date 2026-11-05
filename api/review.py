"""Gates 2 + 3 for the review app: read the CV, write the opening, approve.

    ready_for_review --(approve)--> approved --(reopen)--> ready_for_review
    ready_for_review --(drop)--> skipped
    pursued (drafting gave up) --(retry)--> pursued, attempts reset

The letter FILE (letters/<slug>.md) stays the source of truth, exactly as in V1, so the
CLI tools and the app can never disagree. The app reads and writes that file:
- every save keeps the previous version in letters/.history/<slug>/ (nothing you wrote can
  be lost to a bad save);
- a save carries the hash of the text it was based on, and is refused if the file changed
  on disk since (e.g. you edited it in another editor);
- checks are V1's letter.run_checks, unchanged, run on the text as it is right now.

Approve requires: every fatal check passing (with APPROVED set to yes), and your explicit
"I read the CV" (Gate 2 made structural; it was the one V1 gate nothing enforced). It then
renders the letter with V1's `letter.py --render`, which refuses on its own if a fatal
check fails, so the app cannot approve something the CLI would not.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import drafting
import letter as L
import render as R
import tailor as T

REVIEW_STATES = ("pursued", "drafting", "ready_for_review", "approved")
OPENING_RE = re.compile(r"<!--\s*OPENING: WRITE THIS YOURSELF.*?-->", re.S)
APPROVED_LINE_RE = re.compile(L.APPROVAL_RE)


class Conflict(Exception):
    """The letter changed on disk since the client loaded it."""


class Refused(Exception):
    """The action is not allowed in the job's current state, or a gate failed."""
    def __init__(self, msg: str, checks: list | None = None):
        super().__init__(msg)
        self.checks = checks


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _job(conn, job_id: int) -> dict:
    j = conn.execute("select id, slug, title, company, location, url, source, state, "
                     "draft_error, draft_attempts from jobs where id=%s", (job_id,)).fetchone()
    if j is None:
        raise KeyError(job_id)
    return j


def _latest_doc(conn, job_id: int, kind: str) -> dict | None:
    return conn.execute("select id, version, variant, path, render_path, checks, status, created_at "
                        "from documents where job_id=%s and kind=%s order by version desc limit 1",
                        (job_id, kind)).fetchone()


def _letter_path(root: Path, slug: str) -> Path:
    return root / "letters" / f"{slug}.md"


def _comment_list(text: str, header: str) -> list[str]:
    """Lines of an annotation block the drafter appends, e.g. HOOKS or EVIDENCE."""
    m = re.search(rf"<!--\s*{header}[^\n]*-->\s*\n((?:<!--.*?-->\s*\n?)+)", text)
    if not m:
        return []
    return [re.sub(r"^<!--\s*|\s*-->$", "", ln).strip()
            for ln in m.group(1).splitlines() if ln.strip()]


def _checks(root: Path, slug: str, text: str) -> list[dict]:
    job = T.load_job(root / "jobs" / f"{slug}.yaml")
    return L.run_checks(slug, text, job, R.load_bank())


def cv_ok(cv: dict | None) -> bool:
    """A CV is approvable when every fatal check in its own check file passes. Judged from
    the checks, not the status label: CVs imported from V1 are labelled 'rendered'."""
    checks = (cv or {}).get("checks") or []
    fatal = [c for c in checks if c.get("check") in drafting.CV_FATAL]
    return bool(fatal) and all(c.get("pass") for c in fatal)


def _fatal_fails(checks: list[dict], ignore=()) -> list[dict]:
    return [c for c in checks if c.get("fatal", True) and not c["pass"] and c["check"] not in ignore]


def variants(root: Path) -> list[dict]:
    cfg = yaml.safe_load((root / "render_config.yaml").read_text(encoding="utf-8"))
    return [{"id": v["id"], "label": v.get("label", v["id"])}
            for v in cfg.get("variants", []) if v["id"] != "master"]


# --------------------------------------------------------------------------- reads

def list_review(dsn: str, root: Path) -> list[dict]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute(
            f"""select j.id, j.slug, j.title, j.company, j.state, j.state_changed_at,
                       j.draft_error, j.draft_attempts,
                       s.relative, s.archetype_label,
                       cv.variant as cv_variant, cv.checks as cv_checks
                from jobs j
                left join lateral (select relative, archetype_label from scores where job_id=j.id
                                   order by scored_at desc, id desc limit 1) s on true
                left join lateral (select variant, checks from documents where job_id=j.id
                                   and kind='cv' order by version desc limit 1) cv on true
                where j.state = any(%s)
                order by case j.state when 'ready_for_review' then 0 when 'pursued' then 1
                                      when 'drafting' then 2 else 3 end,
                         s.relative desc nulls last, j.state_changed_at""",
            (list(REVIEW_STATES),)).fetchall()
    for r in rows:
        r["cv_ok"] = cv_ok({"checks": r.pop("cv_checks")})
        p = _letter_path(root, r["slug"])
        r["has_letter"] = p.exists()
        r["opening_written"] = p.exists() and T.opening_written(p)
    return rows


def load(dsn: str, root: Path, job_id: int) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        j = _job(conn, job_id)
        cv = _latest_doc(conn, job_id, "cv")
    p = _letter_path(root, j["slug"])
    text = p.read_text(encoding="utf-8") if p.exists() else None
    if cv:
        cv["ok"] = cv_ok(cv)
    out = {"job": j, "cv": cv, "variants": variants(root), "letter": None}
    if text is not None:
        checks = _checks(root, j["slug"], text)
        out["letter"] = {
            "text": text, "hash": digest(text), "checks": checks,
            "prose": L.prose_of(text), "opening_pending": bool(OPENING_RE.search(text)),
            "hooks": _comment_list(text, "HOOKS"),
            "evidence": _comment_list(text, "EVIDENCE AVAILABLE"),
        }
    return out


def check(root: Path, slug: str, text: str) -> dict:
    """Run the gates on unsaved text (live feedback while typing)."""
    return {"checks": _checks(root, slug, text), "prose": L.prose_of(text),
            "opening_pending": bool(OPENING_RE.search(text))}


# --------------------------------------------------------------------------- writes

def _save(root: Path, slug: str, text: str, base_hash: str) -> str:
    p = _letter_path(root, slug)
    current = p.read_text(encoding="utf-8") if p.exists() else ""
    if digest(current) != base_hash:
        raise Conflict("the letter changed on disk since you opened it -- reload to see it")
    if current == text:
        return digest(text)
    hist = root / "letters" / ".history" / slug
    hist.mkdir(parents=True, exist_ok=True)
    if current:
        (hist / f"{datetime.now():%Y%m%d-%H%M%S-%f}.md").write_text(current, encoding="utf-8")
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(p)                       # atomic: a crash never leaves half a letter
    return digest(text)


def save(dsn: str, root: Path, job_id: int, text: str, base_hash: str) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        j = _job(conn, job_id)
        if j["state"] != "ready_for_review":
            raise Refused(f"the letter can only be edited while the job is ready for review "
                          f"(it is '{j['state']}'); reopen it first")
        new_hash = _save(root, j["slug"], text, base_hash)
        conn.execute("insert into events (job_id, kind, actor, data) values (%s,'letter_saved','user',%s)",
                     (job_id, Jsonb({"hash": new_hash})))
    return {"hash": new_hash, **check(root, j["slug"], text)}


def _set_approved(text: str, yes: bool) -> str:
    line = f"<!-- APPROVED: {'yes' if yes else 'no'} -->"
    if APPROVED_LINE_RE.search(text):
        return APPROVED_LINE_RE.sub(line, text, count=1)
    # Older V1 drafts have no APPROVED line: put it under the generated/job comments.
    m = re.search(r"(<!--\s*generated:[^\n]*-->\n)", text) or re.search(r"(^#[^\n]*\n)", text, re.M)
    if m:
        return text[:m.end()] + line + "\n" + text[m.end():]
    return line + "\n" + text


def approve(dsn: str, root: Path, job_id: int, text: str, base_hash: str, cv_read: bool) -> dict:
    if not cv_read:
        raise Refused("tick 'I read the CV' first: the checks cannot tell whether it leads "
                      "with the right thing for this job")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        j = _job(conn, job_id)
        if j["state"] != "ready_for_review":
            raise Refused(f"only a job that is ready for review can be approved (it is '{j['state']}')")
        cv = _latest_doc(conn, job_id, "cv")
        if not cv_ok(cv):
            raise Refused("the CV has a failing fatal check; rebuild it before approving")
        approved_text = _set_approved(text, True)
        checks = _checks(root, j["slug"], approved_text)
        fails = _fatal_fails(checks)
        if fails:
            raise Refused("not approved: " + "; ".join(f"{c['check']}: {c['detail']}" for c in fails),
                          checks)
        new_hash = _save(root, j["slug"], approved_text, base_hash)
        r = subprocess.run([sys.executable, "letter.py", "--render", j["slug"]], cwd=root,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=180)
        html = root / "out" / "letters" / f"{j['slug']}.html"
        if r.returncode != 0 or not html.exists():
            # roll the approval back in the file so file and state agree
            _save(root, j["slug"], _set_approved(approved_text, False), new_hash)
            tail = (r.stdout + r.stderr).strip().splitlines()
            raise Refused(f"render failed: {tail[-1] if tail else r.returncode}", checks)
        with conn.transaction():
            v = conn.execute("select coalesce(max(version),0)+1 as v from documents "
                             "where job_id=%s and kind='letter'", (job_id,)).fetchone()["v"]
            conn.execute("insert into documents (job_id, kind, version, path, render_path, checks, status) "
                         "values (%s,'letter',%s,%s,%s,%s,'rendered')",
                         (job_id, v, f"letters/{j['slug']}.md", f"out/letters/{j['slug']}.html",
                          Jsonb(checks)))
            conn.execute("update jobs set state='approved', state_changed_at=now(), updated_at=now() "
                         "where id=%s", (job_id,))
            conn.execute("insert into events (job_id, kind, actor, data) values (%s,'approved','user',%s)",
                         (job_id, Jsonb({"cv_read": True, "cv_variant": cv["variant"],
                                         "letter_version": v})))
    return {"state": "approved", "hash": new_hash, "checks": checks}


def reopen(dsn: str, root: Path, job_id: int) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        j = _job(conn, job_id)
        if j["state"] != "approved":
            raise Refused(f"only an approved job can be reopened (it is '{j['state']}')")
        p = _letter_path(root, j["slug"])
        text = p.read_text(encoding="utf-8")
        _save(root, j["slug"], _set_approved(text, False), digest(text))
        with conn.transaction():
            conn.execute("update jobs set state='ready_for_review', state_changed_at=now(), "
                         "updated_at=now() where id=%s", (job_id,))
            conn.execute("insert into events (job_id, kind, actor) values (%s,'reopened','user')",
                         (job_id,))
    return {"state": "ready_for_review"}


def drop(dsn: str, job_id: int) -> dict:
    """Decide against a job after pursuing it. Files stay where they are."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        j = _job(conn, job_id)
        if j["state"] not in ("ready_for_review", "pursued"):
            raise Refused(f"cannot drop a job that is '{j['state']}'")
        d = conn.execute("insert into decisions (job_id, verdict, origin, features) values "
                         "(%s,'skip','app',%s) returning id",
                         (job_id, Jsonb({"dropped_from": j["state"]}))).fetchone()["id"]
        conn.execute("update jobs set state='skipped', state_changed_at=now(), updated_at=now() "
                     "where id=%s", (job_id,))
        conn.execute("insert into events (job_id, kind, actor, data) values (%s,'dropped','user',%s)",
                     (job_id, Jsonb({"from": j["state"], "decision_id": d})))
    return {"state": "skipped"}


def retry(dsn: str, job_id: int) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        j = _job(conn, job_id)
        if j["state"] != "pursued":
            raise Refused("only a job waiting for drafting can be retried")
        conn.execute("update jobs set draft_attempts=0, draft_error=null where id=%s", (job_id,))
    return {"state": "pursued"}


def rebuild_cv(dsn: str, root: Path, job_id: int, variant: str) -> dict:
    """Re-tailor with another variant. Same rules as drafting: an unwritten letter draft is
    rebuilt with it; one whose opening you wrote is kept (re-check its proof points)."""
    if variant not in {v["id"] for v in variants(root)}:
        raise Refused(f"unknown variant '{variant}'")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        j = _job(conn, job_id)
        if j["state"] != "ready_for_review":
            raise Refused(f"the CV can only be rebuilt while the job is ready for review")
        out = drafting.draft_one(root, j["slug"], {}, variant=variant)
        with conn.transaction():
            for kind in ("cv", "letter"):
                d = out[kind]
                v = conn.execute("select coalesce(max(version),0)+1 as v from documents "
                                 "where job_id=%s and kind=%s", (job_id, kind)).fetchone()["v"]
                conn.execute("insert into documents (job_id, kind, version, variant, path, render_path, "
                             "checks, status) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                             (job_id, kind, v, variant if kind == "cv" else None, d["path"],
                              d.get("render_path"), Jsonb(d["checks"]), d["status"]))
            conn.execute("insert into events (job_id, kind, actor, data) values (%s,'cv_rebuilt','user',%s)",
                         (job_id, Jsonb({"variant": variant, "letter": out["letter"]["note"]})))
    return {"variant": variant, "letter_note": out["letter"]["note"], "cv_status": out["cv"]["status"]}


def cv_html_path(dsn: str, root: Path, job_id: int) -> Path | None:
    """The rendered CV for a job, only if it is a path the database recorded, inside out/."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        cv = _latest_doc(conn, job_id, "cv")
    if not cv or not cv["render_path"]:
        return None
    p = (root / cv["render_path"]).resolve()
    out_dir = (root / "out").resolve()
    if out_dir not in p.parents or p.suffix != ".html" or not p.exists():
        return None
    return p
