#!/usr/bin/env python3
"""n8n's connection pools fit inside its postgres, with room to spare.

Every n8n process that talks to the database holds a pool of DB_POSTGRESDB_POOL_SIZE connections. They were 25 each,
four processes = 100 = postgres's max_connections, so a migration, a backup or any reader through N8N_DB_DSN found no
connection left (issues/indox-completion-loop-root-cause-2026-08-10.yaml, DGO-1848). This reads the compose file as
it ships — each service's default pool and postgres's max_connections — and holds the sum to at most 70% of it.

    python3 apps/n8n/test_db_pool.py
"""
import pathlib
import re
import sys

COMPOSE = pathlib.Path(__file__).resolve().parent / "docker-compose.yml"
HEADROOM = 0.7          # the pools may take at most this share of max_connections


def main() -> int:
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(r"max_connections=(\d+)", text)
    if not m:
        print("FAIL n8n-postgres declares no max_connections — the pools cannot be checked against it")
        return 1
    limit = int(m.group(1))
    pools = [int(x) for x in re.findall(r"DB_POSTGRESDB_POOL_SIZE=\$\{DB_POSTGRESDB_POOL_SIZE:-(\d+)\}", text)]
    if not pools:
        print("FAIL no service declares DB_POSTGRESDB_POOL_SIZE — the check would measure nothing")
        return 1
    total, ceiling = sum(pools), int(limit * HEADROOM)
    ok = total <= ceiling
    print(("ok   " if ok else "FAIL ")
          + f"{len(pools)} pool(s) of {pools} = {total} connections, under {ceiling} of max_connections={limit}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
