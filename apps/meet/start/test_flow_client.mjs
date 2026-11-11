// The meeting page's status line (DGO-1325): status.js says what is being done to a meeting in one Hebrew sentence and
// one number, and why the transcript is empty and when it comes; and the two bundles the page loads are their sources.
// bs101 (2026-11-03) on vps1 is the case: no live captions on 2 cores, the ivrit pass 97 minutes, whisper after it.
//   node apps/meet/start/test_flow_client.mjs
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const S = require(path.join(here, "flow/status.js"));
const now = 1793702752;                                    // 2026-11-03T12:25:52Z — the minute of his screenshot
const DUR = 5761;
const why = "לשרת המשרד יש 2 ליבות, וכתוביות חיות צריכות 4";
const rec = { key: "record", state: "done", detail: "312 MB · 1:36:01" };
const cap = { key: "captions", state: "off", detail: "לא היו כתוביות חיות", why };
const later = (key) => ({ key, state: "waiting", detail: "אחרי «קדימה» — העיבוד המלא" });
const review = { key: "review", state: "waiting", detail: "עוד לא נבדק" };
const first = (ivrit, whisper, counts) => ({ state: "first", counts: counts || {}, stages: [rec, cap, ivrit, whisper || { key: "whisper", state: "waiting", detail: "" }, later("speakers"), later("summary"), review] });
let n = 0;
const t = (name, f) => { f(); n++; console.log("ok", name); };

t("transcribing: how far, until when, and why there are no captions", () => {
  const s = S.status(first({ key: "ivrit", state: "running", detail: "40:24 מתוך 1:36:01", pct: 42.1, done_s: 2424, audio_s: DUR, eta: now + 3304 }), now);
  assert.equal(s.tone, "sky");
  assert.equal(s.icon, "spin");
  assert.equal(s.text, `מתמלל את הפגישה · צפוי ~${S.at(now + 3304, now)}`);
  assert.equal(s.num, "42%");
  assert.equal(s.pct, 42.1);
  assert.match(s.sub, /ivrit · 40:24 מתוך 1:36:01/);
  assert.match(s.sub, new RegExp(`בלי כתוביות חיות: ${why}`));
  assert.equal(s.empty.title, "התמלול בדרך");
  assert.match(s.empty.body, new RegExp(`^בפגישה הזו לא היו כתוביות חיות: ${why}\\.`));
  assert.match(s.empty.body, /42%, צפוי להסתיים בסביבות \d\d:\d\d\. השורות יופיעו כאן לבד, בלי לרענן\.$/);
});

t("queued: who is before it and when it ends", () => {
  const s = S.status(first({ key: "ivrit", state: "waiting", detail: "בתור — לפניה 1", ahead: 1, eta: now + 7600 }), now);
  assert.equal(s.tone, "lime");
  assert.equal(s.text, `בתור לתמלול · צפוי ~${S.at(now + 7600, now)}`);
  assert.equal(s.num, "פגישה אחת לפניה");
  assert.match(s.empty.body, /התמלול המלא ממתין בתור \(לפניו פגישה אחת\), וצפוי להסתיים בסביבות \d\d:\d\d\./);
});

t("just ended: the transcription not sent yet", () => {
  const s = S.status(first({ key: "ivrit", state: "waiting", detail: "עוד לא נשלח — המערכת שולחת הקלטה חדשה תוך דקות" }), now);
  assert.equal(s.tone, "lime");
  assert.equal(s.text, "התמלול יתחיל בדקות הקרובות");
  assert.match(s.empty.body, /התמלול המלא ממתין ויתחיל בדקות הקרובות\./);
});

t("transcribed: the lines are there, the topics wait for a person («קדימה»)", () => {
  const s = S.status(first({ key: "ivrit", state: "done", detail: "935 קטעים" }, { key: "whisper", state: "running", pct: 17.9, eta: now + 4500 }, { lines: 935 }), now);
  assert.equal(s.tone, "violet");
  assert.equal(s.text, "התמלול מוכן — הנושאים והמשימות מחכים ל«קדימה»");
  assert.equal(s.num, "935 שורות");
  assert.match(s.sub, /^Whisper: 17%/);
});

t("ready and reviewed", () => {
  const ready = (proposed) => ({ state: "ready", counts: { decisions: 13, tasks: 6, questions: 2, proposed, lines: 934 }, stages: [rec, cap] });
  let s = S.status(ready(11), now);
  assert.deepEqual([s.tone, s.text, s.num], ["violet", "מעובדת — 11 פריטים מחכים לאישור", "11"]);
  assert.equal(s.sub, "13 החלטות · 6 משימות · 2 שאלות");
  s = S.status(ready(1), now);
  assert.equal(s.text, "מעובדת — פריט אחד מחכה לאישור");
  s = S.status(ready(0), now);
  assert.equal(s.tone, "olive");
  s = S.status({ state: "reviewed", stages: [] }, now);
  assert.equal(s.tone, "olive");
});

t("failed: which step, and why", () => {
  const s = S.status(first({ key: "ivrit", state: "failed", detail: "נכשל ב-13:50", why: "התור של המתמלל היה מלא. ייעשה ניסיון נוסף בסבב הבא של המערכת (תוך כמה דקות)" }), now);
  assert.equal(s.tone, "plum");
  assert.equal(s.text, "תמלול עברי נכשל — התור של המתמלל היה מלא. ייעשה ניסיון נוסף בסבב הבא של המערכת (תוך כמה דקות)");
  assert.equal(s.empty.title, "התמלול נכשל");
});

t("live and before", () => {
  let s = S.status({ state: "live", started_ts: now - 600, stages: [{ key: "record", state: "running" }, { key: "captions", state: "off", why }] }, now);
  assert.deepEqual([s.tone, s.icon, s.text, s.num], ["sky", "live", "בשידור · מוקלטת", "10:00"]);
  assert.equal(s.sub, `בלי כתוביות חיות: ${why}`);
  s = S.status({ state: "before", stages: [] }, now);
  assert.equal(s.tone, "muted");
});

t("the meeting's own state comes first, and why a pass waits is said as the server codes it", () => {
  // a meeting processed before 2026-11-02: its flow has no transcript step, and its passes are no longer listed
  let s = S.status({ state: "ready", counts: { proposed: 0 }, stages: [rec, cap, { key: "ivrit", state: "waiting", code: "not-sent" }] }, now);
  assert.equal(s.tone, "olive");
  // a second pass that failed is a note, never the headline of a processed meeting
  s = S.status({ state: "ready", counts: { proposed: 2 }, stages: [rec, cap, { key: "ivrit", state: "done" }, { key: "whisper", state: "failed", why: "התור היה מלא" }] }, now);
  assert.equal(s.tone, "violet");
  s = S.status(first({ key: "ivrit", state: "done" }, { key: "whisper", state: "failed", why: "התור היה מלא" }, { lines: 935 }), now);
  assert.deepEqual([s.tone, s.text], ["violet", "התמלול מוכן — הנושאים והמשימות מחכים ל«קדימה»"]);
  assert.match(s.sub, /^Whisper נכשל: התור היה מלא/);
  s = S.status(first({ key: "ivrit", state: "waiting", code: "no-answer", detail: "המתמלל לא ענה עכשיו" }), now);
  assert.equal(s.text, "המתמלל לא ענה — הדף שואל שוב");
  assert.equal(s.empty.title, "המתמלל לא ענה עכשיו");
  s = S.status(first({ key: "ivrit", state: "off", code: "missing", why: "המתמלל לא מכיר את ההקלטה הזו" }), now);
  assert.deepEqual([s.tone, s.text], ["lime", "התמלול לא נמצא אצל המתמלל"]);
  assert.equal(s.empty.title, "אין תמלול לפגישה הזו");
  s = S.status(first({ key: "ivrit", state: "off", code: "quiet", why: "הקלטת בדיקה לא נשלחת לתמלול" }), now);
  assert.equal(s.text, "הקלטת בדיקה — לא נשלחת לתמלול");
});

t("every step has a Hebrew name and a Hebrew state", () => {
  const s = S.status(first({ key: "ivrit", state: "running", pct: 1, eta: now + 60 }), now);
  for (const x of s.steps) {
    assert.ok(/[א-ת]/.test(x.he), x.key);
    assert.ok(/[א-ת]/.test(x.word), x.key);
  }
  assert.deepEqual(s.steps.map((x) => x.key), ["record", "captions", "ivrit", "whisper", "speakers", "summary", "review"]);
});

t("the bundles are their sources, and status.js and sheet.js are in them after core.js", () => {
  execFileSync("sh", [path.join(here, "flow/build.sh"), "--check"], { stdio: "pipe" });
  const js = readFileSync(path.join(here, "flow/mf.js"), "utf8");
  const at = (s) => js.indexOf(s);
  assert.ok(at("«פגישות» — core.js") >= 0 && at("«פגישות» — core.js") < at("«פגישות» — status.js"));
  assert.ok(at("«פגישות» — status.js") < at("«פגישות» — sheet.js"));
  assert.ok(at("«פגישות» — sheet.js") < at("«פגישות» — meeting.js"));
});

console.log(`${n} passed`);
