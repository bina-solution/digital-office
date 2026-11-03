#!/usr/bin/env python3
"""The git overview (GET /api/overview), as lines an agent can say: the forge, the repositories, one line
per account and one per mirror — each part saying when it could not be read.

The git recipe pipes into it — `./bbox git overview | python3 apps/git/operatives/lines.py`, or the same
API through `./bbox remote <office> <alias> /api/overview`, whose first line (`HTTP <status>  GET
<url>`) it skips and whose office it names. The overview holds up to 100 repository records ahead of
the accounts and the mirrors: read whole, they sit where a model's context cuts it. An answer that is
not an overview is printed as it came and exits 1, so a git that did not answer is never "no repos".
"""
import json
import re
import sys
import time


def flat(v):
    return re.sub(r"\s+", " ", str(v or "")).replace("|", "¦").strip()[:160]


def age(ts):
    if not ts:
        return "never"
    try:
        minutes = int((time.time() - float(ts)) / 60)
    except (TypeError, ValueError):
        return f"last run {flat(ts)}"
    return f"{minutes} min ago" if minutes < 120 else f"{minutes // 60} h ago"


def main():
    text = sys.stdin.read()
    office, head = "", ""
    if text.startswith("HTTP "):
        head, _, text = text.partition("\n")
        if re.match(r"HTTP [45]", head):
            print(head)
            print(text[:600])
            return 1
        m = re.search(r"//[a-z0-9-]+\.([a-z0-9-]+)[:/]", head)
        office = m.group(1) if m else ""
    try:
        d = json.loads(text)
        forge = d["forge"]
        if not isinstance(forge, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        # the head too: a sign-in redirect (HTTP 302, no body) is said as one, not as no answer
        print("\n".join(x for x in (head, (text or "(no answer)")[:600]) if x))
        return 1
    who = f"{office}: " if office else ""
    vault = d.get("vault_error")
    print(f"{who}forge " + ("up" if forge.get("up") else f"DOWN — {flat(forge.get('detail'))}"))
    if vault:
        print(f"{who}the vault could not be read ({flat(vault)}): accounts and repositories are unknown")
    elif d.get("local_repos_error"):
        print(f"{who}repositories could not be read: {flat(d['local_repos_error'])}")
    elif not d.get("local_account"):
        print(f"{who}there is no local forge account")
    else:
        repos = d.get("local_repos") or []
        print(f"{who}{'100 or more' if len(repos) >= 100 else len(repos)} local repositories")
    # each part is counted, so none is told apart from unread: the vault is asked twice (app.py
    # api_overview), and a flap between the calls leaves `accounts` without its list
    connections = (d.get("accounts") or {}).get("connections") if isinstance(d.get("accounts"), dict) else None
    if not isinstance(connections, list):
        print(f"{who}accounts could not be read")
        connections = []
    elif not vault:
        print(f"{who}{len(connections)} accounts")
    for c in connections:
        state = str(c.get("state") or "")
        note = {"git_only": " (code only, not verified)"}.get(state, "")
        why = f" — {flat(c.get('reason'))}" if c.get("reason") else ""
        print(f"{who}account | {flat(c.get('label'))} | {flat(c.get('provider'))} | {state}{note}{why}")
    rows = (d.get("mirrors") or {}).get("mirrors") if isinstance(d.get("mirrors"), dict) else None
    if not isinstance(rows, list):
        print(f"{who}mirrors could not be read")
        rows = []
    else:
        print(f"{who}{len(rows)} mirrors")
    for m in rows:
        status = str(m.get("last_status") or "new")
        status = "not synced yet" if status == "new" else status
        why = f" — {flat(m.get('last_error'))}" if m.get("last_error") else ""
        print(f"{who}mirror | {flat(m.get('source_repo'))} → {flat(m.get('target_repo'))} | {status}{why} | "
              f"{age(m.get('last_run'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
