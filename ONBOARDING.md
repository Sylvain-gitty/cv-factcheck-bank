# Onboarding: set the job engine up from scratch

About 30 minutes, plus the time it takes to write your fact bank (3–5 hours the first
time). Everything runs on this PC.

## 0. What you need

- **Windows 10/11.** The desktop helper uses Windows notifications and Edge, which is
  preinstalled.
- **Docker Desktop.** In its settings, turn on **"Start Docker Desktop when you sign in"**:
  the engine runs on every startup only if Docker does.
- **Git** and **Python 3.11+**. The host scripts use only the standard library.

## 1. Get the code

```bash
git clone https://github.com/Sylvain-gitty/cv-factcheck-bank.git fact-bank
cd fact-bank
```

## 2. The fact bank (the real work)

The engine never writes a claim about you; it only selects from what you have confirmed.
Start from the templates:

```bash
cp profile.example.yaml profile.yaml
cp entities.example.yaml entities.yaml
cp facts.example.yaml facts.yaml
cp vocab.example.yaml vocab.yaml
cp answers.example.yaml answers.yaml
```

- **`profile.yaml`:** contact details; three **role profiles**, each with a human `profile`
  paragraph and a machine `match_text` that is scored against every posting; the deny-list.
- **`entities.yaml`:** jobs, projects and degrees, with dates and authorship
  (sole / co-authored / team).
- **`facts.yaml`:** one claim per record, with a short CV bullet, outcome, metrics, skills
  (from `vocab.yaml`), and `contribution` (`supported` facts never reach a CV).
- **`answers.yaml`:** screening answers. "Why us?" stays `PER_JOB`, and salary stays blank
  until you have researched it.

The design reasoning behind every field is in [docs/v1-onboarding.md](docs/v1-onboarding.md) §5.

Check and confirm the facts. **Nothing renders until a fact is `confirmed`.** Once the stack is
up (step 4), these run without a host install:

```bash
docker compose exec factbank-api python validate.py
docker compose exec factbank-api python confirm.py
```

`confirm.py` writes `out/worksheet.md` and `confirm.txt`. Tick `[x]` in `confirm.txt`, then run:

```bash
docker compose exec factbank-api python confirm.py --apply
```

## 3. Secrets

```bash
python scripts/init_env.py
```

This writes `.env` with fresh random secrets (gitignored). **Copy `.env` somewhere safe
now**: restoring a backup needs the same `N8N_ENCRYPTION_KEY` and database password.

## 4. Start the stack

```bash
docker compose up -d --build
```

You get Postgres, n8n (http://localhost:5678), factbank-api plus the app (http://localhost:8000),
and the daily backup. The schema migrates itself when the API starts.

*Only when moving from V1:* to bring over your old jobs, decisions and applications, run this
once (it refuses to run twice):

```bash
docker compose exec factbank-api python scripts/import_v1.py
```

## 5. n8n

1. Open http://localhost:5678 and create your owner account. It is your login, so you do this yourself.
2. Install the workflows (pipeline, drafting, weekly report, error alerts):
   ```bash
   python scripts/n8n_install.py
   ```
   This restarts n8n, which runs the pipeline once straight away.

There are no n8n credentials to set up: the workflows only call the local API, with the
token taken from n8n's environment.

## 6. The desktop helper

```bash
powershell -ExecutionPolicy Bypass -File scripts\windows\install-notifier.ps1
```

This registers one scheduled task, `JobEngineNotifier`, for your user only, with normal
rights, starting at sign-in. It shows notifications, prints PDFs with Edge, and runs the
health checks. Test it:

```bash
powershell -ExecutionPolicy Bypass -File scripts\windows\notifier.ps1 -Test
```

To remove it: `install-notifier.ps1 -Uninstall`.

## 7. Check it works

- http://localhost:8000/ shows the inbox, with a digest from the run in step 5.
- No health banner at the top: the heartbeat is OK.
- `backups/` contains today's `*-jobengine.dump`, `*-n8n.dump` and `*-files.tgz`.

Then restart the PC once. After signing in you should get a "new jobs" notification
without doing anything.

## Using it

See the README table "A normal day". The short version:

1. **Inbox:** `p` pursue, `s` skip, `x` select plus "Skip selected", `/` search.
2. **Review:** read the CV, write the opening, tick "I read the CV", **Approve**.
3. **Applications:** apply on the employer's site, then **I sent it**. Later, record the outcome.
4. **Report:** weekly. Don't read a rate until it is shown: it appears at 25 resolved applications.

## Tuning, after a few weeks

- **Role profiles:** look at the pursue share per role profile in the Report, and at jobs you
  pursued that scored low. Add their vocabulary to that profile's `match_text`.
- **Sources:** add employer boards to `sources.yaml` (Greenhouse / Lever / Ashby / Personio:
  probe all four patterns per company). Drop sources that are structurally irrelevant, not
  ones that had one quiet day.
- **Skill gaps:** the Report lists the skills postings asked for that no fact evidences. Write
  the fact if you have the experience; otherwise, that list is your learning plan.

## When something breaks

[docs/RUNBOOK.md](docs/RUNBOOK.md) explains every health message, the backups and the restore.
