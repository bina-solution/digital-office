"""computers.transfer — copy a docker volume from one machine to another, RESUMAABLY.

Why this lives in `computers`
-----------------------------
The two machines are reached with THIS app's key (the office key, minted into this app's volume and
approved in each machine's `authorized_keys`). So the bytes pass through this container: ssh
encrypts the leg out of the source and the leg into the destination, and **no key ever travels** —
neither machine is given a credential for the other, and a machine the owner has not approved cannot
be either end of a copy. That property is the whole reason a transfer is an op here instead of a
script that scp's between two hosts.

The shape, and why it can resume
--------------------------------
    source volume ──(ssh: tar -cf - .)──► this container ──(ssh: cat >> stage)──► destination
                                        (64 KiB…256 KiB chunks)                        │
                              destination: tar -xf stage -C <volume>/_data ◄──────────┘

`tar czf` was the obvious first shape and it is a dead end: gzip's output depends on where the stream
was cut, so a link that drops at 60% can only start again at 0. The archive is therefore
UNCOMPRESSED and byte-addressable, and a copy resumes by BYTE OFFSET:

  * the destination holds the archive in flight in ONE staging file (`/var/lib/bina-transfer/`),
    deliberately outside the volume — the volume's own `_data` is what it is finally extracted into,
    and it stays untouched until the archive is complete and verified;
  * an attempt resumes from the staging file's OWN size (`tail -c +N+1` on the source, `cat >>` on
    the destination), so the offset is read off the disk that holds the bytes rather than remembered
    by a process that may itself have died — a restart of this container resumes too;
  * the first attempt records a fingerprint of the volume (paths, sizes, mtimes) beside the staging
    file. A later attempt that finds a DIFFERENT fingerprint refuses instead of splicing two
    different archives together; `restart=true` is the deliberate "start over".

An `ok` job means three things, not one: the staging file reached the measured total size, its bytes
matched the source's own `tar` output byte for byte (`verify` — one read at each end, no network),
and the archive extracted onto the destination volume. Anything less is reported as it is.

Jobs, not requests
------------------
A copy of a real volume outlives an HTTP request, so `start()` returns a job id immediately and
`status()` is the contract — with `bytes`/`percent`/`rate`/`eta` live, so a long copy is observable
instead of an opaque wait. ONE transfer runs at a time: the office's link and the two machines are
shared, and two copies at once is how both of them end up slow. `cancel()` stops the streams and
KEEPS the staging file, so cancelling is how a copy is paused.
"""
from __future__ import annotations

import json
import logging
import os
import select
import shlex
import subprocess
import threading
import time
import uuid
from collections import deque

log = logging.getLogger("computers.transfer")

#: Refuse a volume above this: the destination is usually the smaller machine, and a copy that fills
#: its disk is not a failure that can be undone from here.
MAX_BYTES = int(os.environ.get("COMPUTER_TRANSFER_MAX_BYTES", str(12 * 1024 ** 3)))
CHUNK = 256 * 1024
#: A relay that moves no bytes for this long is a dead link, not a slow one. Without it a dropped
#: connection hangs the job forever, which reads exactly like "still copying".
STALL_SECONDS = int(os.environ.get("COMPUTER_TRANSFER_STALL_S", "180"))
#: Where a docker volume's files live on the host. `docker volume create` guarantees it exists.
VOL_ROOT = "/var/lib/docker/volumes"
#: The archive in flight, ON THE DESTINATION. Outside the volumes on purpose (see the docstring).
STAGE_DIR = os.environ.get("COMPUTER_TRANSFER_STAGE_DIR", "/var/lib/bina-transfer")

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_active: str | None = None

_STEP_TITLES = {
    "prepare": "הכנה ובדיקות",
    "stream": "העברת הבתים",
    "verify": "אימות הבתים",
    "extract": "חילוץ ל-volume ביעד",
    "done": "סיום",
}


class Cancelled(Exception):
    """The caller asked for a stop. Not a failure: the staging file stays and a later run resumes."""


class TransferError(RuntimeError):
    """A refusal with a NAME, so a caller can act on it instead of matching Hebrew text.

    `code` is the machine-readable half: `source_changed` is the one a caller meets in practice — the
    volume moved under a half-finished copy, and the only correct answers are "start over" (restart)
    or "do not copy"."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def volume_path(name: str) -> str:
    return f"{VOL_ROOT}/{name}/_data"


def stage_path(src_vol: str, dst_vol: str) -> str:
    return f"{STAGE_DIR}/{src_vol}__{dst_vol}.tar"


def meta_path(src_vol: str, dst_vol: str) -> str:
    return stage_path(src_vol, dst_vol) + ".json"


def q(s: str) -> str:
    return shlex.quote(s)


def _bash(script: str) -> str:
    """A multi-stage remote command, run by bash so `set -o pipefail` and PIPESTATUS are real.

    Without pipefail the exit code of `tar … | tail …` is tail's, which is 0 for a truncated archive
    — the failure that matters most here would be the one reported as success."""
    return "bash -c " + q(script)


def _run(argv: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except OSError as e:
        return 255, "", str(e)
    dec = lambda b: (b or b"").decode("utf-8", "replace")          # noqa: E731
    return p.returncode, dec(p.stdout), dec(p.stderr)


def _drain(pipe, sink: list) -> None:
    """Read a subprocess's stderr to EOF in the background.

    A pipe nobody reads fills at 64 KiB and then blocks the writer — a copy that dies of its own
    error message. tar's stderr is short in practice and must never be able to do that."""
    try:
        for line in iter(pipe.readline, b""):
            sink.append(line.decode("utf-8", "replace"))
            del sink[:-200]
    except Exception:                              # noqa: BLE001 — a drain thread never reports
        pass
    finally:
        try:
            pipe.close()
        except Exception:                          # noqa: BLE001
            pass


def _append(job: dict, line: str) -> None:
    with _lock:
        job.setdefault("log", []).append({"t": int(time.time()), "line": line[:500]})
        del job["log"][:-200]


def _tap(job: dict, phase: str) -> None:
    with _lock:
        job["phase"] = phase
        job["phase_title"] = _STEP_TITLES.get(phase, phase)


# ── the source: what we are copying, and is it still the same thing? ────────────
_FP = ("find . -printf '%P|%s|%T@\\n' 2>/dev/null | LC_ALL=C sort | sha256sum | cut -d' ' -f1")
#: sha256 of nothing. A source path that does not exist still hashes cleanly, so the empty digest is
#: rejected by name rather than compared — "the volume is a directory that is not there" must not
#: read as "the volume is unchanged".
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _fingerprint(argv_for, machine: str, path: str) -> str:
    code, out, err = _run(argv_for(machine,
                                   _bash(f"test -d {q(path)} || exit 3; cd {q(path)} && {_FP}")),
                          timeout=600)
    fp = (out or "").strip().splitlines()[-1].strip() if out.strip() else ""
    if code != 0 or len(fp) != 64 or fp == _EMPTY_SHA:
        raise RuntimeError(f"לא ניתן לזהות את תוכן ה-volume במקור ({path}): "
                           f"{err.strip()[:200] or fp[:200]}")
    return fp


def _tar_bytes(argv_for, machine: str, path: str) -> int:
    """The archive's exact size, measured on the source (`tar … | wc -c`).

    One extra local read, and it buys a progress bar with a real denominator and a completion test
    that does not depend on the sender's word. Optional (`measure=false`) for a volume so large that
    reading it twice is the expensive part."""
    code, out, err = _run(argv_for(machine,
                                   _bash(f"test -d {q(path)} || exit 3; tar -C {q(path)} -cf - . | wc -c")),
                          timeout=6 * 3600)
    try:
        n = int((out or "").strip().splitlines()[-1].strip())
    except (ValueError, IndexError):
        raise RuntimeError(f"לא ניתן למדוד את גודל הארכיון במקור: {err.strip()[:200]}")
    if n <= 0:
        raise RuntimeError("הארכיון במקור ריק — אין מה להעביר")
    return n


def _data_bytes(argv_for, machine: str, path: str) -> int:
    code, out, _ = _run(argv_for(machine, f"du -sb {q(path)} 2>/dev/null | cut -f1"), timeout=600)
    try:
        return int((out or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def _sha256(argv_for, machine: str, what: str) -> str:
    """sha256 of a remote FILE, or of the source's tar stream (`what` is a prepared command)."""
    code, out, err = _run(argv_for(machine, what), timeout=6 * 3600)
    val = (out or "").strip().splitlines()[-1].strip() if out.strip() else ""
    if code != 0 or len(val) != 64:
        raise RuntimeError(f"חישוב ה-checksum נכשל: {err.strip()[:200] or val[:120]}")
    return val


# ── the worker ─────────────────────────────────────────────────────────────────
def _copy(job: dict, argv_for) -> None:
    """The worker. Every exit path writes the job's state — a copy that dies must not read as
    'running' forever."""
    global _active
    src_vol, dst_vol = job["volume"], job["dest_volume"]
    src_path, dst_path = volume_path(src_vol), volume_path(dst_vol)
    stage, meta = stage_path(src_vol, dst_vol), meta_path(src_vol, dst_vol)
    p_src = p_dst = None
    try:
        # ── prepare ────────────────────────────────────────────────────────────
        _tap(job, "prepare")
        code, out, err = _run(argv_for(job["to"],
                                       f"docker volume create {q(dst_vol)} && "
                                       f"mkdir -p {q(STAGE_DIR)} && chmod 700 {q(STAGE_DIR)} && "
                                       f"test -d {q(dst_path)}"),
                              timeout=180)
        if code != 0:
            raise RuntimeError(f"יצירת ה-volume ביעד נכשלה: {err.strip() or out.strip()}")
        _append(job, f"ה-volume ביעד מוכן: {dst_vol}")

        fp = _fingerprint(argv_for, job["from"], src_path)
        job["fingerprint"] = fp[:12]
        code, out, _ = _run(argv_for(job["to"], f"stat -c %s {q(stage)} 2>/dev/null || echo 0"), 60)
        have = int((out or "0").strip().splitlines()[-1] or 0)
        old_meta = _read_meta(argv_for, job["to"], meta)
        if have:
            same = old_meta.get("fingerprint") == fp
            if not same and not job["restart"]:
                raise TransferError(
                    "ה-volume במקור השתנה מאז ניסיון ההעברה הקודם — אי אפשר להמשיך מאותה נקודה. "
                    "הרץ שוב עם restart=true כדי להתחיל מהתחלה.", code="source_changed")
            if job["restart"] or not same:
                _run(argv_for(job["to"], f"rm -f {q(stage)} {q(meta)}"), 60)
                have = 0
        job["resumed_from"] = have
        # The bytes already on the destination ARE progress: a resumed copy that reports 0% until its
        # first new chunk arrives reads as "nothing happened" to whoever is watching it.
        job["done_bytes"] = have

        total = int(old_meta.get("total") or 0) if (have and job["resume"]) else 0
        if not total and job["measure"]:
            total = _tar_bytes(argv_for, job["from"], src_path)
        job["total"] = total or None
        data = _data_bytes(argv_for, job["from"], src_path)
        job["source_bytes"] = data
        # Room needed on the destination: the archive in flight AND the copy it is extracted into.
        # In direct mode there is no archive to keep, so only the extracted copy has to fit.
        need = int((total or data) * 1.02 + data * 1.02) if job["resume"] else int(data * 1.05)
        where = STAGE_DIR if job["resume"] else dst_path
        code, out, _ = _run(argv_for(job["to"], f"df -B1 --output=avail {q(where)} | tail -1"), 60)
        free = int((out or "0").strip().splitlines()[-1].split()[0] or 0) if out.strip() else 0
        job["dest_free_bytes"] = free
        if free and need and free < need:
            raise RuntimeError(
                f"אין מקום ביעד ({where}): נדרשים {need / 1024 ** 3:.1f}GB פנויים "
                f"(ארכיון בדרך + התוכן שחולץ) ויש {free / 1024 ** 3:.1f}GB")
        if data > MAX_BYTES:
            raise RuntimeError(f"ה-volume גדול מהמותר ({MAX_BYTES // (1024 ** 3)}GB) — הופסק")
        _write_meta(argv_for, job["to"], meta, {"fingerprint": fp, "total": total, "data": data,
                                                "src_volume": src_vol, "dest_volume": dst_vol,
                                                "stage": stage, "started": job["started"]})
        _append(job, f"מקור: {data / 1024 ** 2:.0f}MB · ארכיון: "
                     f"{(str(round(total / 1024 ** 2)) + 'MB') if total else 'לא נמדד'} · "
                     f"פנוי ביעד: {free / 1024 ** 3:.1f}GB" +
                     (f" · ממשיך מ-{have / 1024 ** 2:.0f}MB" if have else ""))

        # ── stream ─────────────────────────────────────────────────────────────
        _tap(job, "stream")
        job["stream_started"] = int(time.time())
        if job["resume"]:
            src_cmd = _bash(f"set -o pipefail; tar -C {q(src_path)} -cf - . | tail -c +{have + 1}")
            dst_cmd = _bash(f"cat >> {q(stage)}")
        else:
            # No staging, no resume: straight into the destination volume. Chosen for a copy that
            # cannot fit twice on the destination disk — and a drop means starting over.
            src_cmd = _bash(f"tar -C {q(src_path)} -cf - .")
            dst_cmd = _bash(f"rm -rf {q(dst_path)} && mkdir -p {q(dst_path)} && "
                            f"tar -xf - -C {q(dst_path)}")
            _append(job, "מצב ישיר (ללא קובץ ביניים): ניתוק יחייב התחלה מהתחלה")

        p_src = subprocess.Popen(argv_for(job["from"], src_cmd), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        p_dst = subprocess.Popen(argv_for(job["to"], dst_cmd), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        err_src, err_dst = [], []
        threading.Thread(target=_drain, args=(p_src.stderr, err_src), daemon=True).start()
        threading.Thread(target=_drain, args=(p_dst.stderr, err_dst), daemon=True).start()
        with _lock:
            job["pids"] = [p_src.pid, p_dst.pid]
        moved, last_log = 0, time.time()
        rate = deque(maxlen=30)
        job["state"] = "running"
        try:
            while True:
                if job.get("cancel"):
                    raise Cancelled()
                r, _, _ = select.select([p_src.stdout], [], [], 5)
                if not r:
                    if moved and time.time() - rate[-1][1] > STALL_SECONDS:
                        raise RuntimeError(f"ההעברה לא התקדמה {STALL_SECONDS} שניות — החיבור כנראה נפל")
                    continue
                chunk = p_src.stdout.read1(CHUNK)
                if not chunk:
                    break
                p_dst.stdin.write(chunk)
                moved += len(chunk)
                now = time.time()
                rate.append((moved, now))
                with _lock:
                    job["bytes"] = moved
                    job["done_bytes"] = have + moved
                if have + moved > MAX_BYTES:
                    raise RuntimeError(f"ה-volume גדול מהמותר ({MAX_BYTES // (1024 ** 3)}GB) — הופסק")
                if now - last_log >= 20:
                    last_log = now
                    _append(job, _progress_line(job, moved, now))
        except BrokenPipeError:
            pass                                   # the destination died; its stderr says why below
        finally:
            try:
                p_dst.stdin.close()
            except (OSError, ValueError):
                pass
        try:
            rc_dst, rc_src = p_dst.wait(), p_src.wait()
        except Exception:                          # noqa: BLE001
            rc_dst = rc_src = -1
        with _lock:
            job["bytes"] = moved
            job["done_bytes"] = have + moved
            job.pop("pids", None)
        if job.get("cancel"):
            raise Cancelled()
        if rc_src != 0:
            raise RuntimeError(f"הקריאה מהמכונה המקורית נכשלה (קוד {rc_src}): "
                               f"{''.join(err_src).strip()[:300]}")
        if rc_dst != 0:
            raise RuntimeError(f"הכתיבה במכונת היעד נכשלה (קוד {rc_dst}): "
                               f"{''.join(err_dst).strip()[:300]}")
        job["bytes_sent"] = moved

        # ── verify ─────────────────────────────────────────────────────────────
        _tap(job, "verify")
        code, out, err = _run(argv_for(job["to"], f"stat -c %s {q(stage)} 2>/dev/null || echo 0"), 60)
        got = int((out or "0").strip().splitlines()[-1] or 0) if out.strip() else 0
        job["staged_bytes"] = got
        if not job["resume"]:
            _append(job, "אין אימות בתים במצב ישיר — החשבון נחתך בזמן ההעברה")
        else:
            if job["total"] and got != job["total"]:
                raise RuntimeError(f"הארכיון אינו שלם: {got} בתים ביעד מול {job['total']} במקור")
            if got < have:
                raise RuntimeError(f"קובץ הביניים קטן מההתחלה ({got} < {have}) — היעד התאפס")
            if job["verify"]:
                _append(job, "מאמת את הארכיון מול המקור (sha256)")
                s_dst = _sha256(argv_for, job["to"], f"sha256sum {q(stage)} | cut -d' ' -f1")
                s_src = _sha256(argv_for, job["from"],
                                _bash(f"set -o pipefail; tar -C {q(src_path)} -cf - . | "
                                      f"sha256sum | cut -d' ' -f1"))
                if s_dst != s_src:
                    raise RuntimeError("האימות נכשל: הארכיון ביעד שונה מהמקור "
                                       f"({s_dst[:12]} מול {s_src[:12]}) — ה-volume ביעד לא נגוע")
                job["sha256"] = s_src
                _append(job, f"האימות עבר: sha256 {s_src[:12]}")

        # ── extract ────────────────────────────────────────────────────────────
        if job["resume"]:
            _tap(job, "extract")
            code, out, err = _run(argv_for(job["to"],
                                           _bash(f"set -e; rm -rf {q(dst_path)}; mkdir -p {q(dst_path)}; "
                                                 f"tar -xf {q(stage)} -C {q(dst_path)}; "
                                                 f"rm -f {q(stage)} {q(meta)}; "
                                                 f"du -sb {q(dst_path)} | cut -f1")),
                                  timeout=6 * 3600)
            if code != 0:
                raise RuntimeError(f"חילוץ הארכיון ביעד נכשל: {err.strip()[:300]}")
            grown = int((out or "0").strip().splitlines()[-1] or 0) if out.strip() else 0
            job["dest_bytes"] = grown
            _append(job, f"חולץ ל-{dst_path} ({grown / 1024 ** 2:.0f}MB) וקובץ הביניים נמחק")

        # ── done ───────────────────────────────────────────────────────────────
        _tap(job, "done")
        job.update(state="ok", ended=int(time.time()), error=None)
        _append(job, f"הועתקו {have + moved} בתים")
    except Cancelled:
        job.update(state="cancelled", ended=int(time.time()), error=None)
        _append(job, f"הופסק לבקשת המשתמש ב-{(job.get('done_bytes') or 0) / 1024 ** 2:.0f}MB — "
                     f"הקובץ ביעד נשמר והרצה נוספת תמשיך ממנו")
    except Exception as e:                          # noqa: BLE001 — the job's state is the report
        job.update(state="error", ended=int(time.time()), error=f"{type(e).__name__}: {e}",
                   error_code=getattr(e, "code", ""))
        _append(job, f"✗ {e}")
        log.warning("transfer %s failed: %s", job["id"], e)
    finally:
        for p in (p_src, p_dst):
            if p is not None and p.poll() is None:
                try:
                    p.kill()
                except Exception:                  # noqa: BLE001
                    pass
        with _lock:
            job.pop("pids", None)
            if _active == job["id"]:
                _active = None


def _progress_line(job: dict, moved: int, now: float) -> str:
    done = (job.get("resumed_from") or 0) + moved
    total = job.get("total") or 0
    el = max(1.0, now - job["started"])
    rate = done / el
    bit = f"{done / 1024 ** 2:.0f}MB"
    if total:
        bit += f" / {total / 1024 ** 2:.0f}MB ({100.0 * done / total:.0f}%)"
    bit += f" · {rate / 1024 ** 2:.1f}MB/s"
    if total and rate > 0 and done < total:
        left = int((total - done) / rate)
        bit += f" · נותרו ~{left // 60}ד׳{left % 60:02d}שנ׳" if left >= 60 else f" · נותרו ~{left}שנ׳"
    return bit


def _read_meta(argv_for, machine: str, meta: str) -> dict:
    code, out, _ = _run(argv_for(machine, f"cat {q(meta)} 2>/dev/null || true"), 60)
    try:
        return json.loads(out or "{}") or {}
    except ValueError:
        return {}


def _write_meta(argv_for, machine: str, meta: str, data: dict) -> None:
    payload = q(json.dumps(data, ensure_ascii=False))
    _run(argv_for(machine, f"printf %s {payload} > {q(meta)} && chmod 600 {q(meta)}"), 60)


def _public(job: dict) -> dict:
    row = {k: v for k, v in job.items() if not k.startswith("_")}
    row["log"] = list(job.get("log") or [])
    total = job.get("total") or 0
    done = job.get("done_bytes") or 0
    row["percent"] = round(100.0 * done / total, 1) if total else None
    # The rate is over the bytes THIS attempt moved, counted from the moment the stream opened: a
    # resumed copy that divides everything (including what was already there, and the minutes spent
    # measuring the archive) by the wall clock reports a speed and an ETA that are both fiction.
    now = int(time.time())
    el = max(1, (job.get("ended") or now) - (job.get("stream_started") or job["started"]))
    row["rate_bps"] = int((job.get("bytes") or 0) / el)
    row["eta_s"] = int((total - done) / row["rate_bps"]) if (total and done < total and row["rate_bps"]) else None
    return row


def start(argv_for, frm: str, to: str, volume: str, dest_volume: str | None = None,
          restart: bool = False, verify: bool = True, measure: bool = True,
          resume: bool = True) -> dict:
    """Begin the copy. Returns the job row — the caller polls `status(job_id)`.

    `argv_for(machine_id, command)` builds the ssh argv for a machine (owned by app.py, which holds
    the fleet and the key). Nothing here knows a host, a user or a path outside the two volumes;
    `restart` wipes a previous staging file instead of resuming it, `resume=false` copies straight
    into the destination volume (no staging file, no resume), `verify=false` skips the sha256
    comparison, `measure=false` skips the source-side size measurement.
    """
    global _active
    if not frm or not to or not volume:
        return {"error": "חסרים from/to/volume"}
    if frm == to:
        return {"error": "המקור והיעד הם אותה מכונה"}
    with _lock:
        if _active:
            return {"error": "העברה אחרת כבר רצה", "active": _active,
                    "active_job": _jobs.get(_active, {}).get("volume")}
        job = {"id": uuid.uuid4().hex[:12], "from": frm, "to": to, "volume": volume,
               "dest_volume": dest_volume or volume, "state": "queued", "phase": None,
               "bytes": 0, "done_bytes": 0, "total": None, "resumed_from": 0,
               "restart": bool(restart), "verify": bool(verify), "measure": bool(measure),
               "resume": bool(resume),
               "started": int(time.time()), "ended": None, "error": None, "log": []}
        _jobs[job["id"]] = job
        _active = job["id"]
    _append(job, f"{volume} → {job['dest_volume']} על {to}")
    threading.Thread(target=_copy, args=(job, argv_for), daemon=True,
                     name=f"transfer-{job['id']}").start()
    return {"job": _public(job)}


def status(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return _public(job) if job else None


def jobs() -> list[dict]:
    with _lock:
        return [_public(j) for j in _jobs.values()]


def cancel(job_id: str) -> dict:
    """Stop an attempt and KEEP what reached the destination — that is what makes it a pause.

    The staging file is deliberately not removed here: the size of that file is the resume point."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return {"error": "אין העברה כזו"}
        if job["state"] not in ("queued", "running"):
            return {"error": f"ההעברה כבר {job['state']}", "job": _public(job)}
        job["cancel"] = True
        pids = list(job.get("pids") or [])
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    return {"stopping": job_id, "done_bytes": job.get("done_bytes")}
