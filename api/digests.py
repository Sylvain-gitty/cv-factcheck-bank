"""The local digest: record a pipeline run, read the latest, mark it notified, render a page.

n8n writes a digest at the end of every pipeline run (and its error workflow writes a
failed one). The Windows notifier polls for digests not yet notified; the page at / shows
the latest. Nothing leaves the machine.
"""
from __future__ import annotations

import html
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

COLUMNS = ("id, created_at, status, trigger, new_count, inbox_size, fetched, sources_run, "
           "sources_failed, top, discover_run_id, score_run_id, workflow, failed_node, error, "
           "execution_url, source_execution, notified_at")


def record(dsn: str, d: dict) -> dict:
    """Insert a digest. Idempotent on source_execution: a repeat returns the first row."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute(
            f"""insert into digests (status, trigger, new_count, inbox_size, fetched,
                    sources_run, sources_failed, top, discover_run_id, score_run_id,
                    workflow, failed_node, error, execution_url, source_execution)
                values (%(status)s, %(trigger)s, %(new_count)s, %(inbox_size)s, %(fetched)s,
                    %(sources_run)s, %(sources_failed)s, %(top)s, %(discover_run_id)s,
                    %(score_run_id)s, %(workflow)s, %(failed_node)s, %(error)s,
                    %(execution_url)s, %(source_execution)s)
                on conflict (source_execution) where source_execution is not null do nothing
                returning {COLUMNS}""",
            {**d, "sources_failed": Jsonb(d.get("sources_failed") or []),
             "top": Jsonb(d.get("top") or [])},
        ).fetchone()
        if row is None:     # already recorded: return the original, flagged
            row = conn.execute(f"select {COLUMNS} from digests where source_execution=%s",
                               (d["source_execution"],)).fetchone()
            row["duplicate"] = True
    return row


def latest(dsn: str) -> dict | None:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return conn.execute(f"select {COLUMNS} from digests order by id desc limit 1").fetchone()


def pending(dsn: str) -> list[dict]:
    """Digests the notifier has not shown yet, oldest first."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return conn.execute(f"select {COLUMNS} from digests where notified_at is null "
                            "order by id").fetchall()


def mark_notified(dsn: str, up_to_id: int) -> int:
    with psycopg.connect(dsn) as conn:
        cur = conn.execute("update digests set notified_at=now() "
                           "where notified_at is null and id <= %s", (up_to_id,))
        return cur.rowcount


# --------------------------------------------------------------------------- page

def _ago(ts: datetime) -> str:
    secs = int((datetime.now(ts.tzinfo) - ts).total_seconds())
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{secs // 60} min ago"
    if secs < 36 * 3600:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} days ago"


def page(d: dict | None) -> str:
    e = html.escape
    if d is None:
        body = "<p>No pipeline run recorded yet. It runs each time the stack starts.</p>"
    elif d["status"] == "failed":
        body = (f"<p class='bad'><b>The last run failed</b> ({_ago(d['created_at'])}), "
                f"in <b>{e(d['workflow'] or '?')}</b> at node <b>{e(d['failed_node'] or '?')}</b>.</p>"
                f"<pre>{e(d['error'] or '')}</pre>"
                + (f"<p><a href='{e(d['execution_url'])}'>Open the execution in n8n</a></p>"
                   if d.get("execution_url") else ""))
    else:
        rows = "".join(
            f"<tr><td class='n'>{e(str(t.get('relative', '')))}</td>"
            f"<td class='m'>{e(str(t.get('archetype') or ''))}</td>"
            f"<td><b>{e(str(t.get('company') or '?'))}</b> — "
            f"<a href='{e(str(t.get('url') or '#'))}' target='_blank' rel='noopener'>"
            f"{e(str(t.get('title') or ''))}</a></td></tr>" for t in d["top"])
        failed = (f"<p class='warn'>Sources that failed: {e(', '.join(d['sources_failed']))}</p>"
                  if d["sources_failed"] else "")
        body = (f"<p class='big'><b>{d['new_count']}</b> new · <b>{d['inbox_size']}</b> waiting "
                f"for a decision</p>"
                f"<p class='m'>Last run {_ago(d['created_at'])} "
                f"({d['created_at']:%a %d %b, %H:%M}) · fetched {d['fetched']} postings "
                f"from {d['sources_run']} sources</p>"
                f"<h2>Top of the inbox</h2><table>{rows}</table>{failed}"
                "<p class='m'>Score is relative to the whole corpus (0-100), not a match %. "
                "“?” means two role profiles were nearly tied.</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job engine</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--bad:#a8261b;--warn:#8a5a00;--link:#1f5fae}}
@media (prefers-color-scheme:dark){{:root{{--bg:#191917;--fg:#ececea;--muted:#a0a09a;--line:#33332f;--bad:#ff8a7d;--warn:#e7b65c;--link:#8ab8ff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:820px;margin:0 auto;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 12px}} h2{{font-size:15px;margin:20px 0 6px}}
a{{color:var(--link)}} .m{{color:var(--muted)}} .bad{{color:var(--bad)}} .warn{{color:var(--warn)}}
.big{{font-size:18px}} table{{border-collapse:collapse;width:100%}}
td{{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
td.n{{text-align:right;width:3em;font-variant-numeric:tabular-nums}} td.m{{width:13em;font-size:13px}}
pre{{white-space:pre-wrap;background:var(--line);padding:8px;border-radius:4px}}
</style></head><body><main><h1>Job engine</h1>{body}
<p class="m">The review screens arrive in step 6; until then this page is the digest.</p>
</main></body></html>"""
