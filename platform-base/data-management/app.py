"""data-management — the platform's backup and restore service.

THE ONE RULE THIS FILE EXISTS TO ENFORCE

    There is ONE implementation of every operation, and it lives here. The web UI in static/ is a
    client of this API. `bbox data view|export|import` are clients of this API. Neither reimplements
    anything, and neither talks to docker directly. A CLI that computes its own inventory and a UI
    that computes a second one is how the two drift and how a store goes missing from an archive
    nobody opens until the old machine is gone.

    inventory.py  = what data exists          (single point of logic)
    this file     = how it is reached          (HTTP, the only interface)
    static/       = one client
    hooks/*       = another client

WHAT IT DRIVES

    Export/import are NOT reimplemented here either — scripts/deployment-archive.py already owns
    the archive format, and export and import must agree byte-for-byte, so they stay one program.
    This service runs it as a subprocess and streams its progress. Adding a second archiver would
    reintroduce exactly the duplication this file forbids.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import pathlib
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import inventory as INV
import plan as PLAN
import pull as PULL
import restic_store as REPO_STORE
import backup_run as BACKUP

REPO = pathlib.Path(os.environ.get("DEPLOYMENT_PATH", "/deployment"))
ARCHIVE_ROOT = pathlib.Path(os.environ.get("DATA_ARCHIVE_ROOT", "/archives"))
ARCHIVER = REPO / "scripts" / "deployment-archive.py"

app = FastAPI(title="Data Management", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1024)

# The herd store's door (app.json `backup-store`, a door with no tile, DGO-945) is how a LINKED office
# reaches this service, and through it the herd store and nothing else: /repo/ and /api/repo-runs. The
# serving office narrows the door's paths only when its `serve.services` declares them, so this service
# holds the line itself, by the name the request was routed under (the door keeps the asker's Host, and
# routes by it). Exports, restores, archives and the page are never reached through it.
STORE_DOOR = "backup-store"


@app.middleware("http")
async def _store_door_only(request, call_next):
    if (request.headers.get("host") or "").split(":", 1)[0].split(".", 1)[0].lower() == STORE_DOOR:
        path = request.url.path
        if not (path.startswith("/repo/") or path == "/api/repo-runs"):
            return JSONResponse({"detail": "through the herd store's door only the store answers"}, status_code=404)
    return await call_next(request)
# restic's REST backend over the generic drive (restic_store.py, DGO-1513). Registered here, before
# every other route, so the page fallback at the end of this file can never answer a /repo path.
app.include_router(REPO_STORE.router)

# In-process job table. Deliberately not a database: a backup job is meaningful only while this
# process lives, and a job row that outlives the process it describes is a lie about what is running.
JOBS: dict[str, dict] = {}

# ── the inventory snapshot ──────────────────────────────────────────────────────────────────────
#
# A full sweep takes ~110s on this host, and 91s of that is the bind section alone (compose config
# plus walking a 16.5GB tree over /mnt/c). Recomputing that per request would mean every page load,
# every CLI call and every export precheck pays it again.
#
# So there is ONE snapshot, computed by ONE background task, and every reader sees the same object.
# Readers never block: they get whatever has landed so far plus `ready` telling them which sections
# are real yet. Partial data labelled partial beats a spinner that hides an answer already known.
SNAP: dict = {"state": "empty", "data": None, "computed_at": None, "started_at": None,
              "error": None, "elapsed": None, "section": None, "section_at": None, "gen": 0,
              "last_wedge": None,
              "last": None}      # the last COMPLETED sweep's snapshot — what a page stands on meanwhile
_SNAP_LOCK = asyncio.Lock()
STALE_AFTER = 300.0          # seconds; a sweep this old is refreshed on next read

# ── the last completed sweep, kept past this process ───────────────────────────────────────────
#
# SNAP lives in memory, so a RESTARTED service had nothing to stand on: its page was placeholders for
# as long as the first sweep took — 85 seconds on a laptop whose binds are walked over /mnt/c
# (DGO-515; the maps' own rule read the screen as never drawn). The last sweep that completed is
# therefore also written to the service's own volume (declared in app.json), and read back at start
# as what it is: OLD numbers, carrying their own time, shown while the first sweep runs.
#
# It is never a sweep of THIS process: it fills SNAP["last"] and nothing else, so `state` stays
# "empty" and every reader that must not act on old numbers (the restore preflight, the CLI's `wait`,
# `complete`) refuses exactly as before. And a file another deployment wrote — a volume restored from
# elsewhere — is not this one's: it is left where it is and not read.
KEPT_FILE = pathlib.Path(os.environ.get("DATA_STATE_DIR", "/state")) / "last-sweep.json"


def _keep(snapshot: dict, computed_at: str):
    """Write the completed sweep beside the last one, whole or not at all (a reader never meets half
    a file). A failure to keep it is said and does not fail the sweep: the page of THIS process has
    its numbers either way."""
    try:
        KEPT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = KEPT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"deployment": INV.deployment_name(), "computed_at": computed_at,
                                   "data": snapshot}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, KEPT_FILE)
    except Exception as e:                                # noqa: BLE001
        print(f"data-management: the completed sweep was NOT kept at {KEPT_FILE}: {type(e).__name__}: {e}",
              file=sys.stderr, flush=True)


def _kept():
    """(snapshot, its time) of the last completed sweep THIS deployment kept, or None."""
    try:
        doc = json.loads(KEPT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    data = doc.get("data") if isinstance(doc, dict) else None
    if (not isinstance(data, dict) or doc.get("deployment") != INV.deployment_name()
            or set(data.get("ready") or []) != set(INV.SECTION_ORDER) or not doc.get("computed_at")):
        return None
    return data, doc["computed_at"]


def _resume():
    """A new process stands on what the last one kept — as old numbers, and on nothing else of it."""
    if (was := _kept()):
        SNAP["last"], SNAP["computed_at"] = was


_resume()

# A sweep that STALLS is not a sweep that is slow, and the difference is the whole point of
# this constant. _sweep() already turns an EXCEPTION into state="error" - but a hang raises
# nothing, so before this existed a single blocking call (any of the docker/psql/git shells,
# none of which carry a timeout) pinned SNAP at state="running" permanently. _ensure_sweep()
# returns early on "running", so every later request - refresh=true included - fell into that
# same early return and the endpoint could not recover short of restarting the container.
#
# The budget is per SECTION, not per sweep. A total-elapsed deadline would kill a legitimately
# slow sweep on a big host (the docstring below walks a 16.5GB tree, and the reader path
# already permits a 3600s wait), while a sweep that has not finished a single section in ten
# minutes is stuck no matter how large the host is. Measured on the portable box for scale:
# the whole 7-section sweep takes ~15s, of which the binds section is ~5s.
SECTION_STALL = 600.0        # seconds without completing ANY section => declare it wedged


# The sweep walks a 16.5GB tree in Python, which holds the GIL between syscalls for long stretches;
# at the default 5ms switch interval a poll landing mid-walk was observed taking 8.6s to answer.
# Shortening the interval trades a little sweep throughput for a server that stays responsive while
# it runs — the right trade for a background job serving a page that polls every 1.2s.
sys.setswitchinterval(0.001)


def _sweep(gen: int):
    """Blocking. Runs in a worker thread — it shells out to docker/psql/git throughout.

    The gen argument is the generation this sweep was started as. Once a wedged sweep can be
    superseded (see SECTION_STALL) a zombie thread may still be parked in a syscall, and if it
    ever returns it would otherwise overwrite a newer, good snapshot with its own stale one.
    Every write below is therefore guarded: a superseded sweep writes NOTHING and exits quietly.
    """
    t0 = time.time()
    try:
        for section, snapshot in INV.inventory_steps(table_limit=40):
            if SNAP["gen"] != gen:
                return
            SNAP["data"] = snapshot
            SNAP["section"] = section
            SNAP["section_at"] = time.time()
            SNAP["elapsed"] = round(time.time() - t0, 1)
        if SNAP["gen"] != gen:
            return
        SNAP["state"] = "ready"
        SNAP["error"] = None
        SNAP["last"] = SNAP["data"]
        if set(SNAP["data"].get("ready") or []) == set(INV.SECTION_ORDER):
            _keep(SNAP["data"], datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except Exception as e:                                # noqa: BLE001
        # Keep whatever sections DID land. A failure in binds must not erase a good volume list.
        if SNAP["gen"] != gen:
            return
        SNAP["state"] = "error"
        SNAP["error"] = f"{type(e).__name__}: {e}"
    finally:
        if SNAP["gen"] == gen:
            SNAP["elapsed"] = round(time.time() - t0, 1)
            SNAP["computed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _shown():
    """(what a page is given, the sections the sweep in hand has finished).

    A sweep builds a NEW snapshot and puts it in the complete one's place at its first section, so
    for as long as a sweep ran the page stood on placeholders for everything not re-scanned yet —
    after a restart, and on every visit that found the last sweep older than STALE_AFTER. By the
    maps' own rule that screen was never drawn: three looks on 2026-10-09 gave up on it after 25
    seconds. "Partial data labelled partial beats a spinner" holds for a FIRST sweep, which has
    nothing else to show; it does not make a known answer worth hiding.

    So while a sweep runs, the page keeps the numbers of the last sweep that COMPLETED (they carry
    their own time, `computed_at`), and the sweep in hand is told beside them: `state`, and the
    sections it has finished. A reader that must not act on old numbers — the restore preflight, the
    CLI's `wait` — does not read this: it waits for the sweep and reads SNAP itself.
    """
    data = SNAP["data"] or {}
    over = SNAP["last"] if SNAP["state"] == "running" else None
    # (before its first section lands, the sweep in hand has finished nothing: what is still in
    #  SNAP["data"] at that moment is the last sweep's)
    fresh = [] if over is not None and data is over else list(data.get("ready") or [])
    return (over if over is not None else data), fresh


async def _ensure_sweep(force=False):
    """Start a sweep if one is warranted, and never a second one concurrently."""
    async with _SNAP_LOCK:
        if SNAP["state"] == "running":
            # Progress is measured by SECTIONS COMPLETED, not by wall time: a sweep still
            # finishing sections is alive however slow it is, and one that has finished none in
            # SECTION_STALL is wedged however fast the host is.
            since = time.time() - (SNAP["section_at"] or SNAP["started_at"] or 0)
            if since < SECTION_STALL:
                return
            # Say WHERE it died. "still running" is what made this invisible; naming the last
            # section that completed is the difference between a spinner and a diagnosis.
            #
            # It is recorded TWICE, and the second one is the point. SNAP["error"] describes
            # the CURRENT state, and the replacement sweep starts immediately below - so on a
            # wedge that recovers, the succeeding sweep sets error=None and the incident
            # vanishes as if it never happened. That is the same silent-recovery failure this
            # whole change exists to remove, so last_wedge is a DURABLE record that no
            # successful sweep clears. Caught by the self-test asserting the message survived
            # recovery, which it did not.
            msg = ("previous inventory sweep WEDGED: no section completed for %.0fs (budget "
                   "%.0fs); last completed section: %s"
                   % (since, SECTION_STALL, SNAP["section"] or "none"))
            SNAP["error"] = msg
            SNAP["last_wedge"] = msg
            SNAP["state"] = "error"
        fresh = (SNAP["state"] == "ready" and SNAP["computed_at"] is not None
                 and (time.time() - (SNAP["started_at"] or 0)) < STALE_AFTER)
        if fresh and not force:
            return
        SNAP["gen"] += 1
        gen = SNAP["gen"]
        SNAP["state"] = "running"
        SNAP["started_at"] = time.time()
        SNAP["section"] = None
        SNAP["section_at"] = None
    asyncio.get_running_loop().run_in_executor(None, _sweep, gen)


@app.get("/healthz")
def healthz():
    return {"ok": True, "deployment": INV.deployment_name(), "repo_visible": REPO.is_dir(),
            "archiver_present": ARCHIVER.is_file()}


@app.get("/api/inventory")
async def api_inventory(archive: str | None = Query(None, description="describe this archive instead of the live host"),
                        refresh: bool = Query(False, description="force a fresh sweep"),
                        wait: bool = Query(False, description="block until the sweep completes"),
                        timeout: float = Query(600.0, ge=1, le=3600),
                        table_limit: int = Query(40, ge=1, le=500)):
    """THE data view. Live by default; an archive when asked.

    Both the console page and `bbox data view` call this. There is no second implementation.

    The live view is a SNAPSHOT, returned immediately with `ready` naming the sections that have
    landed. The console polls and fills in as they arrive; `bbox data view` passes wait=true and
    gets the complete object, because a CLI that printed a half inventory would be read as the
    whole one. Same data either way — the difference is only who waits.
    """
    if archive:
        # Only HERE does a missing file mean "you asked for something that isn't there" (404). The
        # live branch must never return 404: a missing `docker` binary raises FileNotFoundError too,
        # and reporting that as 404 told me the *archive* was absent while the real fault was a
        # broken image. A tool whose failures lie about their cause is worse than one that crashes.
        try:
            return INV.archive_inventory(archive)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:                            # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e
    await _ensure_sweep(force=refresh)
    if wait:
        deadline = time.time() + timeout
        while SNAP["state"] == "running" and time.time() < deadline:
            await asyncio.sleep(0.4)
        if SNAP["state"] == "running":
            raise HTTPException(status_code=504, detail=f"inventory still running after {timeout}s")
    if SNAP["state"] == "error" and SNAP["data"] is None:
        raise HTTPException(status_code=500, detail=SNAP["error"] or "inventory failed")

    data, rescanned = _shown()
    return {
        **data,
        "state": SNAP["state"],
        "error": SNAP["error"],
        "computed_at": SNAP["computed_at"],
        # How far the sweep in hand has got. While it runs `ready` is the page's (the last completed
        # sweep's sections, all of them), so it no longer says that.
        "rescanned": rescanned,
        # LIVE while running. Reporting the stored value meant elapsed froze at whatever the
        # last completed section stamped, so a wedged sweep and a working one were
        # indistinguishable from outside - a frozen number reads as "still going". Computed
        # from started_at it always advances, which makes a stall visible as a number that
        # grows while section does not.
        "elapsed": (round(time.time() - SNAP["started_at"], 1)
                    if SNAP["state"] == "running" and SNAP["started_at"] else SNAP["elapsed"]),
        "section": SNAP["section"],
        # Survives recovery on purpose: a wedge that fixed itself is still a wedge that
        # happened, and an export taken from this host deserves to say so.
        "last_wedge": SNAP["last_wedge"],
        "sections": INV.SECTION_ORDER,
        "complete": SNAP["state"] == "ready" and len(data.get("ready", [])) == len(INV.SECTION_ORDER),
    }


@app.get("/api/archives")
def api_archives():
    """Archives on this host, newest first, each with what its manifest claims."""
    rows = []
    if ARCHIVE_ROOT.is_dir():
        for d in sorted(ARCHIVE_ROOT.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            man = d / "manifest.json"
            entry = {"name": d.name, "path": str(d), "complete": man.is_file()}
            if man.is_file():
                try:
                    m = json.loads(man.read_text(encoding="utf-8"))
                    arts = m.get("artifacts") or {}
                    # Key names are the WRITER's (deployment-archive.py:508-523):
                    # deployment_name / created_utc, and each artifact records `bytes`. Reading
                    # `size` here summed nothing and reported every archive as 0 bytes.
                    entry.update({
                        "mode": m.get("mode"),
                        "created": m.get("created_utc"),
                        "deployment": m.get("deployment_name"),
                        "project": m.get("compose_project"),
                        "format_version": m.get("format_version"),
                        "quiesced": bool(m.get("quiesced")),
                        # Which app this archive is scoped to, or None for a whole deployment. The
                        # two are not interchangeable and the list has to say which it is looking at.
                        "app": (m.get("scope") or {}).get("app"),
                        "apps": sorted({e.get("app") for e in arts.values()
                                        if isinstance(e, dict) and e.get("app")}),
                        "artifacts": len(arts),
                        "bytes": sum((a.get("bytes") or 0) for a in arts.values() if isinstance(a, dict)),
                    })
                except Exception as e:                    # noqa: BLE001
                    entry["error"] = str(e)
            else:
                # No manifest = an export that was interrupted. Say so rather than listing it as
                # an archive somebody might trust.
                entry["error"] = "no manifest.json — incomplete or interrupted export"
            rows.append(entry)
    return {"root": str(ARCHIVE_ROOT), "archives": rows}


async def _run_job(job_id: str, argv: list[str]):
    job = JOBS[job_id]
    job["state"] = "running"
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(REPO), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            job["log"].append(line)
            job["emitted"] += 1                        # MONOTONIC: total lines ever, never trimmed
            del job["log"][:-400]                      # keep the tail bounded
        job["returncode"] = await proc.wait()
        job["state"] = "done" if job["returncode"] == 0 else "failed"
    except Exception as e:                                # noqa: BLE001
        job["state"] = "failed"
        job["log"].append(f"!! {type(e).__name__}: {e}")
        job["emitted"] += 1
    finally:
        job["finished"] = datetime.now(timezone.utc).isoformat()


@app.get("/api/plan")
async def api_plan(archive: str = Query(..., description="archive name (or absolute path) to preflight"),
                   timeout: float = Query(300.0, ge=1, le=3600)):
    """READ-ONLY preflight: what a restore of this archive would overwrite, create, and leave.

    It WRITES NOTHING. That is not incidental - it is why this endpoint is usable while the import
    half is not. A restore is a destructive write that needs an explicit decision, and until this
    existed that decision had to be made blind: the import screen offered the write with no way to
    see what it touched. This is the screen that turns approving a restore into a decision instead
    of a leap.

    It REFUSES to answer from a partial sweep. A half-finished inventory has fewer live volumes in
    it, which makes both `target_only` and `overwrite` shorter than the truth - so a partial plan
    UNDER-reports what a restore would destroy, which is the one direction a preflight must never
    err in.
    """
    # Same containment rule as the download route: a bare name resolves under ARCHIVE_ROOT and may
    # not escape it. An absolute path is accepted because `bbox data view` already passes one.
    p = pathlib.Path(archive)
    if not p.is_absolute():
        p = (ARCHIVE_ROOT / archive).resolve()
        if not str(p).startswith(str(ARCHIVE_ROOT.resolve())):
            raise HTTPException(status_code=400, detail="archive name escapes the archive root")
    try:
        man = INV.archive_inventory(str(p))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:                                # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e

    await _ensure_sweep()
    deadline = time.time() + timeout
    while SNAP["state"] == "running" and time.time() < deadline:
        await asyncio.sleep(0.4)
    live = SNAP["data"] or {}
    ready = live.get("ready") or []
    if SNAP["state"] != "ready" or len(ready) != len(INV.SECTION_ORDER):
        raise HTTPException(
            status_code=503,
            detail=("cannot plan against a partial inventory: state=%s, %d/%d sections. A plan "
                    "built from this would UNDER-report what a restore overwrites."
                    % (SNAP["state"], len(ready), len(INV.SECTION_ORDER))))

    out = PLAN.build_plan(man, live)
    out["archive"]["name"] = p.name
    if SNAP.get("last_wedge"):
        out["warnings"].insert(0, "this host recorded a wedged inventory sweep: %s"
                               % SNAP["last_wedge"])
    return out


@app.post("/api/export")
async def api_export(mode: str = Query("full", pattern="^(full|config)$"),
                     quiesce: bool = Query(False),
                     app_id: str | None = Query(None, alias="app"),
                     resume: str | None = Query(None, description="continue into this archive dir")):
    """Start an export. Returns a job id immediately — a 50GB archive is not an HTTP request.

    quiesce defaults FALSE: stopping the writers is right for a migration and wrong for a routine
    backup of a live system. The manifest records which was used so a restore can never silently
    assume the stronger guarantee.
    """
    if not ARCHIVER.is_file():
        raise HTTPException(status_code=500, detail=f"archiver not found at {ARCHIVER}")
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)

    # Each run gets its OWN directory. This used to pass ARCHIVE_ROOT itself, so every export wrote
    # into the same place: a second run merged into the first (the manifest is kept for resumability,
    # so it would not even look wrong), and /api/archives — which lists SUBDIRECTORIES holding a
    # manifest — could never see any of them. A backup you cannot enumerate is one you will not
    # restore. `resume` re-opens a named run on purpose, which is what resumability actually needs.
    if resume:
        # DGO-620: UNDER the archive root by path, not by string prefix ("../archives-evil" passed), and never the root itself.
        root = ARCHIVE_ROOT.resolve()
        target = (root / resume).resolve()
        if not target.is_relative_to(root) or target == root:
            raise HTTPException(status_code=400, detail="resume must name a directory under the archive root")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = ARCHIVE_ROOT / f"{INV.deployment_name()}-{stamp}{'-' + app_id if app_id else ''}"

    argv = ["python3", str(ARCHIVER), "export", "--mode", mode, "--out", str(target)]
    if quiesce:
        argv.append("--quiesce")
    if app_id:
        argv += ["--app", app_id]
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "kind": "export", "mode": mode, "quiesce": quiesce,
                    "app": app_id, "out": str(target),
                    "state": "starting", "log": [], "emitted": 0, "argv": argv,
                    "started": datetime.now(timezone.utc).isoformat()}
    asyncio.create_task(_run_job(job_id, argv))
    return {"job": job_id, "mode": mode, "quiesce": quiesce, "app": app_id, "out": str(target)}


# ── a backup into a restic repository on a declared target (backup_run.py, DGO-1523) ────────────
STATE_DIR = pathlib.Path(os.environ.get("DATA_STATE_DIR", "/state"))


async def _run_backup(job_id: str, target: str):
    """The run, in a worker thread, its sentences in the job's log. Refused = skipped (nothing started,
    and why); Failed = failed. Neither is ever reported as done."""
    job = JOBS[job_id]

    def log(line: str):
        job["log"].append(line)
        job["emitted"] += 1
        del job["log"][:-400]

    job["state"] = "running"
    try:
        job["result"] = await asyncio.to_thread(
            BACKUP.run, target, INV.deployment_name(), ARCHIVE_ROOT, STATE_DIR, BACKUP.archiver_export(REPO), log)
        job["state"] = "done"
    except BACKUP.Refused as e:
        job["state"] = "skipped"
        log(f"!! skipped: {e}")
    except BACKUP.Failed as e:
        job["state"] = "failed"
        log(f"!! failed: {e}")
    except Exception as e:                                # noqa: BLE001
        job["state"] = "failed"
        log(f"!! failed: {type(e).__name__}: {e}")
    finally:
        job["finished"] = datetime.now(timezone.utc).isoformat()


def _busy(kinds) -> list[str]:
    return [j["kind"] for j in JOBS.values() if j.get("kind") in kinds and j.get("state") in ("starting", "running")]


def start_backup_job(target: str, by: str = "api") -> str:
    """A backup job, started now in this event loop; its id. `by`: who asked (the API, the schedule)."""
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "kind": "backup", "target": target, "state": "starting", "log": [],
                    "emitted": 0, "started": datetime.now(timezone.utc).isoformat(), "by": by}
    asyncio.create_task(_run_backup(job_id, target))
    return job_id


@app.post("/api/backup")
async def api_backup(target: str = Query(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")):
    """Start a backup of this office to a declared target. Returns a job id at once (GET /api/jobs/<id>).
    Not while an export or a restore is going: the run's own export would read a half-restored office,
    or double the load of one already reading it."""
    busy = _busy(("export", "import"))
    if busy:
        raise HTTPException(status_code=409, detail=f"an {busy[0]} is running; a backup waits for it to end")
    return {"job": start_backup_job(target), "target": target}


# ── the nightly schedule (backup_run.due, DGO-1523 slice 3) ─────────────────────────────────────
#
# Every SCHEDULE_TICK the targets file is read again (a target added or a time changed needs no
# restart), and ONE due target is started — never beside an export, a restore or another backup. A
# start that did not become a run (refused: the store not reachable, no room) leaves the target due,
# and it is tried again after SCHEDULE_RETRY, not every tick. Started only when the service starts, so
# an office whose targets name no `nightly_utc` runs nothing.
SCHEDULE_TICK = 60.0
SCHEDULE_RETRY = 3600.0
SCHEDULE_TRIED: dict[str, float] = {}
_SCHEDULE_SAID = {"error": ""}
_SCHEDULE_KEEP_JOBS = 60


async def schedule_tick(now: datetime, start=None) -> list[str]:
    """One pass: the target it started (at most one), for the test."""
    start = start or (lambda t: start_backup_job(t, by="schedule"))
    if _busy(("export", "import", "backup")):
        return []
    try:
        targets = REPO_STORE.targets()
    except ValueError as e:
        if str(e) != _SCHEDULE_SAID["error"]:                # said once, not every minute
            print(f"[data-management] schedule: the targets file cannot be read: {e}", flush=True)
            _SCHEDULE_SAID["error"] = str(e)
        return []
    _SCHEDULE_SAID["error"] = ""
    stamp = now.timestamp()
    for tid in sorted(targets):
        slot = targets[tid].get("nightly_utc")
        if not slot or stamp - SCHEDULE_TRIED.get(tid, float("-inf")) < SCHEDULE_RETRY:
            continue
        offset = BACKUP.spread(BACKUP.LINK_OFFICE or INV.deployment_name(), tid)
        if not BACKUP.due(slot, BACKUP._started(STATE_DIR, tid), now, offset):
            continue
        SCHEDULE_TRIED[tid] = stamp
        start(tid)
        # the job table is this process's memory: the schedule's own finished jobs beyond the newest few go
        mine = sorted((j for j in JOBS.values() if j.get("by") == "schedule"
                       and j.get("state") not in ("starting", "running")), key=lambda j: j.get("started") or "")
        for j in mine[:-_SCHEDULE_KEEP_JOBS]:
            JOBS.pop(j["id"], None)
        return [tid]
    return []


# ── a night that did not happen is SAID (DGO-1517) ──────────────────────────────────────────────
#
# A scheduled target with no good run (a snapshot and a passing check) for STALE_AFTER is told to the office once,
# through its notifications (the bell in the console), and its return is told too: nobody reads a job log to learn
# that the backups stopped. The clock is kept in STALE_FILE (target → since when it has had no good run, and whether
# that was told), so a restart neither forgets an outage nor tells it twice. A target never run is measured from
# when this service first saw it. A notice that was not delivered is tried again after STALE_RETRY.
STALE_AFTER = float(os.environ.get("DATA_STALE_AFTER") or 26 * 3600)
STALE_RETRY = 600.0
STALE_FILE = "stale-alerts.json"
NOTIFICATIONS_URL = (os.environ.get("NOTIFICATIONS_URL") or "http://notifications:8977").rstrip("/")


def _notify(source_id: str, title: str, body: str, level: str) -> bool:
    """One row in the office's notifications, deduplicated by `source_id` (one per outage)."""
    import urllib.request
    req = urllib.request.Request(
        f"{NOTIFICATIONS_URL}/api/notifications", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"source": "data-management", "source_id": source_id, "title": title, "body": body,
                         "level": level, "link": "/#/m/data-management"}, ensure_ascii=False).encode())
    import urllib.error
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status in (200, 201)
    except urllib.error.HTTPError as e:                       # the board answered no: say what it said (G66)
        said = e.read(300).decode("utf-8", "replace").strip() if e.fp else ""
        print(f"[data-management] notice not delivered ({source_id}): HTTP {e.code} {said}", flush=True)
        return False
    except Exception as e:                                    # noqa: BLE001 — a bad status line too: not delivered
        print(f"[data-management] notice not delivered ({source_id}): {type(e).__name__}: {e}", flush=True)
        return False


def _good_at(target: str) -> float | None:
    """When the last good run to `target` finished (a snapshot and a passing check), or None — also when the
    record cannot be read (a permission, a disk): no good run that this service can show is no good run."""
    try:
        got = BACKUP.last(STATE_DIR, target) or {}
        return datetime.fromisoformat(str(got["finished"])).timestamp()
    except (OSError, KeyError, ValueError, TypeError):
        return None


def _num(value) -> float | None:
    """A finite number, or None: a NaN or an infinity written into the file by hand is no time."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


# The key under which STALE_FILE keeps the one notice about the targets file itself: no target id can be it
# (restic_store's target pattern starts with a letter or a digit).
_TARGETS_KEY = "~targets"
_TARGETS_SID = "backup-targets-unreadable"


def tell_stale(now: datetime, notify=_notify, running: frozenset = frozenset()) -> list[str]:
    """Tell the office when a scheduled target has had no good run for STALE_AFTER, and when it has one again. A
    target whose backup is running now is not judged until it ends (a long Sunday prune is not an outage). Returns
    the source ids it told, for the test."""
    path = STATE_DIR / STALE_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        state = {}
    stamp, told = now.timestamp(), []
    before = json.dumps(state, sort_keys=True)
    # A targets file that does not read starts no night at all — the very outage this exists for: told once, at
    # the level that rings, and its return told on the same row (the notifications app upserts by source id).
    rec = state.get(_TARGETS_KEY) if isinstance(state.get(_TARGETS_KEY), dict) else {}
    try:
        targets = REPO_STORE.targets()
    except ValueError as e:
        if not rec.get("told") and stamp - (_num(rec.get("tried")) or 0.0) >= STALE_RETRY:
            rec["tried"] = stamp
            if notify(_TARGETS_SID, "קובץ יעדי הגיבוי לא נקרא — שום גיבוי לילה לא מתחיל",
                      f"ניהול הנתונים לא קורא את קובץ היעדים ({str(e)[:160]}), ולכן אף יעד לא מגובה עד שיתוקן.",
                      "error"):
                rec["told"] = True
                told.append(_TARGETS_SID)
        state[_TARGETS_KEY] = rec
        _save_stale(path, state, before)
        return told
    if rec.get("told"):
        if stamp - (_num(rec.get("tried")) or 0.0) >= STALE_RETRY:
            rec["tried"] = stamp
            if notify(_TARGETS_SID, "קובץ יעדי הגיבוי נקרא שוב", "גיבויי הלילה מתחילים שוב לפי הקובץ.", "info"):
                told.append(_TARGETS_SID)
                state.pop(_TARGETS_KEY, None)
            else:
                state[_TARGETS_KEY] = rec                  # told when it is delivered
    else:
        state.pop(_TARGETS_KEY, None)
    for tid in [t for t in state if not t.startswith("~") and (t not in targets or not targets[t].get("nightly_utc"))]:
        state.pop(tid)                                     # gone or no longer scheduled: nothing to tell
    try:
        _tell_prune_late(targets, state, stamp, notify, told)
    except Exception as e:                                 # noqa: BLE001 — the stale notices below must still go
        print(f"[data-management] prune notice: {type(e).__name__}: {e}", flush=True)
    for tid in sorted(targets):
        if not targets[tid].get("nightly_utc") or tid in running:
            continue
        rec = state.get(tid) if isinstance(state.get(tid), dict) else {}
        since, tried = _num(rec.get("since")), _num(rec.get("tried")) or 0.0
        if rec and since is None:
            rec, tried = {}, 0.0                           # a value nobody can read: the clock starts again
        good = _good_at(tid)
        if good is not None and stamp - good < STALE_AFTER:
            if rec.get("told"):
                if stamp - tried < STALE_RETRY:
                    continue
                # the outage's own row, rewritten: one row per outage, unread until it is seen
                sid = f"backup-stale-{tid}-{int(since or 0)}"
                rec["tried"] = stamp
                if not notify(sid, f"הגיבוי ל-{tid} חזר", "גיבוי לילה הסתיים בהצלחה (תמונת מצב ובדיקה תקינה).",
                              "info"):
                    state[tid] = rec                       # told when it is delivered
                    continue
                told.append(sid)
            state.pop(tid, None)
            continue
        if good is not None and since is not None and good > since:
            rec, tried = {}, 0.0                           # a good run since: this is another outage
        since = good if good is not None else (since if since is not None else stamp)
        rec["since"] = since
        if not rec.get("told") and stamp - since >= STALE_AFTER and stamp - tried >= STALE_RETRY:
            hours = int((stamp - since) // 3600)
            sid = f"backup-stale-{tid}-{int(since)}"
            rec["tried"] = stamp
            body = (f"הגיבוי התקין האחרון ל-{tid} הסתיים לפני {hours} שעות" if good is not None
                    else f"לא נרשם אף גיבוי תקין ל-{tid} מאז שהוגדר, לפני {hours} שעות") + \
                   ". פרטי הריצה האחרונה בניהול הנתונים."
            # `error`: a backup that stopped is what rings the phone (notifications/push.py, PUSH_LEVELS)
            if notify(sid, f"אין גיבוי תקין ל-{tid} כבר {hours} שעות", body, "error"):
                rec["told"] = True
                told.append(sid)
        state[tid] = rec
    _save_stale(path, state, before)
    return told


def _tell_prune_late(targets: dict, state: dict, stamp: float, notify, told: list) -> None:
    """A store that may delete and has not been pruned for BACKUP.PRUNE_LATE (every Sunday's prune blocked by a pull,
    or failing) fills up unseen: told once, and its end on the same row (DGO-1517, the third reader: the result's
    «NOT PRUNED» line reached nobody). Kept under `~prune-<target>` in STALE_FILE."""
    deleting = {t for t, s in targets.items() if s.get("nightly_utc") and BACKUP.retention(s, BACKUP.PRUNE_DAY) == "prune"}
    for key in [k for k in state if k.startswith("~prune-") and k[len("~prune-"):] not in deleting]:
        state.pop(key)                                     # no longer a store that prunes here: nothing to tell
    for tid in sorted(deleting):
        key = f"~prune-{tid}"
        rec = state.get(key) if isinstance(state.get(key), dict) else {}
        try:
            got = BACKUP.last(STATE_DIR, tid)
        except (OSError, ValueError):
            got = None
        pruned = BACKUP._when(got.get("pruned")) if isinstance(got, dict) else None
        late = pruned is not None and stamp - pruned >= BACKUP.PRUNE_LATE
        if stamp - (_num(rec.get("tried")) or 0.0) < STALE_RETRY:
            continue
        if pruned is None and rec.get("told"):
            continue        # a record gone or unreadable is no proof of a prune: no all-clear (the fourth reader)
        if late and not rec.get("told"):
            sid = f"backup-prune-late-{tid}-{int(pruned)}"
            rec.update(tried=stamp, sid=sid)
            days = int((stamp - pruned) // 86400)
            if notify(sid, f"המאגר {tid} לא נוקה כבר {days} ימים",
                      "הגיבויים נשמרים, אבל מה שנשכח לא נמחק מהמאגר והוא מתמלא — הניקוי השבועי נחסם (משיכה של לשכה אחרת "
                      "פתוחה בזמנו) או נכשל. פרטי הריצה האחרונה בניהול הנתונים.", "warning"):
                rec["told"] = True
                told.append(sid)
            state[key] = rec
        elif not late and rec.get("told"):
            rec["tried"] = stamp
            if notify(str(rec.get("sid") or f"backup-prune-late-{tid}"), f"המאגר {tid} נוקה שוב",
                      "הניקוי של המאגר רץ שוב.", "info"):
                told.append(str(rec.get("sid")))
                state.pop(key, None)
            else:
                state[key] = rec                           # told when it is delivered
        elif not late:
            state.pop(key, None)


def _save_stale(path, state: dict, before: str) -> None:
    """STALE_FILE, whole or not at all, when it changed."""
    if json.dumps(state, sort_keys=True) != before:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, path)


async def _schedule_loop() -> None:
    while True:
        try:
            await schedule_tick(datetime.now(timezone.utc))
        except Exception as e:                                # noqa: BLE001 — the schedule must outlive one bad pass
            print(f"[data-management] schedule: {type(e).__name__}: {e}", flush=True)
        try:
            running = frozenset(j.get("target") for j in JOBS.values()
                                if j.get("kind") == "backup" and j.get("state") in ("starting", "running"))
            await asyncio.to_thread(tell_stale, datetime.now(timezone.utc), _notify, running)
        except Exception as e:                                # noqa: BLE001 — as the schedule
            print(f"[data-management] stale notice: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(SCHEDULE_TICK)


_SCHEDULE_TASK: list = []         # the loop's task, held: the event loop keeps only a weak reference


@app.on_event("startup")
async def _start_schedule() -> None:
    _SCHEDULE_TASK.append(asyncio.create_task(_schedule_loop()))


@app.get("/api/backup/last")
def api_backup_last(target: str = Query(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")):
    """The last run that finished with a snapshot and a passing check, or 404."""
    got = BACKUP.last(STATE_DIR, target)
    if got is None:
        raise HTTPException(status_code=404, detail=f"no finished backup to {target} is recorded here")
    return got


@app.post("/api/import")
async def api_import(path: str = Query(..., description="archive directory to restore"),
                     app_id: str | None = Query(None, alias="app"),
                     force: bool = Query(False)):
    """Restore an archive. force is required to restore over the deployment it came from — the
    archiver refuses otherwise, and that refusal is a feature."""
    if not ARCHIVER.is_file():
        raise HTTPException(status_code=500, detail=f"archiver not found at {ARCHIVER}")
    src = pathlib.Path(path)
    if not (src / "manifest.json").is_file():
        raise HTTPException(status_code=400, detail=f"{src} has no manifest.json — not an archive")
    argv = ["python3", str(ARCHIVER), "import", str(src)]
    if app_id:
        argv += ["--app", app_id]
    if force:
        argv.append("--force")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "kind": "import", "path": str(src), "force": force,
                    "app": app_id,
                    "state": "starting", "log": [], "emitted": 0, "argv": argv,
                    "started": datetime.now(timezone.utc).isoformat()}
    asyncio.create_task(_run_job(job_id, argv))
    return {"job": job_id, "path": str(src), "app": app_id}


# ── an archive that is on a LINKED office ───────────────────────────────────────────────────────
#
# Moving an app between two linked offices is: export it there, bring the archive HERE, import it
# here. The middle is `pull.py` (why it is a pull, and what it refuses); this is its job and route.


def _pull(job_id: str, office: str, name: str, target: pathlib.Path):
    """Blocking; runs in a worker thread."""
    job = JOBS[job_id]

    def say(line: str):
        job["log"].append(line)
        job["emitted"] += 1
        del job["log"][:-400]

    job["state"] = "running"
    try:
        PULL.archive(office, name, target, ARCHIVE_ROOT, say)
        job["returncode"], job["state"] = 0, "done"
    except Exception as e:                                # noqa: BLE001 — the reason IS the report
        say(f"!! {type(e).__name__}: {e}")
        job["returncode"], job["state"] = 1, "failed"
    finally:
        job["finished"] = datetime.now(timezone.utc).isoformat()


@app.post("/api/pull")
async def api_pull(office: str = Query(..., description="the linked office that holds the archive"),
                   name: str = Query(..., description="the archive's name there (see its /api/archives)")):
    """Bring one archive from a linked office into this office's archive root. Returns a job id;
    the job's `out` is the directory to hand to /api/import."""
    office = office.strip().lower()
    if not PULL.OFFICE.match(office) or not PULL.ARCHIVE.match(name):
        raise HTTPException(status_code=400, detail="office and name must be plain identifiers")
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_ROOT / f"from-{office}-{name}"
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "kind": "pull", "office": office, "name": name, "out": str(target),
                    "state": "starting", "log": [], "emitted": 0,
                    "started": datetime.now(timezone.utc).isoformat()}
    asyncio.get_running_loop().run_in_executor(None, _pull, job_id, office, name, target)
    return {"job": job_id, "office": office, "name": name, "out": str(target)}


@app.get("/api/jobs")
def api_jobs():
    return {"jobs": [{k: v for k, v in j.items() if k != "log"} for j in JOBS.values()]}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str, tail: int = Query(80, ge=1, le=400)):
    """`first_seq` is the absolute line number of log[0].

    The log is a 400-line ring, so a follower cannot use len(log) as its cursor: once an export
    passes 400 lines the length stops growing, and a client tracking it prints nothing for the rest
    of a multi-hour run. With first_seq the client keeps an ABSOLUTE cursor and can also tell when
    lines were dropped between polls instead of silently missing them.
    """
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="no such job")
    log = j["log"][-tail:]
    return {**{k: v for k, v in j.items() if k != "log"}, "log": log,
            "first_seq": j.get("emitted", len(log)) - len(log)}


@app.get("/api/archives/{name}/download/{artifact:path}")
def api_download(name: str, artifact: str):
    """Stream one artifact out. Whole-archive download is deliberately NOT a single HTTP response:
    50GB through a proxy with an auth timeout is a download that fails at 94%."""
    # DGO-620: `name` is an archive's name (pull's rule) and the file lies INSIDE it by path, not by string prefix.
    root = ARCHIVE_ROOT.resolve()
    if not PULL.ARCHIVE.match(name):
        raise HTTPException(status_code=404, detail="no such artifact")
    base = (root / name).resolve()
    target = (base / artifact).resolve()
    if not (base.is_relative_to(root) and target.is_relative_to(base)) or not target.is_file():
        raise HTTPException(status_code=404, detail="no such artifact")
    return FileResponse(target, filename=target.name)


_STATIC = pathlib.Path(__file__).parent / "static"
if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
def index():
    idx = _STATIC / "index.html"
    if not idx.is_file():
        return JSONResponse({"error": "no static/index.html"}, status_code=500)
    return FileResponse(idx)


# ── the screen lives in its own URL, so a deep link is a PAGE and not a file ────────────────────
#
# static/index.html carries its own router (places summary|byapp|unclaimed|archives|raw) and writes
# the section in view to `/a/data-management/<place>`. That contract is worthless unless the address
# it writes can be OPENED: with only `/` served, every deep path was a 404 — a router that is green
# in the gate and dead in the address bar.
#
# WHAT IT ANSWERS: a GET/HEAD for a path that is none of this app's own surfaces and does not look
# like a file — with static/index.html. The page then reads its own path and opens that section.
#
# WHAT IT MUST NEVER ANSWER: anything an earlier route already owns. FastAPI matches in REGISTRATION
# ORDER, so `/api/...`, `/healthz`, `/` and the `/static` mount are all decided before this function
# is ever reached — this is the last route in the file by construction, and it must stay that way.
# The refusals below exist for what is left: an unknown `/api/...`, `/healthz/...` or `/static/...`
# path is a 404 in the API's own voice, never an HTML page a JSON client would try to parse.
#
# A path that LOOKS LIKE A FILE — it has an extension — is a request for a file, and a missing file
# is a real 404. Answering `missing.js` or `logo.png` with the page would hand an <img>/<script> HTML
# and turn a broken asset into a silent, unparseable success.
_NO_PAGE_AT = frozenset({"api", "healthz", "static", "repo"})


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def page_for(full_path: str):
    """The SPA fallback: the one page, for a page path. See the note above for what it refuses."""
    if full_path.split("/", 1)[0] in _NO_PAGE_AT:
        raise HTTPException(status_code=404, detail=f"no such path: /{full_path}")
    if pathlib.PurePosixPath(full_path).suffix:
        raise HTTPException(status_code=404, detail=f"no such file: /{full_path}")
    idx = _STATIC / "index.html"
    if not idx.is_file():
        return JSONResponse({"error": "no static/index.html"}, status_code=500)
    return FileResponse(idx)
