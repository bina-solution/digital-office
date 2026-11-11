#!/usr/bin/env python3
"""meet-flow-mock — the meeting page («דף הפגישה», apps/meet/start/flow) as an interactive simulation (DGO-1325).

AGENTS.md rule 11: a display change comes back as a mock the owner can drive, starting from the screen he sent. This
runs the REAL page — the bundles flow/build.sh makes (mf.css, mf.js) — on fixtures: a fake server answers the
page's calls (meeting.json, data.js, edits, items, uploads) inside the page itself, so one HTML file runs anywhere,
his phone included, with nothing behind it. The same fixtures drive the page as it was (the bundles of --before), so
every frame has a before and an after on the same data.

Frames: 1 his own screenshot (bs101, 2026-11-03 14:26, during the transcription), then the five states a meeting
passes after it ends — ended (no captions, the transcription not sent yet), queued, transcribing, transcribed (waiting
for «קדימה»), ready — on bs101's measured numbers (1:36:01, 312 MB, ivrit at rtf 0.99, no live captions on 2 cores).
The words of the meeting are made up; the numbers are bs101's.

    python3 digital-office/sim/meet-flow-mock.py --shot <his.jpg> --top <band-top.png> --bottom <band-bottom.png> \
        [--before HEAD] [--out ci-artifacts/meet-flow-mock] [--shots]

--shots photographs every frame with the Mac's Chrome, headless (no server, nothing installed): the phone in his own
chrome (393 × 595, his device's 1.5 scale), the phone alone (390 × 844 at 3) and a desktop (1440 × 900), light and
dark, before and after. The bands are cut from his shot (prep-screen-bands.py, or any crop): rows 0–220 and 1114–1280
of the 591 × 1280 picture he sent.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
FLOW = REPO / "apps/meet/start/flow"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# ── the fixtures: a fake meet-start, written in the page's own language (built at the page's own clock) ─────────────
FIXTURES_JS = r"""
(function () {
  "use strict";
  const ROOM = "bs101", DUR = 5761, MB = 312, H = 3600;
  const SAID = ["בוא נתחיל — יש לנו היום שלושה נושאים על השולחן", "הראשון הוא הדף של הפגישות, איך הוא נראה בטלפון",
    "אני רוצה לראות בדיוק מה קורה עם התמלול ולמה", "כל משימה שעולה כאן צריכה להגיע ישר ל-Plane", "מי לוקח את זה ועד מתי?",
    "בוא נשים את זה בתור החלטה", "החלק התחתון צריך להיפתח למעלה, אחרת אי אפשר לעבוד איתו", "תראה פה, על המסך — זה המצב היום",
    "השאלה היא כמה זמן לוקח לתמלל שעה וחצי", "על שתי ליבות זה כמעט כמו אורך הפגישה עצמה", "אז הכתוביות החיות צריכות לרוץ על מחשב אחר",
    "המחשב הנייד בבית יכול לקחת את זה", "צריך שהדף יגיד את זה במילים פשוטות", "בסדר, ואחרי התמלול — הנושאים וההחלטות",
    "אני אעבור על המשימות ואאשר אותן", "בוא נקבע פגישת המשך לשבוע הבא", "יש עוד משהו פתוח מהפגישה הקודמת?",
    "המסמך של התוכנית צריך להיות מעודכן לפני זה", "אני שולח לך את הקובץ אחרי הפגישה", "מצוין, ככה זה ברור"];
  const pick = (i) => SAID[i % SAID.length];
  function turns(start, n, who) {
    const out = []; const step = DUR / n;
    for (let i = 0; i < n; i++) { const s = Math.round(i * step * 10) / 10; const e = Math.round((s + Math.min(step - 1, 6 + (i % 5) * 4)) * 10) / 10;
      const text = pick(i) + (i % 3 === 0 ? "" : " — " + pick(i + 7));
      out.push({ id: "m" + String(i).padStart(4, "0"), s, e, who: who(i), text, flags: ["ivrit turbo (the office's recogniser), not reviewed"] }); }
    return out;
  }
  const TOPICS = ["מה מוצג היום בדף הפגישה", "למה אין כתוביות חיות", "כמה זמן לוקח התמלול", "החלק התחתון בטלפון", "שורת המצב",
    "הכתוביות על מחשב אחר", "משימות ל-Plane", "החלטות לאישור", "פגישת המשך", "המסמך של התוכנית", "סיכום"];
  const DECS = ["שורת מצב אחת שאומרת מה קורה ולמה", "החלק התחתון נגרר לחצי ולמסך מלא", "חמש לשוניות שנכנסות בטלפון",
    "הכתוביות החיות ירוצו על המחשב שבבית", "התמלול יופיע בלי לרענן", "כל משימה מגיעה ל-Plane", "פגישת המשך בשבוע הבא",
    "הדף אומר מתי התמלול צפוי", "במחשב שני חלקים עם מחיצה", "הכהה נראה כמו הבהיר", "שם הפגישה בשורה אחת",
    "הנגן הקטן נשאר כשהלוח פתוח", "חזרה אחורה מחזירה את הלוח"];
  const TASKS = [["לעדכן את המסמך של התוכנית", "שלמה בולוטין"], ["לבדוק את הדף בטלפון", "שלמה בולוטין"], ["להעביר את הכתוביות למחשב שבבית", "שלמה בולוטין"],
    ["לקבוע פגישת המשך", "שלמה בולוטין"], ["לאשר את ההחלטות", "שלמה בולוטין"], ["לשלוח את הקובץ", "שלמה בולוטין"]];
  const QS = ["כמה ליבות צריך בשביל כתוביות בזמן אמת?", "מי בודק את התמלול לפני שהוא נסגר?"];
  const len = (t) => { t = Math.floor(t); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60; return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; };
  const why = "לשרת המשרד יש 2 ליבות, וכתוביות חיות צריכות 4";

  function base(now, start, state, title) {
    return { room: ROOM, title, series: "bs", n: 101, state, prev: null, started_ts: start, ended_ts: start + DUR, people: ["שלמה בולוטין"],
      uncaptioned: [], recording: { session: "b2abec86-d5ff-40ac-8f4d-18dc01ef7ece", file: "bs101_2026-11-03-12-08-14.mp4", done: true },
      meet_url: "https://meet.staging.digital-office.co.il/bs101", data: `flow/${ROOM}/data.js`, live: null };
  }
  const rec = { key: "record", state: "done", detail: `${MB} MB · ${len(DUR)}` };
  const cap = { key: "captions", state: "off", detail: "לא היו כתוביות חיות", why };
  const later = (k) => ({ key: k, state: "waiting", detail: "אחרי «קדימה» — העיבוד המלא" });
  const review = { key: "review", state: "waiting", detail: "עוד לא נבדק" };
  // the page as meet-start drew it until 2026-11-05 (its stages, for the «before» half)
  const oldStages = (bestState, flow) => [
    { key: "record", state: "done", detail: `bs101_2026-11-03-12-08-14.mp4 · ${MB} MB` },
    { key: "captions", state: "off", detail: "אין כתוביות חיות" },
    { key: "first", state: "done", detail: flow ? "העיבוד המלא קיים" : "ההקלטה והכתוביות החיות על ציר אחד" },
    { key: "best", state: bestState, detail: flow ? "934 שורות, 13200 מילים" : "מזהה הדיבור הטוב ביותר" },
    { key: "speakers", state: flow ? "done" : "waiting", detail: flow ? "שלמה בולוטין" : "מי אמר מה" },
    { key: "summary", state: flow ? "done" : "waiting", detail: flow ? "11 נושאים · 13 החלטות · 6 משימות · 2 שאלות" : "נושאים, החלטות ומשימות" },
    review];
  function data(state, ts) {
    const ready = state === "ready";
    const T = ts;
    return { meeting: { id: ROOM, title: ready ? "bs101 · תוכנית עבודה לדף הפגישה" : ROOM, duration: DUR, subtitle: "", transcript_label: ready ? "תמלול (ivrit, נבדק בעיבוד המלא)" : "תמלול מכונה (ivrit, לא נבדק)",
        facts: [["מה יש כאן", ready ? "העיבוד המלא: התמלול, הדוברים, הנושאים, ההחלטות והמשימות." : "ההקלטה ותמלול המכונה שלה. הנושאים, ההחלטות והמשימות — אחרי «קדימה»."]], docs: [] },
      colors: ready ? { "שלמה בולוטין": "olive" } : {}, video: { src: "../../recordings/b2abec86/bs101.mp4", offset: 0, duration: DUR },
      audio: [{ id: "meet", label: "הקלטת הפגישה", src: null, offset: 0, duration: DUR }],
      frames: [], screens: [], floor: [], presence: [], turns: T, tail: [], captions: [],
      topics: ready ? TOPICS.map((t, i) => ({ s: Math.round(i * DUR / TOPICS.length), e: Math.round((i + 1) * DUR / TOPICS.length), title: t, body: pick(i * 2) + ". " + pick(i * 2 + 1) + "." })) : [],
      decisions: ready ? DECS.map((t, i) => ({ id: "D" + (i + 1), t: Math.round((i + 0.5) * DUR / DECS.length), text: t, who: "שלמה בולוטין" })) : [],
      tasks: ready ? TASKS.map(([t, w], i) => ({ id: "T" + (i + 1), t: Math.round((i + 0.7) * DUR / TASKS.length), text: t, who: w })) : [],
      questions: ready ? QS.map((t, i) => ({ id: "Q" + (i + 1), t: Math.round((i + 0.4) * DUR / 2), text: t, who: "שלמה בולוטין" })) : [],
      likes: [], insights: [], moments: [], job: "tr_36edac5b3740", people: ["שלמה בולוטין"] };
  }
  const NONE = [];
  window.mockFrames = function (now) {
    const F = {};
    { // ended a minute ago: the recording is closed, no captions, the transcription not sent yet
      const start = now - DUR - 60;
      F.ended = { info: Object.assign(base(now, start, "first", ROOM), { rev: "a", counts: { lines: 0 },
        stages: [rec, cap, { key: "ivrit", state: "waiting", detail: "עוד לא נשלח — המערכת שולחת הקלטה חדשה תוך דקות" },
          { key: "whisper", state: "waiting", detail: "אחרי התמלול העברי" }, later("speakers"), later("summary"), review] }),
        old: { title: "bs101 · עיבוד ראשון", stages: oldStages("waiting") }, data: data("first", NONE) };
    }
    { // queued behind another meeting's transcription
      const start = now - DUR - 300, other = 0.7 * 2400 * 0.99, eta = now + other + DUR * 0.99;
      F.queued = { info: Object.assign(base(now, start, "first", ROOM), { rev: "a", counts: { lines: 0 },
        stages: [rec, cap, { key: "ivrit", state: "waiting", detail: "בתור — לפניה התמלול של dgo-tour-2", ahead: 1, eta, since: now - 240 },
          { key: "whisper", state: "waiting", detail: "אחרי התמלול העברי", eta: eta + DUR * 0.96 }, later("speakers"), later("summary"), review] }),
        old: { title: "bs101 · עיבוד ראשון", stages: oldStages("waiting") }, data: data("first", NONE) };
    }
    { // transcribing: where his screenshot was taken (40 minutes into the ivrit pass)
      const started = now - 2400, done = 2400 / 0.99, start = started - DUR - 97;
      F.transcribing = { info: Object.assign(base(now, start, "first", ROOM), { rev: "a", counts: { lines: 0 },
        stages: [rec, cap, { key: "ivrit", state: "running", detail: `${len(done)} מתוך ${len(DUR)}`, pct: Math.round(1000 * done / DUR) / 10, done_s: done, audio_s: DUR, since: started, eta: now + (DUR - done) * 0.99 },
          { key: "whisper", state: "waiting", detail: "אחרי התמלול העברי", eta: now + (DUR - done) * 0.99 + DUR * 0.96 }, later("speakers"), later("summary"), review] }),
        old: { title: "bs101 · עיבוד ראשון", stages: oldStages("waiting") }, data: data("first", NONE) };
    }
    { // transcribed: ivrit done, whisper running, the topics wait for «קדימה»
      const wst = now - 1020, start = wst - 5829 - DUR - 97, T = turns(start, 140, () => "?");
      F.transcribed = { info: Object.assign(base(now, start, "first", ROOM), { rev: "b", counts: { lines: T.length },
        stages: [rec, cap, { key: "ivrit", state: "done", detail: `${T.length} שורות · ${len(DUR)} בתוך 1:37:10` },
          { key: "whisper", state: "running", detail: `${len(1020 / 0.96)} מתוך ${len(DUR)}`, pct: Math.round(1000 * 1020 / 0.96 / DUR) / 10, done_s: 1020 / 0.96, audio_s: DUR, since: wst, eta: now + (DUR - 1020 / 0.96) * 0.96 },
          later("speakers"), later("summary"), review] }),
        old: { title: "bs101 · עיבוד ראשון", stages: oldStages("waiting") }, data: data("first", T) };
    }
    { // ready: «קדימה» processed it — the topics, decisions and tasks, eleven of them waiting for a person
      const start = now - 26 * H, T = turns(start, 140, () => "שלמה בולוטין");
      const items = {}; DECS.forEach((d, i) => { items["decision:D" + (i + 1)] = { state: i < 5 ? "approved" : "proposed" }; });
      TASKS.forEach((d, i) => { items["task:T" + (i + 1)] = i < 5 ? { state: "approved", plane: { key: "DGO-" + (1400 + i), url: "#" } } : { state: "proposed" }; });
      F.ready = { info: Object.assign(base(now, start, "ready", "bs101 · תוכנית עבודה לדף הפגישה — בינה סלושנס והלשכה הדיגיטלית"), { rev: "c",
        counts: { decisions: 13, tasks: 6, questions: 2, proposed: 11, approved: 8, rejected: 0, lines: T.length, marks: 0 },
        stages: [rec, cap, { key: "ivrit", state: "done", detail: `${T.length} שורות · 13,200 מילים` }, { key: "whisper", state: "done", detail: "1,843 קטעים" },
          { key: "speakers", state: "done", detail: "שלמה בולוטין" }, { key: "summary", state: "done", detail: "11 נושאים · 13 החלטות · 6 משימות · 2 שאלות" }, review] }),
        old: { title: "bs101 · תוכנית עבודה לדף הפגישה — בינה סלושנס והלשכה הדיגיטלית", stages: oldStages("done", true) }, data: data("ready", T), items };
    }
    return F;
  };
})();
"""

# ── the page, as meet-start serves it, with the fake server inside it ───────────────────────────────────────────────
SHIM_JS = r"""
(function () {
  "use strict";
  const P = window.MOCK_PICK || Object.fromEntries(new URLSearchParams(location.search));
  const frame = P.frame || "transcribing", variant = P.variant || "after";
  document.documentElement.dataset.theme = P.theme === "dark" ? "midnight" : "light";
  const F = window.mockFrames(Date.now() / 1000)[frame];
  const info = variant === "before" ? Object.assign({}, F.info, F.old) : F.info;
  window.MF_ROOT = "/a/meet/";                 // the console's address of the app
  window.MF_STYLES = Promise.resolve();
  const json = (x) => new Response(JSON.stringify(x), { status: 200, headers: { "Content-Type": "application/json" } });
  window.fetch = async function (url) {
    const p = String(url).split("?")[0];
    if (p.endsWith("/meeting.json")) return json(info);
    if (p.endsWith("/edits")) return json({ edits: [] });
    if (p.endsWith("/items")) return json({ items: F.items || {} });
    if (p.endsWith("/uploads")) return json({ uploads: [] });
    if (p.includes("/flow/api/")) return json({ meetings: [], items: [], hits: [] });
    return new Response("not found", { status: 404 });
  };
  window.MOCK_AFTER_LOAD = function () {
    const MF = window.MF;
    MF.loadData = () => Promise.resolve(JSON.parse(JSON.stringify(F.data)));
    const where = MF.where;
    MF.where = () => { const w = where(); return w.room ? w : Object.assign(w, { room: "bs101", view: new URLSearchParams(location.search).get("v") || P.v || "" }); };
    try { localStorage.clear(); } catch (e) { /* */ }
    if (P.sheet) try { localStorage.setItem("mf:sheet", JSON.stringify(P.sheet)); } catch (e) { /* */ }
    if (P.v) try { localStorage.setItem("mf:tab", JSON.stringify(P.v)); } catch (e) { /* */ }
  };
})();
"""


def app_doc(css: str, js: str, pick: dict | None) -> str:
    """One page of the app: its styles and script inline, the fixtures and the fake server before them."""
    pick_js = f"window.MOCK_PICK = {json.dumps(pick, ensure_ascii=False)};" if pick is not None else ""
    cfg = html.escape(json.dumps({"meet": "https://meet.staging.digital-office.co.il", "room": "bs101", "me": {"username": "owner", "name": "שלמה בולוטין"},
                                  "console": "https://console.staging.digital-office.co.il", "ui": "v2"}, ensure_ascii=False))
    js = js.replace("</script", "<\\/script")
    return (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark">'
            f'<title>פגישות</title><style>{css}</style><script>{pick_js}{FIXTURES_JS}{SHIM_JS}</script>'
            f'<script>{js}</script><script>window.MOCK_AFTER_LOAD();</script></head>'
            f'<body data-config="{cfg}"><div id="app" class="mf"><div class="mf-boot" role="status">טוען את הפגישות…</div></div></body></html>')


FRAMES = [("his", "1 · המסך שלך", "bs101 ב-3.11, 14:26: «עיבוד ראשון», בלי כתוביות, בלי לומר למה ומתי."),
          ("ended", "2 · נגמרה", "רגע אחרי הפגישה: ההקלטה נשמרה; למה אין כתוביות, ומתי התמלול מתחיל."),
          ("queued", "3 · בתור", "התמלול ממתין לפגישה אחרת: לפני מי, ומתי הוא צפוי להסתיים."),
          ("transcribing", "4 · מתמלל", "הרגע של הצילום שלך: כמה אחוזים, כמה מתוך כמה, ומתי ייגמר."),
          ("transcribed", "5 · התמלול מוכן", "השורות הגיעו בלי רענון; הנושאים וההחלטות מחכים ל«קדימה»."),
          ("ready", "6 · מעובדת", "אחרי «קדימה»: נושאים, החלטות ומשימות — ומה מחכה לאישור שלך.")]


def harness(after_css, after_js, before_css, before_js, shot_b64, top_b64, bottom_b64) -> str:
    """The page the owner drives: a frame, before/after, phone/desktop, light/dark — the app inside a frame of his own
    phone's chrome (the bands of his shot) or a desktop window."""
    docs = {}
    for v, (css, js) in {"after": (after_css, after_js), "before": (before_css, before_js)}.items():
        docs[v] = app_doc(css, js, {"frame": "@@FRAME@@", "variant": v, "theme": "@@THEME@@", "sheet": "@@SHEET@@", "v": "@@V@@"})
    frames = json.dumps([[k, t, c] for k, t, c in FRAMES], ensure_ascii=False)
    docs_js = json.dumps(docs, ensure_ascii=False).replace("</script", "<\\/script")
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>דף הפגישה — הדמיה</title>
<style>
:root {{ --bg:#f3f5f7; --surface:#fff; --ink:#1f2a17; --muted:#6a7068; --line:#dcdfde; --olive:#56693f; --olive-ink:#f3f5f7; --olive-soft:#e7eae4; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141b0f; --surface:#1f2a17; --ink:#f3f5f7; --muted:#a2a8a2; --line:#414a3b; --olive:#a5ba8c; --olive-ink:#1f2a17; --olive-soft:#384629; }} }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:13px/1.5 "Segoe UI","Noto Sans Hebrew",system-ui,sans-serif; }}
.bar {{ position:sticky; top:0; z-index:5; background:var(--surface); border-bottom:1px solid var(--line); padding:8px 10px; display:flex; flex-direction:column; gap:6px; }}
.bar h1 {{ margin:0; font-size:15px; }}
.row {{ display:flex; gap:6px; flex-wrap:wrap; align-items:center; }}
.seg {{ display:inline-flex; border:1px solid var(--line); border-radius:9px; overflow:hidden; }}
.seg button, .chip {{ border:0; background:transparent; color:var(--ink); font:inherit; padding:0 10px; min-height:34px; cursor:pointer; }}
.chip {{ border:1px solid var(--line); border-radius:999px; }}
.seg button[aria-pressed=true], .chip[aria-pressed=true] {{ background:var(--olive); color:var(--olive-ink); }}
.cap {{ color:var(--muted); margin:0; }}
.stage {{ display:flex; justify-content:center; padding:10px 0 24px; }}
.dev {{ transform-origin: top center; }}
.phone {{ width:393px; background:#000; border-radius:22px; overflow:hidden; box-shadow:0 10px 40px rgba(0,0,0,.35); }}
.phone img {{ display:block; width:393px; }}
.phone iframe {{ display:block; width:393px; height:595px; border:0; background:#141b0f; }}
.bare iframe {{ display:block; width:390px; height:844px; border:0; border-radius:18px; box-shadow:0 10px 40px rgba(0,0,0,.35); }}
.desk iframe {{ display:block; width:1440px; height:900px; border:0; border-radius:10px; box-shadow:0 10px 40px rgba(0,0,0,.35); }}
.his img {{ display:block; width:393px; border-radius:22px; box-shadow:0 10px 40px rgba(0,0,0,.35); }}
.shot .bar {{ display:none; }} .shot .stage {{ padding:0; display:block; }}
.shot #dev {{ position:absolute; top:0; left:0; }}   /* headless Chrome lays out at least 500 px wide and shoots from the left */
.shot :is(.phone, .bare iframe, .desk iframe, .his img) {{ border-radius:0; box-shadow:none; }}
</style></head><body>
<div class="bar">
  <h1>דף הפגישה — הדמיה (DGO-1325)</h1>
  <p class="cap">הדף האמיתי, על נתונים לדוגמה: אפשר ללחוץ, לגרור את הלוח למעלה ולמטה, לבחור לשונית ולנגן. המספרים של bs101, המילים לדוגמה.</p>
  <div class="row" id="frames"></div>
  <div class="row">
    <span class="seg" id="variant"><button data-v="before">לפני</button><button data-v="after">אחרי</button></span>
    <span class="seg" id="view"><button data-v="his">הטלפון שלך</button><button data-v="phone">טלפון מלא</button><button data-v="desk">מחשב</button></span>
    <span class="seg" id="theme"><button data-v="light">בהיר</button><button data-v="dark">כהה</button></span>
  </div>
  <p class="cap" id="caption"></p>
</div>
<div class="stage"><div class="dev" id="dev"></div></div>
<script>
const DOCS = {docs_js};
const FRAMES = {frames};
const SHOT = "data:image/jpeg;base64,{shot_b64}", TOP = "data:image/png;base64,{top_b64}", BOTTOM = "data:image/png;base64,{bottom_b64}";
const S = {{ frame: "his", variant: "after", view: "his", theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light", sheet: "half", v: "" }};
const Q = new URLSearchParams(location.search), SHOOT = !!Q.get("shot");      // the camera's own address: no bar, no scale
if (SHOOT) {{ document.body.classList.add("shot"); for (const k of Object.keys(S)) if (Q.get(k)) S[k] = Q.get(k); }}
const $ = (s) => document.querySelector(s);
$("#frames").innerHTML = FRAMES.map(([k, t]) => `<button class="chip" data-f="${{k}}">${{t}}</button>`).join("");
function doc() {{
  return DOCS[S.variant].replace('"@@FRAME@@"', JSON.stringify(S.frame)).replace('"@@THEME@@"', JSON.stringify(S.theme))
    .replace('"@@SHEET@@"', JSON.stringify(S.sheet)).replace('"@@V@@"', JSON.stringify(S.v));
}}
function fit() {{
  const c = $("#dev").firstElementChild, d = $("#dev"), w = (c && c.offsetWidth) || 393, h = (c && c.offsetHeight) || 851;
  const s = SHOOT ? 1 : Math.min(1, (innerWidth - 16) / w, S.view === "desk" ? 1 : Math.max(0.55, (innerHeight - $(".bar").offsetHeight - 30) / h));
  d.style.transform = `scale(${{s}})`; d.parentElement.style.height = Math.ceil(h * s + 34) + "px";
}}
function draw() {{
  for (const b of document.querySelectorAll("[data-f]")) b.setAttribute("aria-pressed", b.dataset.f === S.frame);
  for (const [id, k] of [["#variant", "variant"], ["#view", "view"], ["#theme", "theme"]]) for (const b of $(id).querySelectorAll("button")) b.setAttribute("aria-pressed", b.dataset.v === S[k]);
  $("#caption").textContent = (FRAMES.find((f) => f[0] === S.frame) || [])[2] || "";
  const d = $("#dev");
  if (S.frame === "his") d.innerHTML = `<div class="his"><img src="${{SHOT}}" alt="המסך שנשלח, 3.11 14:26"></div>`;
  else if (S.view === "his") d.innerHTML = `<div class="phone"><img src="${{TOP}}" alt=""><iframe title="דף הפגישה"></iframe><img src="${{BOTTOM}}" alt=""></div>`;
  else if (S.view === "phone") d.innerHTML = `<div class="bare"><iframe title="דף הפגישה"></iframe></div>`;
  else d.innerHTML = `<div class="desk"><iframe title="דף הפגישה"></iframe></div>`;
  const f = d.querySelector("iframe"); if (f) f.srcdoc = doc();
  for (const i of d.querySelectorAll("img")) i.addEventListener("load", fit);
  requestAnimationFrame(fit);
}}
document.addEventListener("click", (e) => {{
  const f = e.target.closest("[data-f]"); if (f) {{ S.frame = f.dataset.f; if (S.frame !== "his" && S.view === "his" && false) {{}} draw(); return; }}
  for (const [id, k] of [["#variant", "variant"], ["#view", "view"], ["#theme", "theme"]]) {{ const b = e.target.closest(id + " button"); if (b) {{ S[k] = b.dataset.v; draw(); return; }} }}
}});
addEventListener("resize", fit);
draw();
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shot", required=True, help="his screenshot (frame one)")
    ap.add_argument("--top", required=True, help="the band above the app in his shot (PNG)")
    ap.add_argument("--bottom", required=True, help="the band under the app in his shot (PNG)")
    ap.add_argument("--before", default="HEAD", help="the commit whose bundles are «before» (default HEAD)")
    ap.add_argument("--out", default=str(REPO / "ci-artifacts/meet-flow-mock"))
    ap.add_argument("--shots", action="store_true", help="photograph every frame with headless Chrome")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    after_css, after_js = (FLOW / "mf.css").read_text(encoding="utf-8"), (FLOW / "mf.js").read_text(encoding="utf-8")
    show = lambda p: subprocess.run(["git", "-C", str(REPO), "show", f"{a.before}:apps/meet/start/flow/{p}"], check=True,
                                    capture_output=True).stdout.decode("utf-8")
    before_css, before_js = show("mf.css"), show("mf.js")
    b64 = lambda p: base64.b64encode(pathlib.Path(p).read_bytes()).decode("ascii")
    page = harness(after_css, after_js, before_css, before_js, b64(a.shot), b64(a.top), b64(a.bottom))
    (out / "meet-flow-mock.html").write_text(page, encoding="utf-8")
    print(f"{out / 'meet-flow-mock.html'}  {len(page.encode()) // 1024} KB")
    # one file per variant for the camera: the frame, theme and snap come from its query
    for v, (css, js) in {"after": (after_css, after_js), "before": (before_css, before_js)}.items():
        d = out / "a/meet/flow/bs101"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{v}.html").write_text(app_doc(css, js, None), encoding="utf-8")
    if not a.shots:
        return 0
    if not pathlib.Path(CHROME).exists():
        print("no Chrome at " + CHROME, file=sys.stderr)
        return 2
    # his phone: his own chrome above and under the page (393 × 851 at his 1.5); the phone alone; a desktop
    views = {"his": (393, 851, 1.5), "phone": (390, 844, 3), "desk": (1440, 900, 1)}
    plan = []
    for frame, _, _ in FRAMES[1:]:
        for view in views:
            for theme in ("light", "dark"):
                plan.append((frame, "after", view, theme, "half", ""))
        plan.append((frame, "before", "his", "dark", "half", ""))   # the before: as he saw it (his phone, dark)
    plan += [("transcribing", "after", "his", "dark", "full", ""), ("transcribing", "after", "his", "dark", "peek", ""),
             ("ready", "after", "his", "dark", "half", "task"), ("ready", "after", "his", "dark", "full", "ov")]
    shots = []
    harness_uri = (out / "meet-flow-mock.html").resolve().as_uri()
    for frame, v, view, theme, snap, tab in plan:
        w, h, dsf = views[view]
        name = f"{frame}-{view}-{theme}{'' if v == 'after' else '-before'}{'' if snap == 'half' else '-' + snap}{'-' + tab if tab else ''}.png"
        url = f"{harness_uri}?shot=1&frame={frame}&variant={v}&view={view}&theme={theme}&sheet={snap}&v={tab}"
        for attempt in (1, 2, 3):                          # a headless Chrome now and then exits 2 on its own: again
            run = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                                  "--allow-file-access-from-files", f"--force-device-scale-factor={dsf}", f"--window-size={w},{h}",
                                  "--virtual-time-budget=8000", f"--screenshot={out / name}", url],
                                 capture_output=True, timeout=120)
            if run.returncode == 0 and (out / name).exists():
                shots.append(name)
                print(name, flush=True)
                break
        else:
            print(f"{name}: Chrome failed ({run.returncode}): {run.stderr.decode(errors='replace')[-300:]}", file=sys.stderr, flush=True)
    print(f"{len(shots)} shots in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
