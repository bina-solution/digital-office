#!/usr/bin/env python3
"""A meeting's full processing — the flow folder meet-start's /flow door reads (start/server.py flows(), flow_meeting())
and that, until now, nothing in the repo wrote (issues/a-meetings-flow-has-a-page-but-no-pipeline.yaml).

    build_flow.py RECORDING.mp4 ANALYSIS.json [--he HE.json] [--whisper WHISPER.json]

RECORDING is the meeting's recording on the recordings volume (<root>/<session>/<room>_<time>.mp4). The folder is
written beside it: <root>/<session>/flow/{flow.json, data.js}, each whole (a temp file, then rename), so the page never
reads half of one. Run where that volume is writable: meet-jibri (meet-start mounts it read-only).

HE / WHISPER are the transcriber's answers (apitools-asr: {model, segments: [{start, end, text}]}) on the recording's
clock — the same the workflow puts on the meeting's MEET item. HE becomes the transcript's lines; WHISPER is used only
when there is no HE (an English meeting). ANALYSIS is what was understood from them (the step an agent does on «קדימה»):

    {"title": "…", "who": ["…"], "speaker": "the name for lines nobody else is named on",
     "summary": "…", "tags": ["…"], "docs": [{"title": "…", "href": "…"}],
     "topics":    [{"s": 69, "e": 158, "title": "…", "body": "…"}],
     "decisions": [{"id": "D1", "t": 145, "text": "…", "type": "…"}],
     "tasks":     [{"id": "T1", "t": 97, "text": "…", "who": "…", "area": "…", "due": "",
                    "plane": {"key": "FPG-622", "url": "https://…"}}],
     "questions": [{"id": "Q1", "t": 230, "text": "…", "blocks": "what cannot go on until it is answered"}]}

A question is something said and left OPEN in the meeting that blocks work — never a clear statement turned around
(the owner, DGO-1183: «if I say something clear, so it should be clear, there's no question about it»). What was
said clearly is a decision, a task, or nothing. So each question names what it "blocks", and a meeting gets at most
MAX_QUESTIONS of them; more is refused, not trimmed — the analysis is redone.

A task that already has its Plane item says so in "plane"; link_tasks.py (run in meet-start) then stores it approved
with that link, so the page shows «ב-Plane · FPG-622» and approving it never files a second item. Plane stays the one
place tasks are managed; the page only points at it.

Exit 0 written, 2 refused (nothing written). A second run with the same input writes the same files.
"""
import json
import math
import os
import re
import sys

STAMP = re.compile(r"^(?P<room>.+)_(?P<d>\d{4}-\d\d-\d\d)-(?P<h>\d\d)-(?P<m>\d\d)-(?P<s>\d\d)\.mp4$")
HUES = ["sky", "lime", "olive", "plum"]
FILLER = re.compile(r"^[\sאהםמ.…,!?-]*$")          # «אהההה», «…»: no words
# start/server.py's own: a folder whose room or session these refuse is skipped by flows(), an id by the item doors
FLOW_ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
FLOW_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
MAX_QUESTIONS = 5                                   # DGO-1183: pages with hundreds of «open questions» nobody had


def die(why):
    print(f"build_flow: {why}", file=sys.stderr)
    sys.exit(2)


def load(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError) as e:
        die(f"{what}: {e}")
    if not isinstance(got, dict):
        die(f"{what}: not a JSON object")
    return got


def segments(asr):
    out = []
    for s in asr.get("segments") or []:
        try:
            a, b, text = float(s["start"]), float(s["end"]), str(s.get("text") or "").strip()
        except (KeyError, TypeError, ValueError):
            continue
        if text and not FILLER.fullmatch(text):
            out.append((a, max(a + 0.1, b), text))
    return out


def items(rows, kind, prefix):
    out = []
    for i, x in enumerate(rows or []):
        if not isinstance(x, dict) or not str(x.get("text") or "").strip():
            die(f"analysis.{kind}[{i}]: needs text")
        x = dict(x, id=str(x.get("id") or f"{prefix}{i + 1}"))
        if not FLOW_ID_RE.fullmatch(x["id"]):
            die(f"analysis.{kind}[{i}].id: {FLOW_ID_RE.pattern}")
        if x.get("t") is not None:
            try:
                x["t"] = round(float(x["t"]), 2)
            except (TypeError, ValueError):
                x["t"] = math.nan
            if not math.isfinite(x["t"]) or x["t"] < 0:     # NaN would reach data.js, which JSON.parse refuses
                die(f"analysis.{kind}[{i}].t: seconds from the recording's start")
        out.append(x)
    ids = [x["id"] for x in out]
    if len(set(ids)) != len(ids):
        die(f"analysis.{kind}: ids repeat")
    return out


def write_whole(path, text):
    tmp = f"{path}.part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def duration_of(rec, fallback):
    # the recording's own length (finalize.sh's silence/holes JSON knows it; ffprobe is in meet-jibri)
    try:
        import subprocess
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", rec],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return fallback


def main(argv):
    args, opts = [], {}
    it = iter(argv)
    for a in it:
        if a in ("--he", "--whisper"):
            opts[a[2:]] = next(it, None)
        else:
            args.append(a)
    if len(args) != 2 or None in opts.values():
        die("usage: build_flow.py RECORDING.mp4 ANALYSIS.json [--he HE.json] [--whisper WHISPER.json]")
    rec, an = os.path.abspath(args[0]), load(args[1], "analysis")    # the folder it is named in, never a link's target
    m = STAMP.match(os.path.basename(rec))
    if not m or not os.path.isfile(rec):
        die(f"{rec}: not a recording (<room>_<yyyy-mm-dd-hh-mm-ss>.mp4)")
    session, room = os.path.basename(os.path.dirname(rec)), m["room"].lower()
    if not FLOW_ROOM_RE.fullmatch(room) or not SESSION_RE.fullmatch(session):
        die(f"room {room!r} or session {session!r} is one the meetings page does not list")
    started = f"{m['d']} {m['h']}:{m['m']}"
    he = segments(load(opts["he"], "he")) if opts.get("he") else []
    wh = segments(load(opts["whisper"], "whisper")) if opts.get("whisper") else []
    if not he and not wh:
        die("no transcript: give --he and/or --whisper with words in them")
    last = max([e for _, e, _ in he + wh] + [1.0])
    dur = round(duration_of(rec, last), 1)

    speaker = str(an.get("speaker") or (an.get("who") or ["משתתף"])[0])
    colors = {speaker: HUES[0]}
    for w in an.get("who") or []:
        colors.setdefault(str(w), HUES[len(colors) % len(HUES)])
    turns = [{"id": f"t{i:04d}", "s": round(a, 2), "e": round(b, 2), "who": speaker, "text": t, "flags": []}
             for i, (a, b, t) in enumerate(he or wh)]
    # data.js "tail" is what was said AFTER the call (stage.js: «אחרי השיחה»), shown with the lines in the player — a
    # second transcript there doubled every line with the weaker one (MEET-48: Whisper over ivrit). ivrit is the
    # transcript; Whisper stays on the MEET item, and is the transcript only when there is no ivrit.
    tail = []
    topics = []
    for i, x in enumerate(an.get("topics") or []):
        try:
            topics.append({"s": round(float(x["s"]), 2), "e": round(float(x["e"]), 2), "title": str(x["title"]),
                           "body": str(x.get("body") or "")})
        except (KeyError, TypeError, ValueError):
            die(f"analysis.topics[{i}]: needs s, e, title")
    questions = items(an.get("questions"), "questions", "Q")
    if len(questions) > MAX_QUESTIONS:
        die(f"{len(questions)} questions: at most {MAX_QUESTIONS} — a clear statement is a decision or a task, not a question")
    for x in questions:
        if not str(x.get("blocks") or "").strip():
            die(f"question {x['id']}: say what it blocks — or it is not an open question")
    tasks = items(an.get("tasks"), "tasks", "T")
    for x in tasks:
        p = x.get("plane")
        if p is not None and not (isinstance(p, dict) and p.get("key") and str(p.get("url", "")).startswith("https://")):
            die(f"task {x['id']}: plane must be {{key, url (https)}}")
    # every reader (server.py docs_of, the page) takes {title, href}; "url" is accepted for it
    docs = []
    for i, d in enumerate(an.get("docs") or []):
        if isinstance(d, (list, tuple)) and len(d) >= 2:   # [title, href], as docs_of also takes
            d = {"title": d[0], "href": d[1]}
        href = str(d.get("href") or d.get("url") or "") if isinstance(d, dict) else ""
        if not href:
            die(f"analysis.docs[{i}]: needs href")
        docs.append({"title": str(d.get("title") or href), "href": href})
    people = [str(w) for w in an.get("who") or []] or [speaker]
    title = str(an.get("title") or room)
    used = ("he", "he") if he else ("whisper", "whisper")    # the one the lines came from
    m = load(opts[used[0]], used[1]).get("model") if opts.get(used[0]) else None
    model = str(m.get("name") or "") if isinstance(m, dict) else str(m or "")    # apitools-asr: {name, revision, …}
    data = {
        "meeting": {"id": room, "title": title, "duration": dur,
                    "subtitle": f"{started} · {', '.join(people[:8])}",
                    "transcript_label": "תמלול מכונה במשרד (" + ("ivrit.ai" if he else "Whisper") + ", לא נבדק)",
                    "facts": [["סיכום", str(an.get("summary") or "")]] + ([["מודל התמלול", model]] if model else []),
                    "docs": docs},
        "colors": colors,
        "video": {"src": f"../../recordings/{session}/{os.path.basename(rec)}", "offset": 0, "duration": dur},
        "audio": [{"id": "meet", "label": "הקלטת הפגישה", "src": None, "offset": 0, "duration": dur}],
        "frames": [], "screens": [], "floor": [], "presence": [], "turns": turns, "tail": tail, "captions": [],
        "topics": topics, "decisions": items(an.get("decisions"), "decisions", "D"), "tasks": tasks,
        "questions": questions, "likes": [], "insights": [], "moments": [],
        "people": people,
    }
    words = sum(len(t["text"].split()) for t in turns)
    flow = {"room": room, "title": title, "started": started, "session": session, "length": dur, "who": people,
            "tags": list(an.get("tags") or []), "docs": docs,
            "stages": {"best": {"state": "done", "detail": f"{len(turns)} שורות, {words} מילים"},
                       "speakers": {"state": "done", "detail": ", ".join(people)},
                       "summary": {"state": "done", "detail": f"{len(topics)} נושאים · {len(data['decisions'])} החלטות · "
                                                              f"{len(tasks)} משימות · {len(data['questions'])} שאלות"}}}
    folder = os.path.join(os.path.dirname(rec), "flow")
    os.makedirs(folder, exist_ok=True)
    write_whole(os.path.join(folder, "data.js"),
                "window.MEETING = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n")
    write_whole(os.path.join(folder, "flow.json"), json.dumps(flow, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"ok": True, "folder": folder, "room": room, "lines": len(turns), "topics": len(topics),
                      "decisions": len(data["decisions"]), "tasks": len(tasks), "questions": len(data["questions"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
