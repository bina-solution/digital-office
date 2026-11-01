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

REPO = pathlib.Path(os.environ.get("DEPLOYMENT_PATH", "/deployment"))
ARCHIVE_ROOT = pathlib.Path(os.environ.get("DATA_ARCHIVE_ROOT", "/archives"))
ARCHIVER = REPO / "scripts" / "deployment-archive.py"

app = FastAPI(title="Data Management", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1024)

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
        target = (ARCHIVE_ROOT / resume).resolve()
        if not str(target).startswith(str(ARCHIVE_ROOT.resolve())):
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
    base = (ARCHIVE_ROOT / name).resolve()
    target = (base / artifact).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
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
