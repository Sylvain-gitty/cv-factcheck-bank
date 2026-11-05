# Runbook: when something is wrong

The engine tells you when something breaks, through the desktop helper's notifications
and the banner on the Inbox. This page says what each message means and what to do.

## Health messages (the heartbeat)

| Code | Means | Do |
|---|---|---|
| `n8n_down` | n8n doesn't answer, so nothing runs | `docker compose ps`; `docker compose up -d` |
| `silent_pipeline` | The pipeline ran, but no digest was recorded, so you would hear nothing | `docker compose logs factbank-api --tail 50`. Look for `POST /digests` that isn't 200 |
| `unrecorded_fail` | An n8n run failed, and the error workflow couldn't record it | Open http://localhost:5678 → Executions, then the API log as above |
| `no_discovery` | No successful discovery for 3+ days while the stack was up | Restart n8n (`docker compose restart n8n`), or run the pipeline workflow by hand |
| `stuck_drafting` | A job has been "drafting" for 15+ minutes (normally seconds) | It goes back to "waiting" by itself after 15 minutes. If it repeats, check `docker compose logs factbank-api` |
| `stuck_pdfs` | PDFs have waited 10+ minutes | The desktop helper isn't running: Task Scheduler → `JobEngineNotifier` → Run |
| `drafts_given_up` | Drafting failed 3 times for a job | Review shows the error, and a Retry button |
| `backup_stale` | The newest database backup is over 36 h old, or missing | `docker compose logs backup`; `docker compose up -d backup` |

"Job engine not reachable" (from the helper itself) means the API didn't answer for
about 6 minutes: Docker Desktop is probably not running.

## Backups

The `backup` service writes to `backups/` once when it starts, then every 24 h, and keeps 14 days:

- `<ts>-jobengine.dump`: the engine's database (jobs, decisions, applications, …)
- `<ts>-n8n.dump`: n8n's database (workflows, executions)
- `<ts>-files.tgz`: the files that exist nowhere else: `profile/entities/facts/vocab/answers/
  sources/render_config.yaml`, `letters/`, `jobs/`, `out/applications/`

**Not included: `.env`.** Keep a copy somewhere safe yourself. Restoring n8n needs the same
`N8N_ENCRYPTION_KEY`, and the databases need the same password.

`backups/` sits on the same disk as everything else. For protection against disk loss, copy it
somewhere else now and then (an external drive, or encrypted cloud storage).

### Restore the engine's database

Tested on 2026-11-05: row counts matched exactly.

```bash
docker compose stop n8n factbank-api
docker compose exec -T postgres dropdb -U jobengine jobengine
docker compose exec -T postgres createdb -U jobengine jobengine
docker compose exec -T backup pg_restore --no-owner -d jobengine /backups/<ts>-jobengine.dump
docker compose up -d
```

For n8n, do the same with `n8n` and `<ts>-n8n.dump`. To restore files:
`tar -xzf backups/<ts>-files.tgz`, run inside the `fact-bank` folder. Check what it would
overwrite first with `tar -tzf`.

To try a restore without touching live data, restore into a scratch database
(`createdb restore_check`, `pg_restore -d restore_check …`), compare, then `dropdb restore_check`.

## Running the pipeline while the PC stays on

By design, the pipeline runs on every startup. To also run every 12 hours, open the pipeline
workflow in n8n, select **"Every 12 hours (OFF…)"**, press **D** to enable it, and save. Extra
runs are harmless: duplicates are dropped, and each source is capped at 8 new jobs per 24 h.
