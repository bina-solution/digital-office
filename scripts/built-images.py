#!/usr/bin/env python3
"""Read a `docker compose config --format json` on stdin, print every image this repo BUILDS.

Compose defaults a built service's image to <project>-<service>, but a service may override it
with an explicit `image:`. A sweep that greps for the default prefix therefore misses those —
which is exactly how incoming-documents-local and my-docs-local survived a "delete every
first-party image" rebuild.
"""
import json, sys

# LF endings on every platform. print() emits CRLF on Windows, so each name reached `docker rmi`
# with a trailing carriage return: "invalid reference format" fifteen times over, while the
# pipeline still exited 0 and the clean rebuild looked like it had wiped everything.
sys.stdout.reconfigure(newline="\n")

cfg = json.load(sys.stdin)
# The project prefix comes from compose itself rather than a hardcoded "deployment-hacohen-":
# compose derives it from the project directory, so it differs on any clone in another folder.
project = cfg.get("name") or "deployment-hacohen"
for name, svc in (cfg.get("services") or {}).items():
    if svc.get("build"):
        print(svc.get("image") or f"{project}-{name}")
