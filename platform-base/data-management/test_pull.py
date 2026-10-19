"""data-management's pull, against a peer this test plays itself.

The peer is an HTTP server answering exactly the URLs the console's door would
(`/a/data-management.<office>/api/archives/<name>/download/<artifact>`), so every way a linked
office's archive can be wrong is something this test can serve on demand: a byte flipped in transit,
an artifact longer than it claims, a name that climbs out of the archive, an archive that is not there.

It needs this service's own dependencies, so it runs in a throwaway container of its image:

    docker run --rm -v "$PWD/platform-base/data-management:/src:ro" -w /tmp <image> python /src/test_pull.py
"""
import hashlib
import http.server
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(tempfile.mkdtemp(prefix="pull-test-"))
os.environ["DATA_ARCHIVE_ROOT"] = str(ROOT / "archives")
os.environ["CONSOLE_INTERNAL_URL"] = "http://127.0.0.1:18765"
os.environ.setdefault("DEPLOYMENT_PATH", "/tmp")
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("dm_app", HERE / "app.py")
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)

PEER = {}          # archive name -> {artifact path: bytes}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        prefix = "/a/data-management.macbook/api/archives/"
        if not self.path.startswith(prefix):
            return self.send_error(404)
        name, _, artifact = self.path[len(prefix):].partition("/download/")
        body = PEER.get(name, {}).get(artifact)
        if body is None:
            said = json.dumps({"detail": f"no artifact {artifact!r} in {name!r}"}).encode()
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(said)))
            self.end_headers()
            return self.wfile.write(said)
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i in range(0, len(body), 4096):
            chunk = body[i:i + 4096]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
        self.wfile.write(b"0\r\n\r\n")


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


srv = Server(("127.0.0.1", 18765), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def archive(files, tamper=None):
    """A peer's archive: {artifact: bytes} plus the manifest that describes it."""
    arts = {rel: {"kind": "volume", "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), "app": "notes"}
            for rel, b in files.items()}
    arts["volumes/notes_cache.HANDLED"] = {"kind": "skipped", "bytes": 0, "sha256": ""}
    man = {"format_version": 1, "artifacts": arts}
    if tamper:
        tamper(man, files)
    served = dict(files)
    served["manifest.json"] = json.dumps(man).encode()
    return served


def pull(name):
    target = dm.ARCHIVE_ROOT / f"from-macbook-{name}"
    dm.JOBS[name] = {"id": name, "log": [], "emitted": 0, "state": "starting"}
    dm._pull(name, "macbook", name, target)
    return dm.JOBS[name], target


GOOD = {"apps/notes/notes.dump": os.urandom(300_000), "volumes/notes_files.tar.gz": os.urandom(90_000)}
bad = 0


def check(label, ok, detail=""):
    global bad
    bad += 0 if ok else 1
    print(("PASS  " if ok else "FAIL  ") + label + (f" — {detail}" if detail else ""))


# 1. a whole archive arrives, byte for byte, and only then has a manifest
PEER["good"] = archive(GOOD)
job, target = pull("good")
same = all((target / rel).read_bytes() == b for rel, b in GOOD.items())
check("a whole archive arrives byte for byte and is listed complete",
      job["state"] == "done" and same and (target / "manifest.json").is_file()
      and not list(target.rglob("*.part")) and not (target / "manifest.json.pulled").exists(), job["log"][-1])

# 2. pulled again: nothing is fetched twice
PEER["good"] = {"manifest.json": PEER["good"]["manifest.json"]}          # the peer now has ONLY the manifest
job, _ = pull("good")
check("an archive that is already here is not fetched again",
      job["state"] == "done" and sum("already here" in l for l in job["log"]) == 2, job["log"][-1])

# 3. a byte changed on the way
flipped = dict(GOOD)
PEER["flipped"] = archive(GOOD)
PEER["flipped"]["apps/notes/notes.dump"] = bytes([GOOD["apps/notes/notes.dump"][0] ^ 1]) + GOOD["apps/notes/notes.dump"][1:]
job, target = pull("flipped")
check("an artifact that does not hash to what the manifest says is refused and not kept",
      job["state"] == "failed" and not (target / "apps/notes/notes.dump").exists()
      and not (target / "manifest.json").exists(), job["log"][-1])

# 4. longer than it claims
PEER["long"] = archive(GOOD)
PEER["long"]["volumes/notes_files.tar.gz"] = GOOD["volumes/notes_files.tar.gz"] + os.urandom(5_000_000)
job, target = pull("long")
check("an artifact longer than it claims is cut off at the claim, not stored",
      job["state"] == "failed" and "longer" in job["log"][-1]
      and not list(target.rglob("notes_files*")), job["log"][-1])

# 5. names that are not plain paths under the archive
for label, rel in (("climbs out with ..", "../../etc/cron.d/x"), ("is absolute", "/etc/passwd"),
                   ("shadows the manifest", "manifest.json"), ("hides a .. inside", "volumes/../../x")):
    def tamper(man, files, rel=rel):
        man["artifacts"][rel] = {"kind": "volume", "bytes": 3, "sha256": "0" * 64, "app": "notes"}
    PEER["evil"] = archive(GOOD, tamper)
    job, target = pull("evil")
    outside = [p for p in ROOT.rglob("*") if p.is_file() and "archives" not in p.parts]
    check(f"a manifest entry that {label} is refused before anything is fetched",
          job["state"] == "failed" and not outside and not (target / "apps").exists(), job["log"][-1][:110])

# 6. sizes and hashes that are not sizes and hashes
for label, entry in (("a negative size", {"kind": "volume", "bytes": -1, "sha256": "0" * 64}),
                     ("a size that is text", {"kind": "volume", "bytes": "12", "sha256": "0" * 64}),
                     ("no hash", {"kind": "volume", "bytes": 3, "sha256": ""})):
    def tamper(man, files, entry=entry):
        man["artifacts"]["volumes/x.tar.gz"] = entry
    PEER["odd"] = archive(GOOD, tamper)
    job, _ = pull("odd")
    check(f"an entry with {label} is refused", job["state"] == "failed", job["log"][-1][:90])

# 7. not there / not given
job, target = pull("absent")
check("an archive the office does not hand over fails with the reason, and leaves no manifest",
      job["state"] == "failed" and "did not hand over" in job["log"][-1] and not (target / "manifest.json").exists(),
      job["log"][-1][:120])

# 7b. it hands over the manifest and then refuses an artifact: the reason is ITS sentence
PEER["half"] = {"manifest.json": archive(GOOD)["manifest.json"]}
job, target = pull("half")
check("an office that refuses an artifact part-way is quoted, and nothing is listed as an archive",
      job["state"] == "failed" and "HTTP 404: no artifact 'apps/notes/notes.dump' in 'half'" in job["log"][-1]
      and not (target / "manifest.json").exists() and not (target / "manifest.json.pulled").exists(),
      job["log"][-1][:150])

# 8. the route refuses names that are not identifiers (before any job exists)
import asyncio
from fastapi import HTTPException
for office, name in (("macbook", "../x"), ("Mac Book", "good"), ("macbook/../vps1", "good"), ("", "good")):
    try:
        asyncio.run(dm.api_pull(office=office, name=name))
        check(f"the route refuses office={office!r} name={name!r}", False)
    except HTTPException as e:
        check(f"the route refuses office={office!r} name={name!r}", e.status_code == 400)

print(f"\n{bad} failing")
sys.exit(1 if bad else 0)
