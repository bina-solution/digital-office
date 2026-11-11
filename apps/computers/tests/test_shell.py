"""shell_test — the terminal's session manager, proven without a machine (DGO-553).

The heavy half of a terminal is a pty and a cursor, and neither needs SSH to be tested: a session
here is `/bin/sh -i`, which is exactly the shape the office's ssh sessions have (a process on a
master fd that talks back). What this asserts is what the browser depends on:

  * a session says what it said, and a reader that comes back with `cursor` gets only the new bytes
    — that is the whole of "polling does not lose output";
  * a reader that fell behind the buffer is TOLD it lost bytes (`lost`) instead of being served a
    silent hole;
  * input reaches the far side and the answer comes back on the same call;
  * the caps refuse in a sentence a screen can show, not with a traceback;
  * a closed session answers "gone", and the idle reaper does not eat a session somebody is using.

Run: python3 apps/computers/tests/test_shell.py   (or pytest — it is plain functions)
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # apps/computers, so `import shell` is the app's

import shell  # noqa: E402


def _open(**kw) -> shell.Session:
    s = shell.start("testcid", ["/bin/sh", "-i"], 80, 24)
    for _ in range(30):                            # the shell prints its prompt on its own time
        s.drain(0.05)
        if s.total:
            break
    return s


def _settle(s: "shell.Session", cursor: int, quiet: float = 0.35,
            timeout: float = 10.0) -> tuple[bytes, int]:
    """Read until the shell has been SILENT for `quiet` seconds — then it has finished answering.

    "Wait for the marker" is not the same property: the pty echoes the typed line, so the marker of
    a command shows up BEFORE the command's own output, and a test that stops there sees the rest as
    "unexpected new bytes" (measured 2026-11-01: the same test went green twice and red once per
    run). Silence is the only honest signal that a prompt has come back.
    """
    deadline = time.time() + timeout
    got = b""
    cur = cursor
    last = time.time()
    while time.time() < deadline:
        s.drain(0.1)
        data, cur, _ = s.since(cursor)
        if len(data) > len(got):
            got, last = data, time.time()
        elif time.time() - last >= quiet:
            return got, cur
    raise AssertionError(f"the shell never went quiet; last output {got[-200:]!r}")


def test_cursor_returns_only_new_bytes() -> None:
    s = _open()
    try:
        s.write("echo FIRST\n")
        first, cur = _settle(s, 0)
        assert b"FIRST" in first, f"the command's own output: {first!r}"
        again, cur2, _ = s.since(cur)
        assert again == b"", f"the reader is caught up, so nothing comes back: {again!r}"
        assert cur2 == cur, "an idle read does not move the cursor"
        s.write("echo SECOND\n")
        second, cur3 = _settle(s, cur2)
        assert b"SECOND" in second, f"the next answer: {second!r}"
        assert b"FIRST" not in second, f"the reader already had the first answer: {second!r}"
        assert cur3 > cur2
    finally:
        s.close()


def test_a_reader_that_fell_behind_is_told() -> None:
    old = shell.BUFFER_BYTES
    shell.BUFFER_BYTES = 4096                      # a small buffer makes the loss happen at once
    s = None
    try:
        s = _open()
        # more than the buffer, in one go: the front of the stream is dropped
        s.write("head -c 9000 /dev/zero | tr '\\0' 'x'\n")
        for _ in range(40):
            s.drain(0.1)
            if s.total > shell.BUFFER_BYTES:
                break
        data, cur, lost = s.since(0)
        assert lost, "the reader's cursor is older than the buffer, and it is told so"
        assert cur == s.total
        assert len(data) <= shell.BUFFER_BYTES, "the buffer never grows past its cap"
    finally:
        shell.BUFFER_BYTES = old
        if s is not None:
            s.close()


def test_a_closed_session_answers_instead_of_raising() -> None:
    s = _open()
    s.write("exit\n")
    for _ in range(40):
        s.drain(0.1)
        if s.closed:
            break
    assert not s.alive(), "the shell ended"
    data, cur, _ = s.since(0)                      # the SHAPE of the answer survives the end
    assert cur == s.total and isinstance(data, bytes)
    s.close()
    try:
        shell.get("testcid", s.key.split(":", 1)[1])
    except shell.ShellError as e:
        assert e.status == 404, "a session that is gone is a 404 with a sentence"
    else:
        raise AssertionError("a closed session must not still be handed out")


def test_the_cap_refuses_with_a_sentence() -> None:
    old = shell.MAX_SESSIONS
    shell.MAX_SESSIONS = 1
    first = _open()
    try:
        try:
            shell.start("testcid", ["/bin/sh", "-i"])
        except shell.ShellError as e:
            assert e.status == 429 and e.action, "a refusal says what to do about it"
        else:
            raise AssertionError("the cap must refuse the next session")
    finally:
        shell.MAX_SESSIONS = old
        first.close()


def test_ssh_that_cannot_start_is_a_refusal_not_a_crash() -> None:
    try:
        shell.start("testcid", ["/definitely/not/a/binary"])
    except shell.ShellError as e:
        assert e.status == 502 and "ssh" in str(e)
    else:
        raise AssertionError("a missing ssh must refuse")


def test_idle_reaper_leaves_a_session_being_used() -> None:
    s = _open()
    try:
        s.at = time.time() - (shell.IDLE_SECONDS + 5)
        gone = shell.reap()
        assert s.key in gone, "an idle session is closed"
        assert not s.alive(), "and its process is gone with it"
    finally:
        s.close()



def test_a_session_belongs_to_the_caller_that_opened_it():
    """A session is answered to the caller that opened it, and to nobody else.

    The key is `<machine>:<sid>` — the machine and a random id, with no caller in it — so before this
    an office that learned the id could read or type into another office's terminal (second reader,
    2026-11-02). Sharing a machine shares the MACHINE, not the output of somebody's session.
    """
    s = shell.start("sharedcid", ["/bin/sh", "-i"], 80, 24, owner="macbook")
    try:
        assert shell.get("sharedcid", s.key.split(":", 1)[1], owner="macbook") is s
        for other in ("vps1", ""):
            try:
                shell.get("sharedcid", s.key.split(":", 1)[1], owner=other)
            except shell.ShellError as e:
                assert e.status == 404, e.status
            else:
                raise AssertionError(f"a session opened by macbook was handed to {other!r}")
    finally:
        s.close()

if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:                 # noqa: BLE001 — a test runner reports, never hides
                fails += 1
                print(f"FAIL {name}: {e}")
    print(f"shell_test — {fails} failing")
    sys.exit(1 if fails else 0)
