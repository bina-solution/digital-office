"""The oracle of packaging/dgo/internal/console: platform-base/console/app.py, UNMODIFIED, answering
through Flask's own test client — what the Go server is compared with.

The app's source is executed as a fresh module whose `__file__` lies inside a fixture root, so its
ROOT, STATIC and modules.yaml are the fixture's (exactly as the image lays them out: /app/app.py,
/app/static, /app/modules.yaml) and nothing in platform-base/console is written — not even bytecode.

stdin : {"app": <path of app.py>, "root": <fixture root>, "env": {name: value},
         "requests": [{"method": ..., "path": ..., "headers": [[name, value], ...]}]}
stdout: {"versions": {...}, "responses": [{"status", "headers": [[name, value], ...],
         "body": <base64>, "decoded": <base64 of the body with its Content-Encoding undone>}],
         "image_shell": <app.py's own _shell_build() as its Linux image runs it — see below>}
"""
import base64
import importlib.metadata
import json
import mimetypes
import os
import posixpath
import sys
import types


def main():
    spec = json.load(sys.stdin)
    # Only what the spec says reaches the app: no telemetry DSN from the developer's shell, and the
    # two planes app.py could dial point at a port nothing listens on — the oracle never asks the
    # network anything (the routes that would are proxied by the Go server, not compared).
    for name in ("SENTRY_DSN", "BUILD_VERSION", "GENERATED_REGISTRY", "CONSOLE_PEERS_DIR", "PLATFORM_SERVICES"):
        os.environ.pop(name, None)
    os.environ["APP_MANAGEMENT_URL"] = os.environ["CONNECTIONS_URL"] = "http://127.0.0.1:9"
    os.environ.update(spec["env"])

    # The console's image (python:3.12-slim) has no /etc/mime.types, so Python's own table is the
    # whole truth there. Windows would add its registry and a Linux desktop its /etc/mime.types:
    # both are switched off, so the oracle answers what the office's console answers.
    mimetypes._winreg = None
    mimetypes._mimetypes_read_windows_registry = None
    mimetypes.knownfiles[:] = []
    mimetypes.init()

    sys.dont_write_bytecode = True
    with open(spec["app"], encoding="utf-8") as f:
        source = f.read()
    mod = types.ModuleType("console_oracle")
    mod.__file__ = os.path.join(spec["root"], "app.py")
    sys.modules[mod.__name__] = mod          # so Flask's root_path is the fixture root, as /app is
    exec(compile(source, spec["app"], "exec"), mod.__dict__)

    from flask_compress.flask_compress import _uncompress_data

    client = mod.app.test_client()
    out = []
    for r in spec["requests"]:
        resp = client.open(r["path"], method=r["method"], headers=r["headers"])
        body = resp.get_data()
        enc = resp.headers.get("Content-Encoding")
        decoded = _uncompress_data(body, enc) if enc and body and enc in ("zstd", "br", "gzip", "deflate") else body
        out.append({"status": resp.status_code, "headers": [[k, v] for k, v in resp.headers.items()],
                    "body": base64.b64encode(body).decode(), "decoded": base64.b64encode(decoded).decode()})
    # The digest a shell built into dgo must report is the one app.py computes in its LINUX image, on
    # whatever host this runs: the same function, unmodified, over the same files, given the image's
    # `os` — paths joined and made relative with `/`. On a Linux host this is _SHELL itself.
    host = os
    mod.os = types.SimpleNamespace(path=posixpath, walk=lambda top: (
        (base.replace(host.sep, "/"), dirs, files) for base, dirs, files in host.walk(top)))
    mod.STATIC = mod.STATIC.replace(host.sep, "/")
    image_shell = mod._shell_build()

    versions = {"python": sys.version.split()[0]}
    for dist in ("flask", "werkzeug", "flask-compress", "pyyaml"):
        versions[dist] = importlib.metadata.version(dist)
    json.dump({"versions": versions, "responses": out, "image_shell": image_shell}, sys.stdout)


if __name__ == "__main__":
    main()
