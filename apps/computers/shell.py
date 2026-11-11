"""shell — an INTERACTIVE shell on a machine, for a terminal in the browser (DGO-… / lnk-028).

Why this file exists
--------------------
`ssh_run` (app.py) runs ONE command, keeps its whole output in memory and answers when the command
ends. That is the right shape for "run this and tell me what it said", and the wrong shape for a
terminal: a terminal is a SESSION — keystrokes go one way, output the other, and nothing ends until
somebody types `exit`. A session cannot be a `/exec` with a longer timeout: its output arrives while
it runs, and its input is written by a human one key at a time.

The transport is deliberately NOT a websocket
---------------------------------------------
A websocket is the obvious shape and it does not survive the two proxies this office already has
between a browser and an app: the console's `/a/<alias>/` proxy is Flask + `requests` and strips
`Upgrade` (`platform-base/console/app.py`, `_HOP`), so an office whose console frames the app at
`/a/terminal/` would get a socket that never opens. The link's own door copies bytes both ways and
*would* carry one — but only for an app reached on a host of its own, which is exactly the case that
breaks under `*.localhost`.

So a session here is ORDINARY HTTP: start it, post keys to it, poll it. `cursor` is an absolute byte
counter of the stream, so a reader that lost a poll (a tab asleep, a phone in a lift) asks for what
it missed and gets it — up to the buffer, after which it is told it lost data instead of silently
being served a hole. It costs ~150 ms of latency on a keystroke, which is what a person notices as
"the shell is a bit slow", and it costs nothing else.

What it is NOT
--------------
* Not a privilege. The key this session uses is the office's own key, and the machine decides what
  that key may do — exactly as it does for `/exec`. A session that the far side refuses answers with
  the same vocabulary (`classify_stderr`'s words), not with a different one.
* Not persistent. A session lives in this process (a restart ends every shell, and the browser is
  told so). Nothing is written to the volume: the point of a terminal is the machine's own state,
  and a half-recorded session log on disk would be a new place secrets accumulate.
"""
from __future__ import annotations

import errno
import fcntl
import logging
import os
import pty
import select
import struct
import subprocess
import termios
import threading
import time

log = logging.getLogger("computers.shell")

#: How many shells may exist at once. A terminal costs a process and a pty on BOTH ends; the cap is
#: low on purpose (a person has one or two open, and a stuck tab must not be able to exhaust the
#: container).
MAX_SESSIONS = int(os.environ.get("COMPUTERS_SHELL_MAX", "8"))
#: Seconds of silence before a session is closed on its behalf. A terminal left open overnight keeps
#: an SSH connection to somebody's machine alive for no reason.
IDLE_SECONDS = float(os.environ.get("COMPUTERS_SHELL_IDLE", "1800"))
#: Bytes of output kept per session for a reader that is catching up (a slow link, a tab in the
#: background). Beyond it the reader is TOLD it lost bytes (`lost`), never handed a silent gap.
BUFFER_BYTES = int(os.environ.get("COMPUTERS_SHELL_BUFFER", "262144"))
#: What one drain() reads at most, in bytes and in seconds of reading. `yes` on the far side writes
#: without end: an unbounded drain held the session's lock, and a request's worker, for as long as it ran.
#: The rest waits in the pty for the next poll. A QUARTER of the buffer, and never one read past it: a
#: reader that was caught up before a drain is still inside the buffer after it, so nothing is «lost» to
#: it — not even the bytes of a letter held back for the next read (the second reader, round 2).
DRAIN_BYTES = max(1, BUFFER_BYTES // 4)
DRAIN_SECONDS = 0.25
#: How long a write may wait for the far side to take what was typed. The pty is non-blocking: a write
#: that blocked held the session's lock for good when the remote command stopped reading its input
#: (a paste into `sleep`), and every poll, resize, close and the reaper waited on it (round 2).
WRITE_SECONDS = 2.0
#: The TERM every session is opened with — a lie otherwise: `screen-256color` promises keys and
#: sequences we do not forward.
TERM = os.environ.get("COMPUTERS_SHELL_TERM", "xterm-256color")

_SESSIONS: dict[str, "Session"] = {}
_LOCK = threading.Lock()
_REAPER = {"started": False}


class ShellError(RuntimeError):
    """A refusal with a sentence a screen can show (never a bare traceback)."""

    def __init__(self, message: str, status: int = 400, action: str = ""):
        super().__init__(message)
        self.status = status
        self.action = action


def _own_terminal() -> None:
    """Make the pty the child's CONTROLLING terminal (runs in the child, between fork and exec).

    A pty passed as stdin is not enough: a process in a new session with no controlling terminal
    gets `tcgetpgrp` back as ENOTTY, and an interactive shell then announces "can't access tty; job
    control turned off" and — the part that matters — a program that asks the terminal for its size
    or its foreground group gets nothing. `setsid()` detaches from the parent's session and
    `TIOCSCTTY` adopts the pty, which is the ordinary recipe every terminal emulator follows.
    Found by `tests/test_shell.py` on 2026-11-01, when a local `/bin/sh -i` refused its tty while the
    office's ssh sessions (whose pty is on the FAR side) looked fine.
    """
    os.setsid()
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass                                        # a kernel that refuses it: run anyway, say nothing


class Session:
    """One interactive shell: a child process on a pty, and the bytes it has produced so far."""

    def __init__(self, key: str, argv: list[str], cols: int = 100, rows: int = 30,
                 owner: str = ""):
        self.key = key
        #: WHICH CALLER OPENED THIS (an office id, empty for a local caller). The key is
        #: `<machine>:<sid>` and says nothing about who — so a session belonged to whoever knew the
        #: 16 hex characters (second reader, 2026-11-02). Sharing a machine shares its OUTPUT with the
        #: office that opened it, not with every office that can reach the machine.
        self.owner = str(owner or "")
        self.argv = argv
        self.started = time.time()
        self.at = time.time()                       # last time anyone touched it
        self.buf = bytearray()
        self.total = 0                              # absolute offset of the FIRST byte not in buf…
        self.dropped = 0                            # …and of the first byte buf still holds
        self.closed = False
        self.error = ""
        # REENTRANT: `drain()` holds this while it reads, and calls `_finish()` when the stream
        # ends — which has to close the master fd under the same lock. A plain Lock deadlocked
        # the session on its own last read.
        self.lock = threading.RLock()
        self.master, slave = pty.openpty()
        os.set_blocking(self.master, False)         # every read and write here is bounded (WRITE_SECONDS)
        _set_size(self.master, cols, rows)
        env = dict(os.environ)
        env.setdefault("TERM", TERM)
        try:
            self.proc = subprocess.Popen(           # noqa: S603 — argv is built by the caller, never a shell
                argv, stdin=slave, stdout=slave, stderr=slave, env=env,
                close_fds=True, preexec_fn=_own_terminal,
            )
        except OSError as e:                        # ssh itself is missing: say so, do not raise into a route
            os.close(self.master)
            os.close(slave)
            raise ShellError(f"לא ניתן להפעיל ssh: {e}", 502,
                             "בדוק את שירות המחשבים (התמונה אמורה לכלול openssh-client).") from e
        finally:
            try:
                os.close(slave)                     # the child holds its own copy from here on
            except OSError:
                pass

    # ── the stream ───────────────────────────────────────────────────────────────────────────────
    def drain(self, wait: float = 0.0) -> bool:
        """Read whatever the far side has said, waiting up to `wait` seconds for the FIRST byte.

        0.0 = do not wait (the poll case); ~0.12 = "I just sent keys, give the shell a moment" (the
        keystroke case). Whatever is already there is read, so a chatty session is never throttled by
        the wait — up to DRAIN_BYTES / DRAIN_SECONDS a call; the rest is the next poll's.

        True when it stopped on that cap: there may be more in the pty, so a session whose ssh has
        just ended is not «over» for its reader until a drain comes back without it.
        """
        deadline = time.time() + max(0.0, wait)
        first = True
        got, stop_at = 0, None                       # the cap: DRAIN_BYTES, or DRAIN_SECONDS from the first byte
        with self.lock:
            while True:
                if self.closed:
                    return False
                if got >= DRAIN_BYTES or (stop_at is not None and time.time() >= stop_at):
                    return True
                timeout = max(0.0, deadline - time.time()) if (first and wait) else 0.0
                try:
                    r, _, _ = select.select([self.master], [], [], timeout)
                except (OSError, ValueError):
                    self._finish("הקצה המקומי של הטרמינל נסגר")
                    return False
                if not r:
                    break
                try:
                    chunk = os.read(self.master, min(65536, DRAIN_BYTES - got))
                except BlockingIOError:              # ready a moment ago, empty now: nothing to read
                    break
                except OSError as e:
                    if e.errno in (errno.EIO, errno.EBADF):   # the shell ended — that is an answer
                        self._finish("")
                        return False
                    self._finish(str(e))
                    return False
                if not chunk:
                    self._finish("")
                    return False
                self._append(chunk)
                got += len(chunk)
                if stop_at is None:
                    stop_at = time.time() + DRAIN_SECONDS
                first = False
        return False

    def _append(self, chunk: bytes) -> None:
        self.buf += chunk
        self.total += len(chunk)
        if len(self.buf) > BUFFER_BYTES:
            cut = len(self.buf) - BUFFER_BYTES
            del self.buf[:cut]
            self.dropped += cut

    def _finish(self, why: str) -> None:
        """End this session — under its lock, and the master fd closed exactly once.

        `drain()` holds the lock while it is inside `select`/`os.read` on that fd, so closing it
        without the lock let the NUMBER be reused by the next session's pty: a reader that was still
        in `os.read` on the old number then served ANOTHER terminal's bytes (second reader,
        2026-11-02). Whoever gets the lock first marks the session closed; the fd goes with it once.
        """
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if why:
                self.error = why
            try:
                os.close(self.master)
            except OSError:
                pass

    def since(self, cursor: int) -> tuple[bytes, int, bool]:
        """(new bytes, the cursor to send next time, whether bytes were lost before it)."""
        with self.lock:
            lost = cursor < self.dropped
            start = max(cursor, self.dropped)
            data = bytes(self.buf[start - self.dropped:])
            return data, self.total, lost

    def alive(self) -> bool:
        if self.closed:
            return False
        return self.proc.poll() is None

    # ── input ────────────────────────────────────────────────────────────────────────────────────
    def write(self, data: str) -> None:
        """Hand what was typed to the far side, waiting at most WRITE_SECONDS for it to take it all.

        The lock is held for that bounded time only. A far side that stopped reading (a paste into a
        command that never reads its input) is a 409 that says how much went through — never a lock
        held for good."""
        if not data:
            return
        self.at = time.time()
        raw = data.encode("utf-8", "replace")
        deadline = time.time() + WRITE_SECONDS
        with self.lock:
            if self.closed:
                raise ShellError("הטרמינל כבר נסגר", 409, "פתח טרמינל חדש למחשב הזה.")
            sent = 0
            while sent < len(raw):
                try:
                    sent += os.write(self.master, raw[sent:])
                    continue
                except BlockingIOError:
                    pass                            # the pty is full: wait below for room, up to the deadline
                except OSError as e:
                    self._finish(str(e))
                    raise ShellError("הכתיבה לטרמינל נכשלה", 409, "פתח טרמינל חדש.") from e
                left = deadline - time.time()
                if left <= 0:
                    # 503, not 409: the session is alive and may take keys again — the screen keeps it (it drops a
                    # session only on 404 / 409, which mean it is gone) (the second reader, round 3)
                    raise ShellError(f"המחשב לא קורא את מה שמוקלד: עברו {sent} מתוך {len(raw)} בתים", 503,
                                     "הפקודה שרצה לא קוראת קלט. חכה שתסתיים, או סגור את הטרמינל ופתח חדש.")
                try:
                    select.select([], [self.master], [], left)
                except (OSError, ValueError):
                    self._finish("הקצה המקומי של הטרמינל נסגר")
                    raise ShellError("הטרמינל כבר נסגר", 409, "פתח טרמינל חדש למחשב הזה.") from None

    def resize(self, cols: int, rows: int) -> None:
        with self.lock:
            if self.closed:
                raise ShellError("הטרמינל כבר נסגר", 409, "פתח טרמינל חדש למחשב הזה.")
            _set_size(self.master, cols, rows)

    # ── the end ─────────────────────────────────────────────────────────────────────────────────
    def close(self) -> None:
        if not self.closed:
            self._finish("")
        try:
            if self.proc.poll() is None:
                self.proc.terminate()               # ssh, not the remote shell: SIGHUP ends the session
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except OSError:
            pass
        with _LOCK:
            _SESSIONS.pop(self.key, None)


def _set_size(fd: int, cols: int, rows: int) -> None:
    """Tell the pty how big the terminal is. Half the value of a terminal is that `htop` knows."""
    cols = max(20, min(500, int(cols or 100)))
    rows = max(5, min(200, int(rows or 30)))
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass                                        # a size the kernel refused is not a failed session


def _short(key: str) -> str:
    """`<machine>:<first 4 of the id>…` — the session id is what a caller presents to type into the shell, so
    the log never holds it whole."""
    cid, _, sid = key.rpartition(":")
    return f"{cid}:{sid[:4]}…"


def start(cid: str, argv: list[str], cols: int = 100, rows: int = 30,
          owner: str = "") -> Session:
    """Open a session for machine `cid`. Refuses — with a sentence — before it opens one too many."""
    reap()
    # THE CAPS AND THE REGISTRATION ARE ONE CRITICAL SECTION. They used to be two: two opens at the
    # same instant both counted the same live sessions, both passed, and the office ran one pty and
    # one ssh process over the cap — per concurrent click (second reader, 2026-11-02).
    with _LOCK:
        live = [s for s in _SESSIONS.values() if s.key.startswith(f"{cid}:")]
        if len(live) >= MAX_SESSIONS:
            raise ShellError(f"יש כבר {len(live)} טרמינלים פתוחים למחשב הזה", 429,
                             "סגור טרמינל אחד ונסה שוב.")
        if len(_SESSIONS) >= MAX_SESSIONS * 4:
            raise ShellError("יש יותר מדי טרמינלים פתוחים בלשכה", 429, "סגור אחד מהם ונסה שוב.")
        sid = os.urandom(8).hex()
        key = f"{cid}:{sid}"
        s = Session(key, argv, cols, rows, owner=owner)
        _SESSIONS[key] = s
    _ensure_reaper()
    log.info("shell opened: %s (%d open)", _short(key), len(_SESSIONS))
    return s


def get(cid: str, sid: str, owner: str = "") -> Session:
    """One session, as the caller it was opened by. A session opened by ANOTHER caller is answered
    exactly like one that does not exist: the caller has no business knowing it is there."""
    with _LOCK:
        s = _SESSIONS.get(f"{cid}:{sid}")
    if s is None or s.owner != str(owner or ""):
        raise ShellError("הטרמינל הזה אינו פתוח יותר", 404,
                         "פתח טרמינל חדש — הלשכה הופעלה מחדש או שהחיבור פג.")
    s.at = time.time()
    return s


def reap(force: bool = False) -> list[str]:
    """Close what nobody is using: an hour-old shell to somebody's server is not a feature."""
    now = time.time()
    gone = []
    with _LOCK:
        items = list(_SESSIONS.items())
    for key, s in items:
        idle = now - s.at
        if s.closed and s.proc.poll() is not None:
            with _LOCK:
                _SESSIONS.pop(key, None)
            gone.append(key)
        elif idle > IDLE_SECONDS:
            log.info("shell reaped after %.0fs idle: %s", idle, _short(key))
            s.close()
            gone.append(key)
    return gone


def _ensure_reaper() -> None:
    """One background thread per process, not one per session."""
    with _LOCK:
        if _REAPER["started"]:
            return
        _REAPER["started"] = True

    def loop() -> None:
        while True:
            time.sleep(60)
            try:
                for s in list(_SESSIONS.values()):
                    s.drain(0.0)
                reap()
            except Exception:                       # a reaper that dies is worse than one that skips
                log.warning("shell reaper pass failed", exc_info=True)

    threading.Thread(target=loop, name="shell-reaper", daemon=True).start()


def count() -> int:
    return len(_SESSIONS)


def close_all() -> None:
    for s in list(_SESSIONS.values()):
        try:
            s.close()
        except Exception:
            pass
