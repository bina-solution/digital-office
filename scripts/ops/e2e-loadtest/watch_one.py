#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_one.py — polls incoming_documents for E2ELT-marked rows (SYNC_NAME in the e2e-* pipes,
filename LIKE 'E2ELT_%') and prints STATUS + elapsed wall-clock on every change, until COMPLETED
(or --timeout-s). This is the single-document proof point: apitools's own cache-miss cost is
256-302s (coordinator-supplied datapoint, ~95% of per-document pipeline cost), so this normally
takes minutes, not seconds — a poll interval of 15s keeps that visible without hammering the DB.

Usage: python3 watch_one.py --deployment-name shlomo-laptop --timeout-s 900 --interval-s 15
"""
import argparse
import subprocess
import time


def psql(dn, sql, timeout=20):
    r = subprocess.run(["docker", "exec", f"supabase-db-{dn}", "psql", "-U", "postgres", "-d", "postgres",
                        "-tAc", sql], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deployment-name", default="shlomo-laptop")
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--interval-s", type=int, default=15)
    a = ap.parse_args()
    dn = a.deployment_name

    t0 = time.time()
    last = None
    print(f"t=0.0s watching for E2ELT rows...")
    while time.time() - t0 < a.timeout_s:
        rows = psql(dn,
            "select \"ID\",\"SYNC_NAME\",\"STATUS\",\"TYPE\",\"COMPANY_NAME\",created_at,updated_at "
            "from incoming_documents where \"NAME\" like 'E2ELT_%' "
            "or \"SOURCE_LINK\" like '%E2ELT_%' "
            "or \"ID\" in (select \"ID\" from incoming_documents where \"SYNC_NAME\" in "
            "('e2e-mail','e2e-drive-gdoc','e2e-drive-bs')) "
            "order by updated_at desc limit 5")
        elapsed = time.time() - t0
        if rows != last:
            print(f"t={elapsed:6.1f}s  {rows or '(no E2ELT row visible yet)'}")
            last = rows
        if rows and "COMPLETED" in rows:
            print(f"\n[watch_one] COMPLETED at t={elapsed:.1f}s")
            return 0
        time.sleep(a.interval_s)
    print(f"\n[watch_one] TIMEOUT after {a.timeout_s}s — last seen:\n{last}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
