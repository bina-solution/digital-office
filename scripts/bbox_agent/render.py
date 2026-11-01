"""bbox_agent.render — a terminal view of an agent at work, in the idiom of an agentic CLI.

    ⏺ bash(git status --short)           a tool call, its arguments summarised
      ⎿ 12 lines · M apps/dgo-extend/app.py   the result, collapsed to a preview
    the agent's text, streamed as it arrives
    ── turn 3 ended · 2m 14s · 48 steps  a turn boundary

Colour and the spinner only on a TTY; piped output is plain lines. Reasoning is hidden unless
asked for (--thinking). Everything that is not a byte of text goes to stdout in the order it happened.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Optional

TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None and os.environ.get("TERM") != "dumb"


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if TTY else s


dim = lambda s: _c("2", s)
bold = lambda s: _c("1", s)
cyan = lambda s: _c("36", s)
green = lambda s: _c("32", s)
yellow = lambda s: _c("33", s)
red = lambda s: _c("31", s)
magenta = lambda s: _c("35", s)

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def fmt_dur(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def one_line(s: str, width: int = 100) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= width else s[: width - 1] + "…"


def _iso_delta(start, end) -> Optional[float]:
    """Seconds between two ISO-8601 stamps the harness puts on its events (None if either is missing)."""
    from datetime import datetime
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max(0.0, (b - a).total_seconds())


def _turn_end_reason(reason) -> str:
    """The suffix for a turn boundary: silent for a normal end, loud for an error.

    A turn the provider refused (402 QUOTA, 401, 5xx) ends in a second with no assistant text;
    without this it read exactly like a fast success — the 2026-09-30 23:53 false "credits back".
    """
    if isinstance(reason, dict):
        kind = str(reason.get("kind") or "")
        err = reason.get("error") if isinstance(reason.get("error"), dict) else None
        if kind == "error" or err:
            err = err or {}
            code = " ".join(str(x) for x in (err.get("code"), err.get("status")) if x)
            msg = one_line(err.get("message") or reason.get("message") or "", 160)
            return "  " + red(f"✗ {code}: {msg}" if code else f"✗ {msg or 'error'}")
        if kind and kind not in ("completed", "complete", "done", "ok", "stop", "end_turn"):
            return "  " + yellow(f"· {kind}")
        return ""
    if isinstance(reason, str) and reason and reason not in ("completed", "complete", "done", "ok", "stop", "end_turn"):
        return "  " + yellow(f"· {one_line(reason, 120)}")
    return ""


def args_preview(name: str, args) -> str:
    """The one argument a human wants to see for this tool, like the harness's own UI."""
    if isinstance(args, dict):
        for key in ("command", "cmd", "path", "file_path", "query", "url", "pattern", "objective", "description", "prompt", "text"):
            if key in args and isinstance(args[key], str):
                return one_line(args[key], 90)
        if len(args) == 1:
            v = next(iter(args.values()))
            return one_line(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False), 90)
        return one_line(json.dumps(args, ensure_ascii=False), 90)
    return one_line(str(args), 90)


class Renderer:
    def __init__(self, show_thinking: bool = False, verbose: bool = False, out=None):
        self.thinking = show_thinking
        self.verbose = verbose
        self.out = out or sys.stdout
        self.lock = threading.Lock()
        self.spinner_on = False
        self.spinner_text = ""
        self.spinner_thread: Optional[threading.Thread] = None
        self.stop_spin = threading.Event()
        self.streaming_text = False   # a delta line is open on the terminal
        self.stream_kind = None
        self.turn_started_at: Optional[float] = None
        self.turn_started_iso: Optional[str] = None   # the harness's own stamp on turn.start
        self.steps = 0
        self.tools = 0
        self.calls = {}                 # tool call id → name
        self.last_activity = time.time()

    # ── spinner (TTY only)
    def spin(self, text: str) -> None:
        self.spinner_text = text
        if not TTY:
            return
        if self.spinner_thread is None:
            self.stop_spin.clear()
            self.spinner_thread = threading.Thread(target=self._spin_loop, daemon=True)
            self.spinner_thread.start()
        self.spinner_on = True

    def _spin_loop(self) -> None:
        i = 0
        while not self.stop_spin.is_set():
            if self.spinner_on and not self.streaming_text:
                with self.lock:
                    elapsed = fmt_dur(time.time() - (self.turn_started_at or self.last_activity))
                    self.out.write(f"\r\033[2K{cyan(SPINNER[i % len(SPINNER)])} {dim(self.spinner_text)} {dim(elapsed)}")
                    self.out.flush()
            i += 1
            time.sleep(0.1)

    def _clear_spinner(self) -> None:
        if TTY and self.spinner_on:
            self.out.write("\r\033[2K")

    def stop(self) -> None:
        self.spinner_on = False
        self.stop_spin.set()
        if TTY:
            with self.lock:
                self.out.write("\r\033[2K")
                self.out.flush()

    # ── lines
    def line(self, s: str = "") -> None:
        with self.lock:
            self._close_stream()
            self._clear_spinner()
            self.out.write(s + "\n")
            self.out.flush()
        self.last_activity = time.time()

    def _close_stream(self) -> None:
        if self.streaming_text:
            self.out.write("\n")
            self.streaming_text = False
            self.stream_kind = None

    def delta(self, kind: str, text: str) -> None:
        if kind == "reasoning" and not self.thinking:
            return
        with self.lock:
            self._clear_spinner()
            if self.streaming_text and self.stream_kind != kind:
                self.out.write("\n")
                self.streaming_text = False
            if not self.streaming_text:
                self.out.write(dim("  ⋯ ") if kind == "reasoning" else "")
            self.out.write(dim(text) if kind == "reasoning" else text)
            self.out.flush()
            self.streaming_text = True
            self.stream_kind = kind
        self.last_activity = time.time()

    # ── one contract event
    def event(self, ev: str, d) -> None:
        d = d if isinstance(d, dict) else {}
        if ev == "open":
            self.line(dim(f"— attached to {d.get('id', '')}{' (history)' if d.get('history') else ''} —"))
            self.spin("waiting for the agent")
        elif ev == "snapshot":
            for e in d.get("events") or []:
                self.event(e.get("type", ""), e)
            self.line(dim("— live —"))
        elif ev == "turn.start":
            self.turn_started_at = time.time(); self.turn_started_iso = d.get("at"); self.steps = 0; self.tools = 0
            self.line(bold(f"▶ turn {d.get('turn', '')}"))
            self.spin("thinking")
        elif ev == "turn.end":
            # duration from the events' own stamps when both are there (a replayed history would
            # otherwise measure the replay: every past turn read "0s"); wall clock while live
            took = ""
            stamped = _iso_delta(self.turn_started_iso, d.get("at"))
            if stamped is not None:
                took = fmt_dur(stamped)
            elif self.turn_started_at:
                took = fmt_dur(time.time() - self.turn_started_at)
            self.line(dim(f"── turn {d.get('turn', '')} ended · {took} · {self.steps} steps · {self.tools} tool calls")
                      + _turn_end_reason(d.get("reason")))
            self.spin("idle — waiting for the next turn")
        elif ev == "step.start":
            self.steps += 1
            self.spin(f"step {self.steps}")
        elif ev == "step.end":
            pass
        elif ev == "user":
            src = d.get("source")
            tag = {"user": "you", "plugin": "system", "agent": "subagent"}.get(src, src or "user")
            text = d.get("text", "")
            if src == "plugin" and not self.verbose:
                text = one_line(text, 140)   # background-job notices are long; the first line says it
            self.line(f"{green('›')} {bold(tag)}: {one_line(text, 400)}")
        elif ev == "inbox":
            self.line(f"{yellow('›')} {bold('steer')}: {one_line(d.get('text', ''), 400)}")
        elif ev == "reasoning":
            if self.thinking:
                self.line(dim("  ⋯ " + one_line(d.get("text", ""), 600)))
        elif ev == "assistant":
            with self.lock:
                self._close_stream()
                self._clear_spinner()
                self.out.write(d.get("text", "").rstrip() + "\n")
                self.out.flush()
            self.spin("working")
        elif ev == "delta":
            self.delta(d.get("kind", "text"), d.get("text", ""))
        elif ev == "attempt.start":
            self.spin("model is answering")
        elif ev in ("attempt.end", "attempt.finish"):
            with self.lock:
                self._close_stream()
            if d.get("reason") == "error" and d.get("message"):
                self.line(yellow(f"  ⚠ {one_line(d['message'], 200)}"))
        elif ev == "tool.call":
            if d.get("id") and d.get("id") in self.calls:
                return                      # the harness logs a call twice (its own event + the message block); show it once
            self.tools += 1
            self.calls[d.get("id")] = d.get("name")
            self.line(f"{cyan('⏺')} {bold(d.get('name', '?'))}({args_preview(d.get('name', ''), d.get('args'))})")
            self.spin(f"running {d.get('name', 'tool')}")
        elif ev == "tool.result":
            text = str(d.get("text") or "")
            n = text.count("\n") + (1 if text else 0)
            head = one_line(text.strip().splitlines()[0] if text.strip() else "(no output)", 110)
            mark = green("⎿") if d.get("ok", True) else red("⎿ error")
            self.line(f"  {mark} {dim(f'{n} lines · ') if n > 1 else ''}{dim(head)}")
            if self.verbose and n > 1:
                for ln in text.strip().splitlines()[1:30]:
                    self.line(dim("    " + ln[:200]))
            self.spin("thinking")
        elif ev == "retry":
            self.line(yellow(f"  ↻ retry: {one_line(d.get('reason') or 'provider error', 160)}"))
        elif ev == "retry.start":
            self.spin(f"retrying (attempt {d.get('attempt', '?')})")
        elif ev == "approval.asked":
            self.line(magenta("  ? approval requested — answer it in the office UI"))
        elif ev == "approval.decided":
            self.line(dim("  ✓ approval decided"))
        elif ev == "goal":
            g = d.get("goal") or {}
            self.line(magenta(f"  ◎ goal {g.get('phase', '')}: {one_line(g.get('objective', ''), 160)}"))
        elif ev == "title":
            self.line(dim(f"  title: {d.get('title')}"))
        elif ev == "error":
            self.line(red(f"✗ {d.get('code', '')} {d.get('message', '')}"))
        elif ev == "end":
            self.line(dim("— stream ended —"))
        elif ev == "raw":
            self.line(json.dumps(d, ensure_ascii=False)[:2000])
        # unknown events are ignored on purpose: the contract may grow before this renderer does
