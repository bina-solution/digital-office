"""A stand-in for the docker CLI in tests: answers `ps` and `inspect` from FAKE_DOCKER_STATE (JSON)."""
import json
import os
import sys

with open(os.environ["FAKE_DOCKER_STATE"], encoding="utf-8") as f:
    s = json.load(f)
args = sys.argv[1:]
if s.get("fail"):
    print("Cannot connect to the Docker daemon at unix:///var/run/docker.sock", file=sys.stderr)
    sys.exit(1)
if args[:1] == ["ps"]:
    for name, state, status, project in s.get("ps", []):
        print(f"{name}\t{state}\t{status}\t{project}")
    sys.exit(0)
if args[:1] == ["inspect"] and "{{.Name}} {{.State.Pid}}" in args:
    for name in args[3:]:
        if name in s.get("pids", {}):
            print(f"/{name} {s['pids'][name]}")
    sys.exit(0)
if args[:1] == ["restart"]:
    name = args[-1]
    s.setdefault("restarted", []).append(name)
    with open(os.environ["FAKE_DOCKER_STATE"], "w", encoding="utf-8") as f:
        json.dump(s, f)
    if name in s.get("restart_fail", []):
        print(f"Error response from daemon: cannot restart {name}", file=sys.stderr)
        sys.exit(1)
    print(name)
    sys.exit(0)
if args[:1] == ["inspect"]:
    if s.get("ip"):
        print(s["ip"] + " ")
        sys.exit(0)
    print("Error: No such object", file=sys.stderr)
    sys.exit(1)
sys.exit(2)
