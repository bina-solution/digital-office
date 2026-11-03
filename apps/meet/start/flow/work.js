/* «פגישות» — work.js: what a meeting decided, who has to do what, what stayed open — and the moments people marked.
   Everything the machine proposes waits for a person: approved, it becomes work (a task goes to Plane with a link back
   to the moment it was said); rejected, it stays visible and greyed, never deleted. Every item jumps to its moment. */
(() => {
  "use strict";
  const MF = window.MF;
  const K = { task: "T", question: "Q", decision: "D" };
  MF.itemId = (kind, x, i) => (x && x.id ? String(x.id) : (K[kind] || "U") + (i + 1));
  MF.KIND = {
    task: { he: "משימה", many: "משימות", icon: "task", approve: "אישור ושליחה ל-Plane", approved: "אושרה" },
    decision: { he: "החלטה", many: "החלטות", icon: "flag", approve: "אישור ההחלטה", approved: "אושרה" },
    question: { he: "שאלה פתוחה", many: "שאלות פתוחות", icon: "help", approve: "סימון כנענתה", approved: "נענתה" },
    mark: { he: "סימון", many: "סימונים", icon: "bookmark", approve: "אישור", approved: "אושר" },
  };
  MF.MARK = { decision: "החלטה", task: "משימה", important: "חשוב", question: "שאלה" };
  MF.ST = { proposed: "ממתין לאישור", approved: "אושר", rejected: "נדחה", edited: "נערך — ממתין" };

  // one item as it is now: the meeting's data under the stored overrides (edited text, owner, due) and state
  MF.itemView = (kind, x, i, items) => {
    const id = MF.itemId(kind, x, i), key = `${kind}:${id}`, st = (items || {})[key] || {};
    const f = Object.assign({}, st.fields || {});
    return {
      kind, id, key, src: x, state: st.state === "edited" ? "proposed" : st.state || "proposed", edited: st.state === "edited" || !!st.fields,
      text: f.text ?? x.text ?? "", owner: f.owner ?? x.who ?? x.owner ?? "", due: f.due ?? x.due ?? "", t: +(f.t ?? x.t ?? x.s ?? 0),
      also: x.also || [], type: x.type || "", area: x.area || "", where: x.where || "", label: f.label || x.label || "",
      plane: st.plane || null, by: st.by || null, at: st.at || null,
    };
  };
  // the items of one kind in a meeting: its data, then what people added (live marks, a task from a moment)
  MF.itemsOf = (kind, M, items) => {
    const base = kind === "mark" ? [] : (({ task: M.tasks, decision: M.decisions, question: M.questions })[kind] || []).map((x, i) => MF.itemView(kind, x, i, items));
    const added = Object.entries(items || {}).filter(([k, v]) => k.startsWith(kind + ":") && (v.added || /^[um]\d/.test(k.slice(kind.length + 1))))
      .map(([k, v]) => MF.itemView(kind, Object.assign({ id: k.slice(kind.length + 1) }, v.fields || {}), 0, items));
    return base.concat(added).sort((a, b) => (kind === "mark" ? a.t - b.t : 0));
  };

  async function act(room, v, action, fields) {
    const r = await MF.api(`flow/${encodeURIComponent(room)}/items`, { method: "POST", body: { kind: v.kind, id: v.id, action, fields: fields || {} } });
    return r && r.item ? r.item : null;
  }
  MF.act = act;

  /* ---------- one card ---------- */
  MF.itemCard = (v, o = {}) => {
    const { esc, fmt, ic } = MF;
    const k = MF.KIND[v.kind];
    const facts = [];
    if (v.kind === "task") { if (v.owner) facts.push(["אחראי", `<bdi>${esc(v.owner)}</bdi>`]); if (v.due) facts.push(["מתי", `<span dir="auto">${esc(v.due)}</span>`]); if (v.where) facts.push(["איפה", `<span dir="auto">${esc(v.where)}</span>`]); if (v.area) facts.push(["תחום", `<span dir="auto">${esc(v.area)}</span>`]); }
    if (v.kind === "decision" && v.type) facts.push(["סוג", `<span dir="auto">${esc(v.type)}</span>`]);
    if (v.kind === "mark" && v.label) facts.push(["סוג", esc(MF.MARK[v.label] || v.label)]);
    if (o.meeting) facts.unshift(["פגישה", `<a href="${esc(MF.roomUrl(o.meeting.room))}" data-go>${esc(o.meeting.title || o.meeting.room)}</a>`]);
    const times = [v.t].concat(v.also || []).filter((x) => x != null && !isNaN(x));
    const seek = (x) => (o.meeting ? `<a class="mf-t" href="${esc(MF.roomUrl(o.meeting.room) + "#t" + Math.floor(x))}" data-go title="לפתוח את הפגישה ברגע הזה"><time dir="ltr">${fmt(x)}</time></a>` : `<button class="mf-t" type="button" data-seek="${x}" title="לנגן מהרגע הזה"><time dir="ltr">${fmt(x)}</time></button>`);
    let foot = "";
    if (o.readOnly) foot = "";
    else if (v.state === "approved") foot = `${v.plane && v.plane.url ? `<a class="btn sm ghost" href="${esc(v.plane.url)}" target="_blank" rel="noopener">${ic("external")}<span>ב-Plane${v.plane.key ? " · " + esc(v.plane.key) : ""}</span></a>` : ""}<button class="btn sm ghost" type="button" data-a="reopen">פתיחה מחדש</button>`;
    else if (v.state === "rejected") foot = `<button class="btn sm ghost" type="button" data-a="reopen">פתיחה מחדש</button>`;
    else foot = `<button class="btn sm" type="button" data-a="approve">${ic(v.kind === "task" ? "send" : "tick")}<span>${esc(k.approve)}</span></button><button class="btn sm ghost" type="button" data-a="edit">עריכה</button><button class="btn sm ghost danger" type="button" data-a="reject">דחייה</button>`;
    if (o.compact) {
      const meta = facts.slice(0, 4).map(([a, b]) => `<span><span class="k">${a}</span> ${b}</span>`).join("");
      return `<article class="mf-item compact" data-key="${esc(v.key)}" data-state="${v.state}"${o.meeting ? ` data-room="${esc(o.meeting.room)}"` : ""}>
        <div class="mf-item-main"><header class="mf-item-h">${ic(k.icon)}<span class="mf-st" data-st="${v.state}">${esc(v.state === "approved" ? k.approved : MF.ST[v.state] || v.state)}</span>${times.slice(0, 1).map(seek).join("")}</header>
          <p class="mf-item-tx"${MF.dirAttr(v.text)}>${esc(v.text)}</p>${meta ? `<div class="mf-item-meta">${meta}</div>` : ""}</div>
        ${foot ? `<footer class="mf-item-f">${foot}</footer>` : ""}</article>`;
    }
    return `<article class="mf-item" data-key="${esc(v.key)}" data-state="${v.state}"${o.meeting ? ` data-room="${esc(o.meeting.room)}"` : ""}>
      <header class="mf-item-h">${ic(k.icon)}<span class="mf-item-id" dir="ltr">${esc(v.id)}</span><span class="mf-st" data-st="${v.state}">${esc(v.state === "approved" ? k.approved : MF.ST[v.state] || v.state)}</span>${v.edited ? `<span class="mf-tag">${ic("edit")}נערך</span>` : ""}<span class="mf-grow"></span>${times.slice(0, 4).map(seek).join("")}</header>
      <p class="mf-item-tx"${MF.dirAttr(v.text)}>${esc(v.text)}</p>
      ${facts.length ? `<dl class="mf-facts">${facts.map(([a, b]) => `<div><dt>${a}</dt><dd>${b}</dd></div>`).join("")}</dl>` : ""}
      ${foot ? `<footer class="mf-item-f">${foot}</footer>` : ""}
    </article>`;
  };

  /* ---------- a card's actions (one handler for a whole list, in a meeting or across meetings) ---------- */
  MF.bindItems = (root, getCtx) => {
    root.addEventListener("click", async (e) => {
      const s = e.target.closest("[data-seek]");
      if (s) { const c = getCtx(null); if (c.stage) { c.stage.seek(+s.dataset.seek); } return; }
      const b = e.target.closest("[data-a]"); if (!b) return;
      const card = b.closest(".mf-item"), c = getCtx(card);
      const v = c.find(card.dataset.key); if (!v) return;
      const a = b.dataset.a;
      if (a === "edit") return editCard(card, v, c);
      if (a === "reject" && !(await MF.ask({ title: `לדחות את ה${MF.KIND[v.kind].he}?`, body: "היא תישאר ברשימה, מסומנת כנדחתה — אפשר לפתוח אותה מחדש.", ok: "דחייה", danger: true, facts: [["נאמר ב-", MF.fmt(v.t)], ["הטקסט", v.text.slice(0, 120)]] }))) return;
      b.disabled = true; b.classList.add("busy");
      try {
        const item = await act(c.room, v, a);
        c.store(v.key, item || { state: a === "approve" ? "approved" : a === "reject" ? "rejected" : "proposed" });
        if (a === "approve" && v.kind === "task") {
          const p = item && item.plane;
          MF.tell(p && p.key ? `המשימה נשלחה ל-Plane · ${p.key}` : "המשימה אושרה ונשלחה ל-Plane", "ok", p && p.url ? { act: ["פתיחה", () => window.open(p.url, "_blank", "noopener")] } : {});
        } else MF.tell(a === "approve" ? `${MF.KIND[v.kind].he}: ${MF.KIND[v.kind].approved}` : a === "reject" ? "נדחתה" : "נפתחה מחדש", "ok");
        c.changed();
      } catch (err) {
        b.disabled = false; b.classList.remove("busy");
        MF.tell(err.message || "הפעולה נכשלה", "bad", { more: err.doc ? JSON.stringify(err.doc) : "", stay: err.code === 502 });
      }
    });
  };
  function editCard(card, v, c) {
    if (card.querySelector(".mf-item-edit")) return;
    const { esc } = MF;
    const people = c.people || [];
    const tx = card.querySelector(".mf-item-tx"); tx.hidden = true;
    tx.insertAdjacentHTML("afterend", `<div class="mf-item-edit">
      <label class="field"><span>הטקסט</span><textarea rows="3" dir="auto" name="text">${esc(v.text)}</textarea></label>
      ${v.kind === "task" ? `<div class="mf-edit-row"><label class="field"><span>אחראי</span><input name="owner" dir="auto" list="mf-people" value="${esc(v.owner)}"></label><label class="field"><span>מתי</span><input name="due" dir="auto" value="${esc(v.due)}" placeholder="למשל 2026-11-02 או «לפני התשלומים»"></label></div><datalist id="mf-people">${people.map((p) => `<option value="${esc(p)}">`).join("")}</datalist>` : ""}
      <div class="mf-edit-acts"><button class="btn sm" type="button" data-e="save">שמירה</button><button class="btn sm ghost" type="button" data-e="cancel">ביטול</button></div></div>`);
    const box = card.querySelector(".mf-item-edit");
    box.querySelector("textarea").focus();
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-e]"); if (!b) return;
      if (b.dataset.e === "cancel") { box.remove(); tx.hidden = false; return; }
      const fields = { text: box.querySelector("[name=text]").value.trim() };
      if (v.kind === "task") { fields.owner = box.querySelector("[name=owner]").value.trim(); fields.due = box.querySelector("[name=due]").value.trim(); }
      if (!fields.text) { MF.tell("הטקסט ריק", "warn"); return; }
      b.disabled = true; b.classList.add("busy");
      try { const item = await act(c.room, v, "edit", fields); c.store(v.key, item || { state: "edited", fields }); MF.tell("נשמר", "ok"); c.changed(); }
      catch (err) { b.disabled = false; b.classList.remove("busy"); MF.tell(err.message, "bad"); }
    });
  }

  /* ---------- a list of one kind, inside a meeting ---------- */
  MF.WorkList = function WorkList(el, ctx) {
    const { esc, ic } = MF;
    const kind = ctx.kind, k = MF.KIND[kind];
    let filter = MF.store.get("wf:" + kind, "all"), who = "";
    function views() { return MF.itemsOf(kind, ctx.M, ctx.items); }
    function render() {
      const all = views();
      const n = { all: all.length, proposed: all.filter((v) => v.state === "proposed").length, approved: all.filter((v) => v.state === "approved").length, rejected: all.filter((v) => v.state === "rejected").length };
      const owners = kind === "task" ? [...new Set(all.map((v) => v.owner).filter(Boolean))] : [];
      const shown = all.filter((v) => (filter === "all" || v.state === filter) && (!who || v.owner === who));
      const seg = [["all", "הכול"], ["proposed", "ממתין"], ["approved", kind === "question" ? "נענו" : "אושרו"], ["rejected", "נדחו"]];
      el.innerHTML = `
        <div class="mf-work-bar">
          <div class="mf-seg" role="tablist" aria-label="סינון לפי מצב">${seg.map(([s, h]) => `<button type="button" role="tab" data-f="${s}" aria-selected="${filter === s}"${n[s] ? "" : " disabled"}>${h}<span class="n">${MF.num(n[s])}</span></button>`).join("")}</div>
          ${owners.length > 1 ? `<div class="mf-who-filter" role="group" aria-label="אחראי">${owners.map((w) => `<button type="button" class="mf-chip" data-own="${esc(w)}" aria-pressed="${who === w}">${MF.avatar(w, ctx.hue(w))}<bdi>${esc(w)}</bdi></button>`).join("")}</div>` : ""}
          ${kind === "task" && n.proposed ? `<button class="btn sm ghost" type="button" data-bulk="1" title="לאשר ולשלוח ל-Plane את כל המשימות שמוצגות וממתינות">${ic("send")}<span>אישור כל המוצגות</span></button>` : ""}
          ${kind === "task" ? `<button class="btn sm ghost" type="button" data-add="1">${ic("plus")}<span>משימה חדשה</span></button>` : ""}
        </div>
        <div class="mf-items">${shown.map((v) => MF.itemCard(v)).join("") || `<div class="mf-empty">${ic(k.icon)}<p>${all.length ? "אין פריטים במצב הזה." : `אין ${k.many} בפגישה הזו${ctx.M.meeting && ctx.state === "first" ? " עדיין — הן יופיעו אחרי העיבוד המלא" : ""}.`}</p></div>`}</div>`;
    }
    el.addEventListener("click", async (e) => {
      const f = e.target.closest("[data-f]"); if (f) { filter = f.dataset.f; MF.store.set("wf:" + kind, filter); render(); return; }
      const o = e.target.closest("[data-own]"); if (o) { who = who === o.dataset.own ? "" : o.dataset.own; render(); return; }
      if (e.target.closest("[data-add]")) { addTask(); return; }
      if (e.target.closest("[data-bulk]")) {
        const todo = views().filter((v) => v.state === "proposed" && (!who || v.owner === who));
        if (!todo.length) return;
        if (!(await MF.ask({ title: `לשלוח ${MF.num(todo.length)} משימות ל-Plane?`, body: "כל אחת תהיה פריט עבודה ב-Plane עם קישור לרגע שבו נאמרה.", ok: `שליחת ${MF.num(todo.length)}`, facts: [["אחראים", [...new Set(todo.map((v) => v.owner || "—"))].join(", ")], ["פגישה", ctx.title || ctx.room]] }))) return;
        let ok = 0, bad = 0;
        for (const v of todo) { try { const item = await act(ctx.room, v, "approve"); ctx.store(v.key, item || { state: "approved" }); ok++; } catch (err) { bad++; if (err.code === 502) break; } }
        MF.tell(bad ? `נשלחו ${MF.num(ok)}, ${MF.num(bad)} נכשלו` : `נשלחו ${MF.num(ok)} משימות ל-Plane`, bad ? "warn" : "ok");
        ctx.changed();
      }
    });
    async function addTask(pre) {
      pre = pre || {};
      const text = await MF.ask({ title: "משימה חדשה מהפגישה", body: pre.t != null ? `מהרגע ${MF.fmt(pre.t)}` : "", input: { label: "מה צריך לעשות", value: pre.text || "" }, ok: "הוספה" });
      if (text == null || !String(text).trim()) return;
      try {
        const r = await MF.api(`flow/${encodeURIComponent(ctx.room)}/items`, { method: "POST", body: { kind: "task", id: null, action: "add", fields: { text: String(text).trim(), t: pre.t ?? (ctx.stage ? ctx.stage.t : 0), owner: pre.owner || "" } } });
        const it = r && r.item; if (it && it.id) ctx.store(`task:${it.id}`, Object.assign({ added: true }, it));
        MF.tell("המשימה נוספה — ממתינה לאישור", "ok"); ctx.changed();
      } catch (err) { MF.tell(err.message, "bad"); }
    }
    MF.bindItems(el, () => ({ room: ctx.room, stage: ctx.stage, people: ctx.people, find: (key) => views().find((v) => v.key === key), store: ctx.store, changed: ctx.changed }));
    render();
    return { render, addTask };
  };
})();
