#!/usr/bin/env python3
"""test_offsite — the daily backup that leaves the server (FPG-26), each piece run for real where it can be.

- the script: the snapshot under its OWN, per-office name, the free-space check sized for the copies it
  writes, the key never exported (only openssl's environment) and never in a command (stdin), umask 077, a
  killed run's plaintext removed by the next — that office's snapshot and nothing else — no pruning of the
  pre-upgrade backups, a malformed key refused without «delete it»;
- the encryption, in bash with real tar and openssl and a stand-in docker: it decrypts with the key (pinned
  -md sha256) and holds the snapshot; a wrong key does not open it; a .json beside it says how; no
  plaintext; yesterday's replaced; a failing tar fails the step and keeps the last archive;
- the copies here, listed by the real shell over a stand-in docker: anchored to the office; NONE is an
  answer; a docker that fails is a failure, never «none»;
- the key: made once, read back; NEVER made while copies encrypted with a key exist here; a vault that does
  not answer is not «the key is gone», and nothing is made on it;
- the transfer: followed to ok; waits its turn while another runs; a lost job (404) fails at once; a copy
  past its time is CANCELLED;
- the step: a stamp or file name forged in the machine's log never reaches a command here; a transfer that
  fails — or is cut short by a refused connection — leaves no volume and no staging behind; a sha that
  differs at home fails; a verified copy is marked, and retention counts only those; the snapshot's WARN
  lines come back as warnings; a backup still running from an earlier run is followed, not doubled; a
  machine shared with another office is refused;
- start_detached(secret=True): the script travels on stdin, its byte count checked; never in the command.

Run: python3 apps/dgo-extend/tests/test_offsite.py   (needs bash, tar, openssl, GNU stat — the app's image)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

FAIL: list[str] = []
KEY = "k" * 43
REAL = {n: getattr(converge, n) for n in ("_http", "exec_on", "must", "vault_secret", "start_detached",
                                           "wait_detached", "_transfer_volume", "_offsite_key", "_records")}
REAL_SLEEP = converge.time.sleep


def check(cond, what):
    if not cond:
        FAIL.append(what)


def restore():
    for n, f in REAL.items():
        setattr(converge, n, f)
    converge.time.sleep = REAL_SLEEP


def test_cache_left_out():
    """FPG-92: a volume an app declares rebuildable (data.cache) is left out of the off-server copy, by name — under
    its compose prefix too — and only of that copy; an odd name never reaches the script."""
    s = converge.offsite_script("/opt/o", "fireplace", KEY, "abc123def456", ["apitools_asr_data", "x;rm -rf /"])
    r = subprocess.run(["sh", "-c", 'for v in fireplace_apitools_asr_data apitools_asr_data fireplace_db; do ' +
                        s[s.index('  case "$v" in dgo-offsite*)'):s.index("  src=/var/lib/docker/volumes/$v/_data")] +
                        '  echo "KEEP $v"; done'], capture_output=True, text=True)
    check(r.stdout.split("\n").count("KEEP fireplace_db") == 1 and "KEEP fireplace_apitools" not in r.stdout
          and "KEEP apitools_asr_data" not in r.stdout and r.stdout.count("rebuildable (data.cache)") == 2,
          f"the cache volume is left out under either name, the rest kept: {r.stdout!r} {r.stderr!r}")
    check("rm -rf /" not in s.split("trap")[0] + s[s.index('case "$v" in dgo-offsite*)'):], "an odd name never reaches it")
    check("rebuildable" not in converge.offsite_script("/opt/o", "fireplace", KEY, "abc123def456"),
          "no cache declared: nothing left out")


def test_script():
    s = converge.offsite_script("/opt/o", "fireplace", KEY, "abc123def456")
    lines = s.splitlines()
    check(lines[0] == "umask 077" and lines[1] == f"K='{KEY}'" and s.count(KEY) == 1,
          "umask first, the key once, NOT exported")
    check("export DGO_OFFSITE_KEY" not in s and 'DGO_OFFSITE_KEY="$K" openssl' in s and "-pass env:DGO_OFFSITE_KEY" in s,
          "only openssl's own environment holds the key")
    check(re.search(r"^D=/root/offsite-fireplace-\$STAMP$", s, re.M) and not re.search(r"^D=/root/backup-", s, re.M),
          "the snapshot goes under the office's own name, never a pre-upgrade backup's")
    check("/root/backup-" not in s and "PRUNED=" not in s, "the daily copy never prunes a pre-upgrade backup")
    check("vol_mb * 225 / 100" in s and "vol_mb * 125 / 100" not in s, "the room check covers the copies it writes")
    check("-name 'offsite-fireplace-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]' -mmin +180" in s
          and "-name 'offsite-*'" not in s and "trap 'rm -rf \"/root/offsite-fireplace-${STAMP:-none}\"' EXIT" in s,
          "a killed run's plaintext is removed by the next — that office's snapshot shape only")
    check("dgo-offsite*) " in s and "docker volume create dgo-offsite-fireplace" in s,
          "the off-server volumes are never in a backup, and the office has its own")
    check('"key": "offsite_key-fireplace", "key_fingerprint": "abc123def456"' in s and "-md sha256" in s,
          "the .json names the key and its fingerprint; the digest is pinned")
    # the cleanup's pattern, by find itself: this office's snapshots, never a drill's dir or another office's
    with tempfile.TemporaryDirectory() as t:
        for n in ("offsite-fireplace-20261022-224700", "offsite-restore", "offsite-other-20261022-224700",
                  "backup-20261022-224700-pre-upgrade", "offsite-fireplace-x"):
            Path(t, n).mkdir()
        glob = converge.OFFSITE_SNAP_GLOB.replace("__OID__", "fireplace")
        hit = subprocess.run(["find", t, "-maxdepth", "1", "-name", glob], capture_output=True, text=True).stdout.split()
        check([Path(h).name for h in hit] == ["offsite-fireplace-20261022-224700"], f"the cleanup matches only its own: {hit}")
    for bad in ("short", "has space " + "x" * 40, ""):
        try:
            converge.offsite_script("/opt/o", "fireplace", bad, "fp")
            check(False, f"a malformed key is refused: {bad!r}")
        except converge.StepFailed as e:
            check("אל תמחק" in e.action, f"and never told to delete it: {e.action!r}")


def _tail(oid="fireplace"):
    return (converge.OFFSITE_ENCRYPT.replace("__VOLUME__", converge.offsite_volume(oid)).replace("__OID__", oid)
            .replace("__CIPHER__", converge.OFFSITE_CIPHER).replace("__ITER__", str(converge.OFFSITE_ITER))
            .replace("__KEYID__", f"offsite_key-{oid}").replace("__FP__", "fp12"))


def test_encrypt_roundtrip():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        snap, out, bin_ = t / "snap", t / "vol", t / "bin"
        for d in (snap / "pg", out, bin_):
            d.mkdir(parents=True)
        (snap / "pg" / "db.sql").write_text("CREATE TABLE customers (name text);\n")
        (out / "fireplace-20000101-000000.tar.enc").write_text("yesterday")
        (out / "fireplace-20000101-000000.tar.enc.json").write_text("{}")
        (bin_ / "docker").write_text("#!/bin/bash\n"
                                     f'[ "$1 $2" = "volume inspect" ] && echo "{out}"; exit 0\n')
        os.chmod(bin_ / "docker", 0o755)
        env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}
        script = f"set -e\nK='{KEY}'\nSTAMP=20261022-224700\nD='{snap}'\n" + _tail()
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=env)
        f = converge.parse_facts(r.stdout)
        enc = out / "fireplace-20261022-224700.tar.enc"
        meta = json.loads((out / (enc.name + ".json")).read_text()) if (out / (enc.name + ".json")).exists() else {}
        check(r.returncode == 0 and enc.exists() and f.get("OFFSITE_FILE") == enc.name
              and f.get("OFFSITE_BYTES") == str(enc.stat().st_size) and len(f.get("OFFSITE_SHA", "")) == 64,
              f"the archive is written and named: rc={r.returncode} {f} {r.stderr[-300:]!r}")
        check(meta.get("sha256") == f.get("OFFSITE_SHA") and meta.get("pbkdf2_iter") == converge.OFFSITE_ITER
              and meta.get("key") == "offsite_key-fireplace" and meta.get("md") == "sha256",
              f"a .json beside it says how to open it: {meta}")
        check(not snap.exists(), "the plaintext snapshot is gone")
        check(sorted(p.name for p in out.iterdir()) == [enc.name, enc.name + ".json"],
              f"yesterday's archive and its .json are replaced: {sorted(p.name for p in out.iterdir())}")
        check(b"customers" not in enc.read_bytes(), "the archive is encrypted")
        dec = subprocess.run(["bash", "-c", f"openssl enc -d -aes-256-cbc -md sha256 -pbkdf2 -iter {converge.OFFSITE_ITER} "
                                            f"-pass env:K -in '{enc}' | tar xOf - ./pg/db.sql"],
                             capture_output=True, timeout=60, env={**os.environ, "K": KEY})
        check(dec.returncode == 0 and b"CREATE TABLE customers" in dec.stdout,
              f"it decrypts with the key and holds what the snapshot held: {dec.stderr[-200:]!r}")
        wrong = subprocess.run(["bash", "-c", f"openssl enc -d -aes-256-cbc -md sha256 -pbkdf2 -iter {converge.OFFSITE_ITER} "
                                              f"-pass env:K -in '{enc}' >/dev/null"],
                               capture_output=True, timeout=60, env={**os.environ, "K": "x" * 43})
        check(wrong.returncode != 0, "a wrong key does not open it")
        # a tar that fails fails the step (pipefail); the trap removes the plaintext and the half archive
        snap2 = t / "snap2"
        (snap2 / "pg").mkdir(parents=True)
        (bin_ / "tar").write_text("#!/bin/bash\necho broken >&2\nexit 2\n")
        os.chmod(bin_ / "tar", 0o755)
        r2 = subprocess.run(["bash", "-c", f"set -e\nK='{KEY}'\nSTAMP=20261022-230000\nD='{snap2}'\n" + _tail()],
                            capture_output=True, text=True, timeout=60, env=env)
        check(r2.returncode != 0 and "OFFSITE_FILE" not in r2.stdout and not snap2.exists() and enc.exists()
              and not list(out.glob("*.part")),
              f"a failing tar fails the step, leaves no plaintext, keeps the last archive: rc={r2.returncode}")


def _with_docker(listing: str, rc: int, cmd: str) -> subprocess.CompletedProcess:
    """`cmd` run by the real bash, over a docker that answers `volume ls -q` with `listing` and exit `rc`."""
    with tempfile.TemporaryDirectory() as t:
        Path(t, "docker").write_text(f"#!/bin/bash\nprintf '%s' '{listing}'\nexit {rc}\n")
        os.chmod(Path(t, "docker"), 0o755)
        return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30,
                              env={**os.environ, "PATH": f"{t}:{os.environ['PATH']}"})


def test_home_copies():
    vols = ("dgo-offsite-fireplace-20261021-224700\ndgo-offsite-fireplace-20261022-224700\n"
            "dgo-offsite-fireplace-x-20261022-224700\ndgo-offsite-fireplace\nfireplace_db\n")
    r = _with_docker(vols, 0, converge._home_copies("fireplace"))
    check(r.returncode == 0 and r.stdout.split() == ["dgo-offsite-fireplace-20261021-224700",
                                                     "dgo-offsite-fireplace-20261022-224700"],
          f"the office's copies, anchored — not another office's, not its own machine-side volume: {r.stdout!r}")
    r = _with_docker("fireplace_db\n", 0, "set -o pipefail; " + converge._home_copies("fireplace") + " | wc -l")
    check(r.returncode == 0 and r.stdout.strip() == "0", f"none is an answer, also under pipefail: {r.stdout!r} rc={r.returncode}")
    r = _with_docker("", 1, converge._home_copies("fireplace") + " | wc -l")
    check(r.returncode != 0, f"a docker that fails is a failure, never «none»: rc={r.returncode} {r.stdout!r}")


def test_key():
    store, calls, homes = {}, [], {"n": "0", "rc": 0}

    def must(m, cmd, t=120, what="", stdin=None):
        r = _with_docker("dgo-offsite-fireplace-20261022-224700\n" * int(homes["n"]), homes["rc"], cmd)
        if r.returncode != 0:
            raise converge.StepFailed(what, "", r.stderr)
        return r.stdout
    converge.must = must

    def http(method, url, body=None, timeout=30):
        calls.append((method, url))
        if store.get("down"):
            return {"_status": 502, "error": "bad gateway"}
        if method == "GET":
            iid = url.rsplit("/", 2)[-2]
            return {"secret": store[iid]} if iid in store else {"_status": 404}
        if store.get("refuse"):
            return {"_status": 500}
        store[body["id"]] = body["secret"]
        return {"id": body["id"]}
    converge._http = http
    office = {"id": "fireplace", "label": "The Fireplace Guys"}
    k1, fp1 = converge._offsite_key(office)
    k2, fp2 = converge._offsite_key(office)
    check(len(k1) >= 40 and k1 == k2 and fp1 == fp2 and len(fp1) == 12 and sum(m == "POST" for m, _ in calls) == 1,
          f"made once, then read from the vault, with a stable fingerprint: {calls}")
    store.clear()
    calls.clear()
    homes["n"] = "3"
    try:
        converge._offsite_key(office)
        check(False, "a missing key while copies exist here is refused, never replaced")
    except converge.StepFailed as e:
        check("לא נוצר" in e.action and not [c for c in calls if c[0] == "POST"], f"…and nothing is minted: {e.action!r} {calls}")
    homes.update(n="0", rc=1)
    try:
        converge._offsite_key(office)
        check(False, "a docker here that fails is not «no copies»: nothing is minted on it")
    except converge.StepFailed:
        check(not [c for c in calls if c[0] == "POST"], f"…nothing minted: {calls}")
    homes["rc"] = 0

    def unreachable(method, url, body=None, timeout=30):
        calls.append((method, url))
        raise urllib.error.URLError("connection refused")
    converge._http = unreachable
    homes["n"] = "3"
    try:
        converge._offsite_key(office)
        check(False, "a vault that cannot be reached is a failure")
    except converge.StepFailed as e:
        check("לא ענתה" in e.reason and "החזר" not in e.action,
              f"…said as the vault not answering — never «the key is missing, restore the vault»: {e.reason!r} {e.action!r}")
    homes["n"] = "0"
    converge._http = http
    store["down"] = True
    try:
        converge._offsite_key(office)
        check(False, "a vault that does not answer is a failure")
    except converge.StepFailed as e:
        check("לא ענתה" in e.reason and not [c for c in calls if c[0] == "POST"],
              f"…said as the vault not answering, never «the key is gone», and nothing made: {e.reason!r}")
    store.clear()
    store["refuse"] = True
    try:
        converge._offsite_key(office)
        check(False, "a vault that refuses the new key is a failure")
    except converge.StepFailed:
        pass
    restore()


def test_transfer():
    seen, waits = [], []
    converge.time.sleep = lambda s: waits.append(s)

    def http_for(posts, states):
        p, it = iter(posts), iter(states)

        def http(method, url, body=None, timeout=30):
            seen.append((method, url))
            if url.endswith("/cancel"):
                return {"cancelled": True}
            return next(p) if method == "POST" else next(it)
        return http
    converge._http = http_for([{"error": "העברה אחרת כבר רצה", "active": "j0"}, {"job": {"id": "j1"}}],
                              [{"transfer": {"state": "running", "percent": 50.0}}, {"transfer": {"state": "ok", "sha256": "x"}}])
    lines = []
    out = converge._transfer_volume("m", "local", "dgo-offsite-x", "dgo-offsite-x-1", lines.append)
    check(out.get("state") == "ok" and "   50.0%" in lines and any("ממתין לתורה" in ln for ln in lines),
          f"waits its turn behind another office's copy, then followed to ok: {lines}")
    for posts, states, what in (([{"job": {"id": "j1"}}], [{"transfer": {"state": "error", "error": "x"}}], "error"),
                                ([{"error": "x"}], [], "never started"),
                                ([{"job": {"id": "j1"}}], [{"_status": 404}], "a lost job (404)")):
        converge._http = http_for(posts, states)
        try:
            converge._transfer_volume("m", "local", "v", "d", lines.append)
            check(False, f"{what} is a failure")
        except converge.StepFailed:
            pass
    seen.clear()
    converge._http = http_for([{"job": {"id": "j9"}}], [{"transfer": {"state": "running", "percent": 1.0}},
                                                        {"transfer": {"state": "verifying"}}, {"transfer": {"state": "cancelled"}}])
    try:
        converge._transfer_volume("m", "local", "v", "d", lines.append, limit=-1)
        check(False, "a copy past its time is a failure")
    except converge.StepFailed:
        gets = [u for m, u in seen if m == "GET"]
        check(("POST", f"{converge.COMPUTERS_URL}/api/transfers/j9/cancel") in seen and len(gets) == 3,
              f"…and it is CANCELLED, and followed until it really ended (verify does not stop at once): {seen}")
    # a status that stops answering: two blips are waited out, the third cancels the copy
    seen.clear()
    answers = iter([urllib.error.URLError("timed out"), ValueError("a body that is not JSON"),
                    urllib.error.URLError("refused")])

    def flaky(method, url, body=None, timeout=30):
        seen.append((method, url))
        if method == "POST" and url.endswith("/transfer"):
            return {"job": {"id": "j7"}}
        if url.endswith("/cancel"):
            return {"cancelled": True}
        nxt = next(answers, None)
        if nxt is not None:
            raise nxt
        return {"transfer": {"state": "cancelled"}}
    converge._http = flaky
    try:
        converge._transfer_volume("m", "local", "v", "d", lines.append)
        check(False, "a copy nobody can follow is a failure")
    except converge.StepFailed as e:
        check("לא עונה" in e.reason and ("POST", f"{converge.COMPUTERS_URL}/api/transfers/j7/cancel") in seen,
              f"…and it is cancelled, never left streaming into a deleted file: {e.reason!r} {seen}")
    restore()


def test_received_copy():
    """What the client's machine sent is checked by the real shell here before anything reads it: exactly the
    archive and its .json, as plain files — a link or a pipe from there leads no root command here."""
    office = {"id": "fireplace", "path": "/opt/o", "machine": "m"}
    with tempfile.TemporaryDirectory() as t:
        vol, bin_ = Path(t, "vol"), Path(t, "bin")
        vol.mkdir()
        bin_.mkdir()
        Path(bin_, "docker").write_text(f"#!/bin/bash\n[ \"$1 $2\" = \"volume inspect\" ] && echo '{vol}'; exit 0\n")
        os.chmod(Path(bin_, "docker"), 0o755)
        env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}
        fname = "fireplace-20261022-224700.tar.enc"
        Path(vol, fname).write_bytes(b"ciphertext")
        Path(vol, fname + ".json").write_text("{}")
        real_sha = subprocess.run(["sha256sum", str(Path(vol, fname))], capture_output=True, text=True).stdout.split()[0]
        ran = []

        def must(machine, cmd, timeout=120, what="", stdin=None):
            ran.append(cmd)
            if "sha256sum" in cmd or ".verified" in cmd:
                r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30, env=env)
                if r.returncode:
                    raise converge.StepFailed(what, "", r.stderr)
                return r.stdout
            return "KEPT=1\n"
        for planted, ok in ((None, True), ("link", False), ("fifo", False), ("extra", False)):
            for p in vol.iterdir():
                if p.name not in (fname, fname + ".json"):
                    p.unlink()
            if planted == "link":
                os.symlink("/etc/hostname", vol / ".verified")
            elif planted == "fifo":
                os.mkfifo(vol / "x.fifo")
            elif planted == "extra":
                Path(vol, "notes.txt").write_text("x")
            _step_world(facts=f"OFFSITE_STAMP=20261022-224700\nOFFSITE_FILE={fname}\nOFFSITE_BYTES=10\nOFFSITE_SHA={real_sha}\n")
            converge.must = must
            try:
                res = converge.step_offsite(office, {}, lambda ln: None)
                check(ok and res.get("verified") and Path(vol, ".verified").is_file()
                      and not Path(vol, ".verified").is_symlink(), f"exactly the archive and its .json: verified, marked: {res}")
            except converge.StepFailed as e:
                check(not ok and "מלבד הארכיון" in e.reason, f"{planted} in the copy is refused, before it is read: {e.reason!r}")
            restore()


def test_backup_waits():
    """A pre-upgrade snapshot never runs beside an off-server one that outlived its run: it waits for it."""
    order = []
    converge.exec_on = lambda m, cmd, t=120, stdin=None: (
        {"code": 0, "stdout": "BUSY\n"} if "pgrep" in cmd else {"code": 0, "stdout": "present\n"})
    converge.wait_detached = lambda office, name, emit, limit, every=8.0: order.append(f"wait:{name}") or (
        "BACKUP_DONE=/root/backup-x\nPG=1\nVOL=2\nSIZE=1M\n" if name == "backup" else "")
    converge.start_detached = lambda office, name, script, secret=False: order.append(f"start:{name}")
    converge.step_backup({"id": "fireplace", "path": "/opt/o", "machine": "m"}, {}, lambda ln: None)
    check(order == ["wait:offsite", "start:backup", "wait:backup"], f"the off-server snapshot ends first: {order}")
    restore()


SHA = "a" * 64


def _step_world(transfer=None, home_sha=None, facts=None, busy=(), decls=(), free=None):
    calls = {"exec": [], "must": [], "secret": None, "started": False, "waited": [], "on": []}
    converge._offsite_key = lambda office: (KEY, "fp12")
    converge._records = lambda want: [d for d in decls if want(d)]

    def start(office, name, script, secret=False):
        calls.update(secret=secret, script=script, started=True)
    converge.start_detached = start

    def wait(office, name, emit, limit, every=8.0):
        calls["waited"].append(name)
        return facts or ("WARN: pg_dumpall failed for x-db: refused\nOFFSITE_STAMP=20261022-224700\n"
                         f"OFFSITE_FILE=fireplace-20261022-224700.tar.enc\nOFFSITE_BYTES=123\nOFFSITE_SHA={SHA}\n")
    converge.wait_detached = wait

    def exec_on(machine, cmd, timeout=120, stdin=None):
        calls["exec"].append(cmd)
        calls["on"].append((machine, cmd))
        if "df -PB1" in cmd and free is not None:
            return {"code": 0, "stdout": f"{free}\n"}
        running = [n for n in busy if f"/{n}[.]sh" in cmd]
        return {"code": 0, "stdout": "BUSY\n" if "pgrep" in cmd and running else "ready\n"}

    def must(machine, cmd, timeout=120, what="", stdin=None):
        calls["must"].append(cmd)
        calls["on"].append((machine, cmd))
        if "sha256sum" in cmd:
            return (home_sha or SHA) + "\n"
        return "KEPT=3\n"
    converge.exec_on, converge.must = exec_on, must
    converge._transfer_volume = transfer or (lambda *a, **k: {"state": "ok"})
    return calls


def test_store_and_room():
    """FPG-92: the copies go to the declared store (offsite_to) and are checked and kept there; a store without room
    for twice the archive refuses before anything moves."""
    office = {"id": "fireplace", "path": "/opt/o", "machine": "m", "offsite_to": "computer_hp"}
    sent = []

    def to_store(frm, to, *a, **k):
        sent.append((frm, to))
        return {"state": "ok"}
    calls = _step_world(transfer=to_store, free=10 ** 12)
    res = converge.step_offsite(office, {}, lambda ln: None)
    at_home = [c for m, c in calls["on"] if "df -PB1" in c or "sha256sum" in c or ".verified" in c]
    on_store = {m for m, c in calls["on"] if "df -PB1" in c or "sha256sum" in c or ".verified" in c}
    check(sent == [("m", "computer_hp")] and res.get("store") == "computer_hp" and at_home and on_store == {"computer_hp"},
          f"the room, the check, the mark and the retention are on the declared store: {sent} {on_store} {res}")
    sent.clear()
    _step_world(transfer=to_store, free=200)
    try:
        converge.step_offsite(office, {}, lambda ln: None)
        check(False, "a store without room fails the step")
    except converge.StepFailed as e:
        check(not sent and "computer_hp" in e.detail, f"…before anything moves, the store named: {sent} {e.detail}")
    check(converge.offsite_home({"id": "x"}) == converge.LOCAL_MACHINE, "no store declared: this home, as before")


def test_step():
    office = {"id": "fireplace", "path": "/opt/o", "machine": "m"}
    calls = _step_world()
    res = converge.step_offsite(office, {}, lambda ln: None)
    check(calls["secret"] is True and res.get("verified") is True and res.get("kept") == "3"
          and res.get("key") == "offsite_key-fireplace" and res.get("key_fingerprint") == "fp12"
          and res.get("warnings") == ["WARN: pg_dumpall failed for x-db: refused"],
          f"a whole run: secret script, verified at home, the key named, the WARN line kept: {res}")
    check(any("rm -f \"$m\"/.verified && : > \"$m\"/.verified" in c for c in calls["must"])
          and any("[ -f \"$m\"/.verified ] && [ ! -L \"$m\"/.verified ]" in c for c in calls["must"]),
          f"a verified copy is marked, and retention counts only those: {calls['must']}")
    # the busy check must not match its own shell (its argv carries the pattern)
    probe = next(c for c in calls["exec"] if "pgrep" in c and "offsite" in c)
    check("pgrep -f '[.]digital-office/fireplace/offsite[.]sh'" in probe, f"the busy check cannot match itself: {probe!r}")

    def refused(*a, **k):
        raise urllib.error.URLError("connection refused")

    def failed(*a, **k):
        raise converge.StepFailed("העברת הגיבוי נכשלה", "", "x")
    for world, what in ((dict(transfer=failed), "a failed transfer"),
                        (dict(transfer=refused), "a transfer cut short by a refused connection"),
                        (dict(home_sha="b" * 64), "a sha that differs at home")):
        calls = _step_world(**world)
        try:
            converge.step_offsite(office, {}, lambda ln: None)
            check(False, f"{what} fails the step")
        except converge.StepFailed:
            cleanup = [c for c in calls["exec"] if "docker volume rm dgo-offsite-fireplace-20261022-224700" in c]
            check(cleanup and re.search(r"rm -f '?/var/lib/bina-transfer/dgo-offsite-fireplace__"
                                        r"dgo-offsite-fireplace-20261022-224700\.tar'?\*", cleanup[0]),
                  f"{what} leaves no volume and no staging behind: {calls['exec']}")
    # a stamp or a file name forged in the machine's log never reaches a command here
    for forged in ("OFFSITE_STAMP=1;touch /tmp/pwned;#\nOFFSITE_FILE=fireplace-1;touch /tmp/pwned;#.tar.enc\n",
                   "OFFSITE_STAMP=20261022-224700\nOFFSITE_FILE=$(touch /tmp/pwned)\n"):
        calls = _step_world(facts=forged + f"OFFSITE_SHA={SHA}\n")
        try:
            converge.step_offsite(office, {}, lambda ln: None)
            check(False, f"a forged fact is refused: {forged!r}")
        except converge.StepFailed:
            ran = calls["must"] + [c for c in calls["exec"] if "pgrep" not in c and "openssl" not in c]
            check(not any("pwned" in c for c in ran), f"…and reaches no command here: {ran}")
    calls = _step_world(busy=("offsite",))
    converge.step_offsite(office, {}, lambda ln: None)
    check(calls["started"] is False, "a backup still running from an earlier run is followed, never doubled")
    calls = _step_world(busy=("backup",))
    converge.step_offsite(office, {}, lambda ln: None)
    check(calls["waited"][:2] == ["backup", "offsite"] and calls["started"] is True,
          f"a pre-upgrade backup that outlived its converge ends first: {calls['waited']}")
    # a copy still running after its cancel is left alone — its volume is not removed beside its extract

    def still_running(*a, **k):
        e = converge.StepFailed("העברת הגיבוי לא הסתיימה בזמן", "", "")
        e.copy_running = True
        raise e
    calls = _step_world(transfer=still_running)
    said = []
    try:
        converge.step_offsite(office, {}, said.append)
        check(False, "a copy past its time fails the step")
    except converge.StepFailed:
        check(not [c for c in calls["exec"] if "docker volume rm" in c] and any("עדיין רצה" in s for s in said),
              f"…and a copy still running keeps its volume until retention: {calls['exec']} {said}")
    calls = _step_world(decls=({"id": "other", "machine": "m"}, {"id": "fireplace", "machine": "m"},
                               {"id": "far", "machine": "n"}, {"id": "peer", "machine": "m", "kind": "paired"}))
    try:
        converge.step_offsite(office, {}, lambda ln: None)
        check(False, "a machine shared with another office is refused")
    except converge.StepFailed as e:
        check(e.detail == "other" and not calls["started"], f"…naming it, and nothing started: {e.detail!r}")
    restore()


def test_secret_on_stdin():
    seen = {}
    converge.must = lambda m, cmd, t=120, what="", stdin=None: seen.update(cmd=cmd, stdin=stdin) or ""
    converge.exec_on = lambda m, cmd, t=120, stdin=None: {"code": 0, "stdout": "@@"}
    converge.start_detached({"machine": "m", "path": "/opt/o", "id": "x"}, "offsite", f"K='{KEY}'\necho hi\n", secret=True)
    body = seen.get("stdin") or ""
    check(KEY in body and KEY not in seen["cmd"] and "cat > " in seen["cmd"]
          and f"-eq {len(body.encode())} ]" in seen["cmd"],
          f"the secret script travels on stdin, its byte count checked, never in the command: {seen.get('cmd')!r}")
    converge.start_detached({"machine": "m", "path": "/opt/o", "id": "x"}, "plain", "echo hi\n")
    check(seen.get("stdin") is None and "base64 -d" in seen["cmd"], "a plain script still travels as before")
    restore()


def main() -> int:
    for t in (test_script, test_cache_left_out, test_encrypt_roundtrip, test_home_copies, test_key, test_transfer, test_step,
              test_store_and_room, test_received_copy, test_backup_waits, test_secret_on_stdin):
        before = len(FAIL)
        t()
        print(("PASS " if len(FAIL) == before else "FAIL ") + t.__name__)
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
