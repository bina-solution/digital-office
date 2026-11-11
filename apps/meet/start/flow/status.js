/* «פגישות» — status.js: what is happening to a meeting, in ONE Hebrew sentence and one number, and why (DGO-1325).
   The owner, 2026-11-03: «שאני אוכל לראות מה בדיוק קורה ולמה אני לא מקבל עדיין כתוביות». Pure: it reads the
   meeting as meeting.json says it (its state, and each step's state, detail, progress and expected end, which the
   server measures) and returns the words. No page, no fetch — so node tests it (apps/meet/start/test_flow_client.mjs).
   The palette's legend: sky = in motion · lime = it waits, look here · olive = done · violet = needs a person ·
   plum = failed. */
(function (root) {
  "use strict";
  const OFFICE_TZ = "Asia/Jerusalem";
  const STEP = {
    record: "הקלטה", captions: "כתוביות חיות", ivrit: "תמלול עברי", whisper: "תמלול שני (Whisper)",
    speakers: "מי אמר מה", summary: "נושאים · החלטות · משימות", review: "בדיקה של אדם",
    // the keys of a meeting processed before 2026-11-05 (its flow folder's own stages)
    first: "עיבוד ראשון", best: "תמלול מלא",
  };
  const STATE_WORD = { done: "הושלם", running: "רץ עכשיו", waiting: "ממתין", off: "לא פעיל", failed: "נכשל" };
  // why a pass waits or is off, as the server codes it (server.py flow_stages), in the status line's words
  const WAIT_SAYS = { "not-sent": "התמלול יתחיל בדקות הקרובות", "no-answer": "המתמלל לא ענה — הדף שואל שוב", recording: "ההקלטה נסגרת — התמלול יתחיל מיד אחריה" };
  const OFF_SAYS = { quiet: "הקלטת בדיקה — לא נשלחת לתמלול", missing: "התמלול לא נמצא אצל המתמלל" };

  const pad = (n) => String(n).padStart(2, "0");
  // 0:12:34 or 12:34 — a length of time
  function len(t) {
    t = Math.max(0, Math.floor(+t || 0));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }
  // 15:40 (the office's wall clock), with the day when it is not today
  function at(ts, now) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    let hm;
    try { hm = new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d); }
    catch (e) { hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`; }
    const day = (x) => { try { return new Intl.DateTimeFormat("en-CA", { timeZone: OFFICE_TZ }).format(x); } catch (e) { return x.toDateString(); } };
    if (day(d) === day(new Date((now || Date.now() / 1000) * 1000))) return hm;
    if (day(d) === day(new Date(((now || Date.now() / 1000) + 86400) * 1000))) return `מחר ${hm}`;
    return `${hm} (${new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, day: "numeric", month: "numeric" }).format(d)})`;
  }
  const num = (n) => { try { return new Intl.NumberFormat("he-IL").format(+n || 0); } catch (e) { return String(+n || 0); } };

  /* the steps, as the page lists them: each with its Hebrew name, its state's word, and what it says */
  function steps(info) {
    return (info.stages || []).map((x) => ({
      key: x.key, he: STEP[x.key] || x.key, state: x.state, word: STATE_WORD[x.state] || x.state,
      detail: x.detail || "", why: x.why || "", pct: x.pct == null ? null : +x.pct, eta: x.eta || null,
      since: x.since || null, done_s: x.done_s == null ? null : +x.done_s, audio_s: x.audio_s == null ? null : +x.audio_s,
      ahead: x.ahead || 0, code: x.code || "",
    }));
  }

  /* what the transcript pane says while it has no line: why, and when the lines come */
  function emptyOf(info, st, now) {
    const by = Object.fromEntries(st.map((x) => [x.key, x]));
    const cap = by.captions, iv = by.ivrit || by.best;
    const why = cap && cap.state !== "done" && cap.state !== "running" && cap.why ? `בפגישה הזו לא היו כתוביות חיות: ${cap.why}.` : "";
    if (info.state === "before") return { title: "הפגישה עוד לא התחילה", body: "כשהיא תתחיל, מה שנאמר יופיע כאן." };
    if (info.state === "live") return { title: "מחכים למילים הראשונות", body: why || "השורות מופיעות כאן כשמישהו מדבר." };
    if (!iv) return { title: "אין עוד שורות בתמלול", body: why };
    if (iv.state === "running") {
      return { title: "התמלול בדרך", body: `${why ? why + " " : ""}התמלול המלא רץ עכשיו — ${num(Math.floor(iv.pct || 0))}%${iv.eta ? `, צפוי להסתיים בסביבות ${at(iv.eta, now)}` : ""}. השורות יופיעו כאן לבד, בלי לרענן.` };
    }
    if (iv.state === "waiting" && iv.code === "no-answer") {
      return { title: "המתמלל לא ענה עכשיו", body: `${why ? why + " " : ""}הדף שואל אותו שוב כל 15 שניות, והשורות יופיעו כאן לבד, בלי לרענן.` };
    }
    if (iv.state === "waiting" && iv.code === "recording") {
      return { title: "ההקלטה נסגרת", body: `${why ? why + " " : ""}התמלול יתחיל מיד אחריה, והשורות יופיעו כאן לבד.` };
    }
    if (iv.state === "waiting") {
      const queue = iv.ahead ? `ממתין בתור (לפניו ${iv.ahead === 1 ? "פגישה אחת" : `${num(iv.ahead)} פגישות`})` : "ממתין";
      const when = iv.eta ? `, וצפוי להסתיים בסביבות ${at(iv.eta, now)}` : " ויתחיל בדקות הקרובות";
      return { title: "התמלול ממתין", body: `${why ? why + " " : ""}התמלול המלא ${queue}${when}. השורות יופיעו כאן לבד, בלי לרענן.` };
    }
    if (iv.state === "failed") return { title: "התמלול נכשל", body: `${why ? why + " " : ""}${iv.why || iv.detail || ""}` };
    if (iv.state === "off") return { title: "אין תמלול לפגישה הזו", body: [why, iv.why || iv.detail].filter(Boolean).join(" ") };
    return { title: "אין עוד שורות בתמלול", body: why };
  }

  /* the headline: the step that moves now wins, then what waits for a person, then what is done */
  function status(info, now) {
    now = now || Date.now() / 1000;
    const st = steps(info || {});
    const by = Object.fromEntries(st.map((x) => [x.key, x]));
    const c = (info && info.counts) || {};
    const out = { tone: "muted", icon: "clock", text: "", sub: "", num: "", pct: null, steps: st, empty: emptyOf(info || {}, st, now) };
    const set = (tone, icon, text, numText, sub, pct) => Object.assign(out, { tone, icon, text, num: numText || "", sub: sub || "", pct: pct == null ? null : pct });
    const cap = by.captions;
    const capNote = cap && cap.state === "off" && cap.why ? `בלי כתוביות חיות: ${cap.why}` : "";
    const state = (info && info.state) || "";

    if (state === "before") return set("muted", "clock", "הפגישה עוד לא התחילה — תוקלט ותתומלל כשתתחיל");
    if (state === "live") {
      const since = info.started_ts ? len(now - info.started_ts) : "";
      const rec = by.record;
      const recWord = rec && rec.state === "running" ? "מוקלטת" : rec && rec.state === "failed" ? "ההקלטה נכשלה" : rec && rec.state === "waiting" ? "ההקלטה מתחילה" : "לא מוקלטת";
      return set(rec && rec.state === "failed" ? "plum" : "sky", "live", `בשידור · ${recWord}`, since, capNote || (cap && cap.state === "running" ? cap.detail : ""));
    }
    const wh = by.whisper;
    const whNote = wh && wh.state === "running" ? `Whisper: ${num(Math.floor(wh.pct || 0))}%` : wh && wh.state === "failed" ? `Whisper נכשל: ${wh.why || wh.detail}` : "";
    if (state === "first") {
      // the second pass is a help: only a failure of the recording or of the Hebrew pass is the meeting's headline
      const failed = st.find((x) => x.state === "failed" && (x.key === "record" || x.key === "ivrit"));
      if (failed) return set("plum", "alert", `${failed.he} נכשל — ${failed.why || failed.detail || "בלי סיבה ידועה"}`, "", capNote);
      if (by.record && by.record.state === "running") return set("sky", "spin", "ההקלטה נסגרת — התמלול יתחיל מיד אחריה", "", capNote);
      const iv = by.ivrit;
      if (iv && iv.state === "running") {
        const of = iv.done_s != null && iv.audio_s ? `${len(iv.done_s)} מתוך ${len(iv.audio_s)}` : "";
        return set("sky", "spin", `מתמלל את הפגישה${iv.eta ? ` · צפוי ~${at(iv.eta, now)}` : ""}`, `${num(Math.floor(iv.pct || 0))}%`,
          [of && `ivrit · ${of}`, capNote].filter(Boolean).join(" · "), Math.max(0, Math.min(100, iv.pct || 0)));
      }
      if (iv && iv.state === "waiting") {
        const ahead = iv.ahead ? (iv.ahead === 1 ? "פגישה אחת לפניה" : `${num(iv.ahead)} לפניה`) : "";
        const text = iv.eta ? `בתור לתמלול · צפוי ~${at(iv.eta, now)}` : (WAIT_SAYS[iv.code] || "התמלול יתחיל בדקות הקרובות");
        return set("lime", "clock", text, ahead, [iv.code === "no-answer" ? "" : iv.detail, capNote].filter(Boolean).join(" · "));
      }
      if (iv && iv.state === "off") return set("lime", "alert", OFF_SAYS[iv.code] || "אין תמלול לפגישה הזו", "", [iv.why, capNote].filter(Boolean).join(" · "));
      const lines = c.lines || 0;
      return set("violet", "user", "התמלול מוכן — הנושאים והמשימות מחכים ל«קדימה»", lines ? `${num(lines)} שורות` : "", [whNote, capNote].filter(Boolean).join(" · "));
    }
    if (state === "ready") {
      const wait = c.proposed || 0;
      const sum = [c.decisions && `${num(c.decisions)} החלטות`, c.tasks && `${num(c.tasks)} משימות`, c.questions && `${num(c.questions)} שאלות`].filter(Boolean).join(" · ");
      if (wait) return set("violet", "user", `מעובדת — ${wait === 1 ? "פריט אחד מחכה" : `${num(wait)} פריטים מחכים`} לאישור`, num(wait), sum);
      return set("olive", "check", "מעובדת — הכול אושר, מחכה לבדיקה של אדם", "", sum);
    }
    if (state === "reviewed") return set("olive", "check", "נבדקה — התמלול, ההחלטות והמשימות סגורים", "", "");
    return set("muted", "clock", "טוען…");
  }

  const api = { status, steps, emptyOf, STEP, STATE_WORD, len, at };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root && root.MF) { root.MF.status = status; root.MF.STEP = STEP; root.MF.STEP_STATE = STATE_WORD; root.MF.atClock = at; }
})(typeof window !== "undefined" ? window : globalThis);
