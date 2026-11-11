#!/usr/bin/env python3
"""no-phone-home-lint — gate G99: an office does not announce itself to its vendors on every start.

    python3 scripts/refactor/no-phone-home-lint.py [--self-test]

WHY THIS EXISTS. Measured 2026-11-09 (DGO-1596): the edge asked `update.traefik.io` (and, on the
office where it was captured, `api.github.com`) whether a newer build exists on every start, and
Plane's object store asked `dl-1.min.io` the same — both unconfigured defaults of the vendor, both
leaving the office's own network to a third party, neither answer used by anything here. The image of
each is pinned by tag (G15) and an office that moves a version does it in a commit; a process that
learns about a release by itself is a channel nobody asked for.

Traefik cannot be talked out of the check by a static config file: with `--configFile` present this
engine IGNORED `--global.checkNewVersion=false` (measured 2026-11-09 — the effective static config
still read `"checkNewVersion": true`), while with the flags alone the effective config is
`"global": {}`. So the rule is about the flag list, and this gate reads the flag list.

WHAT IT READS, and nothing else:
  * `platform-base/traefik/docker-compose.yml` — `--global.checkNewVersion=false` and
    `--global.sendAnonymousUsage=false` must both be in the service's command. A missing flag is a
    finding; `=true` is a finding.
  * every `apps/*/docker-compose.yml` and `platform-base/*/docker-compose.yml` that runs a MinIO
    (`image:` naming `minio`) must set `MINIO_UPDATE: off` (or `MINIO_UPDATE=off` in a list-form
    environment). MinIO's own default is to look for an update on every start.

It does NOT enumerate "every vendor that might phone home" — a list nobody maintains is a list that
lies. It holds the two that were measured, and the docstring says why those two.
"""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

TRAEFIK = REPO / "platform-base/traefik/docker-compose.yml"
TRAEFIK_FLAGS = ("--global.checkNewVersion=false", "--global.sendAnonymousUsage=false")


def compose_files():
    return sorted(REPO.glob("apps/*/docker-compose.yml")) + \
        sorted(REPO.glob("platform-base/*/docker-compose.yml"))


def traefik_findings(text):
    out = []
    for flag in TRAEFIK_FLAGS:
        if flag in text:
            continue
        name = flag.split("=", 1)[0]
        if re.search(rf"{re.escape(name)}(=|:|$)", text):
            out.append(f"{TRAEFIK.relative_to(REPO)}: {name} is set to something else (must be false)")
        else:
            out.append(f"{TRAEFIK.relative_to(REPO)}: {name}=false is missing from the command")
    return out


def minio_findings(path, text):
    """A MinIO service must switch its update check off."""
    if not re.search(r"image:\s*\S*minio", text, re.I):
        return []
    if re.search(r"MINIO_UPDATE\s*[:=]\s*[\"']?off", text):
        return []
    return [f"{path.relative_to(REPO)}: a MinIO service without MINIO_UPDATE=off — it asks "
            f"dl.min.io for an update on every start"]


def scan(files):
    """(findings, read) over [(path, text)] — the two halves, no stack, no network."""
    found = []
    for path, text in files:
        if path == TRAEFIK:
            found += traefik_findings(text)
        found += minio_findings(path, text)
    return found, len(files)


def self_test():
    ok = 0
    good = ("command:\n    - --entrypoints.web.address=:80\n"
            "    - --global.checkNewVersion=false\n    - --global.sendAnonymousUsage=false\n")
    assert traefik_findings(good) == []
    ok += 1
    assert traefik_findings("command:\n    - --entrypoints.web.address=:80\n") == [
        f"{TRAEFIK.relative_to(REPO)}: --global.checkNewVersion=false is missing from the command",
        f"{TRAEFIK.relative_to(REPO)}: --global.sendAnonymousUsage=false is missing from the command"], "both missing"
    ok += 1
    assert len(traefik_findings("--global.checkNewVersion=true\n--global.sendAnonymousUsage=false\n")) == 1, "true is a finding"
    ok += 1
    assert minio_findings(TRAEFIK, "image: pgsty/minio:RELEASE.2026-08-01\n") != [], "minio without the switch"
    ok += 1
    assert minio_findings(TRAEFIK, "image: pgsty/minio:RELEASE.2026-08-01\n    environment:\n      MINIO_UPDATE: off\n") == []
    ok += 1
    assert minio_findings(TRAEFIK, "image: pgsty/minio:RELEASE.2026-08-01\n    environment:\n      - MINIO_UPDATE=off\n") == []
    ok += 1
    assert minio_findings(TRAEFIK, "image: postgres:17\n") == [], "a non-minio service is not judged"
    ok += 1
    real = [(p, p.read_text(encoding="utf-8")) for p in [TRAEFIK] + compose_files()]
    if len(real) < 10:
        raise SystemExit(f"self-test FAILED: read {len(real)} compose file(s) — that is not this tree")
    ok += 1
    print(f"self-test OK — {ok} checks")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    files = [(p, p.read_text(encoding="utf-8")) for p in dict.fromkeys([TRAEFIK] + compose_files())]
    found, read = scan(files)
    if found:
        print("AN OFFICE THAT ANNOUNCES ITSELF TO ITS VENDORS ON EVERY START")
        print("-" * 78)
        for line in found:
            print(f"  {line}")
        print("-" * 78)
        print("  -> traefik: put `- --global.checkNewVersion=false` and "
              "`- --global.sendAnonymousUsage=false` in its command.\n"
              "     minio: `MINIO_UPDATE: off` in the service's environment.\n"
              "     Neither answer is used here; the version is a commit (G15).")
        print(f"\nG99 FAIL — {len(found)} finding(s) over {read} compose file(s).")
        return 1
    print(f"G99 PASS — the edge and every MinIO start without asking a vendor for news "
          f"({read} compose file(s) read).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
