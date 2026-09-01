# The n8n layer

Two importable workflows plus the bridge they talk to.

| File | Runs | Does |
|---|---|---|
| `daily-pipeline.json` | 07:00, weekdays | Discover → rank → email digest → **Gate 1** → tailor CV + draft letter |
| `weekly-report.json` | Friday 18:00 | Response rates, what needs chasing, the ready-to-send queue |

---

## Why there is a bridge instead of Execute Command nodes

n8n runs in Docker. The pipeline is Python on the Windows host. **A container cannot run a
program on its host**, and the usual workarounds are worse than the indirection:

- Installing Python into the n8n image breaks on every image update.
- Mounting the host filesystem into a Node container to shell out is fragile and hard to
  reason about when it fails at 07:00 on a Tuesday.

So the tools stay put and expose a narrow local HTTP API. n8n drives them with plain HTTP
Request nodes. Nothing in the workflows changes if you later move n8n elsewhere — or drop
n8n entirely and call the same endpoints from cron.

## Security, because it is a server that runs programs

`bridge.py` has three constraints and none is optional:

1. **Bound to `127.0.0.1`.** Not `0.0.0.0`. It is unreachable from your network. Changing
   this publishes a remote code execution endpoint — do not.
2. **A fixed action allowlist.** No endpoint accepts a command string. Each route maps to a
   hard-coded argv list, and the only caller-supplied value is a slug validated against
   `[a-z0-9._-]{1,80}` before it goes near a subprocess. Verified against
   `a; rm -rf /`, `../../etc/passwd`, `a && curl evil.com`, `$(whoami)` and a poisoned
   `variant` — all rejected with 400.
3. **Bearer token**, generated on first run into `.state/bridge-token` (gitignored).
   Without it any local process could drive your job applications.

From n8n in Docker the host is `http://host.docker.internal:899`, which is still a loopback
path on the host side.

---

## Setup

**1. Start the bridge** (leave it running; it is the only long-lived process):

```bash
cd n8n-automations/fact-bank && python bridge.py
```

It prints the token. Get it again any time with `python bridge.py --print-token`.

**2. Start n8n.** Two options, and Node 26 is already installed here so the second is the
lighter one.

*Docker* — start Docker Desktop first; it is installed but the daemon was stopped when this
was written:

```bash
docker run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n --add-host host.docker.internal:host-gateway docker.n8n.io/n8nio/n8n
```

*Native* — no container, no image to maintain:

```bash
npx n8n
```

Running natively, n8n reaches the bridge at `http://127.0.0.1:899` rather than
`host.docker.internal`. Change the URL in the four HTTP Request nodes, or set the whole
base as a variable.

**Native n8n could use Execute Command nodes and skip the bridge entirely — I would still
not.** Execute Command inherits a shell whose working directory and Python resolution
depend on how n8n was launched, which is a tedious class of failure to debug at 07:00. The
HTTP boundary behaves identically whichever way you run n8n, and stays put if you later
switch to Docker, move machines, or replace n8n with Task Scheduler.

**3. Set three variables** in n8n (Settings → Variables), so no secret lives in the
workflow JSON:

| Variable | Value |
|---|---|
| `BRIDGE_TOKEN` | the token from step 1 |
| `BRIDGE_PORT` | `899` |
| `NOTIFY_EMAIL` | where the digest goes |

**4. Import both JSON files** (Workflows → Import from File) and attach an SMTP credential
to the email nodes.

**5. Test before scheduling.** Run the daily workflow manually once. If discovery fails,
the alert branch fires — the usual cause is the bridge not running.

---

## Where the human gates live

The workflows automate assembly and stop at judgement, exactly as the plans specify.

**Gate 1 — in n8n.** A `Wait` node set to *On webhook call* pauses the execution
indefinitely. The digest email renders two links per job, `pursue` and `skip`, pointing at
that execution's resume URL. Clicking one resumes the workflow with your verdict.

**Gates 2 and 3 — deliberately outside n8n.** After the CV and letter draft exist you get an
email and the workflow ends. Reading the CV and writing the letter opening happen at your
desk. Building a "click to approve" button for those would turn two acts of judgement into
two clicks, which is the failure this whole design is arranged against.

**Gate 4 — nowhere.** No workflow submits anything. There is no node for it and no endpoint
behind it.

---

## Known rough edges

- **Written against n8n's schema without an n8n instance to import into.** The JSON is
  structurally valid and every connection resolves to a real node, but node `typeVersion`s
  move with releases. If the import complains, it will name the node.
- **The `Pursue?` branch handles one job per resume.** Clicking three `pursue` links
  resumes three separate executions, which is the intended behaviour but looks odd in the
  executions list.
- **Email, not Telegram.** Telegram gives nicer inline buttons; the resume URLs work
  identically. Swap the node if you prefer.
- **`llm: false` in the rank node.** Flip it once `OPENROUTER_API_KEY` is in the *bridge
  process's* environment, not n8n's — the bridge is what runs the Python.

## Running it without n8n at all

The bridge is optional. Everything works from a shell, and this is the honest way to start:

```bash
cd n8n-automations/fact-bank && python discover.py && python rank.py
```

n8n buys scheduling and the Gate 1 button. It does not buy anything the pipeline cannot
already do, and it is worth getting a week of manual runs behind you before adding a
scheduler to a process you have not yet felt.
