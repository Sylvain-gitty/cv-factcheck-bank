"""Stage 2b as a service: BM25 against each archetype's match_text, stored in Postgres.

Reuses rank.score_batch unchanged (margin rule, ambiguous labels, batch-relative 0-100).

THE CORPUS IS EVERY JOB IN THE DATABASE, NOT ONLY TODAY'S. BM25's IDF depends on the
corpus, so scoring a batch of five new postings on their own would make "relative" swing
wildly from day to day. Scoring against the whole history keeps IDF stable. Scores are
STORED only for jobs still waiting for Gate 1 (state new or scored), so the inbox is always
ranked on one consistent run. Decided jobs keep the score they had when you decided.
"""
from __future__ import annotations

from pathlib import Path

import psycopg
import yaml
from psycopg.types.json import Jsonb

import rank

WAITING = ("new", "scored")


def run_scoring(dsn: str, root: Path, top: int = 10) -> dict:
    profile = yaml.safe_load((root / "profile.yaml").read_text(encoding="utf-8"))
    with psycopg.connect(dsn) as conn:
        run_id = conn.execute("insert into runs (workflow) values ('api:score') returning id"
                              ).fetchone()[0]
        conn.commit()
        try:
            rows = conn.execute("select id, slug, title, company, location, tags, description, "
                                "state from jobs").fetchall()
            corpus = {r[1]: {"title": r[2], "company": r[3], "location": r[4], "tags": r[5],
                             "description": r[6]} for r in rows}
            meta = {r[1]: (r[0], r[7]) for r in rows}
            scores = rank.score_batch(corpus, profile) if corpus else {}

            newly, stored = [], 0
            with conn.transaction():
                for slug, s in scores.items():
                    jid, state = meta[slug]
                    if state not in WAITING:
                        continue
                    conn.execute(
                        """insert into scores (job_id, run_id, method, per_archetype, archetype,
                               archetype_confident, archetype_label, margin, raw, relative)
                           values (%s,%s,'bm25',%s,%s,%s,%s,%s,%s,%s)""",
                        (jid, run_id, Jsonb(s["per_archetype"]), s["archetype"],
                         s["archetype_confident"], s["archetype_label"], s["margin"],
                         s["raw"], s["relative"]))
                    stored += 1
                    if state == "new":
                        conn.execute("update jobs set state='scored', state_changed_at=now(), "
                                     "updated_at=now() where id=%s", (jid,))
                        conn.execute("insert into events (job_id, kind, actor, data) "
                                     "values (%s,'state_change','system',%s)",
                                     (jid, Jsonb({"from": "new", "to": "scored", "run_id": run_id})))
                        newly.append(slug)

            inbox = conn.execute(
                """select j.id, j.slug, j.title, j.company, j.url, s.relative, s.archetype_label
                   from jobs j
                   join lateral (select * from scores where job_id=j.id
                                 order by scored_at desc, id desc limit 1) s on true
                   where j.state='scored'
                   order by s.relative desc nulls last, j.first_seen desc
                   limit %s""", (top,)).fetchall()
            result = {
                "run_id": run_id, "corpus": len(corpus), "stored": stored,
                "newly_scored": len(newly),
                "inbox_size": conn.execute("select count(*) from jobs where state='scored'"
                                           ).fetchone()[0],
                "top": [{"id": r[0], "slug": r[1], "title": r[2], "company": r[3], "url": r[4],
                         "relative": r[5], "archetype": r[6]} for r in inbox],
            }
            conn.execute("update runs set finished_at=clock_timestamp(), status='ok', stats=%s where id=%s",
                         (Jsonb({k: v for k, v in result.items() if k != "top"}), run_id))
            conn.commit()
            return result
        except Exception as e:
            conn.rollback()
            conn.execute("update runs set finished_at=clock_timestamp(), status='failed', error=%s where id=%s",
                         (f"{type(e).__name__}: {e}"[:2000], run_id))
            conn.commit()
            raise
