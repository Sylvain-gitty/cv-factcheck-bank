"""Stage 1 as a service: fetch -> filter -> dedupe against Postgres -> insert.

Reuses discover.py's adapters, rules and dedupe (discover.collect), so the filter behaves
exactly as it did in V1. What changes is where state lives:

- Exact dedupe uses job_keys in Postgres (every key ever kept, never pruned: a repost of the
  same company/title/location is the same job).
- Near-duplicate checks also run against every job first seen in the last 120 days, not
  only against the current run. 14 days was too short: boards re-list a role with a
  reworded location ("Berlin, Berlin (Hybrid)" -> "Berlin (Hybrid)"), which changes the
  exact hash, and a job you skipped in September came back to the inbox in November.
- Each new job is inserted with state 'new', a job_keys row and a 'discovered' event, and is
  still written to jobs/<slug>.yaml, because tailor.py and letter.py read that file (until
  step 7 points them at the database).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import psycopg
import yaml
from psycopg.types.json import Jsonb

import discover

NEAR_DUP_DAYS = 120


def load_config(root: Path) -> dict:
    return yaml.safe_load((root / "sources.yaml").read_text(encoding="utf-8"))


def enabled_sources(cfg: dict) -> list[dict]:
    """Same expansion as discover.main: feeds plus enabled company boards."""
    sources = list(cfg.get("sources", []))
    for b in cfg.get("company_boards") or []:
        if b.get("enabled", True):
            sources.append({**b, "id": b.get("id") or f"{b['type']}-{b['token']}",
                            "enabled": True, "defaults": b.get("defaults", {})})
    return [s for s in sources if s.get("enabled")]


def _unique_slug(conn, base: str) -> str:
    slug, n = base, 2
    while conn.execute("select 1 from jobs where slug=%s", (slug,)).fetchone():
        slug = f"{base[:66]}-{n}"
        n += 1
    return slug


def _job_doc(job: dict) -> dict:
    """The jobs/<slug>.yaml shape tailor.py consumes (identical to V1)."""
    return {
        "title": job["title"], "company": job.get("company"),
        "location": job.get("location"), "url": job.get("url"),
        "source": job["source"], "language": job.get("language", "en"),
        "posted": str(job.get("posted_at") or ""),
        "salary_raw": job.get("salary_raw"), "tags": job.get("tags"),
        "description": job.get("description", ""),
    }


def run_discovery(dsn: str, root: Path, limit: int, only: list[str] | None) -> dict:
    cfg = load_config(root)
    sources = enabled_sources(cfg)
    known_ids = {s["id"] for s in sources}
    if only:
        unknown = sorted(set(only) - known_ids)
        if unknown:
            raise ValueError(f"unknown or disabled source ids: {unknown}")

    with psycopg.connect(dsn) as conn:
        run_id = conn.execute("insert into runs (workflow) values ('api:discover') returning id"
                              ).fetchone()[0]
        conn.commit()
        try:
            seen = {r[0] for r in conn.execute("select job_key from job_keys")}
            baseline = [{"company": c, "title": t, "job_id": k} for c, t, k in conn.execute(
                "select company, title, coalesce(job_key, slug) from jobs "
                "where first_seen > now() - make_interval(days => %s)", (NEAR_DUP_DAYS,))]

            rules = cfg.get("rules", {})
            kept, stats = discover.collect(sources, rules, seen, only=only,
                                           limit=10_000, baseline=baseline)

            # PER-SOURCE CAP PER 24 HOURS, NOT PER RUN. discover.collect caps each source
            # per call (max_per_source, 8). That was "8 a day" when V1 ran once a day; with
            # the pipeline running on every startup it became "8 per restart", and OpenAI's
            # board alone added 8 on each of seven test restarts. The quota now counts what
            # each source already added in the last 24 h. Postings over quota are not
            # recorded anywhere, so they come back on a later day rather than being lost.
            cap = rules.get("max_per_source", 8)
            used = dict(conn.execute(
                "select source, count(*) from jobs where first_seen > now() - interval '24 hours' "
                "group by source").fetchall())
            over_quota: dict[str, int] = {}
            capped = []
            for job in kept:
                if used.get(job["source"], 0) >= cap:
                    over_quota[job["source"]] = over_quota.get(job["source"], 0) + 1
                    continue
                used[job["source"]] = used.get(job["source"], 0) + 1
                capped.append(job)
            kept = capped[:limit]

            new_jobs = []
            now = datetime.now(timezone.utc)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(exist_ok=True)
            files: list[tuple[str, dict]] = []
            with conn.transaction():
                for job in kept:
                    slug = _unique_slug(conn, discover.slugify(job.get("company"), job.get("title")))
                    doc = _job_doc(job)
                    jid = conn.execute(
                        """insert into jobs (slug, job_key, title, company, location, url,
                               source, language, posted_raw, salary_raw, tags, description,
                               state, first_seen, raw)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'new',%s,%s)
                           returning id""",
                        (slug, job["job_id"], job["title"], job.get("company"),
                         job.get("location"), job.get("url"), job["source"],
                         job.get("language", "en"), doc["posted"] or None,
                         None if job.get("salary_raw") is None else str(job["salary_raw"]),
                         None if job.get("tags") is None else str(job["tags"]),
                         job.get("description", ""), now,
                         Jsonb({k: (v if isinstance(v, (str, int, float, bool, type(None)))
                                    else str(v)) for k, v in job.items()})),
                    ).fetchone()[0]
                    conn.execute("insert into job_keys (job_key, slug, source, first_seen, job_id) "
                                 "values (%s,%s,%s,%s,%s) on conflict (job_key) do nothing",
                                 (job["job_id"], slug, job["source"], now, jid))
                    conn.execute("insert into events (job_id, kind, actor, data) "
                                 "values (%s,'discovered','system',%s)",
                                 (jid, Jsonb({"source": job["source"], "run_id": run_id})))
                    files.append((slug, doc))
                    new_jobs.append({"id": jid, "slug": slug, "title": job["title"],
                                     "company": job.get("company"), "source": job["source"],
                                     "url": job.get("url")})

            # Files only after the rows are committed: a rolled-back insert must not
            # leave an orphan YAML that V1 tools would pick up.
            for slug, doc in files:
                (jobs_dir / f"{slug}.yaml").write_text(
                    yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                                   default_flow_style=False, width=95), encoding="utf-8")

            per_source = [{"source": s, "fetched": f, "filtered": r, "duplicates": d,
                           "error": e or None} for s, f, r, d, e in stats]
            failed = [p["source"] for p in per_source if p["error"]]
            result = {"run_id": run_id, "new": len(new_jobs), "new_jobs": new_jobs,
                      "over_daily_quota": over_quota,
                      "sources_run": len(per_source), "sources_failed": failed,
                      "fetched": sum(p["fetched"] for p in per_source),
                      "per_source": per_source}
            conn.execute("update runs set finished_at=clock_timestamp(), status='ok', stats=%s where id=%s",
                         (Jsonb({k: v for k, v in result.items() if k != "new_jobs"}), run_id))
            conn.commit()
            return result
        except Exception as e:
            conn.rollback()
            conn.execute("update runs set finished_at=clock_timestamp(), status='failed', error=%s where id=%s",
                         (f"{type(e).__name__}: {e}"[:2000], run_id))
            conn.commit()
            raise
