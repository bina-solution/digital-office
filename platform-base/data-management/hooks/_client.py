"""Shared transport for the `bbox data` verbs. NOT shared logic — there is none here to share.

    Every verb is an HTTP call to the data-management service. The service owns the logic; these
    hooks own presentation and nothing else. If you find yourself computing an inventory, a size or
    a coverage verdict in this directory, it belongs in inventory.py instead — the whole point of
    the app is that the CLI and the web UI cannot disagree because there is only one implementation
    for them both to call.

WHY IT TALKS THROUGH `docker exec` RATHER THAN THE ROUTE

    The traefik route is behind authentik forwardAuth, so a CLI hitting data-management.localhost
    would need an SSO session — a login prompt in a shell script. Publishing a host port instead
    would put an unauthenticated backup/restore API on the host's network. Executing the request
    INSIDE the container needs neither: the docker socket is already the trust boundary the operator
    crossed to run bbox at all.

    The request is issued by python, not curl. The image is python:3.12-slim with only the docker CLI
    and postgres client added; curl is not in it, and every verb failed with "executable file not
    found". Adding curl to carry one GET would be a package for something the interpreter already
    does — and the interpreter is guaranteed present, since it is what runs the service.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def container() -> str:
    dn = os.environ.get("DEPLOYMENT_NAME")
    if not dn:
        # lib.sh exports DEPLOYMENT_NAME for hooks; when run bare, read it from .env the same way.
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        try:
            for line in open(os.path.join(repo, ".env"), encoding="utf-8", errors="replace"):
                if line.startswith("DEPLOYMENT_NAME="):
                    dn = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except OSError:
            pass
    return f"data-management-{dn or 'bina-deployment'}"


def call(method: str, path: str, timeout: int = 600):
    """One HTTP call, executed inside the service container. Returns parsed JSON."""
    c = container()
    url = f"http://localhost:8080{path}"
    # Written as a -c program rather than a file so the hook needs nothing copied into the container.
    prog = (
        "import sys,urllib.request,urllib.error\n"
        "r=urllib.request.Request(sys.argv[1],method=sys.argv[2])\n"
        "try:\n"
        "    sys.stdout.write(urllib.request.urlopen(r,timeout=float(sys.argv[3])).read().decode())\n"
        "except urllib.error.HTTPError as e:\n"
        # An API error body is the most useful thing the CLI can show, so it goes to stdout and the
        # exit code carries the failure. Discarding it would leave the operator with a bare 500.
        "    sys.stdout.write(e.read().decode('utf-8','replace')); sys.exit(22)\n"
    )
    cmd = ["docker", "exec", "-i", c, "python", "-c", prog, url, method, str(timeout)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        if r.returncode == 22:                            # HTTP error: the body is the message
            body = (r.stdout or b"").decode("utf-8", "replace")
            try:
                body = json.loads(body).get("detail", body)
            except json.JSONDecodeError:
                pass
            sys.exit(f"[bbox data] service refused the request:\n{str(body)[:800]}")
        if "No such container" in err or "is not running" in err:
            sys.exit(f"[bbox data] the data-management service is not running ({c}).\n"
                     f"           start it with:  ./bbox run\n"
                     f"           (the CLI is a client of that service - there is no offline mode,\n"
                     f"            deliberately, so the CLI and the UI cannot drift apart)")
        sys.exit(f"[bbox data] transport failed: {err or r.returncode}")
    body = (r.stdout or b"").decode("utf-8", "replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        sys.exit(f"[bbox data] service returned non-JSON:\n{body[:800]}")
