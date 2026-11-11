"""ollama-watch — what the office's local models are doing, as bars in «כל מקביל» (DGO-1797, package 4).

The owner, at the Dell (DGO-1797): «מודלים ollama שרואים בכל מקביל אם הם פועלים». Two things are his question, and
this small service answers both on the flow (flowpub, `dgo:flow:ollama`), so they are rows of «כל מקביל» with
nothing to declare there:

  * A MODEL IN MEMORY is a bar: it opens when the model appears in the engine's `/api/ps` and closes when it
    leaves (keep-alive ran out, an unload, the engine restarted). Its title is «<model> · 1.9 GB · בזיכרון», and a
    model the engine will never let go (keep-alive -1: an expiry decades ahead) says «נשאר בזיכרון» and carries
    `pinned` — the Dell held 9.6 GB that way for five hours, and nothing showed it (DGO-1797's root).

TITLES ARE WRITTEN LATIN FIRST, HEBREW LAST. «כל מקביל» draws a bar's label left to right (index.html: the bar's
`ctx.direction="ltr"`), and a number written after a Hebrew word is pulled into the Hebrew run: «gemma4:e2b בזיכרון
· 7.1 GB» was drawn «gemma4:e2b 7.1 · GB בזיכרון» (measured in the page, 2026-11-10). With the model, the size, the
office and the seconds first and the Hebrew words at the end, each part keeps its place.
  * A TURN (chat, generate, embed) is a bar from its start to its end, read off the front's access log (Caddy,
    JSON, `/log/access.json`): one line per request, written when it ends, with its duration. So a turn is told
    once, by its END alone, carrying `t0` and `ms`: «כל מקביל» draws an end with no start it saw from its `t0`
    (apps/any-concurrency/flow_source.py) — a start written at the same moment would make the bar start there.
    The model is named only when exactly one is loaded (the access log does not hold the request's body); the
    office that asked, when a linked office's agent says so (`x-dgo-office`).

Never the request's body, never a header but that one: the flow is read by every agent of the office.
Standard library only (python:3.12-alpine runs it as mounted), and never in the engine's way: a failure is
written to this container's log at most once a minute, and the loop goes on.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/opt/dgo")                       # the office's ONE flow publisher, mounted read-only

APP = "ollama"
ENGINE = os.environ.get("OLLAMA_WATCH_ENGINE", "http://ollama-engine:11434")
LOG = os.environ.get("OLLAMA_WATCH_LOG", "/log/access.json")
EVERY_S = float(os.environ.get("OLLAMA_WATCH_EVERY_S", "3"))
#: the requests that are a model's work; anything else through the front (the screen, /api/tags, /api/ps) is not
TURNS = {"/api/chat": "chat", "/api/generate": "generate", "/api/embed": "embed", "/api/embeddings": "embed"}
#: an expiry further than this is keep-alive -1 — Ollama writes a date centuries ahead for «never»
PINNED_S = 30 * 24 * 3600
#: the engine silent this many polls in a row: the models it held are no longer known to be there
SILENT_POLLS = 3
#: the most of an unfinished access-log line kept between polls (Caddy writes a line whole; this is the bound)
BUF_MAX = 1 << 20
#: what a linked office's agent may call itself in `x-dgo-office` — anything else is not repeated on the flow
OFFICE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


def _gb(n) -> str:
    try:
        return f"{int(n) / 1e9:.1f} GB"
    except (TypeError, ValueError):
        return "?"


def _expiry_s(text: str) -> float | None:
    """Seconds from now to an RFC 3339 expiry as Ollama writes it (nanoseconds, an offset); None if unreadable."""
    if not isinstance(text, str) or not text:
        return None
    t = text.strip().replace("Z", "+00:00")
    head, dot, rest = t.partition(".")
    if dot:                                             # fromisoformat takes at most microseconds
        n = len(rest) - len(rest.lstrip("0123456789"))  # the fraction's digits only — never the offset's
        t = f"{head}.{rest[:n][:6]}{rest[n:]}"
    try:
        when = datetime.fromisoformat(t)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (when - datetime.now(timezone.utc)).total_seconds()


class Models:
    """The models in memory, each an open bar; `see()` takes one `/api/ps` answer (or None: no answer)."""

    def __init__(self, pub):
        self.pub = pub                                  # flowpub, or a test's stand-in
        self.open: dict[str, tuple[str, int]] = {}      # model → (span id, t0)
        self.silent = 0

    def _title(self, m: dict, pinned: bool) -> str:
        return f"{m.get('name')} · {_gb(m.get('size'))} · " + ("נשאר בזיכרון" if pinned else "בזיכרון")

    def see(self, models: list | None) -> None:
        if models is None:
            self.silent += 1
            if self.silent >= SILENT_POLLS:
                self.close_all("המנוע לא עונה")
            return
        self.silent = 0
        now = {}
        for m in models:
            if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"]:
                now[m["name"]] = m
        for name in [n for n in self.open if n not in now]:
            self._close(name, None)
        for name, m in now.items():
            if name in self.open:
                continue
            left = _expiry_s(m.get("expires_at"))
            pinned = left is not None and left > PINNED_S
            data = {"model": name, "size_mb": int((m.get("size") or 0) / 1e6),
                    "vram_mb": int((m.get("size_vram") or 0) / 1e6), "pinned": pinned}
            sid, t0, _ = self.pub.span_start(APP, "model", self._title(m, pinned), data)
            self.open[name] = (sid, t0)

    def _close(self, name: str, why: str | None) -> None:
        sid, t0 = self.open.pop(name)
        self.pub.span_end(APP, "model", f"{name} · יצא מהזיכרון", sid, t0, False, {"model": name, **({"why": why} if why else {})})

    def close_all(self, why: str) -> None:
        for name in list(self.open):
            self._close(name, why)

    def only(self) -> str | None:
        return next(iter(self.open)) if len(self.open) == 1 else None


def turn(line: str, model: str | None):
    """One access-log line → (type, title, data) of a turn's end, or None when the line is not a turn."""
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    req = rec.get("request") if isinstance(rec.get("request"), dict) else {}
    path = str(req.get("uri") or "").split("?", 1)[0]
    kind = TURNS.get(path)
    if req.get("method") != "POST" or kind is None:
        return None
    try:
        end = float(rec["ts"])
        dur = max(0.0, float(rec.get("duration") or 0))
        status = int(rec.get("status") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    headers = req.get("headers") if isinstance(req.get("headers"), dict) else {}
    office = next((v[0] if isinstance(v, list) and v else v for k, v in headers.items()
                   if str(k).lower() == "x-dgo-office"), None)
    if not isinstance(office, str) or not OFFICE_RE.match(office):
        office = None                                   # a caller writes this header: only an office id is repeated
    t1 = int(end * 1000)
    t0 = int((end - dur) * 1000)
    words = [kind] + ([model] if model else []) + ([office] if office else []) + [f"{dur:.1f} שניות"]
    data = {"path": path, "status": status, "span": uuid.uuid4().hex[:12], "t0": t0, "ms": t1 - t0}
    if model:
        data["model"] = model
    if office:
        data["office"] = office
    return (f"turn.{'failed' if status >= 400 or status == 0 else 'ended'}", " · ".join(words), data)


class Tail:
    """New lines of a file that Caddy rolls (renames, then starts a new one): read from where it was, and a new
    file from its start — but a file that was already there when this process began, from its END: the turns
    before this process are not news."""

    def __init__(self, path: str):
        self.path, self.f, self.ino, self.buf = path, None, None, ""
        self.skip_old = os.path.exists(path)

    def lines(self) -> list[str]:
        try:
            st = os.stat(self.path)
        except OSError:
            return []
        if self.f is not None and (st.st_ino != self.ino or st.st_size < self.f.tell()):
            if st.st_ino != self.ino:                   # rolled: the old file is still open under its new name —
                self.buf += self.f.read()               # its last lines first, then the new file from its start
            else:
                self.buf = ""                           # cut in place: what was half-read is gone with it
            self.f.close()
            self.f = None
        if self.f is None:
            self.f = open(self.path, encoding="utf-8", errors="replace")
            self.ino = st.st_ino
            if self.skip_old:
                self.f.seek(0, os.SEEK_END)
                self.skip_old = False
        self.buf += self.f.read()
        *done, self.buf = self.buf.split("\n")
        self.buf = self.buf[-BUF_MAX:]                  # a line that never ends is not kept whole forever
        return [x for x in done if x.strip()]


def ps(url: str = ENGINE, timeout: float = 5.0) -> list | None:
    try:
        with urllib.request.urlopen(f"{url}/api/ps", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        models = body.get("models") if isinstance(body, dict) else None
        return models if isinstance(models, list) else None   # an answer that is not one: not «nothing loaded»
    except urllib.error.HTTPError as e:                 # the engine ANSWERED, with an error: say what it said
        said = (e.read() or b"")[:200].decode("utf-8", "replace") if e.fp else ""
        print(f"ollama-watch: {url}/api/ps answered {e.code}: {said}", file=sys.stderr, flush=True)
        return None
    except Exception:                                   # noqa: BLE001 — the engine away is a state, not an error
        return None


def main() -> int:
    import flowpub

    models, tail = Models(flowpub), Tail(LOG)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    said = 0.0
    while not stop:
        try:
            models.see(ps())
            for line in tail.lines():
                t = turn(line, models.only())
                if t:
                    flowpub.emit(APP, *t)
        except Exception as e:                          # noqa: BLE001 — never down for one bad step
            if time.time() - said > 60:
                print(f"ollama-watch: {type(e).__name__}: {e}"[:300], file=sys.stderr, flush=True)
                said = time.time()
        time.sleep(EVERY_S)
    models.close_all("הצופה נעצר")
    flowpub.flush(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
