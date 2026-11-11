"""platform.state.yaml is REPLACED under its lock, never rewritten in place (DGO-616).

    python3 platform/manager/test_state_write.py          (or: python -m pytest platform/manager/test_state_write.py -q)

The compiler wrote the office's desired state with `write_text`: the file truncated first, then filled. A
reader in between (`render`, the console, the link's catalog) saw an office with no apps, and a write that
failed half way left the file EMPTY. Its native twin (packaging/dgo internal/compiler/writers.go) always
replaced the file under data/.locks/platform.state. What this holds, on synthetic files only:
  * a write replaces the file (a new inode), keeps its mode, and leaves nothing beside it;
  * a write that fails half way — a text that cannot be encoded — leaves the OLD file whole;
  * a frozen file (chmod 444) is refused with PermissionError and left as it was;
  * a writer waits for the lock another writer holds;
  * where no lock can be had the write still happens, and says nothing (the twin's oracle compares output);
  * ensure_state creates a missing file with the mode a plain create gives it.
On the code before DGO-616 the first, second and fourth fail.
"""
import importlib.util
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_state_write_mod", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_state_write_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()

STATE_TEXT = """# platform.state.yaml — a comment that must survive every write
schema_version: 1

apps:
  traefik:          { enabled: true }   # the edge
  console:          { enabled: true }
"""


def _repo():
    d = pathlib.Path(tempfile.mkdtemp(prefix="dgo616-"))
    state = d / "platform.state.yaml"
    state.write_text(STATE_TEXT, encoding="utf-8")
    rc.REPO, rc.STATE, rc.GEN, rc.DEFAULT_STATE = d, state, d / ".generated", d / "platform.state.default.yaml"
    return d, state


def _left(d):
    return sorted(p.name for p in d.glob(".platform.state.yaml.*"))


def test_a_write_replaces_the_file_and_keeps_its_mode():
    d, state = _repo()
    os.chmod(state, 0o640)
    before = state.stat().st_ino
    assert rc.set_disposition("console", "disabled") is True
    assert "  console:          { state: disabled, by: user }\n" in state.read_text(encoding="utf-8")
    assert state.stat().st_ino != before, "written in place: a reader could have caught it empty"
    assert stat.S_IMODE(state.stat().st_mode) == 0o640
    assert _left(d) == []


def test_a_write_that_fails_half_way_leaves_the_old_file():
    d, state = _repo()
    try:
        rc.set_disposition("console", "disabled", by="\udc80")   # a lone surrogate: utf-8 cannot write it
    except UnicodeEncodeError:
        pass
    else:
        raise AssertionError("the write did not fail")
    assert state.read_text(encoding="utf-8") == STATE_TEXT, "a failed write emptied the desired state"
    assert _left(d) == []


def test_a_frozen_file_is_refused_and_untouched():
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return   # root may write a read-only file, the old writer and the new alike
    d, state = _repo()
    os.chmod(state, 0o444)
    try:
        rc.set_disposition("console", "disabled")
    except PermissionError as e:
        assert str(state) in str(e)
    else:
        raise AssertionError("a frozen state file was written")
    assert state.read_text(encoding="utf-8") == STATE_TEXT
    assert _left(d) == []


def test_a_writer_waits_for_the_lock():
    if sys.platform == "win32":
        return
    d, state = _repo()
    (d / "data" / ".locks").mkdir(parents=True)
    holder = subprocess.Popen([sys.executable, "-c",
                               "import fcntl,os,sys,time\n"
                               "fd=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o666)\n"
                               "fcntl.flock(fd,fcntl.LOCK_EX)\nprint('held',flush=True)\ntime.sleep(1.5)\n",
                               str(d / "data" / ".locks" / "platform.state")], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    done = []
    t0 = time.monotonic()
    w = threading.Thread(target=lambda: done.append(rc.set_disposition("console", "disabled")))
    w.start()
    time.sleep(0.5)
    assert not done, "the writer did not wait for the lock another writer held"
    assert state.read_text(encoding="utf-8") == STATE_TEXT
    w.join(10)
    holder.wait(10)
    assert done == [True] and time.monotonic() - t0 >= 1.0
    assert "{ state: disabled, by: user }" in state.read_text(encoding="utf-8")


def test_another_thread_waits_for_the_lock_too():
    """Re-entrant per THREAD, not per process: a second thread of the same process waits on the flock (the
    second reader of DGO-616 — a process-wide count let it write without the lock)."""
    if sys.platform == "win32":
        return
    _repo()
    order = []

    def holder():
        with rc._state_lock():
            order.append("A in")
            time.sleep(0.6)
            order.append("A out")

    def second():
        time.sleep(0.2)
        with rc._state_lock():
            order.append("B in")

    a, b = threading.Thread(target=holder), threading.Thread(target=second)
    a.start(); b.start(); a.join(5); b.join(5)
    assert order == ["A in", "A out", "B in"], order


def test_no_lock_to_be_had_still_writes_and_says_nothing():
    d, state = _repo()
    (d / "data").mkdir()
    (d / "data" / ".locks").write_text("a file where the lock's directory would be")
    import contextlib
    import io
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
        assert rc.set_disposition("console", "disabled") is True
    assert err.getvalue() == ""
    assert "{ state: disabled, by: user }" in state.read_text(encoding="utf-8")


def test_ensure_state_creates_a_missing_file_with_a_plain_mode():
    d, state = _repo()
    state.unlink()
    rc.DEFAULT_STATE.write_text(STATE_TEXT, encoding="utf-8")
    umask = os.umask(0o022)
    try:
        rc.ensure_state()
    finally:
        os.umask(umask)
    assert state.read_text(encoding="utf-8") == STATE_TEXT
    if sys.platform != "win32":
        assert stat.S_IMODE(state.stat().st_mode) == 0o644
    assert _left(d) == []


def main():
    fails = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
        try:
            fn()
            print("PASS  " + name)
        except Exception as e:   # noqa: BLE001 — every failure is reported, then the next test runs
            fails += 1
            print(f"FAIL  {name}\n        {type(e).__name__}: {e}")
    print("\nall passed" if not fails else f"\n{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
