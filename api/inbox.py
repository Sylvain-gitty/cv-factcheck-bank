"""Gate 1 for the review app: list the inbox, record pursue/skip, undo.

Every decision snapshots the job's latest score into `features` AT DECISION TIME (the same
shape V1 stored in .state/decisions.json), because re-deriving it later would score
against a corpus that no longer exists. That snapshot is the training set.

State transitions owned here:  scored -> pursued | skipped,  and back on undo.
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

LATEST_SCORE = """
    left join lateral (select * from scores where job_id = j.id
                       order by scored_at desc, id desc limit 1) s on true"""


def list_inbox(dsn: str, source: str | None, archetype: str | None, q: str | None,
               limit: int) -> dict:
    where, args = ["j.state = 'scored'"], []
    if source:
        where.append("j.source = %s")
        args.append(source)
    if archetype:
        where.append("s.archetype = %s")
        args.append(archetype)
    if q:
        where.append("(j.title ilike %s or j.company ilike %s or j.description ilike %s)")
        args += [f"%{q}%"] * 3
    sql_where = " and ".join(where)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        jobs = conn.execute(
            f"""select j.id, j.slug, j.title, j.company, j.location, j.url, j.source,
                       j.posted_at, j.first_seen, left(j.description, 600) as snippet,
                       length(j.description) as desc_len,
                       s.relative, s.archetype, s.archetype_label, s.archetype_confident,
                       s.margin, s.per_archetype
                from jobs j {LATEST_SCORE}
                where {sql_where}
                order by s.relative desc nulls last, j.first_seen desc
                limit %s""", (*args, limit)).fetchall()
        total = conn.execute(f"select count(*) as n from jobs j {LATEST_SCORE} where {sql_where}",
                             args).fetchone()["n"]
        facets = {
            "sources": conn.execute(
                "select source as key, count(*) as n from jobs where state='scored' "
                "group by 1 order by 2 desc, 1").fetchall(),
            "archetypes": conn.execute(
                f"select s.archetype as key, count(*) as n from jobs j {LATEST_SCORE} "
                "where j.state='scored' group by 1 order by 2 desc").fetchall(),
        }
        inbox_size = conn.execute("select count(*) as n from jobs where state='scored'"
                                  ).fetchone()["n"]
    return {"jobs": jobs, "matching": total, "inbox_size": inbox_size, "facets": facets}


def job_detail(dsn: str, job_id: int) -> dict | None:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return conn.execute(
            f"""select j.id, j.slug, j.title, j.company, j.location, j.url, j.source,
                       j.state, j.posted_at, j.first_seen, j.description, j.salary_raw, j.tags,
                       s.relative, s.archetype_label, s.per_archetype, s.margin
                from jobs j {LATEST_SCORE} where j.id = %s""", (job_id,)).fetchone()


def decide(dsn: str, job_ids: list[int], verdict: str) -> dict:
    """Record one verdict for many jobs. Only jobs still in the inbox are touched."""
    target = "pursued" if verdict == "pursue" else "skipped"
    decided, skipped_ids = [], []
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        rows = conn.execute(
            f"""select j.id, s.id as score_id, s.per_archetype, s.archetype,
                       s.archetype_confident, s.archetype_label, s.margin, s.raw, s.relative
                from jobs j {LATEST_SCORE}
                where j.id = any(%s) and j.state = 'scored'
                for update of j""", (job_ids,)).fetchall()
        found = {r["id"] for r in rows}
        skipped_ids = [i for i in job_ids if i not in found]
        for r in rows:
            features = {k: (float(r[k]) if k in ("margin", "raw") and r[k] is not None else r[k])
                        for k in ("per_archetype", "archetype", "archetype_confident",
                                  "archetype_label", "margin", "raw", "relative")}
            did = conn.execute(
                "insert into decisions (job_id, verdict, features, origin, score_id) "
                "values (%s, %s, %s, 'app', %s) returning id",
                (r["id"], verdict, Jsonb(features), r["score_id"])).fetchone()["id"]
            conn.execute("update jobs set state=%s, state_changed_at=now(), updated_at=now() "
                         "where id=%s", (target, r["id"]))
            conn.execute("insert into events (job_id, kind, actor, data) values "
                         "(%s, 'decision', 'user', %s)",
                         (r["id"], Jsonb({"verdict": verdict, "decision_id": did})))
            decided.append({"job_id": r["id"], "decision_id": did})
    return {"decided": decided, "not_in_inbox": skipped_ids, "state": target}


def undo(dsn: str, decision_ids: list[int]) -> dict:
    """Put jobs back in the inbox. Refuses if the job has moved past its decision
    (e.g. drafting already started on a pursue)."""
    restored, refused = [], []
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction():
        rows = conn.execute(
            """select d.id, d.job_id, d.verdict, j.state from decisions d
               join jobs j on j.id = d.job_id
               where d.id = any(%s) and d.undone_at is null and d.origin = 'app'
               for update of j""", (decision_ids,)).fetchall()
        for r in rows:
            expected = "pursued" if r["verdict"] == "pursue" else "skipped"
            if r["state"] != expected:
                refused.append({"decision_id": r["id"], "state": r["state"]})
                continue
            conn.execute("update decisions set undone_at=now() where id=%s", (r["id"],))
            conn.execute("update jobs set state='scored', state_changed_at=now(), "
                         "updated_at=now() where id=%s", (r["job_id"],))
            conn.execute("insert into events (job_id, kind, actor, data) values "
                         "(%s, 'decision_undone', 'user', %s)",
                         (r["job_id"], Jsonb({"decision_id": r["id"]})))
            restored.append(r["job_id"])
    return {"restored": restored, "refused": refused}


def counts(dsn: str) -> dict:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        by_state = {r["state"]: r["n"] for r in conn.execute(
            "select state, count(*) as n from jobs group by 1").fetchall()}
        today = conn.execute(
            "select count(*) filter (where verdict='pursue') as pursued, "
            "count(*) filter (where verdict='skip') as skipped from decisions "
            "where origin='app' and undone_at is null and decided_at::date = current_date"
        ).fetchone()
    return {"by_state": by_state, "decided_today": today}
