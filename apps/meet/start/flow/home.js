/* «פגישות» — home.js: the centre of the office's meetings and the work they create (…/flow/). What is on now, what
   comes next in each series (and what it inherits: what the meeting before it left open), what waits for a person to
   approve, every meeting by day, and one search over everything that was ever said, decided or assigned. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Home = function Home(app, where) {
    const { esc, ic, fmt } = MF;
    const timers = [];
    let dead = false, data = null, inbox = null, view = ["meetings", "tasks", "decisions"].includes(where.view) ? where.view : "meetings";
    let hue = MF.people({});
    document.title = "פגישות";

    app.innerHTML = `<div class="pg mf-home">
      <header class="pg-head">
        <div><h1>פגישות</h1><div class="pg-sub">כל פגישה במקום אחד — מההקלטה, דרך כל מילה, ועד ההחלטות והמשימות</div></div>
        <div class="pg-actions"><form class="mf-roomform" data-room-form novalidate><label class="mf-vh" for="mf-room-name">שם החדר</label><input id="mf-room-name" name="room" dir="ltr" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="go" placeholder="fpg107" aria-describedby="mf-room-err"><button class="btn ghost" type="submit" title="פתיחת החדר בשם הזה, כמארח, בחלון חדש">${ic("video")}<span>פתיחה לפי שם</span></button><output id="mf-room-err" class="mf-room-err" aria-live="polite"></output></form><a class="btn" href="${esc(MF.url("new"))}" target="_blank" rel="noopener" data-new title="פגישה חדשה בחלון חדש">${ic("plus")}<span>פגישה חדשה</span></a></div>
      </header>
      <label class="mf-bigsearch"><span class="mf-vh">חיפוש בכל הפגישות</span>${ic("search")}<input type="search" placeholder="חיפוש בכל הפגישות — מילה, שם, החלטה, משימה" autocomplete="off" enterkeyhint="search" value="${esc(where.q)}"><output class="muted small" aria-live="polite"></output></label>
      <div class="mf-home-body"><div class="mf-loading" role="status"><span class="mf-spin"></span><span>טוען…</span></div></div>
    </div>`;
    const body = app.querySelector(".mf-home-body"), input = app.querySelector(".mf-bigsearch input"), out = app.querySelector(".mf-bigsearch output");
    // «פגישה חדשה»: the host's door with a fresh room (the same as the Meet tile's own button). «פתיחה לפי שם»: a room the
    // office names (fpg107: the series the centre reads), as Jitsi's own welcome page did before the tile opened here
    // (CHAT-67): the host's door r/<room>, in a new window. Jitsi refuses / ? & : " ' % # in a room's name.
    const roomForm = app.querySelector("[data-room-form]");
    roomForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const inp = roomForm.querySelector("input"), err = roomForm.querySelector("output");
      const name = inp.value.normalize("NFKC").trim().toLowerCase();
      if (!name) { err.textContent = "כתבו שם לחדר"; inp.setAttribute("aria-invalid", "true"); inp.focus(); return; }
      if (name.length > 200 || /[\/?&:"'%#\s]/.test(name)) { err.textContent = "בלי רווחים ובלי / ? & : \" ' % #"; inp.setAttribute("aria-invalid", "true"); inp.focus(); return; }
      err.textContent = ""; inp.removeAttribute("aria-invalid");
      window.open(MF.url("r/" + encodeURIComponent(name)), "_blank", "noopener");
    });


    async function load() {
      try {
        const [m, i] = await Promise.all([MF.api("flow/api/meetings"), MF.api("flow/api/inbox?all=1").catch(() => ({ items: [] }))]);
        data = m || { meetings: [], live: [] }; inbox = (i && i.items) || [];
      } catch (e) {
        body.innerHTML = `<div class="callout warn"><b>הפגישות לא נטענו</b><p>${esc(e.message)}</p><button class="btn sm" type="button" data-retry>לנסות שוב</button></div>`;
        body.querySelector("[data-retry]").onclick = load; return;
      }
      if (dead) return;
      const names = {}; for (const m of data.meetings || []) for (const p of m.people || []) names[p] = names[p] || null;
      hue = MF.people(names);
      if (input.value.trim().length >= 2) search(); else render();
    }

    /* ---------- the centre ---------- */
    function render() {
      const ms = data.meetings || [], live = data.live || [];
      const byRoom = Object.fromEntries(ms.map((m) => [m.room, m]));
      const waiting = inbox.filter((r) => r.state === "proposed");
      // what comes next in a series: the newest meeting of a series + 1, when the series has more than one meeting
      const series = {};
      for (const m of ms) if (m.n != null && m.series) (series[m.series] = series[m.series] || []).push(m);
      const next = Object.entries(series).filter(([, a]) => a.length > 1).map(([s, a]) => {
        const last = a.slice().sort((x, y) => y.n - x.n)[0];
        const room = s + (last.n + 1);
        if (byRoom[room] || live.some((l) => l.room === room)) return null;
        const open = inbox.filter((r) => r.room === last.room && r.kind === "task" && r.state !== "approved" && r.state !== "rejected").length;
        return { room, last, open };
      }).filter(Boolean);
      const days = [];
      for (const m of ms) { const d = MF.day(m.start_ts || m.started, data.now); const g = days.find((x) => x.d === d); g ? g.rows.push(m) : days.push({ d, rows: [m] }); }
      const seg = [["meetings", "פגישות", ms.length], ["tasks", "משימות", inbox.filter((r) => r.kind === "task").length], ["decisions", "החלטות", inbox.filter((r) => r.kind === "decision").length]];
      body.innerHTML = `
        ${live.length ? `<section class="mf-home-sec"><h2 class="mf-h2"><i class="mf-pulse"></i>עכשיו בשידור</h2><div class="mf-cards live">${live.map((l) => `
          <article class="mf-card mf-livecard"><div class="mf-livecard-h">${MF.statePill("live")}<b dir="auto">${esc((byRoom[l.room] || {}).title || l.room)}</b></div>
            <p class="muted small">${l.since ? `התחילה ${esc(MF.ago(l.since))}` : ""}${l.people ? ` · ${MF.num(l.people)} משתתפים` : ""}${l.recording === "on" ? " · מוקלטת" : ""}</p>
            ${(l.names || []).length ? `<div class="mf-people">${l.names.slice(0, 8).map((n) => MF.avatar(n, hue(n))).join("")}<span class="mf-people-n">${esc(l.names.slice(0, 3).join(", "))}</span></div>` : ""}
            <footer><a class="btn sm" href="${esc(MF.url("r/" + encodeURIComponent(l.room)))}" target="_blank" rel="noopener">${ic("video")}<span>הצטרפות</span></a><a class="btn sm ghost" href="${esc(MF.roomUrl(l.room))}" data-go>${ic("eye")}<span>צפייה חיה</span></a></footer></article>`).join("")}</div></section>` : ""}
        ${next.length ? `<section class="mf-home-sec"><h2 class="mf-h2">${ic("calendar")}הבאה בתור</h2><div class="mf-cards">${next.map((x) => `
          <a class="mf-card mf-nextcard" href="${esc(MF.roomUrl(x.room))}" data-go><span class="mf-next-room" dir="ltr">${esc(x.room)}</span>
            <span class="muted small">אחרי ${esc(x.last.title || x.last.room)}${x.open ? ` · ${MF.num(x.open)} משימות פתוחות ממנה` : ""}</span><span class="mf-next-go">הכנה ופתיחה ${ic("chevronL")}</span></a>`).join("")}</div></section>` : ""}
        ${waiting.length ? `<section class="mf-home-sec"><h2 class="mf-h2">${ic("inbox")}ממתין לאישור<span class="n wait">${MF.num(waiting.length)}</span></h2>
          <div class="mf-items mf-inbox">${waiting.slice(0, 4).map((r) => card(r, byRoom)).join("")}</div>
          ${waiting.length > 4 ? `<button class="btn sm ghost" type="button" data-view="tasks">לכל ${MF.num(waiting.length)} הממתינים</button>` : ""}</section>` : ""}
        <section class="mf-home-sec">
          <div class="mf-seg mf-homeseg" role="tablist" aria-label="תצוגה">${seg.map(([k, h, n]) => `<button type="button" role="tab" data-view="${k}" aria-selected="${view === k}">${h}<span class="n">${MF.num(n)}</span></button>`).join("")}</div>
          <div class="mf-home-view"></div>
        </section>`;
      const v = body.querySelector(".mf-home-view");
      if (view === "meetings") v.innerHTML = days.length ? days.map((g) => `<div class="mf-day"><h3 class="mf-day-h">${esc(g.d)}</h3><div class="mf-rows">${g.rows.map(row).join("")}</div></div>`).join("")
        : `<div class="mf-empty big">${ic("video")}<p><b>עוד אין פגישות.</b> פגישה שמוקלטת מופיעה כאן מעצמה — בשידור בזמן שהיא מתקיימת, ואחריה עם ההקלטה והתמלול.</p><a class="btn" href="${esc(MF.url("new"))}" target="_blank" rel="noopener">${ic("plus")}<span>פגישה ראשונה</span></a></div>`;
      else work(v, view === "tasks" ? "task" : "decision", byRoom);
    }
    function row(m) {
      const c = m.counts || {};
      const st = MF.STATE[m.state] || {};
      return `<a class="mf-row" href="${esc(MF.roomUrl(m.room))}" data-go data-state="${esc(m.state)}">
        <span class="mf-row-time" dir="ltr">${esc(MF.clock(m.start_ts || m.started))}</span>
        <span class="mf-row-main"><b dir="auto">${esc(m.title || m.room)}</b>
          <span class="mf-row-meta">${m.length_min ? `<span>${esc(MF.fmtLen(m.length_min * 60))}</span>` : ""}${(m.people || []).length ? `<span class="mf-people sm">${m.people.slice(0, 4).map((p) => MF.avatar(p, hue(p))).join("")}<span class="mf-people-n">${esc(m.people.slice(0, 3).join(", "))}</span></span>` : ""}${(m.tags || []).filter((t) => t[1] === "bad").map((t) => `<span class="mf-tag" data-tone="bad">${esc(t[0])}</span>`).join("")}</span></span>
        <span class="mf-row-counts">${c.decisions ? `<span title="החלטות">${ic("flag")}${MF.num(c.decisions)}</span>` : ""}${c.tasks ? `<span title="משימות">${ic("task")}${MF.num(c.tasks)}</span>` : ""}${c.proposed ? `<span class="wait" title="ממתינים לאישור">${MF.num(c.proposed)} ממתינים</span>` : ""}</span>
        <span class="mf-state" data-tone="${esc(st.tone || "muted")}" title="${esc(st.hint || "")}">${st.tone === "live" ? '<i class="mf-pulse"></i>' : ""}${esc(st.he || m.state)}</span>
        ${ic("chevronL", "mf-go")}
      </a>`;
    }
    function card(r, byRoom) {
      const meet = byRoom[r.room] || { room: r.room, title: r.title || r.room };
      const v = MF.itemView(r.kind, Object.assign({ id: r.id, who: r.owner }, r), 0, {});
      v.state = r.state === "edited" ? "proposed" : r.state || "proposed"; v.plane = r.plane || null;
      if (r.fields) { if (r.fields.text) v.text = r.fields.text; if (r.fields.owner) v.owner = r.fields.owner; if (r.fields.due) v.due = r.fields.due; v.edited = true; }
      return MF.itemCard(v, { meeting: meet, compact: true });
    }
    function work(v, kind, byRoom) {
      let f = MF.store.get("hw:" + kind, "proposed");
      const draw = () => {
        const rows = inbox.filter((r) => r.kind === kind);
        const n = (s) => rows.filter((r) => (s === "all" ? true : (r.state === "edited" ? "proposed" : r.state) === s)).length;
        const shown = rows.filter((r) => f === "all" || (r.state === "edited" ? "proposed" : r.state) === f);
        v.innerHTML = `<div class="mf-work-bar"><div class="mf-seg sm" role="tablist">${[["proposed", "ממתין"], ["approved", "אושרו"], ["rejected", "נדחו"], ["all", "הכול"]].map(([s, h]) => `<button type="button" role="tab" data-hf="${s}" aria-selected="${f === s}">${h}<span class="n">${MF.num(n(s))}</span></button>`).join("")}</div></div>
          <div class="mf-items">${shown.slice(0, 300).map((r) => card(r, byRoom)).join("") || `<div class="mf-empty">${ic(kind === "task" ? "task" : "flag")}<p>${rows.length ? "אין פריטים במצב הזה." : kind === "task" ? "עוד אין משימות מפגישות." : "עוד אין החלטות מפגישות."}</p></div>`}</div>`;
      };
      v.onclick = (e) => { const b = e.target.closest("[data-hf]"); if (b) { f = b.dataset.hf; MF.store.set("hw:" + kind, f); draw(); } };
      draw();
    }
    // approve / reject / edit from the centre: the same cards and the same server calls as inside a meeting
    MF.bindItems(body, (cardEl) => {
      const room = cardEl && cardEl.dataset.room;
      return {
        room, stage: null, people: [],
        find: (key) => { const [kind, id] = key.split(":"); const r = inbox.find((x) => x.room === room && x.kind === kind && String(x.id) === id); return r ? Object.assign(MF.itemView(kind, Object.assign({ id: r.id, who: r.owner }, r), 0, {}), { state: r.state === "edited" ? "proposed" : r.state }) : null; },
        store: (key, item) => { const [kind, id] = key.split(":"); const r = inbox.find((x) => x.room === room && x.kind === kind && String(x.id) === id); if (r && item) { r.state = item.state || r.state; if (item.plane) r.plane = item.plane; if (item.fields) r.fields = item.fields; } },
        changed: () => render(),
      };
    });
    body.addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) { view = b.dataset.view; MF.setQuery("v", view === "meetings" ? "" : view); render(); body.querySelector(".mf-homeseg")?.scrollIntoView({ block: "start", behavior: "smooth" }); } });

    /* ---------- one search over every meeting ---------- */
    let qt = 0, ctl = null;
    async function search() {
      const q = input.value.trim();
      MF.setQuery("q", q);
      if (q.length < 2) { out.textContent = ""; if (data) render(); return; }
      if (ctl) ctl.abort(); ctl = new AbortController();
      out.textContent = "מחפש…";
      let r;
      try { r = await MF.api("flow/api/search?q=" + encodeURIComponent(q), { signal: ctl.signal }); } catch (e) { if (e.name === "AbortError") return; out.textContent = e.message; return; }
      const hits = (r && r.hits) || [];
      out.textContent = hits.length ? `${MF.num(r.total || hits.length)} תוצאות` : "לא נמצא";
      const groups = [];
      for (const h of hits) { const g = groups.find((x) => x.room === h.room); g ? g.hits.push(h) : groups.push({ room: h.room, title: h.title, hits: [h] }); }
      const KH = { line: "נאמר", decision: "החלטה", task: "משימה", question: "שאלה" };
      const words = MF.norm(q).split(/\s+/).filter(Boolean);
      const mark = (s) => { let h = esc(s); for (const w of words) { const n = MF.norm(h); if (n.length !== h.length) continue; let o = "", from = 0, at; while ((at = n.indexOf(w, from)) >= 0) { o += h.slice(from, at) + "<mark>" + h.slice(at, at + w.length) + "</mark>"; from = at + w.length; } h = o + h.slice(from); } return h; };
      body.innerHTML = groups.length ? groups.map((g) => `<section class="mf-home-sec mf-hits"><h2 class="mf-h2"><a href="${esc(MF.roomUrl(g.room))}" data-go>${esc(g.title || g.room)}</a><span class="n">${MF.num(g.hits.length)}</span></h2>
        <ol class="mf-hitlist">${g.hits.slice(0, 40).map((h) => `<li><a href="${esc(MF.roomUrl(h.room) + (h.kind === "line" ? "?q=" + encodeURIComponent(q) : "?v=" + h.kind) + "#t" + Math.floor(h.t || 0))}" data-go>
          <time dir="ltr">${fmt(h.t || 0)}</time><span class="mf-tag">${KH[h.kind] || h.kind}</span>${h.who ? `<b class="mf-who" data-hue="${esc(hue(h.who))}"><bdi>${esc(h.who)}</bdi></b>` : ""}<span class="mf-hit-tx"${MF.dirAttr(h.text)}>${mark(h.text)}</span></a></li>`).join("")}</ol>
        ${g.hits.length > 40 ? `<p class="muted small">ועוד ${MF.num(g.hits.length - 40)} בפגישה הזו — חפשו בתוכה.</p>` : ""}</section>`).join("")
        : `<div class="mf-empty big">${ic("search")}<p>לא נמצא «${esc(q)}» באף פגישה.</p></div>`;
    }
    input.addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(search, 250); });
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") { input.value = ""; search(); } });
    window.addEventListener("keydown", function slash(e) { if (dead) { window.removeEventListener("keydown", slash); return; } if ((e.key === "/" || e.code === "Slash") && !e.target.closest("input, textarea")) { e.preventDefault(); input.focus(); } });

    load();
    timers.push(setInterval(() => { if (!dead && !document.hidden && input.value.trim().length < 2) load(); }, 30000));
    return { destroy() { dead = true; for (const t of timers) clearInterval(t); if (ctl) ctl.abort(); } };
  };
  MF.start();
})();
