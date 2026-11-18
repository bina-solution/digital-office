#!/usr/bin/env python3
"""context — what an agent, or a person, needs to know about this office or one of its apps, built now from the
office itself: each app's own brief and manifest, joined with what runs at the moment of asking (DGO-1960, DGO-1961).

    ./bbox context              # this office: its apps, which of them run, the commands of each
    ./bbox context <app>        # one app: what it is, whether it runs here, its addresses, its commands, its brief,
                                #   and what its own `hooks/context` says live, when it has one
    ./bbox context [<app>] --json

Nothing here is written by hand about an installation. The brief is the app's own (`agent.context` in its app.json —
the file the compiler also gives the office agent, .generated/registry/agent-context.md); what it is, its addresses
and its commands come from its manifest and its hooks; whether it runs, from this office's state and its engine.
An app that has more to say about itself live ships `hooks/context`, and its output is added as it is. The network
of offices is `./bbox computers map`. Exit 0, or 2 for an app this checkout does not have.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
HOOK_TIMEOUT_S = 30


def _reconcile():
    """The compiler, for its own catalogue and enabled set — never a second reading of the manifests."""
    spec = importlib.util.spec_from_file_location("reconcile_context", REPO / "platform" / "manager" / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_context"] = mod
    spec.loader.exec_module(mod)
    return mod


def _state(rc) -> dict:
    """The office's choices as they are on disk; a checkout with none yet has chosen nothing (read, never made here)."""
    try:
        st = yaml.safe_load(rc.STATE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    apps = st.get("apps") or {}
    for old_id, new_id in rc.LEGACY_APP_IDS.items():   # the compiler's own reading of a renamed app (load_state)
        if old_id in apps and new_id not in apps:
            apps[new_id] = apps.pop(old_id)
    return {**st, "apps": apps}


def _services(a: dict) -> set:
    comp = a["_dir"] / (a.get("compose") or "docker-compose.yml")
    try:
        doc = yaml.safe_load(comp.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return set()
    return set((doc.get("services") or {}).keys())


def _engine() -> list:
    """[{service, project, state, health}] of every container this engine has; [] when docker does not answer."""
    try:
        out = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"], capture_output=True, text=True,
                             timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        try:
            c = json.loads(line)
        except ValueError:
            continue
        lab = dict(kv.split("=", 1) for kv in (c.get("Labels") or "").split(",") if "=" in kv)
        status = c.get("Status") or ""
        rows.append({"service": lab.get("com.docker.compose.service", ""), "project": lab.get("com.docker.compose.project", ""),
                     "running": (c.get("State") or "") == "running",
                     "health": "unhealthy" if "(unhealthy)" in status else "healthy" if "(healthy)" in status else ""})
    return rows


def _own_project(engine: list) -> str:
    counts: dict = {}
    for r in engine:
        if r["running"] and r["project"]:
            counts[r["project"]] = counts.get(r["project"], 0) + 1
    return max(counts, key=counts.get) if counts else ""


VERB_ENDINGS = (".py", ".mjs", ".sh")


def _commands(a: dict) -> list:
    """[(verb, its one-line help)] — the app's verbs as bbox's own `app_verbs` lists them (every entry of hooks/ but
    __pycache__, its .py/.mjs/.sh ending dropped, once each), so a verb printed here is one `./bbox <app> <verb>` runs;
    the help is the `#:` line of the file the verb resolves to."""
    hooks = a["_dir"] / "hooks"
    if not hooks.is_dir():
        return []
    verbs = sorted({next((p.name[: -len(e)] for e in VERB_ENDINGS if p.name.endswith(e)), p.name)
                    for p in hooks.iterdir() if p.name != "__pycache__" and not p.name.startswith(".")})
    out = []
    for v in verbs:
        help_ = ""
        for f in [hooks / v] + [hooks / (v + e) for e in VERB_ENDINGS]:
            if not f.is_file():
                continue
            try:
                help_ = next((l[2:].strip() for l in f.read_text(encoding="utf-8", errors="replace").splitlines()[:8]
                              if l.startswith("#:")), "")
            except OSError:
                pass
            break
        out.append((v, help_))
    return out


def _brief(a: dict) -> str:
    rel = ((a.get("agent") or {}).get("context") or "").strip()
    try:
        return (a["_dir"] / rel).read_text(encoding="utf-8") if rel else ""
    except OSError:
        return ""


def _addresses(a: dict) -> list:
    return [r.get("host") for r in (a.get("routing") or []) if isinstance(r, dict) and r.get("host")]


def _text(v) -> str:
    return v.get("en") or v.get("he") or "" if isinstance(v, dict) else str(v or "")


def app_context(aid: str, a: dict, enabled: set, engine: list, project: str, live: bool = True) -> dict:
    svcs = _services(a)
    # only this office's deployment: another deployment on the same engine runs services of the same names. With
    # nothing running there is no deployment to name, and nothing is counted rather than everything.
    mine = [r for r in engine if r["service"] in svcs and project and r["project"] == project]
    row = {"app": aid, "title": a.get("title"), "summary": a.get("summary"), "layer": a.get("layer"),
           "enabled": aid in enabled, "running": sum(r["running"] for r in mine), "containers": len(mine),
           "unhealthy": sum(r["health"] == "unhealthy" for r in mine), "addresses": _addresses(a),
           "commands": [{"verb": v, "help": h} for v, h in _commands(a)]}
    hook = next((p for p in [a["_dir"] / "hooks" / ("context" + e) for e in ("",) + VERB_ENDINGS] if p.is_file()), None)
    if live and hook:
        row["live"] = _ask_hook(hook)
    return row


def _ask_hook(hook: Path) -> str:
    """What the app's own hooks/context prints, run as bbox would run a plain app's hook (no instance in the air), in
    its own process group so a child left holding the pipe dies with it at the timeout."""
    cmd = ["python3", str(hook)] if hook.suffix == ".py" else ["node", str(hook)] if hook.suffix == ".mjs" else ["bash", str(hook)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("DGO_INSTANCE_")}
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO, env=env,
                             start_new_session=True)
    except OSError as e:
        return f"its hooks/context could not start: {e}"
    try:
        out, err = p.communicate(timeout=HOOK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        return f"its hooks/context did not answer in {HOOK_TIMEOUT_S} s"
    text = (out or "").strip() or (err or "").strip()
    return text if p.returncode == 0 else f"its hooks/context failed (exit {p.returncode}): {text}"


def render_app(r: dict, brief: str) -> str:
    t, s = r["title"] or {}, r["summary"] or {}
    lines = [f"context — {r['app']}: {_text(t)}" + (f" · {t.get('he')}" if isinstance(t, dict) and t.get("he") else ""),
             f"   what      {_text(s)}",
             f"   here      {'enabled' if r['enabled'] else 'not enabled'} · {r['running']} running / {r['containers']} "
             f"container(s)" + (f" · {r['unhealthy']} UNHEALTHY" if r["unhealthy"] else "") + f" · layer {r['layer']}"]
    if r["addresses"]:
        lines.append("   at        " + ", ".join(r["addresses"]) + "  (a host; the office's domain completes it)")
    for c in r["commands"]:
        lines.append(f"   ./bbox {r['app']} {c['verb']:<12} {c['help']}")
    if r.get("live"):
        lines += ["", "== what it says about itself now (hooks/context)", r["live"]]
    if brief:
        lines += ["", "== its brief (agent.context)", brief.strip()]
    return "\n".join(lines)


def render_office(rows: list, office: str) -> str:
    on = [r for r in rows if r["enabled"]]
    lines = [f"context — office {office or 'this office'}, read at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}: "
             f"{len(on)} app(s) enabled, {sum(1 for r in on if r['running'])} running"]
    for r in sorted(on, key=lambda r: r["app"]):
        state = f"{r['running']}/{r['containers']}" + (" UNHEALTHY" if r["unhealthy"] else "")
        verbs = ", ".join(c["verb"] for c in r["commands"][:6]) + (" …" if len(r["commands"]) > 6 else "")
        lines.append(f"   {r['app']:<20} {state:<12} {_text(r['title'])[:34]:<34} {verbs}")
    lines += ["", "one app: ./bbox context <app> · the network of offices: ./bbox computers map · every command: ./bbox help"]
    return "\n".join(lines)


def main(argv: list) -> int:
    if any(a in ("-h", "--help") for a in argv[1:]):
        print(__doc__.split("\n\n")[1])
        return 0
    args = [a for a in argv[1:] if not a.startswith("-")]
    as_json = "--json" in argv
    rc = _reconcile()
    cat = rc.load_catalog()
    enabled = rc.enabled_ids(_state(rc), cat)
    engine = _engine()
    project = _own_project(engine)
    if args:
        aid = args[0]
        if aid not in cat:
            print(f"context: no app '{aid}' in this checkout (./bbox apps list)", file=sys.stderr)
            return 2
        row = app_context(aid, cat[aid], enabled, engine, project)
        brief = _brief(cat[aid])
        print(json.dumps({**row, "brief": brief}, ensure_ascii=False, indent=1) if as_json else render_app(row, brief))
        return 0
    rows = [app_context(aid, a, enabled, engine, project, live=False) for aid, a in sorted(cat.items())]
    try:
        office = rc._envfile_value("DGO_OFFICE_ID") or ""
    except Exception:  # noqa: BLE001 — the office's name is a heading, never a reason to fail
        office = ""
    print(json.dumps({"office": office, "apps": rows}, ensure_ascii=False, indent=1) if as_json else render_office(rows, office))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
