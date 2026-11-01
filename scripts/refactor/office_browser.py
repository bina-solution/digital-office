#!/usr/bin/env python3
"""office_browser — how a gate looks at a RUNNING office with a browser. Not a gate.

Two gates measure rendered pages — G79 (the desktop's dock) and G81 (desktop mode's windows) — and
both need the same two answers; the first had them inline and the second was about to copy them:

  lane()                    how a Playwright script is run on this machine: inside the office's
                            capture image when it exists (it is ON the docker network), else with
                            this host's own playwright — or not at all, and why.
  url(service, port, inside)
                            where that browser reaches a service of THIS office: by its name on the
                            docker network from inside the image, by its container's address from
                            the host (a host's browser is not on that network: the name resolves
                            only inside it, and a measurement aimed at it failed in six seconds on
                            every run).
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
IMAGE = "ui-capture:latest"


def lane() -> tuple[list[str] | None, bool, str]:
    """(the command a script path is appended to, is it inside the image, why there is none)."""
    if shutil.which("docker") and _image(IMAGE):
        return (["docker", "run", "--rm", "--network", "traefik-network", "-v", f"{REPO}:/repo",
                 "-w", "/repo", "-e", "UI_CHROME_BIN=/usr/bin/chromium", IMAGE, "python3"], True, "")
    try:
        import playwright  # noqa: F401
    except ImportError:
        return None, False, f"no {IMAGE} image and no playwright here"
    return [sys.executable], False, ""


def url(service: str, port: int, inside: bool) -> str | None:
    if inside:
        return f"http://{service}:{port}/"
    at = address(service)
    return f"http://{at}:{port}/" if at else None


def address(service: str) -> str | None:
    """A service's container address on the docker network, for a browser on the host.

    Asked by the compose SERVICE, of THIS checkout. Not by name: a container's name carries the
    deployment's, which is another one on every machine — a lookup that spelled one laptop's said
    "no live console reachable" beside a running console on every other office (hp-laptop,
    2026-10-06) — and docker renames a container it could not cleanly replace to `<hash>_<name>`,
    so the undecorated one is preferred. Not by service alone either: one engine may carry a
    neighbour office with a console of its own, so when the checkout's label finds nothing the
    deployment's name is asked for, and an office that is not this one is never answered with.
    Three tools each kept a copy of this (the dock gate, the live map, the parity tool); it is here.
    """
    def ask(*more: str) -> list[str]:
        try:
            return subprocess.run(["docker", "ps", "--format", "{{.Names}}", "--filter",
                                   f"label=com.docker.compose.service={service}", *more],
                                  capture_output=True, text=True, timeout=60).stdout.split()
        except (OSError, subprocess.TimeoutExpired):
            return []
    names = ask("--filter", f"label=com.docker.compose.project.working_dir={REPO}")
    if not names:
        deployment = ""
        try:
            for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("DEPLOYMENT_NAME="):
                    deployment = line.split("=", 1)[1].strip()
        except OSError:
            pass
        names = [n for n in ask() if deployment and n.endswith("-" + deployment)]
    if not names:
        return None
    names.sort(key=lambda n: (bool(re.match(r"^[0-9a-f]{12}_", n)), n))
    try:
        ip = subprocess.run(["docker", "inspect", "-f",
                             "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", names[0]],
                            capture_output=True, text=True, timeout=60).stdout.split()
        return ip[0] if ip else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _image(tag: str) -> bool:
    try:
        return subprocess.run(["docker", "image", "inspect", tag], capture_output=True,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
