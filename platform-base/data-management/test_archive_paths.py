"""test_archive_paths — the download route hands over a file INSIDE an archive, and nothing else.

    python3 platform-base/data-management/test_archive_paths.py

`GET /api/archives/<name>/download/<artifact>` is the door a LINKED office pulls an archive through
(pull.py), so what it serves is decided for a caller this office never signed in. Every refusal
below names a file that exists, outside the archive asked for, and the route must not hand it over:
the parent of the archive root (`..`, which the router also makes of `%2E%2E`), the root itself
(`.`), an absolute path, a symlink out, and a directory that only STARTS like the one asked for
(`a1-evil`, `archives-evil`) — the shape a string-prefix check lets through (DGO-620). The export's
`resume` is held to the same rule. And the names pull.py reads end where the string ends (DGO-623).

Asked through the router where this interpreter can (FastAPI's TestClient, or httpx's ASGI transport
where that TestClient does not run); otherwise the route's function is called directly, with the two
framework names it needs stood in for. The first line printed says which.
"""
import asyncio
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile
import types
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="archive-paths-")).resolve()
ROOT = TMP / "archives"
os.environ["DATA_ARCHIVE_ROOT"] = str(ROOT)
os.environ["DATA_STATE_DIR"] = str(TMP / "state")
os.environ.setdefault("DEPLOYMENT_PATH", str(TMP))
sys.path.insert(0, str(HERE))


def stand_ins() -> bool:
    """The framework, as far as loading app.py and calling one route needs it — only where it is absent."""
    try:
        import fastapi  # noqa: F401
        return False
    except ImportError:
        pass

    class App:
        def __init__(self, *args, **kwargs):
            pass

        def _route(self, *args, **kwargs):
            return lambda fn: fn
        get = post = put = delete = patch = api_route = on_event = middleware = exception_handler = _route

        def add_middleware(self, *args, **kwargs):
            pass

        def mount(self, *args, **kwargs):
            pass

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None, **kwargs):
            super().__init__(detail)
            self.status_code, self.detail = status_code, detail

    class FileResponse:
        def __init__(self, path, *args, **kwargs):
            self.path = path

    fastapi = types.ModuleType("fastapi")
    fastapi.FastAPI, fastapi.HTTPException, fastapi.Query = App, HTTPException, lambda *a, **k: None
    gzip = types.ModuleType("fastapi.middleware.gzip")
    gzip.GZipMiddleware = object
    responses = types.ModuleType("fastapi.responses")
    responses.FileResponse, responses.JSONResponse = FileResponse, dict
    static = types.ModuleType("fastapi.staticfiles")
    static.StaticFiles = lambda *a, **k: None
    sys.modules.update({"fastapi": fastapi, "fastapi.middleware": types.ModuleType("fastapi.middleware"),
                        "fastapi.middleware.gzip": gzip, "fastapi.responses": responses,
                        "fastapi.staticfiles": static})
    return True


STOOD_IN = stand_ins()
spec = importlib.util.spec_from_file_location("dm_app", HERE / "app.py")
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)

SECRET, KEPT = b"a file outside the archive", b"an artifact of archive a1"
(ROOT / "a1/apps/notes").mkdir(parents=True)
(ROOT / "a1/apps/notes/notes.dump").write_bytes(KEPT)
(TMP / "secret.txt").write_bytes(SECRET)                               # the archive root's parent
(ROOT / "a1-evil").mkdir()                                             # starts like `a1`
(ROOT / "a1-evil/secret.txt").write_bytes(SECRET)
(TMP / "archives-evil").mkdir()                                        # starts like the root itself
(TMP / "archives-evil/secret.txt").write_bytes(SECRET)
LINKS = []                                     # the links out this machine lets the test make
try:
    os.symlink(TMP / "secret.txt", ROOT / "a1/link.txt")
    LINKS.append(("a1", "link.txt", "a symlink in the archive that points out of it"))
except (OSError, NotImplementedError):          # Windows without the privilege to make one
    pass
try:
    os.symlink(TMP / "archives-evil", ROOT / "evil", target_is_directory=True)
    LINKS.append(("evil", "secret.txt", "an archive that is a symlink to a directory beside the root"))
except (OSError, NotImplementedError):
    try:                                        # …where a junction (no privilege needed) is the same door
        import _winapi
        _winapi.CreateJunction(str(TMP / "archives-evil"), str(ROOT / "evil"))
        LINKS.append(("evil", "secret.txt", "an archive that is a junction to a directory beside the root"))
    except (ImportError, OSError, AttributeError):
        pass


def _seg(text: str, keep: str = "") -> str:
    """Encoded so the router DELIVERS `text`: a dot too, or the client folds `..` before sending."""
    return urllib.parse.quote(text, safe=keep).replace(".", "%2E")


def _url(name: str, artifact: str) -> str:
    return f"/api/archives/{_seg(name)}/download/{_seg(artifact, '/')}"


def asker():
    """(how it asks, ask(name, artifact) -> (status, body or None))."""
    if not STOOD_IN:
        try:
            from fastapi.testclient import TestClient
            client = TestClient(dm.app)

            def through_client(name, artifact):
                r = client.get(_url(name, artifact))
                return r.status_code, (r.content if r.status_code == 200 else None)
            return "through the router: FastAPI's TestClient", through_client
        except Exception:                                   # noqa: BLE001 — an older starlette vs httpx
            pass
        try:
            import httpx

            async def once(name, artifact):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=dm.app),
                                             base_url="http://data-management") as c:
                    r = await c.get(_url(name, artifact))
                return r.status_code, (r.content if r.status_code == 200 else None)
            return ("through the router: httpx's ASGI transport (FastAPI's TestClient does not run "
                    "with this httpx)"), lambda name, artifact: asyncio.run(once(name, artifact))
        except ImportError:
            pass

    def direct(name, artifact):
        try:
            answer = dm.api_download(name, artifact)
        except dm.HTTPException as e:
            return e.status_code, None
        return 200, pathlib.Path(answer.path).read_bytes()
    return ("calling the route's function directly" + (" — fastapi is not installed here, its names are "
            "stood in for" if STOOD_IN else "")), direct


HOW, ask = asker()
print(f"asked {HOW}; links out made here: {len(LINKS)} of 2"
      + ("" if len(LINKS) == 2 else " (no privilege to make a symlink: the rest are not asked)"))
bad = 0


def check(label, ok, detail=""):
    global bad
    bad += 0 if ok else 1
    print(("PASS  " if ok else "FAIL  ") + label + (f" — {detail}" if detail and not ok else ""))


# DGO-620: a file outside the archive asked for is never handed over, however the path is spelled.
CASES = [
    ("..", "secret.txt", "the archive root's parent, named `..`"),
    (urllib.parse.unquote("%2E%2E"), "secret.txt", "`%2E%2E`, as the router delivers it (`..`)"),
    ("%2E%2E", "secret.txt", "`%2E%2E` left encoded"),
    ("a1", (TMP / "secret.txt").as_posix(), "an absolute path as the artifact"),
    ((TMP / "archives-evil").as_posix(), "secret.txt", "an absolute path as the name"),
    ("a1", "../a1-evil/secret.txt", "an archive that only starts like the one asked for (a1-evil)"),
    ("..", "archives-evil/secret.txt", "a directory that only starts like the root (archives-evil)"),
    ("../archives-evil", "secret.txt", "the same directory, reached through the name"),
    # DGO-620: `.` (`%2E`) is no archive — without the name rule the base IS the root, and every
    # archive's files (and a loose file in the root) are inside it
    (".", "a1/apps/notes/notes.dump", "the archive root itself, named `.` (`%2E`)"),
] + LINKS
for name, artifact, label in CASES:
    status, body = ask(name, artifact)
    check(f"not served: {label}", status != 200, f"{status}, {len(body or b'')} bytes")
status, body = ask("a1", "apps/notes/notes.dump")
check("served: an artifact inside the archive asked for", status == 200 and body == KEPT, f"{status}")

# DGO-623: pull.py's names end where the string ends — `$` also matched just before a final newline.
for rule, value, what in ((dm.PULL.OFFICE, "macbook", "an office"), (dm.PULL.ARCHIVE, "a1", "an archive"),
                          (dm.PULL.ARTIFACT, "apps/notes/notes.dump", "an artifact")):
    check(f"{what} name that ends in a line break is not one",
          bool(rule.match(value)) and not rule.match(value + "\n"), repr(value + "\n"))
started = []
dm._pull = lambda *args: started.append(args)                         # no job may start for it
try:
    asyncio.run(dm.api_pull(office="macbook", name="a1\n"))
    refused = False
except dm.HTTPException as e:
    refused = e.status_code == 400
check("the pull route refuses an archive name that ends in a line break (the router delivers %0A)",
      refused and not started, f"started {started}")

# DGO-620: the export's `resume` names a run UNDER the archive root, by path — the same rule as the
# download's. Called directly (the archiver is a file here and no job runs), whatever the web stack.
(TMP / "scripts").mkdir(exist_ok=True)
(TMP / "scripts/deployment-archive.py").write_text("", encoding="utf-8")   # the archiver the route asks for
jobs = []


def _no_job(job_id, argv):
    jobs.append(argv)
    return asyncio.sleep(0)


dm._run_job = _no_job


def export(resume):
    try:
        return asyncio.run(dm.api_export(mode="full", quiesce=False, app_id=None, resume=resume))
    except dm.HTTPException as e:
        return e.status_code


for resume, label in (("../archives-evil", "a directory that only starts like the root"),
                      ("..", "the root's parent"), (".", "the archive root itself")):
    before, got = len(jobs), export(resume)
    check(f"export refuses resume={resume!r} ({label})", got == 400 and len(jobs) == before, f"{got}")
before, got = len(jobs), export("a1")
check("export resumes a run under the root", isinstance(got, dict) and len(jobs) == before + 1
      and pathlib.Path(got["out"]) == (ROOT / "a1").resolve(), f"{got}")

print(f"\n{bad} failing")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if bad else 0)
