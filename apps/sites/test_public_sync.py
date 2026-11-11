"""sites.public.sync — a site's content comes over the `computers` door in SLICES, whatever it weighs.

The door (and this app) hold a command's whole output in memory, and `computers` runs under a 160 MB
cap: the old sync sent the whole archive as ONE base64 answer and killed it for any site of more than
a few dozen MB (DGO-1503: Exampleu's clone, 213 MB). Here the "machine" is a local shell over a temporary
directory, so the real commands run (tar, tail -c, head -c, base64, sha256), and the test proves:

  * a site several slices big arrives byte for byte (a Hebrew file name included), and no answer
    from the door is bigger than one slice;
  * a slice corrupted on the way is refused — the previous copy keeps serving — and nothing is left
    behind, on the machine or here.

    python3 apps/sites/test_public_sync.py
"""
import os
import random
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("SITES_STATE_DIR", tempfile.mkdtemp())
import machines  # noqa: E402
import public  # noqa: E402

SEEN = {"max_stdout": 0, "calls": 0}
CORRUPT = {"on": False}


def fake_exec(machine_id, command, timeout=60):
    # COPYFILE_DISABLE: macOS's tar would add AppleDouble `._*` members for every file (Linux's does not)
    p = subprocess.run(["sh", "-c", command], capture_output=True, timeout=timeout,
                       env={**os.environ, "COPYFILE_DISABLE": "1"})
    out = p.stdout.decode("utf-8", "replace")
    if CORRUPT["on"] and "head -c" in command and len(out) > 100:
        out = out[:50] + ("A" if out[50] != "A" else "B") + out[51:]
    SEEN["max_stdout"] = max(SEEN["max_stdout"], len(out))
    SEEN["calls"] += 1
    return {"code": p.returncode, "stdout": out, "stderr": p.stderr.decode("utf-8", "replace")}


def fake_stdout_of(machine_id, command, timeout=60, **kw):
    return fake_exec(machine_id, command, timeout)["stdout"]


def main():
    machines.exec_on = fake_exec
    machines.stdout_of = fake_stdout_of
    machines.q = shlex.quote
    work = Path(tempfile.mkdtemp(prefix="sites-sync-"))
    public.PUBLIC_DIR = work / "cache"
    public.SYNC_CHUNK = 256 * 1024
    root = work / "machine" / "site-x"
    (root / "site" / "פרויקטים").mkdir(parents=True)
    (root / "site" / "index.html").write_text("<h1>דוגמה</h1>", encoding="utf-8")
    (root / "site" / "פרויקטים" / "index.html").write_text("<p>פרויקט</p>", encoding="utf-8")
    rnd = random.Random(1503)
    big = bytes(rnd.getrandbits(8) for _ in range(900 * 1024))
    (root / "site" / "hero.mp4").write_bytes(big)
    site = {"id": f"t{os.getpid()}", "machine": "m", "root": str(root), "content": {"type": "dir"}}

    def left_behind():
        return list(Path("/var/tmp").glob(f"bina-site-sync-{site['id']}.*.tar")) + \
            list(public.PUBLIC_DIR.glob(f".{site['id']}.*.tar"))

    res = public.sync(site, force=True)
    assert res["ok"], res
    cache = public.cache_dir(site["id"])
    assert (cache / "hero.mp4").read_bytes() == big
    assert (cache / "פרויקטים" / "index.html").read_text(encoding="utf-8") == "<p>פרויקט</p>"
    assert res["files"] == 3 and res["bytes"] > len(big), res
    assert SEEN["max_stdout"] <= public.SYNC_CHUNK * 4 // 3 + 8, SEEN
    assert SEEN["calls"] >= 6, SEEN                               # 900 KB in 256 KB slices: ≥ 4 reads
    assert not left_behind(), left_behind()

    (root / "site" / "index.html").write_text("<h1>חדש</h1>", encoding="utf-8")
    CORRUPT["on"] = True
    bad = public.sync(site, force=True)
    CORRUPT["on"] = False
    assert not bad["ok"] and "אינו זהה" in bad["reason"], bad
    assert (cache / "index.html").read_text(encoding="utf-8") == "<h1>דוגמה</h1>", "the previous copy must keep serving"
    assert not left_behind(), left_behind()

    # two syncs of one site at once (the switch to `office` and the public pass): never both — the second
    # answers that one is running (it must not WAIT: a caller on the event loop would stop the app), and
    # the copy that lands is whole
    import threading
    results = []
    threads = [threading.Thread(target=lambda: results.append(public.sync(site, force=True))) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(bool(r["ok"]) for r in results) in ([False, True], [True, True]), results
    assert all(r["ok"] or r.get("busy") for r in results), results
    assert (cache / "index.html").read_text(encoding="utf-8") == "<h1>חדש</h1>" and (cache / "hero.mp4").read_bytes() == big
    assert not left_behind(), left_behind()
    # a caller whose next step needs the copy (the switch to `office`, an asset push) WAITS its turn
    results = []
    threads = [threading.Thread(target=lambda: results.append(public.sync(site, force=True, wait=True))) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [r["ok"] for r in results] == [True, True], results

    # a sync that died before its `finally` (the app restarted) left its staging files: the next one sweeps
    # them — and only ITS site's: `<id>-clone` (another site, whose id starts the same) keeps its own
    Path(f"/var/tmp/bina-site-sync-{site['id']}.deadbeef0000.tar").write_bytes(b"x" * 1024)
    (public.PUBLIC_DIR / f".{site['id']}.deadbeef0000.tar").write_bytes(b"x" * 1024)
    sibling = Path(f"/var/tmp/bina-site-sync-{site['id']}-clone.deadbeef0000.tar")
    sibling.write_bytes(b"y")
    assert public.sync(site, force=True)["ok"] and not left_behind(), left_behind()
    assert sibling.exists(), "another site's staging file was swept"
    sibling.unlink()

    # no archive at all (the directory is gone): a failure, and the previous copy keeps serving
    gone = {**site, "root": str(work / "machine" / "no-such-site")}
    miss = public.sync(gone, force=True)
    assert not miss["ok"], miss
    assert (cache / "hero.mp4").read_bytes() == big and not left_behind(), left_behind()
    print("sites sync: 5/5 ok")


if __name__ == "__main__":
    main()
