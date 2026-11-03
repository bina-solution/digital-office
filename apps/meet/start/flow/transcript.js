/* «פגישות» — transcript.js: every line of a meeting, following the player. A person can search it, show one
   speaker, correct a line (the machine's words stay one click away, with who changed them and when — the
   correction never erases its source), copy a link to a moment, and turn a moment into a task. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Transcript = function Transcript(el, ctx) {
    const { esc, fmt, ic } = MF;
    const { M, stage, room, hue } = ctx;
    const turns = stage ? stage.turns : (M.turns || []).concat((M.tail || []).map((x) => ({ ...x, tail: true })));
    const edits = ctx.edits || {};                      // target → the newest edit {after, before, by, at}
    const versions = ctx.versions || {};                // target → every correction of the line, oldest first (CHAT-63)
    const textOf = (x) => (edits[x.id] ? edits[x.id].after : x.text);
    const offs = [];
    const on = (n, ev, fn, o) => { n.addEventListener(ev, fn, o); offs.push(() => n.removeEventListener(ev, fn, o)); };
    const people = [...new Set(turns.map((x) => x.who).filter(Boolean))];
    const NOBODY = new Set(["?", "כתוביות", "משתתף"]);
    const names = () => [...new Set((ctx.people || []).concat(turns.map((x) => x.who)).filter((w) => w && !NOBODY.has(w)))];
    const doubt = (x) => { const low = new Set(x.low); return String(x.text).split(/\s+/).map((w, k) => (low.has(k) ? `<span class="mf-low" title="המזהה לא היה בטוח במילה הזו">${esc(w)}</span>` : esc(w))).join(" "); };
    const unsure = (s) => esc(s).replace(/\[\?\]/g, '<span class="mf-unsure" title="המילה לא נשמעה בוודאות">[?]</span>')
      .replace(/\[לא ברור\]/g, '<span class="mf-unsure" title="קטע שלא נשמע">[לא ברור]</span>');

    el.innerHTML = `
      <div class="mf-tr-bar">
        <label class="mf-find"><span class="mf-vh">חיפוש בתמלול</span>${ic("search")}<input type="search" placeholder="חיפוש במה שנאמר" autocomplete="off" enterkeyhint="search"><output class="mf-find-n" aria-live="polite"></output></label>
        <span class="mf-find-nav"><button class="mf-tb sm" type="button" data-hit="-1" title="הקודם" aria-label="התוצאה הקודמת" disabled>${ic("chevronR")}</button><button class="mf-tb sm" type="button" data-hit="1" title="הבא" aria-label="התוצאה הבאה" disabled>${ic("chevronL")}</button></span>
        ${ctx.onExport ? `<button class="mf-tb sm mf-expbtn" type="button" title="התמלול כקובץ — טקסט, VTT או SRT, עם כל התיקונים" aria-label="הורדת התמלול">${ic("download")}</button>` : ""}
        ${turns.some((x) => x.alts || (x.flags || []).length) ? `<button class="mf-tb sm mf-origbtn" type="button" aria-pressed="false" title="להציג ליד כל שורה מה כל מזהה דיבור שמע, והערות הבדיקה">${ic("layers")}<span>מקור</span></button>` : ""}
      </div>
      ${people.length > 1 ? `<div class="mf-who-filter" role="group" aria-label="להציג דובר">${people.map((w) => `<button type="button" class="mf-chip" data-who="${esc(w)}" aria-pressed="false">${MF.avatar(w, hue(w))}<bdi>${esc(w)}</bdi></button>`).join("")}</div>` : ""}
      <div class="mf-tr-list" role="list"></div>
      <button class="mf-backnow" type="button" hidden>${ic("target")}<span>חזרה לרגע המתנגן</span></button>`;
    const list = el.querySelector(".mf-tr-list"), input = el.querySelector("input[type=search]"), count = el.querySelector(".mf-find-n");
    const backNow = el.querySelector(".mf-backnow");
    const orig = el.querySelector(".mf-origbtn");
    const exp = el.querySelector(".mf-expbtn");
    if (exp) on(exp, "click", () => ctx.onExport());
    if (orig) on(orig, "click", () => { const v = orig.getAttribute("aria-pressed") !== "true"; orig.setAttribute("aria-pressed", v); el.classList.toggle("showorig", v); showOrig = v; const c = cur; render(); cur = -1; markNow(c, -1, true); });

    /* ---------- the lines ---------- */
    function row(x, i) {
      const tx = textOf(x), e = edits[x.id];
      const gone = (x.flags || []).some((f) => /moved/.test(f)) ? "המילים של השורה עברו לשורה הסמוכה" : "שורה שנמחקה בבדיקה";
      const alts = !showOrig ? "" : x.alts ? Object.entries(x.alts).map(([k, v]) => `<div class="mf-alt"><b dir="ltr">${esc(k)}</b> <span dir="auto">${esc(v)}</span></div>`).join("") : "";
      return `<div class="mf-line${x.tail ? " tail" : ""}${e ? " edited" : ""}" role="listitem" data-i="${i}" data-id="${esc(x.id || "")}" data-who="${esc(x.who || "")}" style="--c:var(--${hue(x.who)})">
        <button class="mf-t" type="button" data-seek="${x.s}" title="לנגן מכאן"><time dir="ltr">${fmt(x.s, stage && stage.DUR >= 3600)}</time></button>
        <div class="mf-line-b">
          <div class="mf-line-h"><button class="mf-who" type="button" data-act="who" data-hue="${esc(hue(x.who))}" title="${esc(x.whoWas ? `הדובר תוקן (המכונה: ${x.whoWas}) — לשנות` : "מי אמר את זה? — לבחור דובר")}" aria-label="${esc(`הדובר: ${x.who || "לא ידוע"} — לשנות`)}"><bdi>${esc(x.who || "?")}</bdi>${x.whoWas ? ic("edit") : ""}</button>${e ? `<span class="mf-edited" title="${esc(`תוקן בידי ${e.by && (e.by.name || e.by.username) || "?"} · ${MF.ago(e.at)}`)}">${ic("edit")}תוקן</span>` : ""}${x.tail ? '<span class="mf-tag">אחרי השיחה</span>' : ""}
            <span class="mf-line-acts"><button class="mf-tb xs" type="button" data-act="edit" title="לתקן את השורה" aria-label="לתקן">${ic("edit")}</button>${(versions[x.id] || []).length ? `<button class="mf-tb xs" type="button" data-act="vers" title="כל הגרסאות של השורה" aria-label="גרסאות השורה">${ic("history")}</button>` : ""}<button class="mf-tb xs" type="button" data-act="link" title="להעתיק קישור לרגע הזה" aria-label="קישור לרגע">${ic("link")}</button><button class="mf-tb xs" type="button" data-act="task" title="משימה מהרגע הזה" aria-label="משימה מכאן">${ic("task")}</button></span></div>
          <p class="mf-tx"${MF.dirAttr(tx)}>${tx ? (!e && x.low && x.low.length ? doubt(x) : unsure(tx)) : `<span class="muted">${gone}</span>`}</p>
          ${e ? `<div class="mf-was"><span class="k">היה כתוב</span> <span dir="auto">${esc(e.before)}</span></div>` : ""}
          ${showOrig && (alts || (x.flags || []).length) ? `<div class="mf-alts">${alts}${(x.flags || []).map((f) => `<div class="mf-flag" dir="auto">${esc(f)}</div>`).join("")}</div>` : ""}
        </div>
      </div>`;
    }
    let tailHead = -1, showOrig = false;
    function render() {
      tailHead = turns.findIndex((x) => x.tail);
      list.innerHTML = turns.map((x, i) => (i === tailHead ? `<div class="mf-divider" role="separator"><span>אחרי שהשיחה בווידאו נגמרה — מהקלטה נוספת</span></div>` : "") + row(x, i)).join("")
        || `<div class="mf-empty">${ic("message")}<p>אין עוד שורות בתמלול.</p></div>`;
      applyFilter();
    }

    /* ---------- following the player ---------- */
    let follow = true, cur = -1, userScroll = 0;
    const centerIn = (n, smooth) => {
      if (!n) return;
      const box = list.closest(".mf-pane") || list;
      const r = n.getBoundingClientRect(), b = box.getBoundingClientRect();
      const top = box.scrollTop + (r.top - b.top) - (box.clientHeight - r.height) / 2;
      programmatic = Date.now();
      box.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
    };
    let programmatic = 0;
    const paneOf = () => list.closest(".mf-pane") || list;
    function markNow(i, word, jump) {
      if (i !== cur) {
        list.querySelector(".mf-line.cur")?.classList.remove("cur");
        cur = i;
        const n = list.querySelector(`.mf-line[data-i="${i}"]`);
        if (n) { n.classList.add("cur"); if (follow && el.offsetParent) centerIn(n, !jump); }
      }
    }
    if (stage) offs.push(stage.onTime((s) => { if (s.playing || s.jump) markNow(s.i, s.word, s.jump); }));
    const pane = () => paneOf();
    const onScroll = () => {
      if (Date.now() - programmatic < 700 || !stage || !stage.playing) return;
      if (follow) { follow = false; backNow.hidden = false; }
    };
    setTimeout(() => on(pane(), "scroll", onScroll, { passive: true }), 0);
    on(backNow, "click", () => { follow = true; backNow.hidden = true; centerIn(list.querySelector(".mf-line.cur"), true); });

    /* ---------- search and the speaker filter ---------- */
    let hits = [], hitAt = -1, onlyWho = new Set();
    function applyFilter() {
      const qn = MF.norm(input.value.trim());
      const words = qn.split(/\s+/).filter(Boolean);
      hits = [];
      for (const n of list.querySelectorAll(".mf-line")) {
        const x = turns[+n.dataset.i], tx = textOf(x) || "";
        const whoOk = !onlyWho.size || onlyWho.has(x.who);
        const hit = !words.length || words.every((w) => MF.norm(tx).includes(w));
        n.hidden = !(whoOk && hit && (tx || !words.length));
        const p = n.querySelector(".mf-tx");
        if (words.length && hit && whoOk && tx) {
          hits.push(n);
          let h = unsure(tx);
          for (const w of words) h = markWord(h, w);
          p.innerHTML = h;
        } else if (p.dataset.marked) { p.innerHTML = tx ? unsure(tx) : p.innerHTML; }
        if (words.length) p.dataset.marked = "1"; else delete p.dataset.marked;
      }
      const d = list.querySelector(".mf-divider"); if (d) d.hidden = !!(words.length || onlyWho.size) && !hits.some((n) => turns[+n.dataset.i].tail);
      count.textContent = words.length ? (hits.length ? `${MF.num(hits.length)} שורות` : "לא נמצא") : "";
      el.querySelectorAll("[data-hit]").forEach((b) => { b.disabled = hits.length < 2; });
      hitAt = -1;
      if (!words.length && !onlyWho.size) setTimeout(() => centerIn(list.querySelector(".mf-line.cur"), false), 0);
    }
    // a word of the search, marked inside text that is already escaped (niqqud and final letters ignored)
    function markWord(html, w) {
      const parts = html.split(/(<[^>]+>)/);
      return parts.map((p) => {
        if (p.startsWith("<")) return p;
        const n = MF.norm(p); let out = "", from = 0, at;
        if (n.length !== p.length) return p;           // niqqud moved the letters: the line still counts, unmarked
        while ((at = n.indexOf(w, from)) >= 0) { out += p.slice(from, at) + "<mark>" + p.slice(at, at + w.length) + "</mark>"; from = at + w.length; }
        return out + p.slice(from);
      }).join("");
    }
    let qTimer = 0;
    on(input, "input", () => { clearTimeout(qTimer); qTimer = setTimeout(applyFilter, 120); });
    on(input, "keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); } if (e.key === "Escape") { input.value = ""; applyFilter(); } });
    function step(d) {
      if (!hits.length) return;
      hitAt = (hitAt + d + hits.length) % hits.length;
      const n = hits[hitAt]; centerIn(n, true);
      list.querySelector(".mf-line.hitcur")?.classList.remove("hitcur"); n.classList.add("hitcur");
      count.textContent = `${MF.num(hitAt + 1)} מתוך ${MF.num(hits.length)}`;
      if (stage) stage.seek(turns[+n.dataset.i].s);
    }
    el.querySelectorAll("[data-hit]").forEach((b) => on(b, "click", () => step(+b.dataset.hit)));
    const wf = el.querySelector(".mf-who-filter");
    if (wf) on(wf, "click", (e) => {
      const b = e.target.closest("[data-who]"); if (!b) return;
      const w = b.dataset.who; onlyWho.has(w) ? onlyWho.delete(w) : onlyWho.add(w);
      b.setAttribute("aria-pressed", onlyWho.has(w)); applyFilter();
    });

    /* ---------- a line's own actions: play from here, correct it, link to it, a task from it ---------- */
    on(list, "click", async (e) => {
      const t = e.target.closest("[data-seek]");
      if (t) { if (stage) { stage.seek(+t.dataset.seek); if (!stage.playing) stage.play(); } return; }
      const a = e.target.closest("[data-act]"); if (!a) return;
      const n = a.closest(".mf-line"), x = turns[+n.dataset.i];
      if (a.dataset.act === "link") MF.copy(location.origin + MF.roomUrl(room) + "#t" + Math.floor(x.s), "הקישור לרגע הועתק");
      else if (a.dataset.act === "edit") editLine(n, x);
      else if (a.dataset.act === "who") pickWho(n, x);
      else if (a.dataset.act === "vers") showVersions(n, x);
      else if (a.dataset.act === "task" && ctx.onTaskFrom) ctx.onTaskFrom(x, textOf(x));
    });

    /* ---------- who said it: the speaker of a line, corrected by a person (CHAT-63) ---------- */
    function closePanels(n) { n.querySelectorAll(".mf-whopick, .mf-vers").forEach((p) => p.remove()); }
    function pickWho(n, x) {
      if (!x.id) { MF.tell("לשורה הזו אין מזהה — אי אפשר לשמור תיקון", "warn"); return; }
      if (n.querySelector(".mf-whopick")) { closePanels(n); return; }
      closePanels(n);
      const all = names();
      n.querySelector(".mf-line-h").insertAdjacentHTML("afterend", `<div class="mf-whopick" role="group" aria-label="מי אמר את השורה">
        <span class="muted small">מי אמר את זה?</span>
        ${all.map((w) => `<button type="button" class="mf-chip" data-pick="${esc(w)}" aria-pressed="${w === x.who}">${MF.avatar(w, hue(w))}<bdi>${esc(w)}</bdi></button>`).join("")}
        <button type="button" class="mf-chip" data-pick-other>${ic("user")}<span>מישהו אחר…</span></button>
        ${x.whoWas ? `<button type="button" class="mf-chip" data-pick="${esc(x.whoWas)}" title="מה שהמכונה כתבה">${ic("history")}<span>כמו שהיה: <bdi>${esc(x.whoWas)}</bdi></span></button>` : ""}</div>`);
      const box = n.querySelector(".mf-whopick");
      box.querySelector("button").focus();
      box.addEventListener("click", async (ev) => {
        const b = ev.target.closest("[data-pick], [data-pick-other]"); if (!b) return;
        let name = b.dataset.pick;
        if (b.hasAttribute("data-pick-other")) {
          name = await MF.ask({ title: "מי אמר את השורה?", ok: "שמירה", input: { label: "שם הדובר", value: "" } });
          if (name == null || name === false) return;
          name = String(name).trim();
          if (!name) { MF.tell("צריך לכתוב שם", "warn"); return; }
        }
        if (name === x.who) { closePanels(n); return; }
        await setWho(n, x, name);
      });
    }
    async function setWho(n, x, name) {
      const before = x.who || "";
      try {
        await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "speaker", target: x.id, before, after: name } });
      } catch (err) { MF.tell(err.message || "השמירה נכשלה", "bad"); return; }
      if (x.whoWas == null) x.whoWas = before;
      x.who = name;
      if (x.who === x.whoWas) delete x.whoWas;
      const i = +n.dataset.i;
      n.outerHTML = row(x, i);
      applyFilter();
      if (ctx.onSpeaker) ctx.onSpeaker(x);
      MF.tell(`הדובר נשמר: ${name}`, "ok", { act: ["ביטול", () => { const m = list.querySelector(`.mf-line[data-i="${i}"]`); if (m) setWho(m, x, before); }] });
    }

    /* ---------- every version of a line: the machine's, and each correction — any of them restored (CHAT-63) ---------- */
    function showVersions(n, x) {
      if (n.querySelector(".mf-vers")) { closePanels(n); return; }
      closePanels(n);
      const now = textOf(x) || "";
      const vs = [{ text: x.text || "", who: "המכונה", at: null, machine: true }].concat((versions[x.id] || []).map((e) => ({ text: e.after, who: (e.by && (e.by.name || e.by.username)) || "?", at: e.at })));
      n.querySelector(".mf-line-b").insertAdjacentHTML("beforeend", `<div class="mf-vers" role="list" aria-label="גרסאות השורה">
        ${vs.slice().reverse().map((v, k) => `<div class="mf-ver${v.text === now ? " cur" : ""}" role="listitem"><div class="mf-ver-h"><b>${esc(v.machine ? "מה שהמכונה כתבה" : v.who)}</b>${v.at ? `<span class="muted small">${esc(MF.ago(v.at))}</span>` : ""}${v.text === now ? '<span class="mf-tag" data-tone="ok">מוצגת עכשיו</span>' : `<button class="btn sm ghost" type="button" data-restore="${vs.length - 1 - k}">${ic("history")}<span>שחזור</span></button>`}</div><p dir="auto">${v.text ? esc(v.text) : '<span class="muted">(שורה ריקה)</span>'}</p></div>`).join("")}</div>`);
      n.querySelector(".mf-vers").addEventListener("click", async (ev) => {
        const b = ev.target.closest("[data-restore]"); if (!b) return;
        const v = vs[+b.dataset.restore];
        b.disabled = true;
        try {
          const r = await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "line", target: x.id, before: now, after: v.text } });
          const ed = r && r.edit ? r.edit : { after: v.text, before: now, at: Date.now() / 1000, by: MF.cfg.me };
          (versions[x.id] = versions[x.id] || []).push(ed);
          if (v.text === x.text) delete edits[x.id]; else edits[x.id] = ed;
          const i = +n.dataset.i; n.outerHTML = row(x, i); applyFilter();
          if (ctx.onEdit) ctx.onEdit(x);
          MF.tell("הגרסה שוחזרה", "ok");
        } catch (err) { b.disabled = false; MF.tell(err.message || "השחזור נכשל", "bad"); }
      });
    }
    on(list, "dblclick", (e) => { const n = e.target.closest(".mf-line"); if (n && e.target.closest(".mf-tx")) editLine(n, turns[+n.dataset.i]); });
    function editLine(n, x) {
      if (!x.id) { MF.tell("לשורה הזו אין מזהה — אי אפשר לשמור תיקון", "warn"); return; }
      if (n.querySelector(".mf-edit")) return;
      const p = n.querySelector(".mf-tx"), before = textOf(x) || "";
      p.hidden = true;
      p.insertAdjacentHTML("afterend", `<div class="mf-edit"><textarea rows="2" dir="auto" aria-label="התיקון">${esc(before)}</textarea>
        <div class="mf-edit-acts"><button class="btn sm" type="button" data-e="save">שמירה</button><button class="btn sm ghost" type="button" data-e="cancel">ביטול</button><span class="muted small">Ctrl+Enter לשמירה · Esc לביטול</span></div></div>`);
      const box = n.querySelector(".mf-edit"), ta = box.querySelector("textarea");
      const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + 2 + "px"; };
      grow(); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
      ta.addEventListener("input", grow);
      const close = () => { box.remove(); p.hidden = false; };
      const save = async () => {
        const after = ta.value.trim();
        if (after === before.trim()) { close(); return; }
        const btn = box.querySelector('[data-e="save"]'); btn.disabled = true; btn.classList.add("busy");
        try {
          const r = await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "line", target: x.id, before: x.text || "", after } });
          edits[x.id] = r && r.edit ? r.edit : { after, before: x.text, at: Date.now() / 1000, by: MF.cfg.me };
          (versions[x.id] = versions[x.id] || []).push(edits[x.id]);
          const i = +n.dataset.i;
          n.outerHTML = row(x, i);
          MF.tell("התיקון נשמר", "ok", { act: ["ביטול", () => undo(x, before)] });
          if (ctx.onEdit) ctx.onEdit(x);
          applyFilter();
        } catch (err) {
          btn.disabled = false; btn.classList.remove("busy");
          MF.tell(err.message || "השמירה נכשלה", "bad", { more: err.doc ? JSON.stringify(err.doc) : "" });
        }
      };
      box.addEventListener("click", (ev) => { const b = ev.target.closest("[data-e]"); if (!b) return; b.dataset.e === "save" ? save() : close(); });
      ta.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); save(); } else if (ev.key === "Escape") { ev.preventDefault(); close(); } });
    }
    async function undo(x, text) {
      try {
        const r = await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "line", target: x.id, before: textOf(x) || "", after: text } });
        edits[x.id] = r && r.edit ? r.edit : edits[x.id];
        if (r && r.edit) (versions[x.id] = versions[x.id] || []).push(r.edit);
        if ((edits[x.id] || {}).after === x.text) delete edits[x.id];
        render(); if (ctx.onEdit) ctx.onEdit(x);
      } catch (err) { MF.tell(err.message, "bad"); }
    }

    render();
    return {
      el, refresh: render, focusSearch() { input.focus(); input.select(); },
      setQuery(v) { input.value = v || ""; applyFilter(); if (hits.length) step(1); },
      destroy() { for (const f of offs) f(); },
    };
  };
})();
