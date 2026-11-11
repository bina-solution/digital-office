"""git.mirrors — external repositories, made visible in the office's own forge.

The problem it solves. The office acts on GitHub and GitLab accounts, and those repositories are
readable only through somebody else's web UI, with somebody else's login, one account at a time. The
owner asked for ONE screen that shows every repository the office can touch — the local ones it
creates and the external ones it acts on — and the answer was to stop writing a code browser and use
the forge we already run (Forgejo, `forge:3000`). A **mirror** is how an external repository gets
there: a real copy, in the local forge, that the forge's own UI renders like any other project.

Why this module exists at all, instead of Forgejo's built-in pull mirror: **the token**. Forgejo's
native mirror would have to store the GitHub/GitLab credential in its own database, which is exactly
the crossing the credential plane exists to prevent (platform-service-contract §5a) — and it would
be a second copy of an account that the vault already owns. So the sync runs HERE, where the
credential is already resolvable per request, and — this is the whole trick — it never touches the
token either: both halves of the transfer go through this app's own smart-HTTP proxy,

    git clone --mirror http://git:8978/git/<code>/<source-account>/<owner>/<repo>.git
    git push  --mirror http://git:8978/git/lc/<local-account>/<owner>/<repo>.git

and the proxy injects the credential server-side. Nothing lands in this container's environment, in
a scratch `.git/config`, or in Forgejo's database.

A mirror is a DISPLAY and a copy — not the place to push. Pushes belong to the provider that owns
the repository (`POST /remote` gives the remote for it). That is stated in the UI, because "I pushed
to the mirror and it disappeared" is the failure this design would otherwise invite.

What is deliberately crude here, and why: the clone is a full `--mirror` into scratch and then a
full push. It is slow and it re-sends what has not changed. It is also impossible to get subtly
wrong, it needs no state beyond the last success, and a failed run leaves the previous copy intact
(the push is what mutates the forge). An incremental `git fetch` in the existing scratch dir is the
obvious optimization and is left for the day there are enough mirrors to justify it.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import accounts
import proxy

log = logging.getLogger("git.mirrors")

STATE_DIR = Path(os.environ.get("GIT_STATE_DIR", "/data"))
REGISTRY = STATE_DIR / "mirrors.json"
SCRATCH = STATE_DIR / "scratch"
# One sync at a time, process-wide: two mirrors cloning at once on a 5 GiB engine is how a mirror
# turns into an office outage, and the second one is never urgent.
_SYNC_LOCK = threading.Lock()
_LOCK = threading.Lock()

INTERVAL = int(os.environ.get("GIT_MIRROR_INTERVAL", "3600") or 3600)
# 2 GiB per mirror, and the number is MEASURED rather than chosen: the office's OWN repository
# (bina-solution/digital-office) is a 1.3 GB mirror clone, so a 1 GiB default silently refused
# the one repository most likely to be mirrored — a guard that excludes the intended use is not a
# guard. The engine has ~15 GB free with ~40 containers on it, and the check runs BEFORE the push, so
# an oversized mirror costs a clone and never a permanent byte.
MAX_BYTES = int(os.environ.get("GIT_MIRROR_MAX_BYTES", str(2 * 1024 ** 3)) or 2 * 1024 ** 3)
# Never start a sync that would leave the engine with less than this. Failed syncs do not reclaim
# anything by themselves: the scratch dir has to be removable.
MIN_FREE_MB = int(os.environ.get("GIT_MIRROR_MIN_FREE_MB", "2048") or 2048)
# Keep the scratch copy after a successful sync, so the next run FETCHES instead of cloning 1.26 GB
# again. 0 turns it off (every sync re-downloads, and the disk never holds two copies).
KEEP_SCRATCH = int(os.environ.get("GIT_MIRROR_KEEP_SCRATCH", "1") or 0)
GIT_TIMEOUT = int(os.environ.get("GIT_MIRROR_TIMEOUT", "1800") or 1800)
# A failing mirror is retried on a widening clock, not on its interval forever (herd-408): 1x, 2x, 4x
# … the interval, capped here at a day. Measured 2026-11-09: a row whose run ended in a 30-minute full
# clone was scheduled again an hour later, by which time nothing had changed.
BACKOFF_MAX = int(os.environ.get("GIT_MIRROR_BACKOFF_MAX", "86400") or 86400)


class MirrorError(Exception):
    """A refusal with a Hebrew sentence — what to do, not what went wrong internally."""

    def __init__(self, he_message: str, status: int = 400):
        super().__init__(he_message)
        self.he_message = he_message
        self.status = status


# ── the registry (the app's own state: a mirror is a decision, not a credential) ──────────────────
def load() -> list[dict]:
    try:
        rows = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _save(rows: list[dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(REGISTRY)


def public_base() -> str:
    """The origin a BROWSER uses for the forge — what a deep link in the UI must be built from.

    FORGE_ROOT_URL is Forgejo's own idea of its origin (scheme + port, correct everywhere);
    FORGE_BASE_URL is the bare host the edge matches on. The first is preferred, and the second is
    given a scheme, because a link with a missing scheme is a link that silently does nothing.
    """
    for var in ("FORGE_ROOT_URL", "FORGE_BASE_URL"):
        v = (os.environ.get(var) or "").strip().rstrip("/")
        if v:
            return v if v.startswith("http") else f"http://{v}"
    return "http://forge.localhost:8080"


def internal_base() -> str:
    """The in-network origin — what an op or a git client inside the platform calls."""
    return (os.environ.get("FORGE_URL") or "http://forge:3000").rstrip("/")


def _row_out(row: dict) -> dict:
    base = public_base()
    out = dict(row)
    out["browse_url"] = f"{base}/{row.get('target_owner') or ''}/{row.get('target_repo') or ''}"
    return out


def list_mirrors() -> dict:
    return {"mirrors": [_row_out(r) for r in load()],
            "interval_seconds": INTERVAL,
            "guards": {"max_bytes": MAX_BYTES, "min_free_mb": MIN_FREE_MB},
            "forge": public_base()}


def _find(mid: str) -> dict | None:
    return next((r for r in load() if r.get("id") == mid), None)


# ── creating and removing a mirror ───────────────────────────────────────────────────────────────
def create(source_account: str, repo: str, *, target_owner: str = "", target_repo: str = "",
           target_account: str = "", private: bool = True, note: str = "") -> dict:
    """Register an external repository as a mirror into the local forge.

    `source_account` is the vault instance id (never "the active account": a mirror that follows
    whatever is selected would silently start copying a different repository into the same project).
    """
    inst, sec, err = accounts.resolve(source_account)
    if err:
        raise MirrorError(err, status=409)
    provider, _kind = accounts.provider_kind(inst.get("protocol") or "")
    if provider == "forgejo":
        raise MirrorError("הפורג' המקומי אינו מקור למראה — מאגר מקומי הוא פשוט מאגר מקומי.",
                          status=400)
    repo = (repo or "").strip().strip("/")
    if not repo or "/" not in repo:
        raise MirrorError("צורת המאגר צריכה להיות owner/repo.", status=400)
    owner, name = repo.rpartition("/")[0], repo.rpartition("/")[2]
    if name.endswith(".git"):
        name = name[:-4]
    local_slug, local_cid = _local_account(target_account)
    rows = load()
    mid = f"{inst['id']}:{provider}:{repo}"
    if any(r.get("id") == mid for r in rows):
        raise MirrorError("המאגר הזה כבר רשום כמראה.", status=409)
    row = {
        "id": mid,
        "source_account": inst["id"],
        "source_provider": provider,
        "source_repo": repo,
        "source_owner": owner,
        "source_note": note,
        # The forge side: same name, copied into the local account's own namespace unless a caller
        # says otherwise. A mirror of someone else's repository under OUR name is a copy; there is
        # no ambiguity about who owns the original, and clone URLs in the forge say where it lives.
        "target_account": local_cid,
        "target_owner": (target_owner or local_slug).strip().strip("/"),
        "target_repo": (target_repo or name).strip(),
        "private": bool(private),
        "created_at": int(time.time()),
        "interval": INTERVAL,
        "last_run": None,
        "last_status": "new",
        "last_error": None,
        "last_seconds": None,
        "bytes": None,
        # the schedule's own state (herd-408): a pause a person can see and toggle, and the count of
        # consecutive failures that widens the retry clock.
        "paused": False,
        "consecutive_failures": 0,
        "next_due": None,
    }
    rows.append(row)
    _save(rows)
    return _row_out(row)


def delete(mid: str, *, delete_repo: bool = False) -> dict:
    """Stop syncing. The local COPY survives by default — deleting a repository is the owner's call.

    `delete_repo=True` is the deliberate second step: it removes the forge project too, and it is
    asked for by name in the UI.
    """
    rows = load()
    row = next((r for r in rows if r.get("id") == mid), None)
    if not row:
        raise MirrorError("מראה כזו אינה רשומה.", status=404)
    removed_repo = None
    if delete_repo:
        from adapters import adapter_for
        inst, sec, err = accounts.resolve(row.get("target_account"))
        if err:
            raise MirrorError(f"לא ניתן למחוק את המאגר בפורג': {err}", status=409)
        ad = adapter_for("forgejo", sec or {}, inst.get("id"))
        try:
            ad.delete_repo(f"{row['target_owner']}/{row['target_repo']}")
            removed_repo = f"{row['target_owner']}/{row['target_repo']}"
        except Exception as e:                      # noqa: BLE001 — reported, never swallowed
            raise MirrorError(f"הסרת המראה נעצרה: לא הצלחתי למחוק את המאגר בפורג' "
                              f"({getattr(e, 'he_message', None) or 'שגיאה לא צפויה'}).",
                              status=409)
    _save([r for r in rows if r.get("id") != mid])
    shutil.rmtree(SCRATCH / _slug(mid), ignore_errors=True)
    return {"ok": True, "deleted": mid, "deleted_repo": removed_repo}


def _slug(mid: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in mid)[:120]


def _local_account(target_account: str = "") -> tuple[str, str]:
    """(username, instance id) of the local forge account — the one this app mints for itself."""
    insts, err = accounts.vault_list()
    if err:
        raise MirrorError(f"שירות החיבורים אינו זמין ({err}).", status=503)
    local = [i for i in insts if (i.get("protocol") or "") == "git_forge_local"]
    if not local:
        raise MirrorError("הפורג' המקומי עדיין אינו מחובר — הרץ את apps/git/hooks/prepare.",
                          status=409)
    want = target_account or local[0]["id"]
    inst = next((i for i in local if i.get("id") == want), None)
    if not inst:
        raise MirrorError(f"חשבון הפורג' {want} אינו קיים.", status=404)
    sec = accounts.vault_secret(inst["id"]) or {}
    return (sec.get("username") or "office"), inst["id"]


# ── the sync itself ──────────────────────────────────────────────────────────────────────────────
def _git(args: list[str], cwd: Path | None = None, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run git with no terminal, no prompt and no credential store — the proxy authenticates.

    GIT_TERMINAL_PROMPT=0 matters more than it looks: without it a rejected credential makes git ask
    a question, and a question inside a container is a hang until the timeout. GIT_ASKPASS=/bin/true
    is the second belt: it answers nothing instead of waiting for a terminal that does not exist.
    """
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(STATE_DIR),          # no user gitconfig, no credential helper to inherit
    })
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, env=env,
                          capture_output=True, text=True, timeout=timeout)


def _scratch_usable(path: Path) -> bool:
    """Is `path` a repository git can CONTINUE from?

    Two checks, and it is worth being exact about what each one does NOT catch (measured 2026-11-10):
      * `config` + `git rev-parse --git-dir` — is anything there at all. A failed run that never
        reached git (a 507 free-space refusal, a 409 account) leaves no directory, and this answers
        that without spawning a scan.
      * `git fsck --connectivity-only` — are the objects the refs point at present. It walks refs and
        commits and skips blob contents, so it is seconds on a 1.35 GB mirror.
    `fsck` is VACUOUS on a repository with no refs (it exits 0), so it does not by itself prove a copy
    is complete — and it is not relied on for that: an interrupted `git clone` deletes its own
    directory (measured: exit 128, no directory left), which is why the "drop it" branch exists for the
    empty case rather than for a corrupt one. What this function decides is the useful question: is
    there a usable repository here to fetch into?
    """
    if not (path / "config").exists():
        return False
    try:
        probe = _git(["--git-dir", str(path), "rev-parse", "--git-dir"], timeout=60)
        if probe.returncode != 0:
            return False
        cp = _git(["--git-dir", str(path), "fsck", "--connectivity-only", "--no-progress"],
                  timeout=min(GIT_TIMEOUT, 600))
    except subprocess.TimeoutExpired:
        return False
    return cp.returncode == 0


def _free_mb() -> int:
    try:
        return shutil.disk_usage(str(STATE_DIR)).free // (1024 * 1024)
    except OSError:
        return 0


def _dir_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def sync(mid: str, *, wait: bool = False) -> dict:
    """One mirror, now. Serialized process-wide: a second caller is told `busy` instead of queueing.

    `wait=True` blocks until the running sync finishes — for a person who asked for exactly this
    repository and would rather wait than be told "later". Never used by the scheduler.
    """
    row = _find(mid)
    if not row:
        raise MirrorError("מראה כזו אינה רשומה.", status=404)
    if not _SYNC_LOCK.acquire(blocking=wait):
        return {"ok": False, "id": mid, "status": "busy",
                "error": "סנכרון אחר של מראות רץ כעת — נסה שוב בעוד רגע."}
    started = time.time()
    tmp = SCRATCH / _slug(mid)
    ok = False
    try:
        free = _free_mb()
        if free < MIN_FREE_MB:
            raise MirrorError(f"אין מספיק מקום פנוי לסנכרון ({free}MB פנויים, "
                              f"המינימום {MIN_FREE_MB}MB).", status=507)
        src_inst, _src_sec, err = accounts.resolve(row["source_account"])
        if err:
            raise MirrorError(f"חשבון המקור אינו זמין: {err}", status=409)
        tgt_inst, _tgt_sec, err = accounts.resolve(row["target_account"])
        if err:
            raise MirrorError(f"חשבון הפורג' אינו זמין: {err}", status=409)
        src_remote = proxy.remote_url(src_inst["id"], row["source_provider"], row["source_repo"])
        tgt_remote = proxy.remote_url(tgt_inst["id"], "forgejo",
                                      f"{row['target_owner']}/{row['target_repo']}")

        # 1) the copy lands in scratch, never straight into the forge: a clone that fails halfway
        #    must not leave a half-populated project that looks like a working repository. The
        #    destination is EXPLICIT — `git clone <url>` with no directory derives one from the URL,
        #    which collides the moment two mirrors share a repository name.
        #
        #    A directory that is ALREADY a repository is FETCHED instead of cloned. That is not an
        #    optimization on paper: measured 2026-09-29, a full mirror of the office's own repository
        #    spends 25 minutes moving 1.26 GB, and doing that again every `GIT_MIRROR_INTERVAL` for
        #    data that did not change is what makes a mirror feature nobody leaves switched on.
        tmp.parent.mkdir(parents=True, exist_ok=True)
        seeded_from_forge = False
        seed_note = ""                        # the forge-side reason, when the seed could not run
        touched = False                       # did this run actually start touching the scratch?
        if (tmp / "config").exists():
            touched = True
            cp = _git(["--git-dir", str(tmp), "fetch", "--prune", "--quiet", src_remote,
                       "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"])
            action = "fetch"
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            # SEED FROM THE TARGET FORGE FIRST (herd-408). Measured 2026-11-09 on the MacBook: after
            # any failure the scratch was dropped, so recovery was always ANOTHER full clone of
            # 1.35 GB, which on a loaded engine timed out at 1800 s — and the next run started from
            # zero again. The forge already holds every branch and tag the last successful sync
            # pushed, and its remote is this machine's own proxy, so cloning from it is local; the
            # source fetch after it is then incremental. A first-ever mirror has no repository in the
            # forge: that clone fails at once and the source clone below is what it always was.
            #    The seed gets its OWN short timeout: it is a copy from this machine's proxy, and a run
            #    that spent the full GIT_TIMEOUT on a seed would leave nothing of the budget for the
            #    source fetch that the row's message talks about.
            touched = True
            seed = _git(["clone", "--mirror", "--quiet", tgt_remote, str(tmp)], cwd=tmp.parent,
                        timeout=min(60, GIT_TIMEOUT))
            if seed.returncode == 0:
                #    An empty forge repository clones successfully and brings NOTHING (measured: exit 0,
                #    no refs), so "seeded" is claimed only when the copy actually carries refs — a row
                #    that says it was seeded from the forge should mean it.
                refs = _git(["--git-dir", str(tmp), "for-each-ref", "--count=1"], timeout=60)
                seeded_from_forge = refs.returncode == 0 and bool((refs.stdout or "").strip())
                cp = _git(["--git-dir", str(tmp), "fetch", "--prune", "--quiet", src_remote,
                           "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"])
                action = ("seed-from-forge + fetch" if seeded_from_forge
                          else "clone-from-empty-forge + fetch")
            else:
                seed_note = _git_error(seed)
                shutil.rmtree(tmp, ignore_errors=True)
                cp = _git(["clone", "--mirror", "--quiet", src_remote, str(tmp)], cwd=tmp.parent)
                action = "clone"
        if cp.returncode != 0:
            # NOT removed here: whether a failed copy is worth keeping is ONE decision, in the
            # `finally` below and by `_scratch_usable` (herd-408) — a failed FETCH over a good older
            # copy is a scratch worth retrying from, a failed CLONE is not.
            raise MirrorError(f"המשיכה מהמקור נכשלה ({action}): {_git_error(cp)}"
                              + (f" · ההעתקה מהפורג' לא הייתה זמינה: {seed_note}" if seed_note else ""),
                              status=502)
        size = _dir_bytes(tmp)
        if size > MAX_BYTES:
            raise MirrorError(f"המאגר גדול מהתקרה ({size // (1024*1024)}MB מול "
                              f"{MAX_BYTES // (1024*1024)}MB) — המראה לא נוצרה.", status=413)

        # 2) the project must exist before a push can land. Create it if missing; an existing one is
        #    the normal case on every run after the first.
        _ensure_repo(row)

        # 3) the push IS the mutation: until it starts, the forge still holds the previous copy.
        #
        #    An EXPLICIT refspec, not `--mirror`, and the difference is measured. `--mirror` pushes
        #    every ref a GitHub clone carries, including `refs/pull/<n>/head` — a namespace the forge
        #    RESERVES for its own pull requests. Forgejo refuses those refs, git exits non-zero, and
        #    the sync reports a failure on a push that actually delivered every branch and tag (the
        #    office's own repository: 18 of 25 refs land, the other 7 are GitHub's PR refs). So the
        #    two namespaces a forge really hosts are pushed, with `--prune` — which is what keeps a
        #    branch deleted upstream from living on here forever.
        cp = _git(["--git-dir", str(tmp), "push", "--prune", "--quiet", tgt_remote,
                   "refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*"])
        if cp.returncode != 0:
            raise MirrorError(f"הדחיפה לפורג' נכשלה: {_git_error(cp)}", status=502)

        _update(mid, status="ok", error=None, seconds=round(time.time() - started, 1), size=size)
        ok = True
        return {**_row_out(_find(mid) or row), "ok": True, "id": mid, "status": "ok",
                "bytes": size, "seconds": round(time.time() - started, 1),
                "seeded_from_forge": seeded_from_forge}
    except MirrorError as e:
        _update(mid, status="error", error=e.he_message, seconds=round(time.time() - started, 1))
        _backoff(mid)
        return {"ok": False, "id": mid, "status": "error", "error": e.he_message,
                "status_code": e.status}
    except subprocess.TimeoutExpired:
        msg = f"הסנכרון חרג מהזמן שהוקצב ({GIT_TIMEOUT}s) — המאגר כנראה גדול מדי למכונה הזו."
        _update(mid, status="error", error=msg, seconds=round(time.time() - started, 1))
        _backoff(mid)
        return {"ok": False, "id": mid, "status": "error", "error": msg}
    except Exception as e:                          # noqa: BLE001 — an unexpected failure is reported
        msg = "כשל לא צפוי בסנכרון."
        _update(mid, status="error", error=msg, seconds=round(time.time() - started, 1))
        _backoff(mid)
        log.exception("mirror %s failed", mid)
        return {"ok": False, "id": mid, "status": "error", "error": msg}
    finally:
        # WHAT TO KEEP IS ONE DECISION, AND A FAILED RUN KEEPS ITS SCRATCH (herd-408). A successful
        # sync keeps the copy — that is what makes the next run an incremental fetch instead of
        # another 1.35 GB — and a FAILED one keeps it too, unless the copy is not a usable repository
        # or the free-space floor needs the room. The failure that costs most is a TIMEOUT on a big
        # clone (measured: 1830.8 s against a 1800 s budget, MacBook 2026-11-09); dropping the copy
        # there guarantees the next attempt pays it again from zero. `_scratch_usable` is the line
        # between "a FETCH that failed over a good older copy" (keep, retry incrementally) and "a
        # CLONE that died halfway" (drop — its refs point at objects that never arrived).
        try:
            room = _free_mb() >= MIN_FREE_MB * 2
            keep = bool(ok and KEEP_SCRATCH and room)
            #    `touched` guards the only expensive part: if this run never ran git (a free-space
            #    refusal, an account that would not resolve), there is nothing to inspect and no scan
            #    is worth holding the lock for.
            if not keep and not ok and KEEP_SCRATCH and room and touched and _scratch_usable(tmp):
                keep = True
            if not keep:
                shutil.rmtree(tmp, ignore_errors=True)
        finally:
            #    The lock is released on EVERY path — including an unexpected error from the keeper
            #    itself. Releasing it after a call that shells out to git means one unexpected throw
            #    wedges every later sync into `busy` until the container restarts, which is the same
            #    class of silent stop this whole change exists to remove (found in review).
            _SYNC_LOCK.release()


def sync_in_background(mid: str) -> None:
    """Run `sync` on a thread, and make sure its death is RECORDED rather than silent.

    Written after a real one. A background sync that dies BEFORE `sync`'s own try/except — or whose
    thread ends for any other reason — leaves the registry row exactly as it was: the caller was told
    `started`, the row says nothing new, and the only trace is a scratch directory that stops growing.
    An operator then polls a status that will never move. Everything this thread can fail with is
    therefore logged AND written to the row, so "the sync did not happen" is always visible where the
    caller is looking.
    """
    def run():
        try:
            res = sync(mid)
            log.info("mirror sync %s finished: %s", mid, res.get("status") or res.get("ok"))
        except Exception as e:                      # noqa: BLE001 — the whole point of this wrapper
            log.exception("mirror sync %s died before it could report", mid)
            try:
                _update(mid, status="error",
                        error="הסנכרון נכשל לפני שדיווח — הפרטים בלוג של השירות.")
                _backoff(mid)                       # a thread that died is a failure like any other
            except Exception:                       # noqa: BLE001 — never raise on a daemon thread
                log.exception("could not even record the failure of %s", mid)

    threading.Thread(target=run, daemon=True, name=f"mirror-sync-{mid[:24]}").start()


def _git_error(cp: subprocess.CompletedProcess) -> str:
    """git's own last line, which is the sentence that names the cause."""
    text = (cp.stderr or cp.stdout or "").strip().splitlines()
    return text[-1][:300] if text else f"git exited {cp.returncode}"


def _ensure_repo(row: dict) -> None:
    from adapters import adapter_for
    inst, sec, err = accounts.resolve(row["target_account"])
    if err:
        raise MirrorError(f"חשבון הפורג' אינו זמין: {err}", status=409)
    ad = adapter_for("forgejo", sec or {}, inst.get("id"))
    full = f"{row['target_owner']}/{row['target_repo']}"
    try:
        ad.get_repo(full)
        return
    except Exception:                               # noqa: BLE001 — 404 is the expected path here
        pass
    try:
        ad.create_repo(row["target_repo"], owner=row["target_owner"],
                       private=bool(row.get("private", True)),
                       description=f"מראה של {row['source_repo']} ({row['source_provider']})")
    except Exception as e:                          # noqa: BLE001
        raise MirrorError(f"לא הצלחתי ליצור את המאגר בפורג' "
                          f"({getattr(e, 'he_message', None) or 'שגיאה לא צפויה'}).", status=502)


def _update(mid: str, *, status: str, error: str | None, seconds: float | None = None,
            size: int | None = None) -> None:
    """Write the RESULT of one run into the registry row.

    This is the ONE place that knows the row's field names, because they are not the names a caller
    says out loud: a caller reports a `status` and the row keeps `last_status`. Letting each call site
    name the fields directly is exactly what produced the bug this comment prevents — the sync wrote
    its result under FRESH keys (`status`, `error`, `seconds`) and every row read "new" forever while
    the sync itself was working.
    """
    with _LOCK:
        rows = load()
        for r in rows:
            if r.get("id") == mid:
                # Drop the keys an earlier version of this function wrote by mistake (see its
                # docstring): they are not read by anything, and leaving them in makes the ROW
                # override a caller's own answer when it is spread into a response.
                for legacy in ("status", "error", "seconds"):
                    r.pop(legacy, None)
                r["last_status"] = status
                r["last_error"] = error
                r["last_run"] = int(time.time())
                if status == "ok":
                    # a success resets the widening clock — the next run is due on the interval again
                    r["consecutive_failures"] = 0
                    r.pop("next_due", None)
                if seconds is not None:
                    r["last_seconds"] = seconds
                if size is not None:
                    r["bytes"] = size
        _save(rows)


def _backoff(mid: str) -> None:
    """Widen the clock after a failure: wait 1x, 2x, 4x … the interval, capped at BACKOFF_MAX.

    Called after the row already says `error`, so the operator sees the failure AND the pause in one
    read. Counting on the ROW (not in memory) matters: the app restarts, and a count that lives in a
    process resets on every restart — which is the same as no backoff at all on a container that
    restarts more often than it syncs.
    """
    with _LOCK:
        rows = load()
        for r in rows:
            if r.get("id") == mid:
                n = int(r.get("consecutive_failures") or 0) + 1
                r["consecutive_failures"] = n
                step = min(int(r.get("interval") or INTERVAL) * (2 ** min(n - 1, 8)), BACKOFF_MAX)
                r["next_due"] = int(time.time()) + step
                log.info("mirror %s failed %d time(s) in a row — next attempt in %ds", mid, n, step)
        _save(rows)


def set_paused(mid: str, paused: bool) -> dict:
    """Stop or restart the SCHEDULE for one mirror — the state the row was missing.

    Before this, an operator paused a mirror by setting its interval to ten years (the MacBook,
    2026-11-09T15:45Z) — a number standing in for a state, invisible in the row's own vocabulary and
    one careless edit away from a surprise. A pause stops the SCHEDULER only: the scratch, the forge
    copy and a manual `sync` all survive it, because a pause means "do not run by itself", never
    "forget this mirror". Resuming starts the clock from now instead of firing on the next tick of a
    backoff that was paused for a day.
    """
    with _LOCK:
        rows = load()
        for r in rows:
            if r.get("id") == mid:
                r["paused"] = bool(paused)
                r.pop("next_due", None)
                if not paused:
                    r["next_due"] = int(time.time()) + int(r.get("interval") or INTERVAL)
                _save(rows)
                return _row_out(r)
    raise MirrorError("מראה כזו אינה רשומה.", status=404)


# ── the scheduler ────────────────────────────────────────────────────────────────────────────────
def due(now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for r in load():
        if r.get("paused"):
            continue                     # a paused row is a decision, not a delay
        last = r.get("last_run") or 0
        nxt = r.get("next_due") or 0
        if now - last >= int(r.get("interval") or INTERVAL) and now >= nxt:
            out.append(r)
    return out


def start_scheduler() -> threading.Thread | None:
    """A daemon thread that syncs what is due. Off when GIT_MIRROR_INTERVAL=0.

    A thread and not a cron: the work needs this process's credential resolution, and the app is a
    single container with one volume — the simplest thing that cannot run two syncs at once is here.
    """
    if INTERVAL <= 0:
        log.info("mirror scheduler off (GIT_MIRROR_INTERVAL=0)")
        return None

    def loop():
        time.sleep(30)                  # let the app finish booting before touching anything
        while True:
            try:
                for row in due():
                    if _SYNC_LOCK.locked():
                        break
                    log.info("mirror sync (scheduled): %s", row.get("id"))
                    sync(row["id"])
            except Exception:           # noqa: BLE001 — the loop must survive its own failures
                log.exception("mirror scheduler tick failed")
            time.sleep(300)

    t = threading.Thread(target=loop, name="git-mirror-scheduler", daemon=True)
    t.start()
    return t
