"""Apply db/migrations/*.sql in order, once each.

    python api/migrate.py            # inside the factbank-api container
    python api/migrate.py --status

Also called at API startup, so `docker compose up` always leaves the schema current.
Each file runs in its own transaction: a failing migration leaves nothing half-applied.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent.parent / "db" / "migrations"


def migrate(dsn: str, verbose: bool = True) -> list[str]:
    applied_now = []
    with psycopg.connect(dsn) as conn:
        conn.execute("""create table if not exists schema_migrations (
                            version text primary key,
                            applied_at timestamptz not null default now())""")
        conn.commit()
        done = {r[0] for r in conn.execute("select version from schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.stem in done:
                continue
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (version) values (%s)", (f.stem,))
            applied_now.append(f.stem)
            if verbose:
                print(f"applied {f.stem}")
    if verbose and not applied_now:
        print("schema up to date")
    return applied_now


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    dsn = os.environ["DATABASE_URL"]
    if a.status:
        with psycopg.connect(dsn) as conn:
            try:
                rows = conn.execute("select version, applied_at from schema_migrations "
                                    "order by version").fetchall()
            except psycopg.errors.UndefinedTable:
                rows = []
        done = {v for v, _ in rows}
        for v, at in rows:
            print(f"  applied  {v}  {at:%Y-%m-%d %H:%M}")
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.stem not in done:
                print(f"  pending  {f.stem}")
        return 0
    migrate(dsn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
