#!/usr/bin/env python3
"""test_transfer_modes — a volume copy into a destination reached as root (as always) and as a user who is not
root but may run docker (DGO-1508: the Dell, `PermitRootLogin no`, `AllowUsers owner` in the docker group).

Both ends are this machine, through the real bash; the source is a directory standing in for a volume.
- root (forced): the stage and the volume are host paths, the commands exactly as before — staged, verified,
  extracted, the stage removed;
- docker (real docker and the HELPER image, run only where this user is not root and docker answers): the
  same tree arrives byte for byte — a 120-character name, a nested directory, a link, an empty file, a name
  with spaces — nothing written under /var/lib; a stage left by an earlier attempt RESUMES from its own size;
  one from a different source is refused by name (source_changed); the direct mode empties the volume first;
- a destination that is neither root nor allowed docker is refused by name, before anything is written.

Run: python3 apps/computers/tests/test_transfer_modes.py   (GNU tar/stat on the host; docker for the second half)
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import transfer  # noqa: E402

FAIL: list[str] = []
PROBE = "probe-dgo1508"


def check(cond, what):
    if not cond:
        FAIL.append(what)


def argv_for(machine: str, command: str) -> list[str]:
    return ["bash", "-c", command]


def _tree(root: Path) -> None:
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / ("n" * 120)).write_bytes(os.urandom(70000))
    (root / "with space.txt").write_text("hello\n")
    (root / "empty").write_bytes(b"")
    (root / "big.bin").write_bytes(os.urandom(300000))
    os.symlink("with space.txt", root / "link")


def _listing(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        st = os.lstat(p)
        own = f"{st.st_uid}:{st.st_gid}"
        if p.is_symlink():
            out.append(f"L {rel} -> {os.readlink(p)} {own}")
        elif p.is_file():
            out.append(f"F {rel} {hashlib.sha256(p.read_bytes()).hexdigest()} {own}")
        else:
            out.append(f"D {rel} {own}")
    return out


def _run_job(**kw) -> dict:
    res = transfer.start(argv_for, frm="src", to="dst", **kw)
    check("job" in res, f"the copy starts: {res}")
    jid = (res.get("job") or {}).get("id")
    until = time.time() + 300
    while jid and time.time() < until:
        s = transfer.status(jid)
        if s["state"] not in ("queued", "running"):
            return s
        time.sleep(0.5)
    return transfer.status(jid) if jid else {}


def test_root_mode():
    with tempfile.TemporaryDirectory() as t:
        vols, stage, bin_ = Path(t, "volumes"), Path(t, "stage"), Path(t, "bin")
        src = vols / "srcvol" / "_data"
        src.mkdir(parents=True)
        bin_.mkdir()
        _tree(src)
        # docker here only makes a volume: the directory docker would make
        Path(bin_, "docker").write_text(f"#!/bin/bash\n[ \"$1 $2\" = \"volume create\" ] && mkdir -p '{vols}'/\"$3\"/_data; exit 0\n")
        os.chmod(Path(bin_, "docker"), 0o755)
        saved = (transfer.VOL_ROOT, transfer.STAGE_DIR, transfer._dest_mode, os.environ["PATH"])
        transfer.VOL_ROOT, transfer.STAGE_DIR = str(vols), str(stage)
        transfer._dest_mode = lambda a, m: "root"
        os.environ["PATH"] = f"{bin_}:{os.environ['PATH']}"
        try:
            s = _run_job(volume="srcvol", dest_volume="dstvol")
            check(s.get("state") == "ok" and s.get("dest_mode") == "root" and s.get("sha256"),
                  f"root: staged, verified, extracted: {s.get('state')} {s.get('error')}")
            check(_listing(vols / "dstvol" / "_data") == _listing(src), "root: the tree arrives whole")
            check(not list(stage.glob("*")), f"root: the stage is removed: {list(stage.glob('*'))}")
        finally:
            transfer.VOL_ROOT, transfer.STAGE_DIR, transfer._dest_mode, os.environ["PATH"] = saved


def _docker_ok() -> bool:
    if os.geteuid() == 0 or not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=60).returncode == 0


def _sh(*argv: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), input=stdin, capture_output=True, timeout=300)


def _in_volume(volume: str, script: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return _sh("docker", "run", "--rm", "-i", "--init", "--network", "none", "-v", f"{volume}:/v",
               "-v", f"{transfer.STAGE_VOLUME}:/s", transfer.HELPER, "sh", "-c", script, stdin=stdin)


def _no_link_owner(rows: list[str]) -> list[str]:
    """busybox's tar does not restore a symlink's owner (transfer.HELPER's note): a link is compared without it."""
    return [r.rsplit(" ", 1)[0] if r.startswith("L ") else r for r in rows]


def _volume_listing(volume: str) -> list[str]:
    """The volume's tree as `_listing` says it, read through the helper (this user cannot read it on the host)."""
    r = _in_volume(volume, "cd /v && find . -mindepth 1 | sort | while IFS= read -r p; do o=$(stat -c %u:%g \"$p\"); "
                           "if [ -L \"$p\" ]; then echo \"L ${p#./} -> $(readlink \"$p\") $o\"; "
                           "elif [ -f \"$p\" ]; then echo \"F ${p#./} $(sha256sum < \"$p\" | cut -d' ' -f1) $o\"; "
                           "else echo \"D ${p#./} $o\"; fi; done")
    return r.stdout.decode().splitlines()


def test_docker_mode():
    if not _docker_ok():
        print("SKIP test_docker_mode: needs a user who is not root and may run docker")
        return
    dst, stage_vol = f"{PROBE}-dst", f"{PROBE}-stage"
    with tempfile.TemporaryDirectory() as t:
        vols = Path(t, "volumes")
        src = vols / "srcvol" / "_data"
        src.mkdir(parents=True)
        _tree(src)
        # a file of www-data (33 on Debian/Ubuntu, 82 in alpine's passwd): it must arrive as 33, not by its name
        _sh("docker", "run", "--rm", "-v", f"{src}:/x", transfer.HELPER, "chown", "33:33", "/x/with space.txt")
        saved = (transfer.VOL_ROOT, transfer.STAGE_VOLUME)
        transfer.VOL_ROOT, transfer.STAGE_VOLUME = str(vols), stage_vol
        try:
            check(transfer._dest_mode(argv_for, "dst") == "docker", "a user in the docker group is served through docker")
            check(os.lstat(src / "with space.txt").st_uid == 33, "the fixture: a file of uid 33 on the source")
            s = _run_job(volume="srcvol", dest_volume=dst)
            check(s.get("state") == "ok" and s.get("dest_mode") == "docker" and s.get("sha256"),
                  f"docker: staged, verified, extracted: {s.get('state')} {s.get('error')}")
            check((s.get("dest_free_bytes") or 0) > 0 and (s.get("dest_bytes") or 0) > 0,
                  f"docker: the room was measured and the copy's size read: {s.get('dest_free_bytes')} {s.get('dest_bytes')}")
            check(_no_link_owner(_volume_listing(dst)) == _no_link_owner(_listing(src)), f"docker: the tree arrives byte for byte: "
                                                         f"{_volume_listing(dst)} vs {_listing(src)}")
            left = _in_volume(dst, "ls -A /s").stdout.decode().split()
            check(not left, f"docker: the stage is removed: {left}")
            # a stage an earlier attempt left resumes from its own size
            whole = subprocess.run(["tar", "-C", str(src), "-cf", "-", "."], capture_output=True).stdout
            name = f"/s/srcvol__{dst}.tar"
            fp = transfer._fingerprint(argv_for, "src", str(src))
            _in_volume(dst, f"cat > {name}", stdin=whole[:100000])
            _in_volume(dst, f"printf %s '{{\"fingerprint\": \"{fp}\"}}' > {name}.json")
            _in_volume(dst, "find /v -mindepth 1 -delete")
            s = _run_job(volume="srcvol", dest_volume=dst)
            check(s.get("state") == "ok" and s.get("resumed_from") == 100000 and _no_link_owner(_volume_listing(dst)) == _no_link_owner(_listing(src)),
                  f"docker: a stage left behind resumes at its own size: {s.get('resumed_from')} {s.get('error')}")
            # …and one from another source is refused by name
            _in_volume(dst, f"cat > {name}", stdin=whole[:5000])
            _in_volume(dst, f"printf %s '{{\"fingerprint\": \"{'0' * 64}\"}}' > {name}.json")
            s = _run_job(volume="srcvol", dest_volume=dst)
            check(s.get("state") == "error" and s.get("error_code") == "source_changed",
                  f"docker: another source's stage is refused: {s.get('error_code')} {s.get('error')}")
            s = _run_job(volume="srcvol", dest_volume=dst, restart=True)
            check(s.get("state") == "ok" and s.get("resumed_from") == 0, f"docker: restart starts over: {s.get('error')}")
            # the direct mode empties the volume first, and never removes its mount point
            _in_volume(dst, "echo stale > /v/stale")
            s = _run_job(volume="srcvol", dest_volume=dst, resume=False)
            check(s.get("state") == "ok" and _no_link_owner(_volume_listing(dst)) == _no_link_owner(_listing(src)),
                  f"docker: direct mode replaces what was there: {s.get('error')} {_volume_listing(dst)[:3]}")
        finally:
            transfer.VOL_ROOT, transfer.STAGE_VOLUME = saved
            _sh("docker", "volume", "rm", "-f", dst, stage_vol)
            # what the helper extracted is root's: emptied through it before the directory goes
            shutil.rmtree(t, ignore_errors=True)


def test_neither():
    try:
        transfer._dest_mode(lambda m, c: ["bash", "-c", "echo none"], "dst")
        check(False, "a user who is neither root nor in the docker group is refused")
    except RuntimeError as e:
        check("docker" in str(e), f"…by name: {e}")


def main() -> int:
    for t in (test_root_mode, test_docker_mode, test_neither):
        before = len(FAIL)
        t()
        print(("PASS " if len(FAIL) == before else "FAIL ") + t.__name__)
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
