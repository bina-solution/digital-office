#!/usr/bin/env python3
"""A stand-in client server for a laptop (DGO-1893): with DGOCLOUD_PROVIDER=simulate the front writes each server's
install script to <data>/sim-<name>.sh; this takes the newest one, spends its boot token on /api/node/hello exactly as
install.sh does, reports the install steps, then runs the REAL node/agent.py in --simulate mode (no docker).

    python3 apps/dgo-cloud/tests/sim_node.py <data-dir> [--fast]
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

data = sys.argv[1]
fast = "--fast" in sys.argv
here = os.path.dirname(os.path.abspath(__file__))
done = set()
while True:
    for path in sorted(glob.glob(os.path.join(data, "sim-*.sh")), key=os.path.getmtime):
        if path in done or os.path.exists(path + ".node.json"):
            done.add(path)
            continue
        txt = open(path).read()
        front = re.search(r'FRONT="([^"]+)"', txt).group(1)
        boot = re.search(r'BOOT="([^"]+)"', txt).group(1)
        req = urllib.request.Request(front + "/api/node/hello", data=json.dumps({"boot": boot, "ip": "127.0.0.1"}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        node = json.load(urllib.request.urlopen(req, timeout=10))["data"]
        conf = path + ".node.json"
        with open(conf, "w") as f:
            json.dump(node, f)

        def step(s):
            r = urllib.request.Request(front + "/api/node/progress", data=json.dumps({"step": s, "ok": True}).encode(),
                                       method="POST", headers={"Content-Type": "application/json",
                                                               "Authorization": "Bearer " + node["secret"]})
            urllib.request.urlopen(r, timeout=10)
            print(node["name"], "→", s, flush=True)

        for s in ("שלום מהשרת", "מתקין חבילות", "מתקין Docker", "מנפיק תעודת אבטחה", "מקים את הלשכה", "ready"):
            step(s)
            time.sleep(0.3 if fast else 2)
        subprocess.Popen([sys.executable, os.path.join(here, "..", "node", "agent.py"), "--simulate"],
                         env=dict(os.environ, DGOCLOUD_NODE_JSON=conf))
        done.add(path)
    time.sleep(2)
