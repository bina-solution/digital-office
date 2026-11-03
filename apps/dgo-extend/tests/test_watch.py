#!/usr/bin/env python3
"""test_watch — an office that declares `watch: {health: daily}` is checked once a day, each check kept as a
history line, a failed or warned check told once through the office's bell and its return told once
(FPG-26).

The converge itself, the bell and the clock are stood in for. The runs given to `_watch_record` have the
shape `_execute` really gives them (a step's result under `result`, `warn` when it has warnings, the
`machine` step that runs before every other) — the first version of this test used a shape no run has,
and passed over a summary that was always empty (the reader).

Run: python3 apps/dgo-extend/tests/test_watch.py   (app.py loaded as test_app_input loads it)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("test_app_input", HERE / "test_app_input.py")
tai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tai)
app = tai.load()

FAIL: list[str] = []
DAY = 86400


def check(cond, what):
    if not cond:
        FAIL.append(what)


def run_of(started, status, health=None, machine=None):
    """A run as _execute leaves it."""
    steps = {"machine": machine or {"status": "ok", "result": {"summary": "ok"}},
             "health": health or {"status": "pending"}}
    return {"office": "fireplace", "started": started, "ended": started + 30, "status": status, "by": "watch",
            "steps": steps}


def main() -> int:
    app.DECL_DIR.mkdir(parents=True, exist_ok=True)
    (app.DECL_DIR / "fireplace.yaml").write_text("id: fireplace\nlabel: The Fireplace Guys\nwatch: {health: daily}\n")
    (app.DECL_DIR / "a-broken.yaml").write_text("id: [unclosed\n")                      # sorts first
    (app.DECL_DIR / "b-string.yaml").write_text("id: b\nwatch: daily\n")
    (app.DECL_DIR / "c-paired.yaml").write_text("id: c\nkind: paired\nwatch: {health: daily}\n")
    (app.DECL_DIR / "quiet.yaml").write_text("id: quiet\nlabel: Quiet\n")
    started, answer = [], {"busy": False}

    def start(office, only, by=""):
        if answer["busy"]:
            return {"error": "הלשכה כבר בתהליך"}
        started.append((office["id"], only, by))
        return {"run": {"started": 1}}

    t0 = 1_800_000_000
    did = app._watch_once(t0, start)
    check(did == ["started:fireplace"] and started == [("fireplace", ["health"], "watch")],
          f"one bad record stops nothing; only a declared, unpaired office is checked, by the watch: {did} {started}")
    check(app._watch_once(t0 + DAY - 1, start) == [], "nothing before its day")
    check(app._watch_once(t0 + DAY + 700, start) == ["started:fireplace"], "its day, caught up a tick late…")
    last = json.loads((app.STATE_DIR / "watch.json").read_text())["fireplace"]["last"]
    check(last == t0 + DAY, f"…counts the next day from when it was DUE, not when it ran: {last - t0}")
    answer["busy"] = True
    check(app._watch_once(t0 + 2 * DAY, start) == [], "an office mid-converge is not checked…")
    answer["busy"] = False
    check(app._watch_once(t0 + 2 * DAY + 600, start) == ["started:fireplace"], "…the next pass is")
    check(app._watch_once(t0 - 5 * DAY, start) == ["started:fireplace"],
          "a clock that went back makes the check due, never blocked until the clock returns")

    told = []
    notify = lambda sid, title, body, level: told.append((sid, level, body)) or True  # noqa: E731
    hist = app.STATE_DIR / "watch-fireplace.jsonl"
    if hist.exists():
        hist.unlink()
    # 1. the machine did not answer: health never ran — the reason is the machine step's
    row = app._watch_record(run_of(100, "failed", machine={"status": "failed", "error": {"reason": "ssh refused"}}),
                            notify)
    check(row["status"] == "failed" and row["reason"] == "ssh refused" and told == [("watch-health-failed-fireplace-100", "error", "ssh refused")],
          f"a failed check says the step that failed, and is told once: {row} {told}")
    # 2. still failing next day: not told again
    app._watch_record(run_of(200, "failed", health={"status": "failed", "error": {"reason": "compose invalid"}}), notify)
    check(len(told) == 1, f"a check still failing is not told again: {told}")
    # 3. healthy again: the return is told once, with the real summary
    row = app._watch_record(run_of(300, "ok", health={"status": "ok", "result": {"summary": "42/42 בריאים"}}), notify)
    check(row["summary"] == "42/42 בריאים" and told[-1][:2] == ("watch-health-back-fireplace-100", "info"),
          f"its return is told once, with the step's own summary: {row} {told}")
    # 4. a warned check (a dead host) rings the bell too, at warning level, with what it warned
    row = app._watch_record(run_of(400, "ok", health={"status": "warn", "result": {
        "summary": "41/42", "warnings": ["כתובות שאינן עונות: services.fpg"]}}), notify)
    check(row["status"] == "warn" and told[-1][1] == "warning" and "services.fpg" in told[-1][2],
          f"a warned check is a warn line and is told: {row} {told[-1]}")
    lines = [json.loads(x) for x in hist.read_text().splitlines()]
    check([x["status"] for x in lines] == ["failed", "failed", "ok", "warn"], f"every check is a history line: {lines}")
    # 4b. a warning must not hide the failure that comes after it
    n = len(told)
    app._watch_record(run_of(500, "failed", health={"status": "failed", "error": {"reason": "compose invalid"}}), notify)
    check(len(told) == n + 1 and told[-1][1] == "error", f"warn → failed rings the error bell: {told[n:]}")
    app._watch_record(run_of(600, "failed", health={"status": "failed", "error": {"reason": "compose invalid"}}), notify)
    check(len(told) == n + 1, f"…once: {told[n:]}")
    # 4c. one office whose start raises stops neither another office nor the save of what was started
    (app.DECL_DIR / "aa-first.yaml").write_text("id: aa\nwatch: {health: daily}\n")
    st0 = json.loads((app.STATE_DIR / "watch.json").read_text())
    st0.pop("aa", None)
    st0["fireplace"] = {}
    (app.STATE_DIR / "watch.json").write_text(json.dumps(st0))

    def flaky(office, only, by=""):
        if office["id"] == "fireplace":
            raise RuntimeError("can't start new thread")
        return {"run": {"started": 1}}
    did = app._watch_once(t0 + 9 * DAY, flaky)
    saved = json.loads((app.STATE_DIR / "watch.json").read_text())
    check(did == ["started:aa"] and "last" in saved.get("aa", {}) and "last" not in saved.get("fireplace", {}),
          f"a raising start is skipped, the other is started and saved: {did} {saved}")
    (app.DECL_DIR / "aa-first.yaml").unlink()
    # 4d. a real run the watch started records itself as it ends (_execute's finally), with the step's summary
    cv = app.cv
    saved_runners = dict(cv.RUNNERS)
    cv.RUNNERS["machine"] = lambda office, ctx, emit: {"summary": "up"}
    cv.RUNNERS["health"] = lambda office, ctx, emit: {
        "summary": "43/43 בריאים", "containers": {"healthy": "43", "total": "43", "bad": ""},
        "dead_hosts": [], "answering": 19, "expected": 19}
    real_thread = app.threading.Thread
    app.threading.Thread = lambda *a, **k: type("T", (), {"start": lambda self: None})()
    try:
        office = {"id": "fireplace", "label": "The Fireplace Guys"}
        run = app.start_run(office, ["health"], by="watch")["run"]
        before = len(hist.read_text().splitlines())
        app._execute(office, run, ["health"])
        last_line = json.loads(hist.read_text().splitlines()[-1])
        check(len(hist.read_text().splitlines()) == before + 1 and last_line["summary"] == "43/43 בריאים"
              and last_line["status"] == "ok", f"the run records itself, with its own summary: {last_line}")
        check((last_line.get("healthy"), last_line.get("total"), last_line.get("answering"), last_line.get("expected"))
              == ("43", "43", 19, 19), f"…and the facts a report in another language is written from: {last_line}")
    finally:
        cv.RUNNERS.clear()
        cv.RUNNERS.update(saved_runners)
        app.threading.Thread = real_thread
        app._runs.pop("fireplace", None)
    # 4e. the record takes the declaration, and only that shape
    base = {"id": "w1", "machine": "m", "label": "W", "domain": "w.example", "path": "/opt/w",
            "source": {"repo": "/opt/src/dgo.git", "branch": "dgo-stable", "commit": "a" * 40}}
    d, err = app.validate({**base, "watch": {"health": "daily"}}, None)
    check(err is None and d.get("watch") == {"health": "daily"}, f"a record keeps watch: {{health: daily}}: {err} {d}")
    d, err = app.validate({**base, "watch": {"health": "daily", "backup": "daily"}}, None)
    check(err is None and d.get("watch") == {"health": "daily", "backup": "daily"}, f"backup is a watch too: {err} {d}")
    for bad in ({"health": "hourly"}, {"health": "daily", "x": 1}, "daily", {"backup": "weekly"}):
        _, err = app.validate({**base, "watch": bad}, None)
        check(err is not None, f"a watch that is not {{health: daily}} is refused: {bad!r}")
    d, err = app.validate({"watch": None}, {**base, "watch": {"health": "daily"}})
    check(err is None and "watch" not in d, f"watch: none turns it off: {err} {d}")
    # 4f. the weekly report: counted from the history, in ENGLISH from the checks' facts — the rows below
    # are shaped as _watch_record writes them, Hebrew sentences and all (an IP inside a reason included)
    rows = [
        {"t": t0 - 9 * DAY, "status": "failed", "reason": "ישן מדי", "step": "health"},
        {"t": t0 - 3 * DAY, "status": "ok", "summary": "43/43 בריאים · console עונה 302", "healthy": "43",
         "total": "43", "answering": 19, "expected": 19},
        {"t": t0 - 2 * DAY, "status": "warn", "summary": "42/43 בריאים", "healthy": "42", "total": "43",
         "warnings": ["כתובות שאינן עונות: services.fpg.digital-office.co.il → 502"],
         "dead_hosts": ["services.fpg.digital-office.co.il"], "unhealthy": ["mailapi-fireplace"]},
        {"t": t0 - 1 * DAY, "status": "failed", "step": "dns",
         "reason": "ה־DNS של fpg.digital-office.co.il אינו מצביע על המחשב (93.184.216.10)"},
        {"t": t0, "status": "ok", "summary": "43/43 בריאים", "healthy": "43", "total": "43"}]
    bad = [b'{"t": "abc", "status": "ok"}', b'{"t": 1e20, "status": "ok"}', b'{"t": [], "status": "ok"}',
           b'{"t": 1e400, "status": "ok"}', b'{"t": Infinity, "status": "ok"}',
           b'{"t": ' + str(t0).encode() + b', "status": "ok", "summary": "\xd7"}', b"not json"]
    hist.write_bytes(b"\n".join([json.dumps(r, ensure_ascii=False).encode() for r in rows] + bad) + b"\n")
    rep = app.watch_report("fireplace", 7, t0)
    check({k: rep["counts"][k] for k in ("ok", "warn", "failed", "other")} == {"ok": 3, "warn": 1, "failed": 1, "other": 0}
          and len(rep["checks"]) == 5,
          f"a week counts its own checks (an older one, unreadable lines and an impossible time left out): {rep['counts']}")
    text = rep["text"]
    check("6 of" not in text and "5 daily checks — 3 healthy, 1 with warnings, 1 failed" in text
          and "not answering: services.fpg.digital-office.co.il" in text and "unhealthy: mailapi-fireplace" in text
          and "the office's address (DNS) did not point at the server" in text, f"the report's facts: {text!r}")
    check(not any("֐" <= ch <= "׿" for ch in text) and "93.184.216.10" not in text,
          f"never a Hebrew sentence, never an address from a reason: {text!r}")
    check("no daily check" in app.watch_report("nobody", 7, t0)["text"], "an office with no checks says so")
    hist.write_text(json.dumps({"t": t0, "status": "ok", "healthy": "43", "total": "43"}) + "\n")
    check(": 1 daily check — 1 healthy" in app.watch_report("fireplace", 7, t0)["text"], "one check is a check, not checks")
    # 4g. the backup watch (FPG-26): a pass starts one run; the next starts the other kind
    (app.DECL_DIR / "fireplace.yaml").write_text(
        "id: fireplace\nlabel: The Fireplace Guys\nwatch: {health: daily, backup: daily}\n")
    (app.STATE_DIR / "watch.json").write_text("{}")
    asked = []
    both = lambda office, only, by="": asked.append((office["id"], only)) or {"run": {"started": 1}}  # noqa: E731
    first = app._watch_once(t0 + 30 * DAY, both)
    second = app._watch_once(t0 + 30 * DAY, both)
    check(first == ["started:fireplace"] and second == ["started:fireplace:backup"]
          and asked == [("fireplace", ["health"]), ("fireplace", ["offsite"])],
          f"health, then the backup on the next pass — never two runs at once: {first} {second} {asked}")
    check(app._watch_once(t0 + 30 * DAY, both) == [], "both done for the day")
    # a backup's line and its bell are its own — a failed backup is not a failed health check
    told.clear()
    hist.write_text("")
    st = json.loads((app.STATE_DIR / "watch.json").read_text())
    st["fireplace"].pop("failing", None)
    (app.STATE_DIR / "watch.json").write_text(json.dumps(st))
    # the kind is what the run was ASKED: a backup that failed at its machine step never reached `offsite`
    brun = {"office": "fireplace", "started": 700, "ended": 760, "status": "failed", "by": "watch",
            "only": ["offsite"], "steps": {"machine": {"status": "failed", "error": {"reason": "אין מקום"}}}}
    row = app._watch_record(brun, notify)
    check(row.get("kind") == "backup" and row["status"] == "failed" and told[-1][:2] == ("watch-backup-failed-fireplace-700", "error"),
          f"a failed backup is a backup line, told as a backup: {row} {told}")
    okrun = {"office": "fireplace", "started": 800, "ended": 860, "status": "ok", "by": "watch", "only": ["offsite"],
             "steps": {"machine": {"status": "ok"}, "health": {"status": "skipped"},
                       "offsite": {"status": "ok", "result": {"bytes": "2500000", "volume": "dgo-offsite-fireplace-x",
                                                              "verified": True, "kept": "1"}}}}
    app._watch_record(okrun, notify)
    check(told[-1][:2] == ("watch-backup-back-fireplace-700", "info"), f"its return is told as the backup's: {told}")
    hrow = app._watch_record(run_of(900, "ok", health={"status": "ok", "result": {"summary": "43/43"}}), notify)
    check(hrow.get("kind") is None and len(told) == 2, f"a health check after it rings nothing of the backup's: {told}")
    # a backup that left part of the office out (a database that would not dump) is a warning, told once
    wrun = {"office": "fireplace", "started": 950, "ended": 990, "status": "ok", "by": "watch", "only": ["offsite"],
            "steps": {"offsite": {"status": "warn", "result": {"bytes": "100", "verified": True,
                                                              "warnings": ["WARN: pg_dumpall failed for x-db"]}}}}
    wrow = app._watch_record(wrun, notify)
    check(wrow["status"] == "warn" and told[-1][:2] == ("watch-backup-warn-fireplace-950", "warning")
          and "x-db" in told[-1][2], f"a backup with a part missing is a warning: {wrow} {told}")
    app._watch_record({**wrun, "started": 960}, notify)
    check(len(told) == 3, f"…told once: {told}")
    hist.write_text("\n".join(ln for ln in hist.read_text().splitlines() if '"warn"' not in ln) + "\n")
    rep = app.watch_report("fireplace", 7, 1000)
    check(rep["counts"]["backups_ok"] == 1 and rep["counts"]["backups_failed"] == 1 and rep["counts"]["ok"] == 1
          and "Off-server backups: 1 of 2 made, encrypted and verified" in rep["text"]
          and "(2.5 MB) was copied off the server and verified" in rep["text"]
          and "the off-server backup could not be completed" in rep["text"], f"the report says the backups: {rep['text']!r}")
    # 4h. the card: a backup in progress is not the office's state, and a manual run that also upgrades is a converge
    check(app._run_kind({"only": ["offsite"]}) == "backup" and app._run_kind({"only": ["machine", "offsite"]}) == "backup"
          and app._run_kind({"only": ["offsite", "code"]}) == ""
          and app._run_kind({"only": ["health"]}) == "" and app._run_kind({}) == "", "a backup run is the backup alone")
    app.RUN_DIR.mkdir(parents=True, exist_ok=True)
    app._run_file("fireplace").write_text(json.dumps({"office": "fireplace", "status": "ok", "started": 5,
                                                      "health": {"containers": "43/43"}}))
    app._runs["fireplace"] = {"office": "fireplace", "status": "running", "only": ["offsite"], "started": 9,
                              "steps": {}, "log": []}
    try:
        card = next(i for i in app.api_list()["items"] if i["id"] == "fireplace")
        check((card.get("run") or {}).get("started") == 5 and (card.get("run") or {}).get("health") == {"containers": "43/43"},
              f"while the backup runs the card keeps the last converge and its health check: {card.get('run')}")
        app._persist({**app._runs["fireplace"], "status": "ok", "ended": 12})
        check(json.loads(app._run_file("fireplace").read_text())["started"] == 5
              and json.loads(app._run_file("fireplace", "backup").read_text())["started"] == 9,
              "a backup run is kept in its own file; the converge's stays")
    finally:
        app._runs.pop("fireplace", None)
    # 5. start_run carries who asked
    real_thread = app.threading.Thread
    app.threading.Thread = lambda *a, **k: type("T", (), {"start": lambda self: None})()
    try:
        out = app.start_run({"id": "probe-office"}, ["health"], by="watch")
        check((out.get("run") or {}).get("by") == "watch", f"a run started by the watch carries it: {out}")
    finally:
        app.threading.Thread = real_thread
        app._runs.pop("probe-office", None)
    print("PASS test_watch" if not FAIL else "FAIL test_watch")
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
