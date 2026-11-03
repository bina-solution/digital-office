#!/usr/bin/env python3
"""Drive the browser of a LINKED office — the same task protocol, over the link (lnk-037).

`bbox b42 task --office <office> …` reaches the linked office's browser42 through the link's door
instead of this office's own `docker exec`. The verb, the JSON, the slugs and the evidence files are
the same: an agent here drives the one browser there exactly as it drives a local one, and the office
that OWNS the browser keeps the single driver (its task runner serialises work and holds the queue).

Why the door and not a raw browser: the runner is the office's own semantics — task state, evidence
under its own `data/`, the watchdog, the tab group — and it is the one place that can hold "one
Chromium, one work command at a time". A remote Playwright/MCP client would be a second driver.

Where the door is: nobody declares it. browser42's manifest states its agent door (`agent_api_port`
8766) and who answers it (`agent_api_service`: its task runner); the serving office's compiler writes
both into its registry, and its link opens and publishes the door for every office it shares browser42
with — sharing everything (`"*"`) or naming the app alike (DGO-570, DGO-1009, DGO-1018). This office
posts `/v1/task` to that door through `bbox remote <office> <alias> /v1/task --api`, the platform's one
way to call a linked office's app. When the peer publishes no agent door, this refuses BY NAME —
`no_agent_door`, "<office> serves browser42, but publishes no agent door for it" — rather than
pretending the browser is busy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = "browser42"
TIMEOUT = int(os.environ.get("BROWSER42_TASK_CLIENT_SECONDS", "340"))


def die(code: str, message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(json.dumps({"ok": False, "error": {"code": code, "message": message}}))
    raise SystemExit(2)


def state() -> dict:
    try:
        import yaml  # noqa: PLC0415 — the repo's own parser, present wherever bbox runs
    except ImportError:  # pragma: no cover
        die("no_yaml", "python3-yaml is missing — `bbox b42` cannot read platform.state.yaml")
    path = REPO / "platform.state.yaml"
    try:
        return yaml.safe_load(path.read_text()) or {}
    except OSError as e:
        die("no_state", f"platform.state.yaml is unreadable ({e})")


def door(office: str) -> str:
    """The alias the peer serves browser42 under, or a refusal that names what is missing.

    The call itself is `bbox remote`'s (`main`), the way EVERY other caller of a linked office's app
    reaches it (the console's backend too): `http://<alias>.<office>:<door><path>`, where `<door>` is
    the port the serving office published and the Host header picks the app behind the link's one
    door. That is the platform's one shape for reaching another office's app.

    browser42 needs no exception to it. Its task runner is a port of its own (8766) rather than a
    route of the UI Caddy serves on 80, so the door to it is a SECOND door the same link opens — and
    that door is the app's own: its manifest states the port and the service that answers it, the
    compiler writes both into the serving office's registry, and `_serve_doors` opens it for every
    office the app is shared with, wildcard or named (DGO-32, DGO-570, DGO-1018). An office whose
    dgo-extend predates that publishes no agent door, the one gap left — so the refusal names it
    instead of pretending the browser is busy.
    """
    blocks = state().get("remote") or state().get("serve") or {}
    entries = list(blocks.values()) if isinstance(blocks, dict) else list(blocks)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        names = {str(entry.get("office") or ""), str(entry.get("link") or "")}
        label = entry.get("label")
        if isinstance(label, dict):
            names |= {str(label.get("he") or ""), str(label.get("en") or "")}
        if office.lower() not in {n.lower() for n in names if n}:
            continue
        row = next((a for a in (entry.get("apps") or [])
                    if isinstance(a, dict) and str(a.get("app") or "") == APP), None)
        if row is None:
            die("not_served", f"{office} does not serve {APP} to this office — "
                              f"`bbox dgo link status` says what it does serve")
        port = int(row.get("agent_api_port") or 0)
        if not port:
            die("no_agent_door",
                f"{office} serves {APP}, but publishes no agent door for it: its dgo-extend predates "
                f"the release that shares an app's API and CLI with the app itself (DGO-570, DGO-1009, "
                f"DGO-1018). Its browser can be watched from here and not driven until {office} runs "
                f"that release (`bbox run` there, which renders its registry and rebuilds its "
                f"dgo-extend) — or this office has not pulled {office}'s catalog since it did "
                f"(`bbox dgo link status` says when it last did). Nothing has to be declared by hand "
                f"in either office.")
        # the office by its own id — what `bbox remote` resolves by — whatever name it was asked by
        return str(entry.get("office") or entry.get("link") or office), str(row.get("alias") or APP)
    return die("unknown_office", f"{office!r} is in neither `remote:` nor `serve:` in "
                                 f"platform.state.yaml — link it and converge first")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        die("usage", "usage: bbox b42 task --office <office> <verb> [args…]")
    office, alias = door(argv[0])
    rest = argv[1:]
    request_id = os.environ.get("BROWSER42_REQUEST_ID") or uuid.uuid4().hex
    body = json.dumps({"argv": rest, "requestId": request_id})
    # ONE way to call a linked office's app: `bbox remote` (scripts/remote.py). It builds the address
    # from what the serving office published, makes the request from INSIDE the office network when
    # this host cannot resolve the link's names, and presents the link's own token from the vault.
    # This file posted by itself instead, from the host — on the Mac that is the engine guest, where
    # neither `<alias>.<office>` nor the tunnel address answers (2026-10-22: `runner_unavailable`,
    # Connection refused, while `bbox remote` reached the same door).
    # The body travels on stdin (`-d @-`): one argument is capped at 128 KiB, and a `fill` value or a
    # requirements file can be long.
    try:
        p = subprocess.run([sys.executable, str(REPO / "scripts" / "remote.py"), office, alias,
                            "/v1/task", "--api", "-d", "@-", "--timeout", str(TIMEOUT), "--json"],
                           input=body, capture_output=True, text=True, errors="replace",
                           timeout=TIMEOUT + 120)
    except subprocess.TimeoutExpired:
        die("runner_unavailable", f"`bbox remote {office} {alias}` did not return in {TIMEOUT + 120}s")
    except OSError as e:
        die("runner_unavailable", f"`bbox remote` could not be started ({e})")
    try:
        answer = json.loads(p.stdout)
    except ValueError:
        # remote.py exits 2 for what this office does not declare, 3 for what it cannot reach
        code = "not_served" if p.returncode == 2 else "runner_unavailable"
        die(code, f"`bbox remote {office} {alias}` exited {p.returncode} — "
                  f"{(p.stderr or p.stdout).strip()[-400:] or 'with nothing said'}")
    status, text = int(answer.get("status") or 0), str(answer.get("body") or "")
    if not text.strip():
        # A link answers 502 with no body when the serving office's door reaches no listener.
        die("door_unanswered", f"{office}'s door to its browser answered HTTP {status} with no body "
                               f"— on {office}, nothing listens behind {answer.get('url')}. A serving "
                               f"office whose dgo-extend predates DGO-1018 delivers the agent port to the "
                               f"screen's service, where nothing answers it: `bbox run` there takes the "
                               f"release")
    sys.stdout.write(text)
    return 0 if status < 400 else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
