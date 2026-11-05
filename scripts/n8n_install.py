"""Import (or re-import) the job-engine workflows into the running n8n, and publish them.

    python scripts/n8n_install.py

Run on the host with the stack up. Imports every n8n/workflows/*.json and publishes them,
then restarts n8n: a published "On n8n startup" trigger fires on that restart, so this
also runs the pipeline once. Re-running is safe: workflow ids are fixed, so an import
replaces the earlier version. No credentials are involved: the workflows only call the
local factbank-api, using the token from n8n's environment.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / "n8n" / "workflows"


def sh(*args: str) -> str:
    p = subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode:
        sys.exit(f"failed: docker compose {' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def main() -> int:
    ids = []
    for f in sorted(WORKFLOWS.glob("*.json")):
        wf = json.loads(f.read_text(encoding="utf-8"))          # fail early on bad JSON
        sh("cp", str(f), f"n8n:/tmp/{f.name}")
        sh("exec", "-T", "n8n", "n8n", "import:workflow", f"--input=/tmp/{f.name}")
        print(f"imported  {wf['name']}  [{wf['id']}]")
        ids.append(wf["id"])
    for wid in ids:
        sh("exec", "-T", "n8n", "n8n", "publish:workflow", f"--id={wid}")
        print(f"published {wid}")
    sh("restart", "n8n")
    print("n8n restarted: the startup pipeline is running now (see http://localhost:8000/).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
