"""Stage 6: the report. V1's track.py rules, computed from Postgres.

Kept from V1 because each one stops a specific wrong conclusion:
- Below MIN_N (25) resolved applications no rate is reported, only the interval, for scale.
- No reply inside RESPONSE_WINDOW_DAYS (21) is CENSORED, not a rejection: counting it as one
  biases every rate downwards, worst exactly when you are most active.
- Every proportion carries a Wilson 95% interval, and a breakdown says whether the best and
  worst groups' intervals overlap ("not yet a difference you can act on").
- More than one CV variant across fewer than 25 sent applications gets a warning: nothing
  can be attributed to a variant while it keeps changing.

One change, on purpose: V1 counted a rejection that carried a reply date as "replied", so
its single response rate mixed "they wrote back" with "they want to talk". V2 reports both:
  any reply       = replied | interview | offer | rejected
  interview+      = interview | offer
Withdrawn applications (your choice, not theirs) are left out of every denominator.
"""
from __future__ import annotations

import ast
import re
import statistics
from collections import Counter, defaultdict
from datetime import date

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import track as TR

MIN_N = TR.MIN_N                              # 25
WINDOW = TR.RESPONSE_WINDOW_DAYS              # 21
SNAPSHOT_EVERY_DAYS = 7
REPLY = {"replied", "interview", "offer", "rejected"}
POSITIVE = {"interview", "offer"}


def wilson(k: int, n: int) -> dict:
    p, lo, hi = TR.wilson(k, n)
    return {"k": k, "n": n, "p": round(p, 4), "lo": round(lo, 4), "hi": round(hi, 4)}


def classify(a: dict, today: date) -> str:
    """unsent | withdrawn | positive | reply | no_reply | censored"""
    if not a["sent_date"]:
        return "unsent"
    s = (a["status"] or "").lower()
    if s == "withdrawn":
        return "withdrawn"
    if s in POSITIVE:
        return "positive"
    if s in REPLY or a["first_reply_date"]:
        return "reply"
    if s == "closed":
        return "no_reply"
    return "censored" if (today - a["sent_date"]).days < WINDOW else "no_reply"


def _breakdown(decided: list[dict], key: str) -> dict:
    groups = defaultdict(lambda: [0, 0, 0])          # replies, positive, n
    for a in decided:
        g = str(a.get(key) or "—")
        groups[g][2] += 1
        if a["_c"] in ("reply", "positive"):
            groups[g][0] += 1
        if a["_c"] == "positive":
            groups[g][1] += 1
    rows = [{"group": g, "any_reply": wilson(r, n), "interview": wilson(p, n)}
            for g, (r, p, n) in sorted(groups.items(), key=lambda kv: -kv[1][2])]
    verdict = None
    big = [r for r in rows if r["any_reply"]["n"] >= 5]
    if len(rows) > 1 and all(r["any_reply"]["n"] < 8 for r in rows):
        verdict = "every group has fewer than 8: this split cannot support a comparison yet"
    elif len(big) >= 2:
        best = max(big, key=lambda r: r["any_reply"]["p"])
        worst = min(big, key=lambda r: r["any_reply"]["p"])
        if best is not worst:
            verdict = (f"{best['group']} looks better than {worst['group']}, but the intervals "
                       f"overlap: not yet a difference you can act on"
                       if best["any_reply"]["lo"] <= worst["any_reply"]["hi"]
                       else f"{best['group']} beats {worst['group']} with no interval overlap: "
                            f"the first real signal here")
    return {"rows": rows, "verdict": verdict}


def _missing_skills(conn) -> dict:
    """Skills postings asked for that no confirmed fact evidences, across every job you
    pursued (latest CV per job). The market's curriculum, counted."""
    rows = conn.execute(
        """select distinct on (d.job_id) d.job_id, d.checks from documents d
           where d.kind='cv' order by d.job_id, d.version desc""").fetchall()
    counts, jobs = Counter(), 0
    for r in rows:
        det = next((c.get("detail", "") for c in (r["checks"] or []) if c.get("check") == "keyword_coverage"), "")
        m = re.search(r"missing:\s*(\[.*\])", det or "")
        jobs += 1
        if m:
            try:
                for s in ast.literal_eval(m.group(1)):
                    counts[str(s)] += 1
            except (ValueError, SyntaxError):
                pass
    return {"jobs_with_cv": jobs, "top": [{"skill": s, "jobs": n} for s, n in counts.most_common(15)]}


def compute(dsn: str) -> dict:
    today = date.today()
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        apps = conn.execute(
            """select a.job_id, a.status, a.sent_date, a.first_reply_date, a.cv_variant,
                      j.source, j.company,
                      coalesce(a.archetype, s.archetype) as archetype,
                      coalesce(a.batch_score, s.relative) as batch_score
               from applications a join jobs j on j.id=a.job_id
               left join lateral (select archetype, relative from scores where job_id=j.id
                                  order by scored_at desc, id desc limit 1) s on true""").fetchall()
        f = conn.execute(
            """select
                 (select count(distinct job_id) from decisions where undone_at is null) as surfaced,
                 (select count(distinct job_id) from decisions where undone_at is null and verdict='pursue') as pursued,
                 (select count(distinct job_id) from documents where kind='cv') as drafted,
                 (select count(*) from jobs where state in ('approved','packaged','sent','replied',
                                                           'interview','offer','rejected','closed')) as approved
            """).fetchone()
        gate1 = conn.execute(
            """select coalesce(d.features->>'archetype', '—') as archetype,
                      count(*) filter (where verdict='pursue') as pursue, count(*) as n
               from (select distinct on (job_id) * from decisions where undone_at is null
                     order by job_id, decided_at desc) d
               group by 1 order by 3 desc""").fetchall()
        week = conn.execute(
            """select
                 (select count(*) from decisions where undone_at is null and origin='app'
                    and decided_at > now() - interval '7 days') as decided,
                 (select count(*) from decisions where undone_at is null and origin='app' and verdict='pursue'
                    and decided_at > now() - interval '7 days') as pursued,
                 -- Jobs approved this week that are STILL approved or further along: the events
                 -- log is append-only, so an approval later reopened (or a reverted test) would
                 -- otherwise keep counting.
                 (select count(distinct e.job_id) from events e join jobs j on j.id=e.job_id
                    where e.kind='approved' and e.at > now() - interval '7 days'
                      and j.state in ('approved','packaged','sent','replied','interview','offer',
                                      'rejected','closed')) as approved,
                 (select count(*) from applications where sent_date > current_date - 7) as sent,
                 (select count(*) from applications where first_reply_date > current_date - 7) as replies,
                 (select count(*) from jobs where first_seen > now() - interval '7 days') as discovered
            """).fetchone()
        skills = _missing_skills(conn)

    for a in apps:
        a["_c"] = classify(a, today)
    cls = Counter(a["_c"] for a in apps)
    sent = [a for a in apps if a["_c"] != "unsent"]
    decided = [a for a in sent if a["_c"] in ("reply", "positive", "no_reply")]
    replies = [a for a in decided if a["_c"] in ("reply", "positive")]
    positive = [a for a in decided if a["_c"] == "positive"]

    out = {
        "as_of": today.isoformat(),
        "rules": {"min_n": MIN_N, "window_days": WINDOW},
        "funnel": [
            {"stage": "surfaced (decided at Gate 1)", "n": f["surfaced"]},
            {"stage": "pursued", "n": f["pursued"]},
            {"stage": "drafted (CV + letter)", "n": f["drafted"]},
            {"stage": "approved", "n": f["approved"]},
            {"stage": "sent", "n": len(sent)},
            {"stage": "any reply", "n": len(replies)},
            {"stage": "interview or offer", "n": len(positive)},
        ],
        "outcomes": {"censored": cls["censored"], "no_reply": cls["no_reply"], "reply": cls["reply"],
                     "positive": cls["positive"], "withdrawn": cls["withdrawn"], "unsent": cls["unsent"]},
        "resolved": len(decided),
        "rates_reported": len(decided) >= MIN_N,
        "any_reply": wilson(len(replies), len(decided)),
        "interview": wilson(len(positive), len(decided)),
        "gate1": [{"archetype": g["archetype"], "pursue": wilson(g["pursue"], g["n"])} for g in gate1],
        "week": week,
        "missing_skills": skills,
        "warnings": [],
    }
    if len(decided) < MIN_N:
        out["needed_for_rates"] = MIN_N - len(decided)
    else:
        out["by"] = {"source": _breakdown(decided, "source"), "archetype": _breakdown(decided, "archetype"),
                     "cv_variant": _breakdown(decided, "cv_variant")}
        for a in decided:
            s = int(a["batch_score"] or 0)
            a["score_bucket"] = f"{s // 25 * 25}-{s // 25 * 25 + 24}"
        out["by"]["score_bucket"] = _breakdown(decided, "score_bucket")

    days = sorted((a["first_reply_date"] - a["sent_date"]).days for a in replies
                  if a["first_reply_date"] and a["sent_date"])
    if days:
        out["time_to_reply"] = {"median": statistics.median(days), "min": days[0], "max": days[-1], "n": len(days)}

    variants = Counter(a["cv_variant"] or "—" for a in sent)
    if len(variants) > 1 and len(sent) < MIN_N:
        out["warnings"].append(
            f"{len(variants)} CV variants ({', '.join(f'{v} ×{n}' for v, n in variants.most_common())}) "
            f"across only {len(sent)} sent applications: nothing can be attributed to a variant "
            f"yet. That is fine while the variant follows the role; just do not read a "
            f"variant comparison off this.")
    return out


# --------------------------------------------------------------------------- weekly snapshot

def snapshot_if_due(dsn: str) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        last = conn.execute("select id, created_at from report_snapshots order by id desc limit 1").fetchone()
        due = last is None or conn.execute(
            "select %s < now() - make_interval(days => %s) as due", (last["created_at"], SNAPSHOT_EVERY_DAYS)
        ).fetchone()["due"]
        if not due:
            return {"created": False, "last": last["created_at"].isoformat()}
        data = compute(dsn)
        r = conn.execute("insert into report_snapshots (data) values (%s) returning id",
                         (Jsonb(data),)).fetchone()
        return {"created": True, "id": r["id"]}


def pending(dsn: str) -> list[dict]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute("select id, created_at, data from report_snapshots where notified_at is null "
                            "order by id desc limit 1").fetchall()
    out = []
    for r in rows:
        d = r["data"]
        w = d.get("week", {})
        out.append({"id": r["id"], "created_at": r["created_at"],
                    "headline": f"{w.get('sent', 0)} sent, {w.get('replies', 0)} replies, "
                                f"{w.get('approved', 0)} approved this week",
                    "detail": (f"{d['resolved']} resolved so far"
                               + ("" if d["rates_reported"] else f"; rates appear at {MIN_N}"))})
    return out


def mark_notified(dsn: str, ids: list[int]) -> int:
    with psycopg.connect(dsn) as conn:
        return conn.execute("update report_snapshots set notified_at=now() where id <= %s "
                            "and notified_at is null", (max(ids),)).rowcount
