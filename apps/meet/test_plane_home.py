"""test_plane_home — where Meet files its recordings (DGO-1649), by running hooks/prepare on throwaway trees.

A CLIENT's office that runs its own Plane files them THERE (http://project-pln:80), with the office's own key named
by its vault instance (MEET_PLANE_KEY_VAULT=plane_local_api_token-local — a name, never the key), even when a link
publishes a herd office's Plane; the herd's own offices keep the herd's rule; an office with no Plane of its own
gets no vault line; an address an operator wrote is never touched. The hook only rewrites the tree's .env (nothing
else runs: no firewall, no docker), so it is run whole, as `bbox run` runs it.
Run: python3 apps/meet/test_plane_home.py   (needs bash; PyYAML is optional, as for the hook)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FAIL: list[str] = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def tree(office: str, here: list[str], remotes: dict[str, str], env_extra: str = "") -> Path:
    root = Path(tempfile.mkdtemp(prefix="meet-plane-"))
    (root / "apps/meet/hooks").mkdir(parents=True)
    shutil.copy(REPO / "apps/meet/hooks/prepare", root / "apps/meet/hooks/prepare")
    (root / "scripts").mkdir()
    shutil.copy(REPO / "scripts/herd_home.py", root / "scripts/herd_home.py")
    (root / "apps/computers").mkdir(parents=True)
    shutil.copy(REPO / "apps/computers/herd.yaml", root / "apps/computers/herd.yaml")
    reg = root / ".generated/registry"
    reg.mkdir(parents=True)
    (reg / "office.apps.json").write_text(json.dumps({"apps": [{"app": a} for a in here]}))
    for o, alias in remotes.items():
        (reg / f"remote.{o}.{alias}.json").write_text(json.dumps({"app": "project-pln", "alias": alias, "link_port": 9003}))
    (root / "platform.state.yaml").write_text("apps:\n  meet: { state: enabled }\n")
    (root / ".env").write_text(f"DGO_OFFICE_ID={office}\nDEPLOYMENT_DOMAIN=localhost\n{env_extra}")
    return root


def run(root: Path) -> dict:
    r = subprocess.run(["bash", str(root / "apps/meet/hooks/prepare")], capture_output=True, text=True, timeout=60)
    env = {}
    for ln in (root / ".env").read_text().splitlines():
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.split("=", 1)
            env[k.strip()] = v
    env["_rc"], env["_out"] = r.returncode, r.stdout + r.stderr
    shutil.rmtree(root, ignore_errors=True)
    return env


def main() -> int:
    # Exampleu: a client's office (not in the herd), its own Plane enabled, no link publishing one
    e = run(tree("exampleu", ["project-pln", "meet"], {}))
    check(e["_rc"] == 0, f"the hook runs: {e['_out'][-200:]}")
    check(e.get("MEET_PLANE_API_URL") == "http://project-pln:80" and e.get("MEET_PLANE_API_AUTO") == "1",
          f"a client's own Plane is where its recordings go: {e.get('MEET_PLANE_API_URL')!r}")
    check(e.get("MEET_PLANE_KEY_VAULT") == "plane_local_api_token-local",
          f"…asked with the office's own key, named by its vault instance: {e.get('MEET_PLANE_KEY_VAULT')!r}")
    check(not e.get("MEET_PLANE_API_KEY"), "…and no key is written into .env")

    # the same client office, linked to a herd office that publishes ITS Plane: the client's own still wins
    e = run(tree("exampleu", ["project-pln", "meet"], {"hp-laptop": "plane"}))
    check(e.get("MEET_PLANE_API_URL") == "http://project-pln:80",
          f"a herd office's Plane on the link never takes a client's recordings: {e.get('MEET_PLANE_API_URL')!r}")

    # a herd office (the MacBook) whose Plane runs on another office: the herd's rule, and no vault line
    e = run(tree("macbook", ["meet"], {"hp-laptop": "plane"}))
    check(e.get("MEET_PLANE_API_URL", "").startswith("http://plane.hp-laptop:"),
          f"a herd office keeps the herd's Plane: {e.get('MEET_PLANE_API_URL')!r}")
    check(not e.get("MEET_PLANE_KEY_VAULT"), f"…and no vault instance: {e.get('MEET_PLANE_KEY_VAULT')!r}")

    # a client's office without a Plane of its own: nothing to file into, and no line written for nothing
    e = run(tree("examplef", ["meet"], {}))
    check("MEET_PLANE_KEY_VAULT" not in e, "an office with no Plane of its own gets no MEET_PLANE_KEY_VAULT line")

    # an address an operator wrote (no AUTO mark) is never touched, nor is a vault line added beside it
    e = run(tree("exampleu", ["project-pln", "meet"], {}, "MEET_PLANE_API_URL=http://plane.example:9000\n"))
    check(e.get("MEET_PLANE_API_URL") == "http://plane.example:9000" and "MEET_PLANE_KEY_VAULT" not in e,
          f"an operator's address stays as written: {e.get('MEET_PLANE_API_URL')!r} {e.get('MEET_PLANE_KEY_VAULT')!r}")

    # the client's office stops running its Plane: the address and the vault line this hook wrote go with it
    root = tree("exampleu", ["meet"], {}, "MEET_PLANE_API_URL=http://project-pln:80\nMEET_PLANE_API_AUTO=1\n"
                                        "MEET_PLANE_KEY_VAULT=plane_local_api_token-local\n")
    e = run(root)
    check(not e.get("MEET_PLANE_API_URL") and not e.get("MEET_PLANE_KEY_VAULT"),
          f"its Plane gone, the hook's own lines go: {e.get('MEET_PLANE_API_URL')!r} {e.get('MEET_PLANE_KEY_VAULT')!r}")

    if FAIL:
        print(f"{len(FAIL)} check(s) failed")
        return 1
    print("test_plane_home: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
