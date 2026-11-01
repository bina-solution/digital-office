#!/usr/bin/env python3
"""external-resource-lint — gate G24: `external: true` means something else provides it.

    python3 scripts/refactor/external-resource-lint.py

WHY THIS GATE EXISTS

`apps/chat` declared `wa_media` as `external: true` — the only external VOLUME in the
repo; every other volume is compose-managed. `external` is a claim that the resource has a
lifecycle outside this project and something else creates it. Nothing did.

Locally it never showed, because the volume had been created by hand months earlier and simply
existed. On a fresh machine the install loaded all 26 images, created 20-odd managed volumes, and
then stopped dead:

    external volume "wa_media" not found

The same app binds `./data` for its other storage, so it was not even internally consistent — one
app quietly opting out of the convention, invisible until a machine without the leftover state
tried it.

THE RULE

An `external: true` volume must be listed in KNOWN_EXTERNAL, which names what actually provides it.
Anything else should be compose-managed: compose creates managed volumes automatically, so the
"external" keyword buys nothing and costs a failed install.

Networks are checked the same way. `traefik-network` is legitimately external — it is created
out-of-band before the stack starts, by `bbox run` and by the installer, precisely so apps can join
a network none of them owns.
"""
import pathlib
import sys

try:
    import yaml
except ImportError:
    print("external-resource-lint: pyyaml required", file=sys.stderr)
    raise SystemExit(2)

REPO = pathlib.Path(__file__).resolve().parents[2]

# name -> who creates it. An entry here is a promise that something really does.
KNOWN_EXTERNAL = {
    "traefik-network": "created out-of-band by `bbox run` and by the installer, so every app can "
                       "join a network no single app owns",
}


def main() -> int:
    problems = []
    for compose in sorted(REPO.glob("apps/*/docker-compose.yml")) + sorted(
        REPO.glob("platform-base/*/docker-compose.yml")
    ):
        try:
            doc = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append((compose, "<file>", f"does not parse: {exc}"))
            continue
        rel = compose.relative_to(REPO).as_posix()
        for kind in ("volumes", "networks"):
            for name, spec in (doc.get(kind) or {}).items():
                if not isinstance(spec, dict) or not spec.get("external"):
                    continue
                if name not in KNOWN_EXTERNAL:
                    problems.append((rel, kind[:-1], name))

    if problems:
        print("external-resource-lint: FAIL — `external: true` on something nothing provides\n")
        for rel, kind, name in problems:
            print(f"  {rel}")
            print(f"      {kind} '{name}' is external, but nothing in the platform creates it.")
            print(f"      A fresh install stops with: external {kind} \"{name}\" not found")
        print("\nDrop `external: true` so compose manages it (it creates managed volumes itself),")
        print("or add it to KNOWN_EXTERNAL naming what actually provides it.")
        return 1

    print(f"OK — every external resource is one the platform actually provides "
          f"({', '.join(sorted(KNOWN_EXTERNAL))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
