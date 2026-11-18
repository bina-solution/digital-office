"""clients: a service that gives no answer is described in the reader's words — its sentence is put
on a Hebrew screen as it is, so it never carries an exception's class name or a bare `HTTP 502`.

    python3 apps/digital-assets/tests/test_clients.py
"""
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import clients  # noqa: E402

LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def _why(url, **kw):
    try:
        clients._req("GET", url, **kw)
    except clients.Unavailable as e:
        return str(e)
    raise AssertionError(f"{url} answered")


def test_no_answer():
    # nothing listens: the port of a socket that was bound and closed
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    refused = _why(f"http://127.0.0.1:{port}/api/accounts", timeout=3)
    assert refused == "אינו רץ בלשכה הזאת", refused
    # something listens and never answers
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        slow = _why(f"http://127.0.0.1:{srv.getsockname()[1]}/api/accounts", timeout=0.4)
    finally:
        srv.close()
    assert slow == "לא ענה בזמן", slow
    for said in (refused, slow):
        assert not LATIN_WORD.search(said), said


def test_answered_no():
    assert clients._said(502, {}) == "ענה בשגיאה 502"
    assert clients._said(409, {"error": "החשבון נעול"}) == "החשבון נעול"      # its own sentence, as it is
    assert not LATIN_WORD.search(clients._said(500, {}))


def test_optional_absent_costs_nothing():
    """An absent optional service costs the screen at most the deadline once, then nothing; an answer is never
    remembered (DGO-1839: the overview waited 7.5 s on a social-list that was not there)."""
    import time
    clients._optional_failed.clear()
    calls = []

    def silent():
        calls.append(1)
        time.sleep(3)
        return ["late"]

    t = time.monotonic()
    try:
        clients.optional("t-silent", silent, deadline=0.3)
        raise AssertionError("a silent service answered")
    except clients.Unavailable as e:
        assert str(e) == "לא ענה בזמן", str(e)
    assert time.monotonic() - t < 1.0, "the screen paid more than the deadline"
    t = time.monotonic()
    try:
        clients.optional("t-silent", silent, deadline=0.3)
        raise AssertionError("a remembered failure answered")
    except clients.Unavailable:
        pass
    assert time.monotonic() - t < 0.1 and len(calls) == 1, "a remembered failure is asked again"

    def broken():
        raise RuntimeError("socket.gaierror: Temporary failure in name resolution")
    try:
        clients.optional("t-broken", broken)
        raise AssertionError("a broken read answered")
    except clients.Unavailable as e:
        assert not LATIN_WORD.search(str(e)), str(e)       # the reader's words, never the exception's

    answers = iter([["a"], ["a", "b"]])
    assert clients.optional("t-fresh", lambda: next(answers)) == ["a"]
    assert clients.optional("t-fresh", lambda: next(answers)) == ["a", "b"], "an answer was remembered"
    clients._optional_failed.clear()


if __name__ == "__main__":
    test_no_answer()
    test_answered_no()
    test_optional_absent_costs_nothing()
    print("clients: 3/3 ok")
