#!/usr/bin/env python3
"""test_spool_ingest — the app takes only the sensor's FINISHED batches from the spool (DGO-1838).

    python3 platform-base/security/tests/test_spool_ingest.py     # in the security image: exit 0 = it holds

The sensor writes each batch as `<name>.json.tmp-<pid>` and renames it to `<name>.json`. The app's ingester
listed every file in the spool and deleted what it read, tmp files included, so the sensor's rename failed
(FileNotFoundError) and the sensor died — on the Mac, 2026-11-12 12:13:25Z, which also reset its nft back-off.

It needs the app's own packages (fastapi), so off the image it prints G72's NOT RUN line and exits 2: never a pass.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import fastapi  # noqa: F401
except ImportError:
    print("NOT RUN test_spool_ingest: fastapi is not importable here — run it in the security image")
    sys.exit(2)

ROOT = tempfile.mkdtemp(prefix="spool-")
for name in ("data", "sensor", "registry"):
    os.makedirs(os.path.join(ROOT, name), exist_ok=True)
os.environ.update(SECURITY_DATA=os.path.join(ROOT, "data"), SENSOR_DIR=os.path.join(ROOT, "sensor"),
                  SECURITY_REGISTRY=os.path.join(ROOT, "registry"), DOCKER_SOCK=os.path.join(ROOT, "no.sock"))

import app  # noqa: E402

spool = os.path.join(ROOT, "sensor", "spool")
os.makedirs(spool, exist_ok=True)
done = os.path.join(spool, "1794485605602-000063.json")
writing = os.path.join(spool, "1794485605602-000064.json.tmp-1")
with open(done, "w", encoding="utf-8") as fh:
    json.dump({"at": 1794485605.6, "flows": [], "names": [], "sni": [], "host": [], "auth": [], "vol": []}, fh)
with open(writing, "w", encoding="utf-8") as fh:
    fh.write('{"at": 1794485605.6, "flo')                   # half written: the sensor is still in json.dump

app.ingest_spool()

fails = []
if os.path.exists(done):
    fails.append("a finished batch was not taken")
if not os.path.exists(writing):
    fails.append("a batch the sensor is still writing was deleted under it")
else:
    os.replace(writing, writing.rsplit(".tmp-", 1)[0])    # the sensor's own rename now works
if fails:
    print("test_spool_ingest: FAIL — " + "; ".join(fails))
    sys.exit(1)
print("test_spool_ingest: 2 checks passed — a finished batch is taken, one being written is left alone")
