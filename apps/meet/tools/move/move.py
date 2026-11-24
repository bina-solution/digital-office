"""move — `./bbox meet move <room> --from <office> --to <office> [--remove] [--dry-run]` (DGO-1861).

A recorded meeting, from one office's meet into another's, byte for byte, through this office's computers app: the
door it already has to every machine of the herd (its own machines by SSH, a linked office's through the link). Runs
INSIDE the computers container (hooks/move: `docker exec -w /app … python3 -c <this file>`), where the app answers on
127.0.0.1:8977 and holds the office key. An office is `local`, a linked office's name (its machine,
`computer_local-local.<office>`), or a computer id of `./bbox computers list`.

What a meeting is on disk (apps/meet/start/server.py): one folder of the recordings volume per recording,
recordings/<uuid>/ — the video, its sound, the recorder's notes (metadata.json, capture/holes/silence json) and flow/,
its page once processed — and recordings/flows/<room>/, a page made for a meeting recorded elsewhere. From it the
target makes by itself its transcripts and its MEET item (the recordings' workflow takes a recording that has no item,
DGO-834), the first page (server.py machine_flow) and its copies in Drive (to_drive). NOT carried: what people added
in the source's Drive folder of the meeting — corrections, approvals, uploads (.meet-flow/edits.jsonl, items.json,
uploads.json); a folder that holds them is left where it is, and named.

    1. both machines: where their meet keeps its recordings, and that they are two machines (host.py locate); the
       room's folders on the source, every one finished (meet's own rule); room on the target for the carried copy
       and the placed one
    2. the source: those folders copied into <work>/staged with their manifest (meet_move's: every file's size and
       sha256) — THE BACKUP, kept on the source's own disk (<work> = /var/backups/bbox/meet-move/<room>-<time>)
    3. carried in pieces of 4 MB, read on the source by the app's exec, and written on the target as one tar stream
       over SSH — or by exec, in pieces, where the target is reached only through a link; every file's sha256 checked
       on the way. Nothing is kept on this machine
    4. the target: meet_move place (a file already there with other bytes refuses the whole run; owned like the
       target's recordings; times kept), then its verify; the carried copy is removed there
    5. --remove: the source's folders out of its recordings volume — only while they are byte for byte the backup —
       and the meeting's folder in the source's Drive to Drive's trash, when it holds only meet's own copies
A step that surely did not run (ssh never reached the machine) is asked again, twice; a step that may still be running
there is not — stage, place and remove hold the run's lock on their machine. A failed step stops the run and undoes
nothing before it; the run prints its id first, and `--resume <run>` continues it: this run's backup (a whole manifest,
still covering every file the source has) and its carried copy (whole, the same manifest) are used as they are; a source
already removed in the run is left to its Drive step. A fresh run is safe too: place keeps a file there with the same
bytes. `--src-root`/`--dst-root` stand in for a machine's recordings volume (the tests). Exit 0 done, 1 refused or
failed (it says where), 2 usage, 3 a machine or the app did not answer.
"""
import base64
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("MEET_MOVE_COMPUTERS", "http://127.0.0.1:8977")
WORK = os.environ.get("MEET_MOVE_WORK", "/var/backups/bbox/meet-move")
# One read on the source. Its answer is held whole, as base64, by the computers app and again by this process, and both
# live in the app's container (160 MB): 16 MB pieces passed that cap on the HP and the app restarted mid-carry (exu104,
# 2026-11-19 16:16:51). One write by exec: its stdin takes 1 MiB of text (apps/computers STDIN_MAX).
CHUNK = 4 << 20
PIECE = 600 << 10
TELL = 32 << 20                                         # a line of progress every this many bytes of a file
TRIES, RETRY_WAIT = 3, 15                               # a step that did not run: asked again after 15 s, 30 s
# ssh's own words for a connection that never reached the command (apps/computers classify_stderr): only then is an
# exit 255 a step that surely did not run — 255 is also a command cut off mid-way, or killed
NOT_RUN = re.compile(r"banner exchange|Connection timed out|Connection refused|No route to host|Could not resolve|"
                     r"kex_exchange_identification|Network is unreachable")
LINK_LIMIT = 300                                        # the link's door gives up at 330 s (apps/computers app.py)
MARGIN = 512 << 20
ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
STAMP_RE = re.compile(r"^[^/]+/(?P<stem>[^/]+_\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d)\.mp4$")
USAGE = ("usage: bbox meet move <room> --from <office|computer> --to <office|computer> [--remove] [--dry-run] "
         "[--resume <run>]")


class Refused(Exception):
    """A step said no, or found other bytes than it was promised: the run stops (exit 1)."""


class Unreachable(Exception):
    """The computers app, or a machine through it, did not answer (exit 3)."""


def say(msg):
    print(msg, flush=True)


def q(v):
    return shlex.quote(str(v))


def mb(n):
    return f"{n / 1e6:,.1f} MB"


def cid_of(office):
    """`local` → this office's machine; a linked office's name → its machine through the link; a computer id as is."""
    if office == "local":
        return "computer_local-local"
    return office if office.startswith("computer_") else "computer_local-local." + office


class Machine:
    """One computer of this office's fleet, by its id, through the computers app."""

    def __init__(self, cid, work_root=None):
        self.cid, self.work_root = cid, work_root or WORK

    def run(self, command, stdin=None, timeout=300, again=False):
        """(exit code, stdout, stderr) of one command there (the app's /exec). Asked again, twice, only when it surely
        did not run: ssh could not reach the machine (exit 255 with ssh's own words for it — measured on vps1 2026-11-19,
        «timed out during banner exchange» right after a 7-minute carry). `again` is for a step that may run twice, even
        side by side (a read, a list, a piece already there): it is asked again also when the app answered 5xx or
        nothing — a link that dropped answers 502 while the command may still be running at the far end. A linked
        machine's command is given at most LINK_LIMIT seconds, under the link's own limit."""
        timeout = min(timeout, LINK_LIMIT) if "." in self.cid else timeout
        for attempt in range(TRIES):
            try:
                code, out, err = self._run(command, stdin, timeout)
            except Unreachable as e:
                if not again:
                    raise Unreachable(f"{e} — it may have run there: resume the run, which checks what is there")
                why = str(e)
            else:
                if code != 255:
                    return code, out, err
                why = f"{self.cid}: {(err or out).strip()[-200:] or 'exit 255'}"
                if not again and not NOT_RUN.search(err or ""):
                    raise Unreachable(f"{why} — it may have run there: resume the run, which checks what is there")
            if attempt + 1 < TRIES:
                say(f"  ({why} — asked again in {RETRY_WAIT * (attempt + 1)} s)")
                time.sleep(RETRY_WAIT * (attempt + 1))
        raise Unreachable(why)

    def _run(self, command, stdin, timeout):
        body = {"command": command, "timeout": timeout}
        if stdin is not None:
            body["stdin"] = stdin
        req = urllib.request.Request(f"{BASE}/api/computers/{urllib.parse.quote(self.cid, safe='')}/exec",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 60) as r:
                out = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read() or b"{}")
            except ValueError:
                out = {}
            why = f"{self.cid}: the computers app answered {e.code} {out.get('error') or out.get('reason') or ''}"
            if e.code < 500:                              # it refused the call itself: asking again changes nothing
                raise Refused(why.rstrip()) from None
            raise Unreachable(why.rstrip()) from None
        except (OSError, ValueError) as e:
            raise Unreachable(f"{self.cid}: the computers app did not answer ({e})") from None
        if out.get("code") is None:                       # timed out: it may still be running there — never again
            raise Refused(f"{self.cid}: {out.get('reason') or 'the command did not finish'}")
        return out["code"], out.get("stdout") or "", out.get("stderr") or ""

    def stream_argv(self, command):
        """ssh's argv for one long command fed on its stdin, when the app reaches this machine by SSH (hooks/ssh's own
        way: the app builds it); None for a machine reached through a link, whose door runs commands, not streams."""
        try:
            import app                                    # the computers app, in its own container (-w /app)
        except ImportError:
            return None
        rec, bad = app._resolve(self.cid, app.local_gateway())
        if bad or not rec or not rec.get("host"):
            return None
        sec, _ = app._computer_ctx(rec, app.local_gateway())
        return app.ssh_argv(self.cid, rec["host"], rec["port"], rec["user"], sec, command)


class Host:
    """host.py on one machine: from the run's work folder once installed; before that (a dry run, which writes nothing
    anywhere) sent on stdin."""

    def __init__(self, machine, code, work):
        self.m, self.code, self.work, self.installed = machine, code, work, False

    def install(self, files):
        for name, text in files.items():
            rc, out, err = self.m.run(f"mkdir -p {q(self.work)} && cat > {q(self.work + '/' + name)}", stdin=text,
                                      again=True)
            if rc:
                raise Refused(f"{self.m.cid}: could not write {self.work}/{name}: {(err or out).strip()[-300:]}")
        self.installed = True

    def __call__(self, *args, stdin=None, timeout=600, again=False):
        argv = " ".join(q(a) for a in args)
        if self.installed:
            rc, out, err = self.m.run(f"python3 {q(self.work + '/host.py')} {argv}", stdin=stdin, timeout=timeout,
                                      again=again)
        else:
            rc, out, err = self.m.run(f"python3 - {argv}", stdin=self.code, timeout=timeout, again=again)
        line = next((x for x in out.splitlines()[::-1] if x.startswith("RESULT ")), None)
        if not line:
            raise Refused(f"{self.m.cid}: host.py {args[0]} said nothing (exit {rc}: {(err or out).strip()[-300:]})")
        res = json.loads(line[len("RESULT "):])
        if not res.get("ok"):
            raise Refused(f"{self.m.cid}: {res.get('error')}" + "".join(f"\n    {b}" for b in res.get("bad") or []))
        return res

    def read(self, path, offset, length):
        rc, out, err = self.m.run(f"python3 {q(self.work + '/host.py')} read {q(path)} {offset} {length}", timeout=300,
                                  again=True)
        if rc:
            raise Refused(f"{self.m.cid}: could not read {path} at {offset}: {(err or out).strip()[-300:]}")
        return base64.b64decode(out.strip())

    def locked(self, script, stdin=None):
        """A shell script there under this run's lock (host.py's): never beside a place still running from a step
        that was cut off. Its exit code."""
        rc, out, err = self.m.run(f"flock -n -E 75 {q(self.work + '/.lock')} sh -c {q(script)}", stdin=stdin,
                                  timeout=120)
        if rc == 75:
            raise Refused(f"{self.m.cid}: another step of this run is still running there — wait for it, then resume")
        return rc

    def tool(self, *args):
        """meet_move.py there, under this run's lock (host.py's): (exit code, its RESULT/VERIFY line, what it said)."""
        rc, out, err = self.m.run(f"flock -n -E 75 {q(self.work + '/.lock')} python3 {q(self.work + '/meet_move.py')} "
                                  + " ".join(q(a) for a in args), timeout=600)
        if rc == 75:
            raise Refused(f"{self.m.cid}: another step of this run is still running there — wait for it, then resume")
        line = next((x for x in out.splitlines()[::-1] if x.startswith(("RESULT ", "VERIFY "))), None)
        return rc, (json.loads(line.split(" ", 1)[1]) if line else {}), (err or out).strip()[-600:]


class Pieces(io.RawIOBase):
    """One file of the source's stage, read in CHUNK pieces through the computers app; finish() checks that all of it
    came and that its sha256 is the manifest's."""

    def __init__(self, host, path, size, want):
        super().__init__()
        self.host, self.path, self.size, self.want = host, path, size, want
        self.off, self.buf, self.pos, self.h = 0, b"", 0, hashlib.sha256()
        self.t0, self.told = time.time(), 0

    def readable(self):
        return True

    def readinto(self, b):
        if self.pos >= len(self.buf):
            if self.off >= self.size:
                return 0
            n = min(CHUNK, self.size - self.off)
            data = self.host.read(self.path, self.off, n)
            if len(data) != n:
                raise Refused(f"{self.path}: {len(data)} bytes came at {self.off}, not {n}")
            self.h.update(data)
            self.off += n
            self.buf, self.pos = data, 0
            if self.off - self.told >= TELL and self.off < self.size:
                self.told = self.off
                rate = self.off / max(1e-3, time.time() - self.t0)
                say(f"    {os.path.basename(self.path)}: {mb(self.off)} of {mb(self.size)}, {rate / 1e6:.2f} MB/s, "
                    f"~{(self.size - self.off) / rate:.0f} s left")
        k = min(len(b), len(self.buf) - self.pos)
        b[:k] = self.buf[self.pos:self.pos + k]
        self.pos += k
        return k

    def read(self, n=-1):
        """n bytes, or all that is left: tarfile takes a short read for the end of the data, whatever CHUNK is."""
        left = self.size - self.off + len(self.buf) - self.pos
        n = left if n is None or n < 0 else min(n, left)
        out = bytearray()
        while len(out) < n:
            b = bytearray(n - len(out))
            k = self.readinto(b)
            if not k:
                break
            out += b[:k]
        return bytes(out)

    def finish(self):
        if self.off != self.size or self.h.hexdigest() != self.want:
            raise Refused(f"{self.path}: what came is not the manifest's file ({self.off} of {self.size} bytes)")


def carry_stream(argv, items):
    """Every item into one tar stream, read by `tar -x` on the target over SSH."""
    with tempfile.TemporaryFile() as out:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=out, stderr=out)
        try:
            with tarfile.open(fileobj=p.stdin, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for rel, size, mtime, src in items:
                    ti = tarfile.TarInfo(rel)
                    ti.size, ti.mtime, ti.mode = size, mtime, 0o644
                    tar.addfile(ti, src)
                    src.finish()
                    say(f"  carried {rel} ({mb(size)})")
            p.stdin.close()
        except BrokenPipeError:
            pass
        except BaseException:
            p.kill()                                         # the target's tar ends with what it had: never placed
            try:
                p.stdin.close()
            except OSError:
                pass
            p.wait()
            raise
        rc = p.wait()
        out.seek(0)
        said = out.read().decode("utf-8", "replace").strip()[-400:]
    if rc:
        raise Refused(f"the target's tar ended with {rc}: {said}")


def carry_exec(host, staged, items):
    """Every item written by the app's exec, PIECE bytes at a time (a target reached only through a link)."""
    for rel, size, mtime, src in items:
        path, off = f"{staged}/{rel}", 0
        while True:
            data = src.read(PIECE)
            if not data:
                break
            # again: a piece already there is kept (host.py append), so a link that dropped never ends a long carry
            host("append", path, off, stdin=base64.b64encode(data).decode("ascii"), timeout=120, again=True)
            off += len(data)
        if size == 0:
            host("append", path, 0, stdin="", timeout=120, again=True)
        src.finish()
        host("utime", path, mtime, timeout=60, again=True)
        say(f"  carried {rel} ({mb(size)})")


def exists(machine, path):
    rc, out, err = machine.run(f"test -e {q(path)} && echo yes || echo no", timeout=60, again=True)
    if rc or out.strip() not in ("yes", "no"):
        raise Refused(f"{machine.cid}: cannot tell whether {path} is there: {(err or out).strip()[-200:]}")
    return out.strip() == "yes"


def room_for(machine, loc, carry, place):
    """Refused unless the machine has room for what is still to be written there: the carried copy (in the work folder)
    and the placed one (in the recordings volume), each with a margin; one filesystem is counted once for both."""
    if loc.get("free") is None:
        return
    short = []
    if loc.get("same_fs", True):
        if loc["free"] < carry + place + MARGIN:
            short.append(f"{mb(loc['free'])} free, {mb(carry + place + MARGIN)} needed (carried, placed, a margin)")
    else:
        if loc["work_free"] < carry + MARGIN:
            short.append(f"{mb(loc['work_free'])} free for the carried copy, {mb(carry + MARGIN)} needed")
        if loc["free"] < place + MARGIN:
            short.append(f"{mb(loc['free'])} free for the meeting, {mb(place + MARGIN)} needed")
    if short:
        raise Refused(f"{machine.cid}: " + "; ".join(short))


def backup_of(raw, room, have):
    """The source's manifest, refused unless it is a whole backup of this room that holds every file the source has
    now (a resume after the source changed — a new recording, a page written — starts a fresh run instead)."""
    try:
        man = json.loads(raw)
    except ValueError:
        raise Refused("the backup's manifest is not whole — start a fresh run") from None
    files = man.get("files") or {}
    if (man.get("format") != "dgo-meet-move/1" or man.get("room") != room or not man.get("units") or not files
            or any("mtime" not in i for i in files.values())):
        raise Refused(f"the backup's manifest is not a whole backup of «{room}» — start a fresh run")
    differ = [f["rel"] for f in have["files"] if (files.get(f["rel"]) or {}).get("size") != f["size"]]
    if differ:
        raise Refused(f"the source changed since this run's backup ({', '.join(differ[:4])}) — start a fresh run")
    return man


def drive_step(S, src, container, room, man):
    """The meeting's folder in the source's Drive, to Drive's trash (host.py drive): after the remove, never before."""
    stems = sorted({m["stem"] for m in (STAMP_RE.match(r) for r in man["files"]) if m})
    for f in S("drive", container, room, json.dumps(stems), "--trash")["folders"]:
        if f.get("other"):
            say(f"{src.cid} Drive {f['path']}: kept — {', '.join(f['other'])}")
        else:
            say(f"{src.cid} Drive {f['path']}: to Drive's trash ({', '.join(f['files']) or 'empty'})"
                + ("" if f.get("trashed") else " — Drive trashed nothing"))


def move(room, src, dst, code, tool, remove=False, dry_run=False, src_root=None, dst_root=None, resume=None):
    if resume and not re.fullmatch(re.escape(room) + r"-\d{8}-\d{6}", resume):
        raise Refused(f"--resume takes a run of «{room}» as a run printed it ({room}-<yyyymmdd>-<hhmmss>), not {resume!r}")
    run = resume or f"{room}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    S, D = Host(src, code, f"{src.work_root}/{run}"), Host(dst, code, f"{dst.work_root}/{run}")
    work, staged, there_staged = S.work, S.work + "/staged", D.work + "/staged"
    s_loc = {"root": src_root, "container": None} if src_root else S("locate", S.work, again=True)
    d_loc = {"root": dst_root, "free": None} if dst_root else D("locate", D.work, again=True)
    if s_loc.get("machine") and s_loc["machine"] == d_loc.get("machine"):
        raise Refused(f"{src.cid} and {dst.cid} are the same machine ({s_loc['machine']}): its backup and the carried "
                      f"copy would be one folder")
    have = S("list", s_loc["root"], room, again=True)
    if not have["units"] and resume and exists(src, work + "/removed.json"):
        # removed in this run, after the target verified it (host.py remove leaves removed.json): what is left is Drive
        say(f"«{room}» was removed from {src.cid} in this run already; its backup is {src.cid}:{staged}")
        if remove and s_loc.get("container") and not dry_run:
            rc, raw, err = src.run(f"cat {q(staged + '/manifest.json')}", again=True)
            if rc:
                raise Refused(f"{src.cid}: the backup's manifest cannot be read: {(err or raw).strip()[-300:]}")
            S.installed = True
            drive_step(S, src, s_loc["container"], room, backup_of(raw, room, {"files": []}))
        return 0
    if not have["units"]:
        raise Refused(f"{src.cid} has no recorded meeting of «{room}»")
    if have["recording"]:
        raise Refused(f"«{room}» is not finished on {src.cid} yet ({', '.join(have['recording'])}): Jibri or finalize.sh "
                      f"is still writing it")
    there = D("list", d_loc["root"], room, again=True)
    size = have["bytes"]
    ours = {(f["rel"], f["size"]) for f in have["files"]}
    placed = sum(f["size"] for f in there["files"] if (f["rel"], f["size"]) in ours)
    say(f"«{room}» on {src.cid} ({s_loc.get('container') or s_loc['root']}): {len(have['files'])} files, {mb(size)}, "
        f"in {', '.join(have['units'])}")
    for f in have["files"]:
        say(f"  {f['rel']}  {f['size']:,}")
    if there["units"]:
        say(f"{dst.cid} has some of it already ({', '.join(there['units'])}): a file there with the same bytes is "
            f"kept, one with other bytes refuses the run")
    if not resume:
        room_for(dst, d_loc, size, size - placed)
    say(f"→ {dst.cid} ({d_loc.get('container') or d_loc['root']}), work folder {work}"
        + ("; then removed from the source" if remove else ""))
    if dry_run:
        say("dry run: nothing was written")
        return 0
    say(f"run {run} — if it stops, the same command with --resume {run} continues it")
    files = {"host.py": code, "meet_move.py": tool}
    S.install(files)
    D.install(files)
    if resume and exists(src, staged + "/manifest.json"):
        say(f"the source's backup is there from this run: {src.cid}:{staged}")
    else:
        st = S("stage", s_loc["root"], room, staged)    # (a stage that stopped before its manifest is made again)
        say(f"the source's backup: {src.cid}:{staged} ({st['files']} files, {mb(st['bytes'])}, "
            f"manifest.json beside them)")
    rc, raw, err = src.run(f"cat {q(staged + '/manifest.json')}", again=True)
    if rc:
        raise Refused(f"{src.cid}: the manifest cannot be read: {err.strip()[-300:]}")
    man = backup_of(raw, room, have)
    items = [("recordings/" + rel, info["size"], int(info["mtime"]),
              Pieces(S, f"{staged}/recordings/{rel}", info["size"], info["sha256"]))
             for rel, info in sorted(man["files"].items())]
    items.append(("manifest.json", len(raw.encode()), int(time.time()),
                  Pieces(_Local(raw.encode()), "manifest.json", len(raw.encode()),
                         hashlib.sha256(raw.encode()).hexdigest())))
    carried = there_already = False
    if resume and exists(dst, there_staged + "/manifest.json"):
        # manifest.json is carried last: there, the copy before it is whole — and place checks every file against it
        rc, theirs, _ = dst.run(f"cat {q(there_staged + '/manifest.json')}", again=True)
        carried = rc == 0 and theirs == raw
    if not carried and placed == size:
        # every file is on the target already (an earlier run placed it): verify, which reads the manifest alone where
        # nothing is rewritten, says whether byte for byte — then nothing needs carrying
        rc = D.locked(f"rm -rf {q(there_staged)} && mkdir -p {q(there_staged)} && "
                      f"cat > {q(there_staged + '/manifest.json')}", stdin=raw)
        rc, res, _ = D.tool("verify", there_staged, d_loc["root"]) if rc == 0 else (rc, {}, "")
        there_already = rc == 0 and bool(res) and not res.get("bad")
    if there_already:
        say(f"{dst.cid} has every file of it already, byte for byte (verify): nothing to carry or place")
    elif carried:
        say(f"carried already in this run: {dst.cid}:{there_staged}")
        if resume and not dst_root:
            room_for(dst, D("locate", D.work, again=True), 0, size - placed)
    else:
        D.locked(f"rm -rf {q(there_staged)}")              # a part of this run's own carried copy
        if not dst_root:
            room_for(dst, D("locate", D.work, again=True), size, size - placed)
        argv = dst.stream_argv(f"mkdir -p {q(there_staged)} && tar -xf - -C {q(there_staged)}")
        say(f"carrying {mb(size)} to {dst.cid} " + ("over SSH, one stream" if argv else "through the link, by exec"))
        t0 = time.time()
        if argv:
            carry_stream(argv, items)
        else:
            carry_exec(D, there_staged, items)
        say(f"carried in {time.time() - t0:.0f} s")
    if not there_already:
        rc, res, said = D.tool("place", there_staged, d_loc["root"])
        if rc or not res:
            raise Refused(f"{dst.cid}: place refused: {said}")
        say(f"placed on {dst.cid}: {res.get('created')} written, {res.get('kept')} already there with the same bytes")
    rc, res, said = D.tool("verify", there_staged, d_loc["root"])
    if rc or not res or res.get("bad"):
        raise Refused(f"{dst.cid}: verify found {res.get('bad') or said}")
    say(f"verified on {dst.cid}: {res['files']} files, every sha256 the source's")
    dst.run(f"rm -rf {q(D.work)}", timeout=120, again=True)   # the carried copy: the placed one is verified
    if not remove:
        say(f"the source keeps the meeting; its backup copy is {src.cid}:{staged}")
        return 0
    gone = S("remove", s_loc["root"], staged)
    say(f"removed from {src.cid}: {', '.join(gone['removed']) or '(already, in this run)'} — the backup stays at {staged}")
    if s_loc.get("container"):
        try:
            drive_step(S, src, s_loc["container"], room, man)
        except (Refused, Unreachable) as e:
            raise Refused(f"the meeting is moved and removed from {src.cid}; only its folder in that office's Drive is "
                          f"left as it was ({e}) — the same command with --resume {run} tries that again") from None
    return 0


class _Local:
    """A source for Pieces that is already here (the manifest, read once)."""

    def __init__(self, data):
        self.data = data

    def read(self, path, offset, length):
        return self.data[offset:offset + length]


def main(argv):
    for stream in (sys.stdout, sys.stderr):    # Hebrew on every line: UTF-8 whatever the console's code page (G10)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    # This process shares the computers app's 160 MB: past it, the kernel is to take the mover, never the app (the app
    # restarted under a 16 MB carry, 2026-11-19 — meet-start's helpers ask the same, EXU-20)
    try:
        with open("/proc/self/oom_score_adj", "w") as adj:
            adj.write("1000")
    except OSError:
        pass
    args, opts, flags = [], {}, set()
    it = iter(argv)
    for a in it:
        if a in ("--from", "--to", "--src-root", "--dst-root", "--resume"):
            opts[a] = next(it, "")
        elif a in ("--remove", "--dry-run"):
            flags.add(a)
        elif a.startswith("-"):
            print(f"meet move: {a}?\n{USAGE}", file=sys.stderr)
            return 2
        else:
            args.append(a)
    room = (args[0] if len(args) == 1 else "").strip().lower()
    if not ROOM_RE.fullmatch(room) or not opts.get("--from") or not opts.get("--to"):
        print(USAGE, file=sys.stderr)
        return 2
    src, dst = Machine(cid_of(opts["--from"])), Machine(cid_of(opts["--to"]))
    if src.cid == dst.cid:
        print("meet move: --from and --to are the same machine", file=sys.stderr)
        return 2
    try:
        return move(room, src, dst, os.environ["MEET_MOVE_HOST"], os.environ["MEET_MOVE_TOOL"],
                    remove="--remove" in flags, dry_run="--dry-run" in flags,
                    src_root=opts.get("--src-root"), dst_root=opts.get("--dst-root"), resume=opts.get("--resume"))
    except Refused as e:
        print(f"meet move: {e}", file=sys.stderr)
        return 1
    except Unreachable as e:
        print(f"meet move: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
