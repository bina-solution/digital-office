#!/usr/bin/env python3
"""DGO cloud — the agent on a client server (DGO-1893). A systemd service; it DIALS OUT to the front, so the server
needs no inbound port for it and the front holds no key to the server.

    agent.py                 the loop: poll the front (health in, jobs out), do each job, answer it
    agent.py --install-cert  place lego's wildcard certificate in traefik's file provider (the installer's step 4)
    agent.py --simulate      a laptop's stand-in for a whole server: no docker, answers jobs with plausible results

The verbs are a CLOSED list — nothing the front sends can run an arbitrary command:
  claim {email, name}   the buyer becomes an admin of this office (an authentik superuser) with a fresh password,
                        which goes back to the front ONCE and is shown to the buyer once
  password {email}      a fresh password for that admin
  suspend               `bbox stop`: every container stops, every volume stays
  resume                `bbox run`
  update                `bbox follow`: take the public release now, rather than at the next timer
  health                report now
Once a day: renew the certificate when it has under 30 days left.
"""
import datetime as dt
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request

D = "/opt/dgo-cloud"
OFFICE = os.environ.get("DGO_OFFICE", "/opt/dgo")
SIM = "--simulate" in sys.argv
CONF = os.environ.get("DGOCLOUD_NODE_JSON", os.path.join(D, "node.json"))


def conf():
    with open(CONF) as f:
        return json.load(f)


def call(path, body):
    c = conf()
    req = urllib.request.Request(c["front"] + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + c["secret"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if not d.get("ok"):
        raise RuntimeError(d.get("error"))
    return d.get("data")


def sh(cmd, timeout=1800, env=None):
    p = subprocess.run(cmd, cwd=OFFICE, capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, **(env or {})))
    return p.returncode, (p.stdout + p.stderr)[-1500:]


def new_password():
    # readable over the phone, and strong: 4 groups of 4 from an alphabet without look-alikes
    a = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4))


AK_ADMIN = r'''
import os
from authentik.core.models import User, Group
email = os.environ["DGC_EMAIL"].strip().lower()
u = User.objects.filter(email__iexact=email).first() or User.objects.filter(username=email).first()
if not u:
    u = User.objects.create(username=email, email=email, name=os.environ.get("DGC_NAME") or email, is_active=True)
u.is_active = True
u.set_password(os.environ["DGC_PW"])
u.save()
for g in Group.objects.filter(is_superuser=True):
    g.users.add(u)
print("DGC-OK", u.username)
'''


def make_admin(email, name):
    pw = new_password()
    if SIM:
        return {"user": email, "password": pw}
    c = conf()
    container = f"authentik-server-{os.environ.get('DEPLOYMENT_NAME', 'dgo')}"
    code, out = sh(["docker", "exec", "-e", "DGC_EMAIL=" + email, "-e", "DGC_NAME=" + (name or ""), "-e", "DGC_PW=" + pw,
                    container, "ak", "shell", "-c", AK_ADMIN], timeout=180)
    if code != 0 or "DGC-OK" not in out:
        raise RuntimeError(f"authentik refused ({code}): {out[-300:]}")
    return {"user": email, "password": pw, "console": f"https://console.{c['domain']}"}


def do(job):
    v, a = job["verb"], job.get("args") or {}
    if v == "claim" or v == "password":
        return make_admin(a["email"], a.get("name", ""))
    if v == "health":
        return health()
    if SIM:
        return {"simulated": v}
    if v == "suspend":
        code, out = sh(["bash", "./bbox", "stop"])
    elif v == "resume":
        code, out = sh(["bash", "./bbox", "run"], env={"BBOX_WAIT_TIMEOUT": "900"})
    elif v == "update":
        code, out = sh(["bash", "./bbox", "follow"])
    else:
        raise RuntimeError(f"unknown verb {v}")
    if code != 0:
        raise RuntimeError(out[-400:])
    return {"tail": out[-300:]}


def health():
    if SIM:
        return {"sim": True, "containers": 42, "unhealthy": 0, "load": 0.3, "disk_free_gb": 80, "mem_free_mb": 3000}
    h = {}
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"], capture_output=True, text=True,
                             timeout=20).stdout.splitlines()
        h["containers"] = len(out)
        h["unhealthy"] = [l.split("|")[0] for l in out if "unhealthy" in l][:10]
    except Exception as e:
        h["docker"] = str(e)[:100]
    try:
        h["load"] = round(os.getloadavg()[0], 2)
        du = shutil.disk_usage("/")
        h["disk_free_gb"] = round(du.free / 1e9, 1)
        with open("/proc/meminfo") as f:
            mi = dict(l.split(":", 1) for l in f)
        h["mem_free_mb"] = int(mi["MemAvailable"].split()[0]) // 1024
    except Exception:
        pass
    try:
        h["version"] = subprocess.run(["git", "-C", OFFICE, "rev-parse", "--short", "HEAD"], capture_output=True,
                                      text=True, timeout=10).stdout.strip()
    except Exception:
        pass
    return h


# ── the certificate ──────────────────────────────────────────────────────────────────────────────────────
def install_cert():
    c = conf()
    src = os.path.join(D, "lego", "certificates")
    crt, key = os.path.join(src, c["domain"] + ".crt"), os.path.join(src, c["domain"] + ".key")
    if not (os.path.exists(crt) and os.path.exists(key)):
        raise SystemExit(f"no certificate at {crt}")
    dst = os.path.join(OFFICE, "platform-base", "traefik", "config", "dgo-cloud")
    os.makedirs(dst, exist_ok=True)
    shutil.copyfile(crt, os.path.join(dst, "cert.pem"))
    shutil.copyfile(key, os.path.join(dst, "key.pem"))
    os.chmod(os.path.join(dst, "key.pem"), 0o600)
    # traefik's file provider reads every yaml in its directory: the wildcard is the default certificate, and an ACME
    # order is never placed for a name a certificate in the store already covers
    with open(os.path.join(OFFICE, "platform-base", "traefik", "config", "zz-dgo-cloud-cert.yaml"), "w") as f:
        f.write("# DGO cloud (DGO-1893): this server's one wildcard certificate, renewed by /opt/dgo-cloud/agent.py\n"
                "tls:\n  certificates:\n    - certFile: /etc/traefik/dgo-cloud/cert.pem\n"
                "      keyFile: /etc/traefik/dgo-cloud/key.pem\n"
                "  stores:\n    default:\n      defaultCertificate:\n"
                "        certFile: /etc/traefik/dgo-cloud/cert.pem\n        keyFile: /etc/traefik/dgo-cloud/key.pem\n")
    print("certificate placed for", c["domain"])


def renew_cert():
    c = conf()
    if c.get("zone") == "sslip.io" or SIM:
        return
    stamp = os.path.join(D, "renewed")
    if os.path.exists(stamp) and time.time() - os.path.getmtime(stamp) < 86400:
        return
    env = dict(os.environ, HTTPREQ_PASSWORD=c["secret"])
    p = subprocess.run(["docker", "run", "--rm", "-v", f"{D}/lego:/lego", "-e", "HTTPREQ_ENDPOINT=" + c["acme"],
                        "-e", "HTTPREQ_USERNAME=" + c["name"], "-e", "HTTPREQ_PASSWORD", c["lego_image"],
                        "--accept-tos", "--email", c["acme_email"], "--dns", "httpreq", "-d", c["domain"],
                        "-d", "*." + c["domain"], "--path", "/lego", "renew", "--days", "30"],
                       capture_output=True, text=True, timeout=600, env=env)
    open(stamp, "w").close()
    if p.returncode == 0:
        install_cert()


def main():
    if "--install-cert" in sys.argv:
        install_cert()
        return
    interval = 5
    while True:
        try:
            r = call("/api/node/poll", {"health": health()})
            interval = int(r.get("interval") or 30)
            for job in r.get("jobs") or []:
                try:
                    res = do(job)
                    call(f"/api/node/job/{job['id']}", {"ok": True, "result": res})
                except Exception as e:
                    call(f"/api/node/job/{job['id']}", {"ok": False, "result": {"error": str(e)[:500]}})
            renew_cert()
        except Exception as e:
            print(dt.datetime.utcnow().isoformat(), "poll:", e, flush=True)
            interval = 15
        time.sleep(interval)


if __name__ == "__main__":
    main()
