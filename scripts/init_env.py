"""Create .env with fresh random secrets, from .env.example.

    python scripts/init_env.py           # refuses if .env already exists
    python scripts/init_env.py --force   # overwrite (breaks an existing Postgres volume
                                         # and makes saved n8n credentials unreadable)
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = {"POSTGRES_PASSWORD", "N8N_ENCRYPTION_KEY", "API_TOKEN"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    env = ROOT / ".env"
    if env.exists() and not a.force:
        print(f"{env} already exists; not touching it (use --force to regenerate).")
        return 1
    out = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip()
        if key in SECRETS:
            line = f"{key}={secrets.token_urlsafe(32)}"
        out.append(line)
    env.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {env} with fresh secrets for: {', '.join(sorted(SECRETS))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
