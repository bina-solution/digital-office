"""Who said what on the meeting page (DGO-1627) — the page half of the transcript's speakers.

Two doors show a meeting: the FIRST pass, drawn by meet-start while the recording is still warm
(`apps/meet/start/server.py`), and the flow page, which `build_flow.py` writes after «קדימה». Both
used to give every line one speaker; both now carry the label the transcriber found, and a name
only when somebody gave one.

Runnable with pytest, and (because the office's own boxes do not always have pytest) directly:

    python3 apps/meet/tools/flow/test_build_flow.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)

import build_flow  # noqa: E402  (the module under test)


def _server_module():
    """meet-start's server.py, imported for its pure helpers (nothing starts at import)."""
    path = os.path.join(REPO, "apps", "meet", "start", "server.py")
    spec = importlib.util.spec_from_file_location("meet_start_server_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── fixtures ──────────────────────────────────────────────────────────────────────────

def _transcript(*lines, speakers=None):
    """{"segments": [...]} in the transcriber's shape; speakers=None leaves the field out (an older
    transcript, before the diarizer)."""
    segments = []
    for i, (a, b, text) in enumerate(lines):
        seg = {"start": a, "end": b, "text": text}
        if speakers:
            seg["speaker"] = speakers[i]
        segments.append(seg)
    return {"model": {"name": "ivrit-ai/whisper-large-v3-turbo-ct2"}, "segments": segments}


TWO_VOICES = _transcript(
    (0.5, 3.0, "אני מצפה שכשאני מגיע אני אקבל את האפליקציה הרשמית"),
    (3.2, 6.0, "ומה עם הדף של הפגישה?"),
    (6.4, 9.0, "הדף עובד, בואו נראה"),
    (9.4, 12.0, "מה עוד הרצנו להם?"),
    speakers=["דובר 1", "דובר 2", "דובר 1", "דובר 2"],
)
ONE_VOICE = _transcript(
    (0.5, 3.0, "זה עובד טוב"),
    (3.4, 6.0, "נמשיך מחר"),
    speakers=["דובר 1", "דובר 1"],
)
NO_LABELS = _transcript(
    (0.5, 3.0, "זה עובד טוב"),
    (3.4, 6.0, "נמשיך מחר"),
)

ANALYSIS = {
    "title": "סקירת מוצר",
    "who": ["שלמה", "דנה"],
    "speaker": "שלמה",
    "summary": "סקירה",
    "topics": [{"s": 1, "e": 5, "title": "נושא"}],
    "decisions": [{"id": "D1", "t": 2, "text": "ממשיכים"}],
    "tasks": [{"id": "T1", "t": 3, "text": "לבדוק", "who": "שלמה"}],
    "questions": [],
    "tags": [],
    "docs": [],
}


def _flow(transcript, analysis=ANALYSIS, name="2727a"):
    """Run build_flow.py as meet-start runs it, and read back the page's own data."""
    tmp = tempfile.mkdtemp(prefix="dgo1627-flow-")
    rec = os.path.join(tmp, "session-1", "abc123_2026-11-09-13-48-41.mp4")
    os.makedirs(os.path.dirname(rec))
    with open(rec, "wb") as f:
        f.write(b"not a real recording: every duration falls back to the transcript's last line\n")
    he = os.path.join(tmp, "he.json")
    with open(he, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False)
    an = os.path.join(tmp, "analysis.json")
    with open(an, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False)
    code = build_flow.main([rec, an, "--he", he])
    assert code in (0, None), f"build_flow refused the input (exit {code})"
    with open(os.path.join(os.path.dirname(rec), "flow", "data.js"), encoding="utf-8") as f:
        raw = f.read()
    assert raw.startswith("window.MEETING = ")
    data = json.loads(raw[len("window.MEETING = "):].rstrip().rstrip(";"))
    with open(os.path.join(os.path.dirname(rec), "flow", "flow.json"), encoding="utf-8") as f:
        flow = json.load(f)
    return data, flow


# ── the tests ─────────────────────────────────────────────────────────────────────────

def test_two_voices_reach_the_page_as_two_people() -> None:
    data, flow = _flow(TWO_VOICES)
    who = [t["who"] for t in data["turns"]]
    assert who == ["דובר 1", "דובר 2", "דובר 1", "דובר 2"], who
    assert len(data["colors"]) == 2, data["colors"]          # a colour per voice, not one for all
    assert data["people"][:2] == ["דובר 1", "דובר 2"], data["people"]
    assert flow["stages"]["speakers"]["state"] == "done"
    assert "דובר 2" in flow["stages"]["speakers"]["detail"]


def test_a_label_takes_the_name_the_analysis_gives_it() -> None:
    analysis = dict(ANALYSIS, names={"דובר 1": "שלמה", "דובר 2": "דנה"})
    data, flow = _flow(TWO_VOICES, analysis)
    who = [t["who"] for t in data["turns"]]
    assert who == ["שלמה", "דנה", "שלמה", "דנה"], who
    assert set(data["colors"]) == {"שלמה", "דנה"}, data["colors"]
    assert flow["stages"]["speakers"]["detail"].startswith("שלמה, דנה")


def test_one_voice_is_not_a_guess_at_a_room() -> None:
    data, flow = _flow(ONE_VOICE)
    assert {t["who"] for t in data["turns"]} == {"דובר 1"}
    # one voice is «waiting», not «done»: the page must not claim it knows who spoke
    assert flow["stages"]["speakers"]["state"] == "waiting", flow["stages"]["speakers"]


def test_a_transcript_without_labels_renders_exactly_as_before() -> None:
    """Every meeting filed before DGO-1627 has no speaker in its JSON: those pages must not change."""
    data, flow = _flow(NO_LABELS)
    assert {t["who"] for t in data["turns"]} == {"שלמה"}, [t["who"] for t in data["turns"]]
    # …and the analysis' roster is still there: the labels are new, the participants are not lost
    assert data["people"][:2] == ["שלמה", "דנה"], data["people"]
    assert flow["stages"]["speakers"]["state"] == "waiting"


def test_the_first_pass_shows_the_label_and_never_a_name() -> None:
    server = _server_module()
    assert server.turn_speaker({"speaker": "דובר 2"}) == "דובר 2"
    assert server.turn_speaker({"speaker": ""}) == "?"
    assert server.turn_speaker({}) == "?"          # an older transcript, or a segment with no speaker


def _run() -> int:
    failures = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
    print(f"{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
