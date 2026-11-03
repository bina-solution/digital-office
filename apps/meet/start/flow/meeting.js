/* «פגישות» — meeting.js: ONE address for a meeting's whole life (…/flow/<room>/). Before it starts: what is left
   open from the meeting before it, and the way in. While it runs: what is being said, as it is said, and a button to
   mark a moment. The moment it ends: its recording and its captions. After processing: every word, who said it,
   what was decided and who does what — each on the one time axis, each a click from its moment. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Meeting = function Meeting(app, where) {
    const { esc, ic, fmt } = MF;
    const room = where.room;
    const api = (p) => `flow/${encodeURIComponent(room)}/${p}`;
    const offs = [], timers = [];
    const on = (el, ev, fn, o) => { el.addEventListener(ev, fn, o); offs.push(() => el.removeEventListener(ev, fn, o)); };
    let info = null, M = null, stage = null, tr = null, lists = {}, files = null, items = {}, edits = {}, uploads = [], dead = false;
    let versions = {}, whoEdits = {}, screens = null;    // CHAT-63: every correction of a line; a line's corrected speaker
    let hue = MF.people({});
    const isPhone = () => window.matchMedia("(max-width: 899px)").matches;
    document.title = `${room} · פגישות`;

    app.innerHTML = `<div class="mf-mtg" data-state="loading"><header class="mf-mh"><a class="mf-back" href="${esc(MF.url("flow/"))}" data-go>${ic("chevronR")}<span>פגישות</span></a><div class="mf-mh-t"><h1><bdi>${esc(room)}</bdi></h1><div class="mf-mh-meta"><span class="mf-skel w8"></span></div></div></header><div class="mf-loading" role="status"><span class="mf-spin"></span><span>טוען את הפגישה…</span></div></div>`;

    /* ---------- loading ---------- */
    async function load() {
      try { info = await MF.api(api("meeting.json")); }
      catch (e) { return fail(e); }
      if (dead) return;
      document.title = `${info.title || room} · פגישות`;
      if (info.state === "before") return renderBefore();
      if (info.state === "live") return renderLive();
      if (!info.data) return fail(new MF.Error(404, "לפגישה הזו עוד אין נתונים"));
      try {
        const [m, ed, it] = await Promise.all([
          MF.loadData(info.data),
          MF.api(api("edits")).catch(() => ({ edits: [] })),
          MF.api(api("items")).catch(() => ({ items: {} })),
        ]);
        M = m; items = (it && it.items) || {};
        edits = {}; versions = {}; whoEdits = {};
        for (const e of (ed && ed.edits) || []) {
          if (e.kind === "line") { edits[e.target] = e; (versions[e.target] = versions[e.target] || []).push(e); }
          else if (e.kind === "speaker" && e.after) whoEdits[e.target] = e;
        }
        for (const [k, e] of Object.entries(edits)) if (e.after === e.before) delete edits[k];
        // a corrected speaker is the line's speaker everywhere: the transcript, the axis, who talked how much
        for (const x of (M.turns || []).concat(M.tail || [])) { const w = whoEdits[x.id]; if (w && w.after !== x.who) { x.whoWas = x.who; x.who = w.after; } }
        if (!Array.isArray(M.moments)) M.moments = MF.moments ? MF.moments(M.turns) : [];
        try { const u = await MF.api(api("uploads")); uploads = (u && u.uploads) || []; } catch (e) { uploads = []; }
      } catch (e) { return fail(e); }
      if (dead) return;
      hue = MF.people(M.colors);
      renderFull();
    }
    function fail(e) {
      if (dead) return;
      app.querySelector(".mf-loading").outerHTML = `<div class="mf-fail callout warn"><b>${esc(e.code === 404 ? "הפגישה לא נמצאה" : "הפגישה לא נטענה")}</b><p>${esc(e.message || "")}</p><p><a class="btn sm ghost" href="${esc(MF.url("flow/"))}" data-go>חזרה לפגישות</a> <button class="btn sm" type="button" data-retry>לנסות שוב</button></p></div>`;
      app.querySelector("[data-retry]").onclick = () => MF.render();
    }

    /* ---------- the header and the ribbon of stages (the same for every state) ---------- */
    function head(extraActs) {
      const st = info.state, people = info.people || [];
      const when = info.started_ts ? `${MF.day(info.started_ts)} · ${MF.clock(info.started_ts)}` : "";
      const len = info.started_ts && info.ended_ts ? MF.fmtLen(info.ended_ts - info.started_ts) : "";
      const hostUrl = MF.url("r/" + encodeURIComponent(room));
      const join = st === "before" || st === "live" ? `<a class="btn" href="${esc(hostUrl)}" target="_blank" rel="noopener" title="פתיחת הפגישה בחלון חדש">${ic("video")}<span>${st === "live" ? "הצטרפות לפגישה" : "התחלת הפגישה"}</span></a>` : "";
      return `<header class="mf-mh">
        <a class="mf-back" href="${esc(MF.url("flow/"))}" data-go title="כל הפגישות">${ic("chevronR")}<span>פגישות</span></a>
        <div class="mf-mh-t"><h1><bdi>${esc(info.title || room)}</bdi></h1>
          <div class="mf-mh-meta">${MF.statePill(st)}${when ? `<span>${esc(when)}</span>` : ""}${len ? `<span>${esc(len)}</span>` : ""}${people.length ? `<span class="mf-people">${people.slice(0, 6).map((p) => MF.avatar(p, hue(p))).join("")}<span class="mf-people-n">${esc(people.slice(0, 3).join(", "))}${people.length > 3 ? ` +${people.length - 3}` : ""}</span></span>` : ""}</div></div>
        <div class="mf-mh-acts">${join}${extraActs || ""}<button class="btn ghost" type="button" data-share title="להעתיק את הקישור לפגישה">${ic("share")}<span>שיתוף</span></button></div>
      </header>${ribbon()}`;
    }
    function ribbon() {
      const s = info.stages || [];
      if (!s.length) return "";
      return `<ol class="mf-ribbon" aria-label="שלבי העיבוד">${s.map((x) => `<li data-st="${esc(x.state)}" title="${esc((MF.STAGE_STATE[x.state] || x.state) + (x.detail ? " — " + x.detail : ""))}"><i aria-hidden="true">${x.state === "done" ? ic("tick") : x.state === "running" ? '<span class="mf-spin sm"></span>' : x.state === "failed" ? ic("x") : ""}</i><span>${esc(MF.STAGE[x.key] || x.key)}</span></li>`).join("")}</ol>`;
    }
    function bindHead(root) {
      const sh = root.querySelector("[data-share]");
      if (sh) sh.onclick = () => MF.copy(location.origin + MF.roomUrl(room) + (stage && stage.t > 1 ? "#t" + Math.floor(stage.t) : ""), stage && stage.t > 1 ? `הקישור הועתק — נפתח ב-${fmt(stage.t)}` : "הקישור לפגישה הועתק");
    }

    /* ---------- BEFORE: the way in, and what the meeting before it left open ---------- */
    async function renderBefore() {
      let prevRows = [], prevMeet = null;
      if (info.prev) {
        try {
          const [inb, ms] = await Promise.all([MF.api("flow/api/inbox?all=1"), MF.api("flow/api/meetings")]);
          prevRows = ((inb && inb.items) || []).filter((r) => r.room === info.prev.room && r.state !== "rejected");
          prevMeet = ((ms && ms.meetings) || []).find((m) => m.room === info.prev.room) || null;
        } catch (e) { /* the prep is a help, not a condition */ }
      }
      if (dead) return;
      const guest = info.meet_url || (MF.cfg.meet ? MF.cfg.meet.replace(/\/$/, "") + "/" + encodeURIComponent(room) : "");
      const openTasks = prevRows.filter((r) => r.kind === "task" && r.state !== "approved");
      const sentTasks = prevRows.filter((r) => r.kind === "task" && r.state === "approved");
      const decs = prevRows.filter((r) => r.kind === "decision");
      const docs = (prevMeet && prevMeet.docs) || [];
      app.innerHTML = `<div class="mf-mtg" data-state="before">${head()}
        <div class="mf-before">
          <section class="mf-card mf-door">
            <div class="mf-door-ic">${ic("video")}</div>
            <h2>הפגישה עוד לא התחילה</h2>
            <p class="muted">כשהיא תתחיל, הדף הזה יראה אותה בשידור — כל מה שנאמר, ברגע שנאמר — ואחרי שתסתיים, את ההקלטה, התמלול, ההחלטות והמשימות. הכתובת לא משתנה.</p>
            <div class="mf-door-acts"><a class="btn" href="${esc(MF.url("r/" + encodeURIComponent(room)))}" target="_blank" rel="noopener">${ic("video")}<span>התחלת הפגישה</span></a>${guest ? `<button class="btn ghost" type="button" data-guest="${esc(guest)}">${ic("link")}<span>קישור לאורחים</span></button>` : ""}</div>
            <p class="muted small mf-watching"><span class="mf-pulse idle"></span>הדף בודק כל כמה שניות אם הפגישה התחילה</p>
          </section>
          ${info.prev ? `<section class="mf-card mf-prep">
            <header class="mf-sec-h"><h2>הכנה — מה נשאר פתוח מ<a href="${esc(MF.roomUrl(info.prev.room))}" data-go>${esc(info.prev.title || info.prev.room)}</a></h2></header>
            ${docs.length ? `<div class="mf-prep-docs">${docs.map((d) => { const href = Array.isArray(d) ? d[1] : d.href, title = Array.isArray(d) ? d[0] : d.title; return `<a class="mf-file mf-doc" href="${esc(MF.roomUrl(info.prev.room, href))}" target="_blank" rel="noopener"><span class="mf-file-ic">${ic("file-text")}</span><div class="mf-file-b"><b dir="auto">${esc(title)}</b><span class="muted small">מסמך מהפגישה הקודמת</span></div>${ic("external", "mf-go")}</a>`; }).join("")}</div>` : ""}
            <div class="mf-kpis">${[["משימות פתוחות", openTasks.length, "warn"], ["נשלחו ל-Plane", sentTasks.length, "ok"], ["החלטות", decs.length, ""]].map(([k, n, tone]) => `<div class="mf-kpi" data-tone="${tone}"><b>${MF.num(n)}</b><span>${k}</span></div>`).join("")}</div>
            ${openTasks.length ? `<h3 class="mf-h3">משימות שעוד לא אושרו</h3><div class="mf-items">${openTasks.slice(0, 12).map((r, i) => MF.itemCard(MF.itemView("task", Object.assign({ id: r.id, who: r.owner }, r), i, {}), { meeting: info.prev, readOnly: true, compact: true })).join("")}</div>${openTasks.length > 12 ? `<p><a class="btn sm ghost" href="${esc(MF.roomUrl(info.prev.room) + "?v=task")}" data-go>לכל ${MF.num(openTasks.length)} המשימות</a></p>` : ""}` : ""}
          </section>` : ""}
        </div></div>`;
      bindHead(app);
      const g = app.querySelector("[data-guest]"); if (g) g.onclick = () => MF.copy(g.dataset.guest, "הקישור לאורחים הועתק");
      poll(10000, async () => { const n = await MF.api(api("meeting.json")); if (n.state !== "before") MF.render(); });
    }

    /* ---------- LIVE: what is being said, as it is said ---------- */
    function renderLive() {
      app.innerHTML = `<div class="mf-mtg" data-state="live">${head()}
        <div class="mf-body mf-live">
          <section class="mf-stagecol">
            <div class="mf-card mf-onair">
              <div class="mf-onair-h"><span class="mf-state" data-tone="live"><i class="mf-pulse"></i>בשידור</span><time class="mf-elapsed" dir="ltr">0:00</time><span class="mf-rec muted small"></span></div>
              <div class="mf-bigcap" aria-live="polite"><p class="muted">מחכים למילים הראשונות…</p></div>
              <div class="mf-present"></div>
            </div>
            <div class="mf-card mf-markbar">
              <h3>לסמן את הרגע</h3>
              <div class="mf-marks-acts">${Object.entries(MF.MARK).map(([k, h]) => `<button class="btn ghost" type="button" data-mark="${k}">${ic(k === "decision" ? "flag" : k === "task" ? "task" : k === "question" ? "help" : "star")}<span>${h}</span></button>`).join("")}</div>
              <p class="muted small">סימון נשמר עם הרגע שבו נלחץ, ומופיע בציר הזמן של הפגישה אחרי שתסתיים.</p>
              <div class="mf-marklist"></div>
            </div>
          </section>
          <aside class="mf-side"><div class="mf-pane on mf-livelist" aria-live="off"><div class="mf-empty">${ic("mic")}<p>הכתוביות מופיעות כאן כשמישהו מדבר.</p></div></div></aside>
        </div></div>`;
      bindHead(app);
      const list = app.querySelector(".mf-livelist"), big = app.querySelector(".mf-bigcap"), present = app.querySelector(".mf-present");
      const el = app.querySelector(".mf-elapsed"), rec = app.querySelector(".mf-rec"), marklist = app.querySelector(".mf-marklist");
      let started = info.started_ts || Date.now() / 1000, stick = true, shown = 0;
      list.addEventListener("scroll", () => { stick = list.scrollTop + list.clientHeight > list.scrollHeight - 40; }, { passive: true });
      const tickClock = () => { el.textContent = fmt(Date.now() / 1000 - started); };
      timers.push(setInterval(tickClock, 1000)); tickClock();
      async function marks() {
        try { const r = await MF.api(api("items")); items = (r && r.items) || {}; } catch (e) { return; }
        const ms = MF.itemsOf("mark", { meeting: {} }, items);
        marklist.innerHTML = ms.length ? `<ol class="mf-mlist">${ms.slice(-8).reverse().map((v) => `<li><time dir="ltr">${fmt(v.t)}</time><b>${esc(MF.MARK[v.label] || "סימון")}</b>${v.by ? `<span class="muted small">${esc(v.by.name || v.by.username)}</span>` : ""}</li>`).join("")}</ol>` : "";
      }
      app.querySelector(".mf-marks-acts").addEventListener("click", async (e) => {
        const b = e.target.closest("[data-mark]"); if (!b) return;
        const t = Math.max(0, Date.now() / 1000 - started);
        b.disabled = true;
        try {
          const r = await MF.api(api("items"), { method: "POST", body: { kind: "mark", id: null, action: "add", fields: { t, label: b.dataset.mark } } });
          MF.tell(`סומן: ${MF.MARK[b.dataset.mark]} ב-${fmt(t)}`, "ok");
          if (r && r.item) await marks();
        } catch (err) { MF.tell(err.message, "bad"); }
        finally { b.disabled = false; }
      });
      async function pull() {
        let d;
        try { d = await MF.api(api("live.json")); } catch (e) { rec.textContent = "אין חיבור לכתוביות"; return; }
        if (dead) return;
        if (d && d.flow) { MF.tell("הפגישה הסתיימה — עוברים להקלטה ולתמלול", "ok"); MF.render(); return; }
        if (d.started) started = +d.started;
        const now = d.now || {};
        rec.textContent = now.recording === "on" ? "מוקלטת" : now.recording ? `הקלטה: ${now.recording}` : "";
        const names = now.names || d.people || [];
        const quiet = new Set(d.uncaptioned || []);
        present.innerHTML = names.length ? `<span class="muted small">בפגישה עכשיו</span>${names.map((n) => `<span class="mf-chip static${quiet.has(n) ? " quiet" : ""}" title="${quiet.has(n) ? "הקול שלו לא נכנס לכתוביות — רק להקלטה" : "בכתוביות"}">${MF.avatar(n, hue(n))}<bdi>${esc(n)}</bdi>${quiet.has(n) ? ic("mute") : ""}</span>`).join("")}` : "";
        const segs = (d.segments || []).slice().sort((a, b) => a.t - b.t);
        if (segs.length && segs.length !== shown) {
          shown = segs.length;
          list.innerHTML = segs.map((s) => `<div class="mf-line${s.final ? "" : " interim"}" style="--c:var(--${hue(s.name)})"><span class="mf-t static"><time dir="ltr">${fmt(s.t - started)}</time></span><div class="mf-line-b"><div class="mf-line-h"><b class="mf-who" data-hue="${esc(hue(s.name))}"><bdi>${esc(s.name || "?")}</bdi></b></div><p class="mf-tx"${MF.dirAttr(s.text)}>${esc(s.text)}</p></div></div>`).join("");
          if (stick) list.scrollTop = list.scrollHeight;
          const last = segs.slice(-2);
          big.innerHTML = last.map((s) => `<p${MF.dirAttr(s.text)}><b data-hue="${esc(hue(s.name))}"><bdi>${esc(s.name || "?")}</bdi></b> ${esc(s.text)}</p>`).join("");
        }
      }
      pull(); marks();
      poll(4000, pull); poll(20000, marks);
    }

    /* ---------- AFTER: the whole meeting on one axis ---------- */
    const TABS = [["tr", "תמלול", "message"], ["ov", "סקירה", "eye"], ["decision", "החלטות", "flag"], ["task", "משימות", "task"], ["question", "שאלות", "help"], ["sc", "מסכים", "image"], ["tl", "ציר זמן", "layers"], ["files", "קבצים", "folder"], ["hist", "יומן", "clock"]];
    function countOf(kind) { return MF.itemsOf(kind, M, items); }
    function tabBadge(k) {
      if (k === "sc") return M && (M.moments || []).length ? `<span class="n" title="רגעים שבהם הצביעו על המסך">${MF.num(M.moments.length)}</span>` : "";
      if (!["decision", "task", "question"].includes(k)) return "";
      const all = countOf(k), wait = all.filter((v) => v.state === "proposed").length;
      return all.length ? `<span class="n${wait ? " wait" : ""}" title="${wait ? `${wait} ממתינים לאישור` : "הכול טופל"}">${MF.num(all.length)}</span>` : "";
    }
    function renderFull() {
      const st = info.state;
      const extraAudio = uploads.filter((u) => u.done && (u.kind === "audio" || u.kind === "video") && u.offset != null).map((u) => ({ id: "up-" + u.name, label: u.label || u.name, short: u.label || u.name.replace(/\.[^.]+$/, ""), src: "uploads/" + encodeURIComponent(u.name), offset: +u.offset, duration: +u.duration || 0 }));
      app.innerHTML = `<div class="mf-mtg" data-state="${esc(st)}">${head(`<button class="btn ghost" type="button" data-upload title="הקלטה נוספת, טקסט או מסמך">${ic("upload")}<span>הוספת קובץ</span></button>`)}
        ${st === "first" ? `<div class="callout mf-firstnote">${ic("refresh")}<span><b>עיבוד ראשון.</b> ההקלטה והכתוביות החיות, מיד כשהפגישה נגמרה. התמלול המלא, הדוברים, הנושאים, ההחלטות והמשימות יחליפו את זה כאן — באותה כתובת.</span></div>` : ""}
        <div class="mf-body">
          <section class="mf-stagecol"><div class="mf-player"></div><div class="mf-transportbox"></div><div class="mf-scrubbox"></div></section>
          <aside class="mf-side">
            <nav class="mf-tabs" role="tablist" aria-label="חלקי הפגישה">${TABS.map(([k, h, i]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="false" aria-controls="mf-p-${k}"><span>${h}</span>${tabBadge(k)}</button>`).join("")}</nav>
            <div class="mf-panes">${TABS.map(([k]) => `<div class="mf-pane" id="mf-p-${k}" role="tabpanel" data-pane="${k}"></div>`).join("")}</div>
          </aside>
          <section class="mf-tlbox" aria-label="ציר הזמן"><div class="mf-tl-resize" role="separator" aria-orientation="horizontal" title="גרירה משנה את גובה ציר הזמן"></div><div class="mf-tlmount"></div></section>
        </div>
        <div class="mf-sheet" hidden role="dialog" aria-modal="true"><div class="mf-sheet-b"><header><b class="mf-sheet-t"></b><button class="mf-tb" type="button" data-close aria-label="סגירה">${ic("x")}</button></header><div class="mf-sheet-c"></div></div></div>
      </div>`;
      bindHead(app);
      const root = app.querySelector(".mf-mtg");
      const tlMount = app.querySelector(".mf-tlmount");
      stage = MF.Stage(M, {
        root, host: app, player: app.querySelector(".mf-player"), transport: app.querySelector(".mf-transportbox"), timeline: tlMount,
        scrub: app.querySelector(".mf-scrubbox"),
      }, {
        base: MF.roomUrl(room), hue, textOf: (x) => (edits[x.id] ? edits[x.id].after : x.text), extraAudio,
        stateOf: (k, x) => { const kind = { decision: "decision", task: "task", question: "question" }[k]; if (!kind) return ""; const arr = { decision: M.decisions, task: M.tasks, question: M.questions }[kind]; const i = arr.indexOf(x); const s = items[`${kind}:${MF.itemId(kind, x, i)}`]; return (s && s.state) || "proposed"; },
        marks: MF.itemsOf("mark", M, items).map((v) => ({ t: v.t, label: v.label, text: MF.MARK[v.label] || "" })),
        onPick: (k, x) => pick(k, x),
      });
      offs.push(() => stage && stage.destroy());
      const ctx = { M, room, title: info.title, stage, hue, items, state: st, people: [...new Set((M.turns || []).map((x) => x.who).filter(Boolean))],
        store: (key, v) => { items[key] = Object.assign({}, items[key] || {}, v || {}); },
        changed: () => { refreshWork(); stage.rebuild(); } };
      tr = MF.Transcript(app.querySelector('[data-pane="tr"]'), { M, stage, room, hue, edits, versions,
        people: (info.people || []).concat(M.people || []),
        onEdit: () => { stage.rebuild(); renderHistory(); },
        onSpeaker: () => { stage.rebuild(); renderOverview(); renderHistory(); },
        onExport: () => { showTab("files", true); setTimeout(() => { const x = app.querySelector(".mf-export"); if (x) { x.scrollIntoView({ block: "center", behavior: "smooth" }); const a = x.querySelector("a"); if (a) a.focus({ preventScroll: true }); } }, 60); },
        onTaskFrom: (x, text) => { showTab("task"); lists.task.addTask({ text, t: x.s, owner: x.who }); } });
      offs.push(() => tr && tr.destroy());
      for (const k of ["decision", "task", "question"]) lists[k] = MF.WorkList(app.querySelector(`[data-pane="${k}"]`), Object.assign({}, ctx, { kind: k }));
      renderOverview(); renderHistory();
      files = MF.Files(app.querySelector('[data-pane="files"]'), { M, room, stage, openDoc, onChange: async () => { try { const u = await MF.api(api("uploads")); uploads = (u && u.uploads) || []; } catch (e) { /* */ } if (screens) screens.refresh(); } });
      if (MF.Screens) {
        screens = MF.Screens(app.querySelector('[data-pane="sc"]'), { M, room, stage, uploads: () => uploads,
          onSeek: () => { if (isPhone()) window.scrollTo({ top: 0, behavior: "smooth" }); },
          onSaved: async () => { try { const u = await MF.api(api("uploads")); uploads = (u && u.uploads) || []; } catch (e) { /* */ } if (files) files.reload(); renderHistory(); } });
        offs.push(() => screens && screens.destroy());
      }
      // the axis: under the screen on a wide screen, a tab of its own on a phone
      placeTimeline();
      on(window, "resize", placeTimeline);
      app.querySelector(".mf-tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab, true); });
      app.querySelector("[data-upload]").onclick = () => { showTab("files", true); setTimeout(() => app.querySelector(".mf-drop input")?.click(), 50); };
      app.querySelector(".mf-sheet").addEventListener("click", (e) => { if (e.target.closest("[data-close]") || e.target.classList.contains("mf-sheet")) closeSheet(); });
      resizeTl();
      const want = where.view && TABS.some(([k]) => k === where.view) ? where.view : MF.store.get("tab", "tr");
      showTab(want === "tl" && !isPhone() ? "tr" : want);
      if (where.t != null) { stage.zoomTo(4); stage.seek(where.t); } else stage.seek(0, { hash: false });
      if (where.q) tr.setQuery(where.q);
      keys();
      on(window, "hashchange", () => { const w = MF.where(); if (w.t != null) stage.seek(w.t); });
    }
    function placeTimeline() {
      const box = app.querySelector(".mf-tlbox"), pane = app.querySelector('[data-pane="tl"]'), mount = app.querySelector(".mf-tlmount");
      if (!box || !mount) return;
      const target = isPhone() ? pane : box;
      if (mount.parentElement !== target) { target.appendChild(mount); if (stage) setTimeout(() => stage.relayout(), 0); }
      app.querySelector('[data-tab="tl"]').hidden = !isPhone();
      if (!isPhone() && app.querySelector('[data-tab="tl"][aria-selected="true"]')) showTab("tr");
    }
    function resizeTl() {
      const h = app.querySelector(".mf-tl-resize"), box = app.querySelector(".mf-tlbox"); if (!h) return;
      const saved = MF.store.get("tlH", 0); if (saved) box.style.setProperty("--tlh", saved + "px");
      h.addEventListener("pointerdown", (e) => {
        h.setPointerCapture(e.pointerId);
        const y0 = e.clientY, h0 = box.getBoundingClientRect().height;
        h.onpointermove = (ev) => { const v = Math.max(140, Math.min(window.innerHeight * 0.7, h0 - (ev.clientY - y0))); box.style.setProperty("--tlh", v + "px"); };
        h.onpointerup = () => { h.onpointermove = null; MF.store.set("tlH", Math.round(box.getBoundingClientRect().height)); stage && stage.relayout(); };
      });
    }
    function showTab(k, user) {
      for (const b of app.querySelectorAll(".mf-tabs [data-tab]")) b.setAttribute("aria-selected", b.dataset.tab === k);
      for (const p of app.querySelectorAll(".mf-pane")) p.classList.toggle("on", p.dataset.pane === k);
      if (user) { MF.store.set("tab", k); MF.setQuery("v", k === "tr" ? "" : k); }
      if (k === "tl" && stage) setTimeout(() => stage.relayout(), 0);
      const sel = app.querySelector(`.mf-tabs [data-tab="${k}"]`); if (sel && sel.scrollIntoView && isPhone()) sel.scrollIntoView({ block: "nearest", inline: "center" });
    }
    function refreshWork() {
      for (const k of Object.keys(lists)) lists[k].render();
      for (const b of app.querySelectorAll(".mf-tabs [data-tab]")) { const n = b.querySelector(".n"); const nb = tabBadge(b.dataset.tab); if (n) n.outerHTML = nb || ""; else if (nb) b.insertAdjacentHTML("beforeend", nb); }
      renderOverview(); renderHistory();
    }
    function pick(k, x) {
      if (["decision", "task", "question"].includes(k)) {
        showTab(k, true);
        const arr = { decision: M.decisions, task: M.tasks, question: M.questions }[k];
        const key = `${k}:${MF.itemId(k, x, arr.indexOf(x))}`;
        const card = app.querySelector(`.mf-pane.on .mf-item[data-key="${CSS.escape(key)}"]`);
        if (card) { card.scrollIntoView({ block: "center", behavior: "smooth" }); card.classList.add("flash"); setTimeout(() => card.classList.remove("flash"), 1600); }
      } else if (k === "frame" || k === "screen") {
        const f = k === "frame" ? x.f : (x.frames || [])[0];
        sheet(k === "screen" ? x.label : `המסך ב-${fmt(x.t)}`, `${f ? `<img class="mf-frame" src="${esc(MF.roomUrl(room, "frames/f/" + f))}" alt="">` : ""}${k === "screen" && x.detail ? `<p dir="auto">${esc(x.detail)}</p>` : ""}<p class="muted small">${fmt(x.s ?? x.t)}${x.e ? "–" + fmt(x.e) : ""}</p>`);
      } else if (k === "topic") {
        showTab("ov", true);
        const n = app.querySelector(`.mf-topic[data-s="${x.s}"]`); if (n) { n.open = true; n.scrollIntoView({ block: "center", behavior: "smooth" }); }
      } else if (k === "turn" && !isPhone()) showTab("tr");
    }
    function sheet(title, html) {
      const s = app.querySelector(".mf-sheet"); s.querySelector(".mf-sheet-t").textContent = title || ""; s.querySelector(".mf-sheet-c").innerHTML = html; s.hidden = false;
      s.querySelector("[data-close]").focus();
    }
    function closeSheet() { const s = app.querySelector(".mf-sheet"); if (s) { s.hidden = true; s.querySelector(".mf-sheet-c").innerHTML = ""; } }
    function openDoc(href) {
      sheet("מסמך", `<iframe class="mf-docframe" src="${esc(MF.roomUrl(room, href))}" title="מסמך"></iframe>`);
      const f = app.querySelector(".mf-docframe");
      f.addEventListener("load", () => {
        try {
          const d = f.contentDocument; app.querySelector(".mf-sheet-t").textContent = d.title || "מסמך";
          d.addEventListener("click", (e) => {
            const a = e.target.closest("a[href]"); if (!a) return;
            const m = a.getAttribute("href").match(/#t=?(\d+(?:\.\d+)?)/);
            if (m) { e.preventDefault(); stage.seek(+m[1]); if (isPhone()) closeSheet(); MF.tell(`קופצים ל-${fmt(+m[1])}`, "ok", { ms: 1500 }); }
          });
        } catch (e) { /* another origin: its links stay its own */ }
      });
    }

    /* ---------- the overview: the meeting in one screen ---------- */
    function renderOverview() {
      const p = app.querySelector('[data-pane="ov"]'); if (!p) return;
      const turns = stage.turns, words = turns.reduce((n, x) => n + String(x.text || "").split(/\s+/).filter(Boolean).length, 0);
      const people = [...new Set(turns.map((x) => x.who).filter(Boolean))];
      const talk = people.map((w) => [w, turns.filter((x) => x.who === w).reduce((n, x) => n + Math.max(0, x.e - x.s), 0)]).sort((a, b) => b[1] - a[1]);
      const tot = talk.reduce((n, x) => n + x[1], 0) || 1;
      const k = (kind) => countOf(kind);
      const marks = MF.itemsOf("mark", M, items);
      const kp = [["משך", MF.fmtLen(M.meeting.duration)], ["שורות", MF.num(turns.length)], ["מילים", MF.num(words)], ["החלטות", MF.num(k("decision").length)], ["משימות", MF.num(k("task").length)], ["שאלות", MF.num(k("question").length)]];
      const sec = (title, n, body, open) => `<details class="mf-sec mf-fold"${open ? " open" : ""}><summary><h3>${title}</h3>${n != null ? `<span class="n">${MF.num(n)}</span>` : ""}${MF.ic("chevronD", "mf-caret")}</summary>${body}</details>`;
      p.innerHTML = `
        <div class="mf-strip">${kp.map(([a, b]) => `<div><span>${a}</span><b>${b}</b></div>`).join("")}</div>
        ${people.length ? `<section class="mf-sec"><h3>מי דיבר כמה</h3><div class="mf-talk">${talk.map(([w, s]) => `<div class="mf-talk-row"><span class="mf-talk-who">${MF.avatar(w, hue(w))}<bdi>${esc(w)}</bdi></span><span class="mf-talk-bar"><i style="--p:${(s / tot) * 100}%;--c:var(--${hue(w)})"></i></span><span class="mf-talk-n" dir="ltr">${Math.round((s / tot) * 100)}%</span></div>`).join("")}</div></section>` : ""}
        ${(M.meeting.docs || []).length ? `<section class="mf-sec"><h3>מסמכים</h3>${M.meeting.docs.map((d) => `<button class="mf-file mf-doc" type="button" data-doc="${esc(d.href)}"><span class="mf-file-ic">${ic("file-text")}</span><div class="mf-file-b"><b dir="auto">${esc(d.title)}</b></div>${ic("chevronL", "mf-go")}</button>`).join("")}</section>` : ""}
        ${(M.topics || []).length ? sec("נושאים לפי הסדר", M.topics.length, `<div class="mf-topics">${M.topics.map((x) => `<details class="mf-topic" data-s="${x.s}"><summary><button class="mf-t" type="button" data-seek="${x.s}"><time dir="ltr">${fmt(x.s)}</time></button><b${MF.dirAttr(x.title)}>${esc(x.title)}</b></summary><div class="mf-topic-b"${MF.dirAttr(x.body)}>${esc(x.body || "")}</div></details>`).join("")}</div>`, true) : ""}
        ${marks.length ? sec("רגעים שסומנו", marks.length, `<ol class="mf-mlist">${marks.map((v) => `<li><button class="mf-t" type="button" data-seek="${v.t}"><time dir="ltr">${fmt(v.t)}</time></button><b>${esc(MF.MARK[v.label] || "סימון")}</b>${v.text ? `<span dir="auto">${esc(v.text)}</span>` : ""}${v.by ? `<span class="muted small">${esc(v.by.name || v.by.username)}</span>` : ""}</li>`).join("")}</ol>`, true) : ""}
        ${(M.likes || []).length ? sec("מה אהבו ומה דחו", M.likes.length, `<ul class="mf-plain">${M.likes.map((x) => `<li><button class="mf-t" type="button" data-seek="${x.t}"><time dir="ltr">${fmt(x.t)}</time></button><span class="mf-tag" data-tone="${x.kind === "rejected" ? "bad" : "ok"}">${x.kind === "rejected" ? "נדחה" : "אהבו"}</span><span${MF.dirAttr(x.text)}>${esc(x.text)}</span></li>`).join("")}</ul>`) : ""}
        ${(M.insights || []).length ? sec("תובנות", M.insights.length, `<ul class="mf-plain">${M.insights.map((x) => `<li><button class="mf-t" type="button" data-seek="${x.t}"><time dir="ltr">${fmt(x.t)}</time></button>${x.kind ? `<span class="mf-tag">${esc(x.kind)}</span>` : ""}<span${MF.dirAttr(x.text)}>${esc(x.text)}</span></li>`).join("")}</ul>`) : ""}
        ${(M.meeting.facts || []).length ? sec("על הנתונים", null, `<dl class="mf-facts col">${M.meeting.facts.map(([a, b]) => `<div><dt>${esc(a)}</dt><dd dir="auto">${esc(b)}</dd></div>`).join("")}</dl>`) : ""}`;
      p.onclick = (e) => {
        const s = e.target.closest("[data-seek]"); if (s) { e.preventDefault(); stage.seek(+s.dataset.seek); return; }
        const d = e.target.closest("[data-doc]"); if (d) openDoc(d.dataset.doc);
      };
    }

    /* ---------- the meeting's lifetime: its stages, and what people did to it ---------- */
    function renderHistory() {
      const p = app.querySelector('[data-pane="hist"]'); if (!p) return;
      const ev = [];
      const tOf = (id) => (stage.turns.find((x) => x.id === id) || {}).s;
      for (const vs of Object.values(versions)) for (const e of vs) ev.push({ at: e.at, who: e.by, what: `תיקן שורה`, detail: e.after, t: tOf(e.target) });
      for (const e of Object.values(whoEdits)) ev.push({ at: e.at, who: e.by, what: "תיקן דובר", detail: `${e.before || "?"} ← ${e.after}`, t: tOf(e.target) });
      for (const [k, v] of Object.entries(items)) if (v.at) ev.push({ at: v.at, who: v.by, what: `${({ approved: "אישר", rejected: "דחה", edited: "ערך", proposed: "פתח מחדש" })[v.state] || "הוסיף"} ${(MF.KIND[k.split(":")[0]] || {}).he || ""}`, detail: (v.fields && v.fields.text) || k.split(":")[1], t: v.fields && v.fields.t != null ? +v.fields.t : null, plane: v.plane });
      for (const u of uploads) if (u.at) ev.push({ at: u.at, who: u.by, what: "הוסיף קובץ", detail: u.label || u.name });
      ev.sort((a, b) => b.at - a.at);
      p.innerHTML = `
        <section class="mf-sec"><h3>שלבי העיבוד</h3><ol class="mf-stages">${(info.stages || []).map((x) => `<li data-st="${esc(x.state)}"><i aria-hidden="true">${x.state === "done" ? ic("tick") : x.state === "running" ? '<span class="mf-spin sm"></span>' : ""}</i><div><b>${esc(MF.STAGE[x.key] || x.key)}</b><span class="muted small">${esc(MF.STAGE_STATE[x.state] || x.state)}${x.detail ? " · " + esc(x.detail) : ""}</span></div></li>`).join("")}</ol></section>
        <section class="mf-sec"><h3>מה נעשה בפגישה הזו</h3>${ev.length ? `<ol class="mf-activity">${ev.slice(0, 200).map((x) => `<li><span class="muted small">${esc(MF.ago(x.at))}</span><b><bdi>${esc((x.who && (x.who.name || x.who.username)) || "מישהו")}</bdi> ${esc(x.what)}</b>${x.t != null ? `<button class="mf-t" type="button" data-seek="${x.t}"><time dir="ltr">${fmt(x.t)}</time></button>` : ""}<span class="mf-act-d" dir="auto">${esc(String(x.detail || "").slice(0, 160))}</span>${x.plane && x.plane.url ? `<a href="${esc(x.plane.url)}" target="_blank" rel="noopener">${esc(x.plane.key || "Plane")}</a>` : ""}</li>`).join("")}</ol>` : '<p class="muted small">עוד אף אחד לא תיקן, אישר או הוסיף כאן דבר.</p>'}</section>`;
      p.onclick = (e) => { const s = e.target.closest("[data-seek]"); if (s) stage.seek(+s.dataset.seek); };
    }

    /* ---------- the keyboard ---------- */
    function keys() {
      on(window, "keydown", (e) => {
        if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable], .bask, dialog")) return;
        if (e.key === "Escape") { closeSheet(); return; }
        if (!stage || e.ctrlKey || e.metaKey || e.altKey) return;
        // by the key's place, not its letter: K / L / J / F are the same keys on a Hebrew keyboard (ל / ך / ח / כ)
        if (e.code === "Space" || e.code === "KeyK") { e.preventDefault(); stage.toggle(); }
        else if (e.key === "ArrowRight") { e.preventDefault(); stage.seek(stage.t + (e.shiftKey ? 30 : 5)); }
        else if (e.key === "ArrowLeft") { e.preventDefault(); stage.seek(stage.t - (e.shiftKey ? 30 : 5)); }
        else if (e.code === "KeyL") stage.seek(stage.t + 10);
        else if (e.code === "KeyJ") stage.seek(stage.t - 10);
        else if (e.key === "+" || e.key === "=") stage.zoomIn();
        else if (e.key === "-") stage.zoomOut();
        else if (e.code === "KeyF") stage.setFollow(!stage.follow);
        else if (e.key === "/" || e.code === "Slash") { e.preventDefault(); showTab("tr"); tr.focusSearch(); }
      });
    }
    function poll(ms, f) { timers.push(setInterval(() => { if (dead || document.hidden) return; const p = f(); if (p && p.catch) p.catch(() => {}); }, ms)); }

    load();
    return { destroy() { dead = true; for (const t of timers) clearInterval(t); for (const f of offs) f(); } };
  };
})();
