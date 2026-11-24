// עזריה — the screen (EXU-64). One list of every conversation (Azaria's and Claude's), one conversation,
// one composer. Data: the adapter's /ui door (adapter/ui.mjs), addressed RELATIVE to the page, so the same
// file works on azaria.<domain> and framed by the console under /a/bina/. No library, no build.
(() => {
  "use strict";
  const BASE = new URL(".", document.baseURI);
  const app = document.getElementById("app");
  const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;

  // ── small helpers ────────────────────────────────────────────────────────────────────────────
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ic = (n, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
  const turnsText = (n) => (n === 1 ? "תור אחד" : `${n} תורות`);
  const callsText = (n) => (n === 1 ? "פעולה אחת" : `${n} פעולות`);
  async function api(path, opts = {}) {
    let r;
    try {
      r = await fetch(new URL("ui/" + path, BASE), { credentials: "same-origin", ...opts,
        headers: { ...(opts.body ? { "content-type": "application/json" } : {}), ...(opts.headers || {}) } });
    } catch { throw new Error("אין חיבור לעזריה כרגע. אפשר לנסות שוב."); }
    const text = await r.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = null; }
    if (!r.ok) throw new Error((body && body.error) || "עזריה לא ענה כרגע. אפשר לנסות שוב.");
    return body;
  }
  function ago(iso) {
    if (!iso) return "";
    const t = Date.parse(iso), now = Date.now(), s = (now - t) / 1000;
    if (s < 60) return "עכשיו";
    if (s < 3600) return `לפני ${Math.round(s / 60)} דק׳`;
    // today's and yesterday's rows sit under their own heading, so they say the hour
    const d = new Date(t), y = new Date(); y.setDate(y.getDate() - 1); y.setHours(0, 0, 0, 0);
    if (t >= y.getTime()) return d.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString("he-IL", { day: "numeric", month: "numeric" });
  }
  // what this device remembers for the person: pinned conversations and what was already read
  const store = {
    get(k, d) { try { const v = JSON.parse(localStorage.getItem(k) || "null"); return v ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* a private window */ } },
  };
  function groupOf(s) {
    if (st.pins.has(s.id)) return "pinned";
    if (s.running || s.waiting) return "now";
    if (!s.updated_at) return "older";
    const d = new Date(s.updated_at), today = new Date();
    if (d.toDateString() === today.toDateString()) return "today";
    const y = new Date(today); y.setDate(today.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return "yesterday";
    return (Date.now() - d.getTime()) < 7 * 86400000 ? "week" : "older";
  }
  const GROUPS = { pinned: "מוצמדות", now: "פעילות עכשיו", today: "היום", yesterday: "אתמול", week: "השבוע", older: "קודם" };
  // finished since the person last looked at it (the Claude apps' unread dot)
  const unread = (s) => !!(st.seen && s.updated_at && !s.running && !s.waiting && s.id !== st.cur && Date.parse(s.updated_at) > (st.seen[s.id] || 0));
  function markSeen(id) {
    const s = sessionOf(id);
    if (!st.seen || !s) return;
    const t = Date.parse(s.updated_at || "") || Date.now();
    if ((st.seen[id] || 0) >= t) return;
    st.seen[id] = t;
    store.set("azaria.seen", st.seen);
  }
  function togglePin(id) {
    const on = !st.pins.has(id);
    if (on) st.pins.add(id); else st.pins.delete(id);
    store.set("azaria.pins", [...st.pins]);
    st.pop = null; render(["list", "pop"]);
    toast(on ? "השיחה הוצמדה לראש הרשימה" : "ההצמדה בוטלה");
  }

  // where the other screens are: the harness's full interface (bina.<domain>) and the official Claude app
  // (the console's tile) — on the same domain, framed or not
  function sibling(label) {
    const framed = location.pathname.startsWith("/a/");
    if (framed && label === "console") return location.origin;
    // an address that is not a name (an IP, a bare `localhost`) has no siblings to derive: stay here
    if (/^[\d.:[\]]+$/.test(location.hostname) || !location.hostname.includes(".")) return location.origin;
    return `${location.protocol}//${location.host.replace(/^[^.]+\./, `${label}.`)}`;
  }
  const fullUi = (id) => `${sibling("bina")}/${id && !id.startsWith("local_") ? `?s=${encodeURIComponent(id)}` : ""}`;
  // the official Claude app's own tile — the first app's, or an instance's (`bina-claude-2`, DGO-1920) — by the
  // office's ONE link form, `<console>/go/<app>`, which the console resolves at click time and which survives the
  // sign-in (platform-base/console/links.py, gate G95)
  const claudeId = (app) => (/^bina-claude(-[A-Za-z0-9_.-]{1,60})?$/.test(app || "") ? app : "bina-claude");
  const officialClaude = (app) => `${sibling("console")}/go/${claudeId(app)}`;
  // the office's apps screen, opened on a Claude app's card (DGO-2126): where the office does not run one, its
  // own «התקן» installs it (the one place an app is installed, with its room check); where it runs one that does
  // not answer, the card says what it is (stopped, off) and offers what fits
  const installClaude = (app) => `${sibling("console")}/go/apps?app=${claudeId(app)}`;
  // what a Claude app that does not answer IS (DGO-2126, its second reader): the office does not run it (never
  // installed, turned off or archived — `declared` false), it runs it and it does not answer now (true), or that is
  // not known (null); and when even `installed` was not said, nothing is known. Every place that shows an app's state
  // reads it here, so the place card, the sheets and the footer never disagree.
  function claudeState(c) {
    if (c && c.installed) return c.signed_in ? "on" : "out";
    if (!c || typeof c.installed !== "boolean") return "unknown";
    return c.declared === false ? "absent" : c.declared === true ? "down" : "silent";
  }
  const CLAUDE_WORD = { absent: "לא פועל בלשכה", down: "מותקן, לא עונה כרגע", silent: "לא עונה כרגע", unknown: "לא ידוע כרגע" };
  // the one action that fits a Claude app that does not answer: its install, its card, or nothing
  const claudeFix = (c, cls) => {
    const s = claudeState(c);
    if (s === "absent") return `<a class="btn sm" href="${esc(installClaude(c.id))}" target="${outTarget}" rel="noopener" title="מסך האפליקציות של הלשכה נפתח על קלוד דסקטופ">${ic("plus", "sm")}התקנה</a>`;
    if (s === "down" || s === "silent") return `<a class="btn sm ghost${cls || ""}" href="${esc(installClaude(c.id))}" target="${outTarget}" rel="noopener" title="מסך האפליקציות של הלשכה נפתח על קלוד דסקטופ">${ic("ext", "sm")}במסך האפליקציות</a>`;
    return "";
  };
  const outTarget = window.top !== window ? "_top" : "_blank";

  // ── Markdown, escaped FIRST: nothing in a reply can become markup of its own ─────────────────
  function inline(s) {
    return s
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
  // prose between code blocks (already escaped): headings, bullets, and tables — the answers are full of them
  function prose(part) {
    const lines = part.split("\n"), out = [];
    const row = (l) => /^\s*\|.*\|\s*$/.test(l);
    const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (row(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        let t = `<div class="tbl"><table><thead><tr>${cells(line).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
        for (i += 2; i < lines.length && row(lines[i]); i++) t += `<tr>${cells(lines[i]).map((c) => `<td>${c}</td>`).join("")}</tr>`;
        i--;
        out.push(`${t}</tbody></table></div>`);
        continue;
      }
      const h = /^#{1,4}\s+(.*)$/.exec(line);
      if (h) { out.push(`<span class="h">${inline(h[1])}</span>`); continue; }
      const b = /^(\s*)[-*]\s+(.*)$/.exec(line);
      out.push(b ? `${b[1]}• ${inline(b[2])}` : inline(line));
    }
    return out.join("\n");
  }
  // Markdown, escape-first. A code block carries its language and a copy button, as in the Claude apps.
  // Remembered by text: a long conversation re-renders on every poll, and its old answers do not change.
  // markdown-it (vendor/, pinned, `html: false` — nothing in a reply can become markup of its own): every block
  // reads in its own direction (dir=auto), a code block carries its language and a copy button, a table scrolls
  // sideways on a phone, and a link opens outside the conversation.
  const MD = (() => {
    if (typeof window.markdownit !== "function") return null;
    const md = window.markdownit({ html: false, linkify: true, breaks: true, typographer: false });
    const fence = (tokens, i) => {
      const t = tokens[i], lang = String(t.info || "").trim().split(/\s+/)[0];
      return `<div class="code"><div class="code-bar"><span>${esc(lang || "קוד")}</span><button type="button" class="icbtn" data-codecopy="1" title="העתקת הקוד" aria-label="העתקת הקוד">${ic("copy", "sm")}</button></div><pre><code>${esc(t.content.replace(/\n$/, ""))}</code></pre></div>`;
    };
    md.renderer.rules.fence = fence;
    md.renderer.rules.code_block = fence;
    md.renderer.rules.table_open = () => `<div class="tbl"><table>`;
    md.renderer.rules.table_close = () => `</table></div>`;
    const linkOpen = md.renderer.rules.link_open || ((tokens, i, o, e, self) => self.renderToken(tokens, i, o));
    md.renderer.rules.link_open = (tokens, i, o, e, self) => { tokens[i].attrSet("target", "_blank"); tokens[i].attrSet("rel", "noopener"); return linkOpen(tokens, i, o, e, self); };
    md.core.ruler.push("dir_auto", (state) => {
      for (const t of state.tokens) if (/^(paragraph|heading|blockquote|bullet_list|ordered_list)_open$/.test(t.type)) t.attrSet("dir", "auto");
    });
    return md;
  })();
  const mdMemo = new Map();
  function markdown(text) {
    const hit = mdMemo.get(text);
    if (hit !== undefined) return hit;
    let html;
    try { html = MD ? MD.render(String(text || "")) : `<div class="plain">${legacyMarkdown(text)}</div>`; }
    catch { html = `<div class="plain">${legacyMarkdown(text)}</div>`; }
    if (mdMemo.size > 3000) mdMemo.clear();
    mdMemo.set(text, html);
    return html;
  }
  // the screen's own renderer, kept for a page whose vendor file did not load
  function legacyMarkdown(text) {
    const src = esc(text), out = [];
    const re = /```([^\n`]*)\n?([\s\S]*?)(?:```|$)/g;
    let last = 0, m;
    while ((m = re.exec(src)) !== null) {
      out.push(prose(src.slice(last, m.index)));
      out.push(`<div class="code"><div class="code-bar"><span>${m[1].trim() || "קוד"}</span><button type="button" class="icbtn" data-codecopy="1" title="העתקת הקוד" aria-label="העתקת הקוד">${ic("copy", "sm")}</button></div><pre><code>${m[2].replace(/\n$/, "")}</code></pre></div>`);
      last = re.lastIndex;
      if (last >= src.length) break;
    }
    out.push(prose(src.slice(last)));
    return out.join("");
  }

  // ── a conversation's events → what the Claude apps show ──────────────────────────────────────
  const TOOL_HE = [
    [/todo|plan/i, "עדכן תוכנית"],
    [/bash|shell|exec|command|terminal|pwsh/i, "הריץ פקודה"],
    [/edit|write|patch|replace|create_file/i, "ערך קובץ"],
    [/read|view|cat|open/i, "קרא קובץ"],
    [/grep|glob|search_files|find|ls|list/i, "חיפש בקבצים"],
    [/web|fetch|browse|search/i, "חיפש ברשת"],
    [/task|agent|subagent|delegate/i, "האציל לסוכן"],
  ];
  const toolHe = (name) => (TOOL_HE.find(([re]) => re.test(name || "")) || [null, "השתמש בכלי"])[1];
  function argOf(e) {
    const a = e.input || e.args || e.arguments || {};
    if (typeof a === "string") return a.slice(0, 160);
    for (const k of ["command", "cmd", "file_path", "path", "pattern", "url", "query", "description", "prompt"]) if (typeof a[k] === "string" && a[k]) return a[k].split("\n")[0].slice(0, 160);
    const s = JSON.stringify(a);
    return s === "{}" ? "" : s.slice(0, 160);
  }
  function errOf(e) {
    const r = e.reason;
    const err = e.error || (r && typeof r === "object" && (r.error || (/error|fail/i.test(r.kind || "") ? r : null)));
    if (!err) return null;
    return [err.code, err.message].filter(Boolean).join(": ") || "שגיאה";
  }
  // A turn the app itself injects (Claude Code's <task-notification>, <system-reminder>, a slash command's
  // <command-name>…) is one tagged block from start to end; the Claude apps do not show it as yours.
  const CONTINUED = /^\s*This session is being continued from a previous conversation/;
  const SYSTEM_MSG = /^\s*<(task-notification|system-reminder|local-command-caveat|user-memory-input|command-name|command-message|command-args|local-command-stdout|local-command-stderr|bash-input|bash-stdout|bash-stderr|user-prompt-submit-hook|tool_use_error)(\s[^>]*)?>[\s\S]*<\/\1>\s*$/i;
  // A conversation's events → BLOCKS, each with a stable key (its first event's seq), so the screen redraws only
  // the blocks that changed:
  //   u      the person's message              a      a text of an answer
  //   work   the thinking and the tool calls between two texts — ONE folded row, as Claude Code shows its work
  //   sum    the summary a carried-over conversation opens with
  //   err / warn   how a turn ended badly
  function toBlocks(events) {
    const out = [];
    let work = null;
    // The office's Stop hook sent Claude back after its answer (the Claude door says so with a `hook` event): what
    // Claude writes next is the same turn going on, not a reply to anything new (DGO-2037, the HP: every answer came
    // twice, the second one unexplained). Said once, quietly, where it goes on — and only after that event: a slash
    // command or an image-only message also leaves no message of the person's, and they are not this (second reader).
    let hooked = false;
    const goesOn = (seq) => { if (hooked) { hooked = false; work = null; out.push({ k: "cont", key: `c${seq}` }); } };
    const workAt = (seq) => { goesOn(seq); if (!work) { work = { k: "work", key: `w${seq}`, steps: [] }; out.push(work); } return work; };
    for (const e of events || []) {
      const seq = e.seq ?? out.length;
      if (e.type === "hook") { hooked = true; continue; }
      if (e.type === "turn.start") hooked = false;
      if (e.type === "user") {
        if (e.source && e.source !== "user") continue;
        if (!e.text || SYSTEM_MSG.test(e.text)) continue;
        work = null; hooked = false;
        // a conversation carried over from one that ran out of room opens with its summary: a note, not a bubble
        out.push(CONTINUED.test(e.text) ? { k: "sum", key: `s${seq}`, text: e.text } : { k: "u", key: `u${seq}`, seq: Number(seq), text: e.text });
      } else if (e.type === "assistant") {
        if (e.text && e.text.trim()) { goesOn(seq); work = null; out.push({ k: "a", key: `a${seq}`, text: e.text }); }
      } else if (e.type === "reasoning") {
        if (e.text && e.text.trim()) workAt(seq).steps.push({ kind: "think", text: e.text });
      } else if (e.type === "tool.call") {
        workAt(seq).steps.push({ kind: "tool", id: e.id, name: e.name || e.tool || "", arg: argOf(e), ok: null });
      } else if (e.type === "tool.result") {
        for (let i = out.length - 1; i >= 0; i--) {
          const t = out[i].k === "work" && out[i].steps.find((x) => x.kind === "tool" && x.id === e.id);
          if (t) { t.ok = e.ok !== false; break; }
        }
      } else if (e.type === "turn.end") {
        work = null;
        const msg = errOf(e);
        const kind = typeof e.reason === "string" ? e.reason : e.reason && e.reason.kind;
        if (msg) out.push({ k: "err", key: `n${seq}`, text: msg });
        else if (kind === "max-tokens") out.push({ k: "warn", key: `n${seq}`, text: "התשובה נקטעה: המודל הגיע למגבלת האורך שלו." });
        else if (/cancel|interrupt|abort/i.test(kind || "")) out.push({ k: "warn", key: `n${seq}`, text: "נעצר." });
      }
    }
    return out;
  }
  // a «work» row in words, counted as a person says it: «חשב · הריץ 3 פקודות · ערך קובץ»
  const COUNTED = {
    "הריץ פקודה": (n) => (n === 1 ? "הריץ פקודה" : `הריץ ${n} פקודות`),
    "ערך קובץ": (n) => (n === 1 ? "ערך קובץ" : `ערך ${n} קבצים`),
    "קרא קובץ": (n) => (n === 1 ? "קרא קובץ" : `קרא ${n} קבצים`),
    "האציל לסוכן": (n) => (n === 1 ? "האציל לסוכן" : `האציל ל-${n} סוכנים`),
    "השתמש בכלי": (n) => (n === 1 ? "השתמש בכלי" : `השתמש ב-${n} כלים`),
  };
  function workLabel(steps) {
    const counts = new Map();
    for (const s of steps) if (s.kind === "tool") { const l = toolHe(s.name); counts.set(l, (counts.get(l) || 0) + 1); }
    const parts = [...counts].map(([l, n]) => (COUNTED[l] ? COUNTED[l](n) : l));
    if (steps.some((s) => s.kind === "think")) parts.unshift("חשב");
    const shown = parts.slice(0, 3), extra = parts.length - shown.length;
    return { text: shown.join(" · ") || "עבד", extra };
  }

  // ── state ────────────────────────────────────────────────────────────────────────────────────
  const asked = new URLSearchParams(location.search).get("s");
  const PICK_KEY = "azaria.pick";                                    // the model chosen last, on this device
  let saved = null;
  try { const v = JSON.parse(localStorage.getItem(PICK_KEY) || "null"); if (v && (v.engine === "claude" || v.engine === "azaria")) saved = v; } catch { /* none */ }
  const st = {
    sessions: null, engines: {}, filter: "all", q: "", cur: asked ? null : "new", events: [], loadedFor: null, sig: "",
    drawer: false, pop: null, models: null, pick: saved, sending: false, pending: null, error: "", asked,
    draft: "", drafts: {}, openTools: new Set(), busy: { list: false, thread: false },
    more: false, full: new Set(), loadingOld: false, outbox: null, popId: null,
    stream: { id: null, text: "", think: "" }, answers: {}, answering: null, editing: null, files: [],
    pins: new Set(store.get("azaria.pins", [])), seen: store.get("azaria.seen", null), providers: null, binding: null,
    // Claude's door takes a message at once and hands it to the app in the background (DGO-2044): the
    // conversations whose message is still being handed over, and the ones whose message was not sent (why, and its words)
    handing: new Set(), unsent: {},
    // …and, of those, the ones waiting in the Claude app's line (its cap of turns at once, DGO-2126): id → place
    queued: {},
    // a message the stream already showed in its conversation (the app took it; the door's hand-over is finishing),
    // and the promises (`pending-…`) that started, each → the id it goes on under
    landed: new Set(), adopted: new Map(),
    // the last event a conversation held when a message to Claude went (a «not known» note looks only past it)
    sentSeq: {},
  };
  // The message just sent shows up as a person's event with a sequence number past the last one seen when
  // it went: counted by sequence, not by how many there are, because both engines return a window of the
  // last 400 events, and the newest one pushes the oldest out.
  const lastSeq = (events) => { const e = events && events[events.length - 1]; const n = e ? Number(e.seq) : NaN; return Number.isFinite(n) ? n : -1; };
  const arrived = (events, p) => (events || []).some((e) => e.type === "user" && (!e.source || e.source === "user") && Number(e.seq) > p.seq && !SYSTEM_MSG.test(e.text || ""));
  const sessionOf = (id) => (st.sessions || []).find((s) => s.id === id) || null;
  // a Claude conversation's app (its row says it), sent with every call about it: the door then asks that app first,
  // whatever it still remembers (second reader, DGO-2036)
  const rowApp = (id) => { const s = sessionOf(id); return s && s.engine === "claude" && typeof s.app === "string" ? s.app : null; };
  const appQ = (id) => (rowApp(id) ? `&app=${encodeURIComponent(rowApp(id))}` : "");
  const appOfRow = (id) => (rowApp(id) ? { app: rowApp(id) } : {});
  const cur = () => (st.cur && st.cur !== "new" ? sessionOf(st.cur) : null);
  // Is the open conversation working? Its own events say so first-hand (a turn that started and has not
  // ended); the list's flag can lag behind a stop by a few seconds.
  function working(s) {
    if (!s) return st.sending;
    if (st.sending) return true;
    if (st.pending && st.pending.id === s.id) return true;          // sent, and its turn has not shown up yet
    if (st.handing.has(s.id)) return true;                         // still being handed to the Claude app
    if (st.loadedFor === s.id && st.events.length) {
      let start = -1, end = -1;
      st.events.forEach((e, i) => { if (e.type === "turn.start") start = i; else if (e.type === "turn.end") end = i; });
      if (start > end) {
        // an open turn — unless the list says the conversation rests AND nothing has happened for 90 s
        // (a turn that died without its end must not leave the stop button on for good)
        const last = st.events[st.events.length - 1];
        const fresh = last && last.at && Date.now() - Date.parse(last.at) < 90000;
        return !!s.running || !!fresh;
      }
      if (start >= 0 || end >= 0) return false;
    }
    return !!s.running;
  }
  // a conversation's title: the list's, else the last one its events gave it
  function titleOf(s) {
    if (s && s.title) return s.title;
    if (s && st.loadedFor === s.id) for (let i = st.events.length - 1; i >= 0; i--) if (st.events[i].type === "title" && st.events[i].title) return st.events[i].title;
    return "שיחה ללא שם";
  }
  // Every Claude app of the office (DGO-1920 instances: `bina-claude`, `bina-claude-2`, …), each on its own account;
  // a door from before instances says only `claude`, the first. An app named and not found is no app.
  const claudes = () => {
    const m = st.models;
    if (m && Array.isArray(m.claudes) && m.claudes.length) return m.claudes;
    return m && m.claude ? [{ id: "bina-claude", key: "", title: null, ...m.claude }] : [];
  };
  const claudeApp = (id) => { const all = claudes(); return id ? all.find((c) => c.id === id) || null : all[0] || null; };
  const claudeOk = (id) => { const c = claudeApp(id); return !!(c && c.installed && c.signed_in); };
  // its name on the screen: «Claude» for the first; an instance's own title («קלוד דסקטופ 2»), else «Claude 2»
  const claudeName = (id) => { const c = claudeApp(id); return !c || !c.key ? "Claude" : (c.title && (c.title.he || c.title.en)) || `Claude ${c.key}`; };

  // ── the frame, built once ────────────────────────────────────────────────────────────────────
  app.innerHTML = `
    <aside class="side" id="side" aria-label="השיחות">
      <div class="brand"><span class="mark" aria-hidden="true">ע</span><b>עזריה</b>
        <button type="button" class="icbtn only-phone" data-act="drawer-close" title="סגירת הרשימה" aria-label="סגירת הרשימה">${ic("x")}</button></div>
      <button type="button" class="newbtn" data-act="new" title="שיחה חדשה">${ic("new", "sm")}שיחה חדשה</button>
      <label class="search">${ic("search", "sm")}<input id="q" type="search" placeholder="חיפוש בשיחות" aria-label="חיפוש בשיחות" autocomplete="off"></label>
      <div class="chips" id="chips" role="group" aria-label="סינון לפי מנוע"></div>
      <nav class="list" id="rows" aria-label="רשימת השיחות"></nav>
      <div class="foot" id="foot"></div>
    </aside>
    <div class="scrim-side" data-act="drawer-close"></div>
    <section class="main">
      <header class="top" id="top"></header>
      <div id="body" class="thread"></div>
      <button type="button" class="tobottom" id="tobottom" data-act="bottom" title="לסוף השיחה" aria-label="לסוף השיחה" hidden>${ic("down")}</button>
      <div class="cwrap" id="cwrap"></div>
    </section>
    <div id="pop"></div>
    <svg width="0" height="0" style="position:absolute" aria-hidden="true">
      <symbol id="i-menu" viewBox="0 0 24 24"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></symbol>
      <symbol id="i-up" viewBox="0 0 24 24"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></symbol>
      <symbol id="i-stop" viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1.5"/></symbol>
      <symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></symbol>
      <symbol id="i-x" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></symbol>
      <symbol id="i-down" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></symbol>
      <symbol id="i-more" viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></symbol>
      <symbol id="i-pin" viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></symbol>
      <symbol id="i-edit" viewBox="0 0 24 24"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></symbol>
      <symbol id="i-trash" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></symbol>
      <symbol id="i-left" viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"/></symbol>
      <symbol id="i-term" viewBox="0 0 24 24"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></symbol>
      <symbol id="i-pen" viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></symbol>
      <symbol id="i-file" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></symbol>
      <symbol id="i-tool" viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></symbol>
      <symbol id="i-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></symbol>
      <symbol id="i-new" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></symbol>
      <symbol id="i-ext" viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></symbol>
      <symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></symbol>
      <symbol id="i-zap" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></symbol>
      <symbol id="i-cpu" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/></symbol>
      <symbol id="i-msg" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></symbol>
      <symbol id="i-login" viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></symbol>
      <symbol id="i-clip" viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></symbol>
      <symbol id="i-image" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></symbol>
      <symbol id="i-sliders" viewBox="0 0 24 24"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></symbol>
      <symbol id="i-plus" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></symbol>
      <symbol id="i-key" viewBox="0 0 24 24"><circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3 21 2"/><path d="m16 7 3 3"/><path d="m19 4 2 2"/></symbol>
    </svg>`;
  const el = { side: document.getElementById("side"), chips: document.getElementById("chips"), rows: document.getElementById("rows"), foot: document.getElementById("foot"),
               top: document.getElementById("top"), body: document.getElementById("body"), cwrap: document.getElementById("cwrap"), pop: document.getElementById("pop"), q: document.getElementById("q"),
               down: document.getElementById("tobottom") };

  // ── the list ─────────────────────────────────────────────────────────────────────────────────
  // the model a conversation runs on, in words: «Opus 5.5», «DeepSeek-V4-Pro», «qwen3.5:4b · 4.2B»
  function modelOf(s) {
    if (!s || !s.model) {
      if (s && s.engine === "claude") return "האפליקציה הרשמית";
      const d = st.models && st.models.azaria && st.models.azaria.default;   // a conversation not yet started runs on the default
      return d ? placeName({ engine: "azaria", provider: d.provider, model: d.model }) : "";
    }
    if (s.engine === "claude") {
      const m = /claude-(opus|sonnet|haiku|fable)-(\d+)-(\d+)/i.exec(s.model.model || "");
      return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}` : s.model.model || "Claude";
    }
    const name = modelName({ engine: "azaria", provider: s.model.provider, model: s.model.model }) || s.model.model || "";
    // a local model says which computer of the office it runs on: «Qwen 3.5 · 4B · Dell»
    return isLocal(s.model.provider) && name ? `${name} · ${computerName(s.model.provider)}` : name;
  }
  function rowHTML(s) {
    const tag = s.engine === "claude" ? `<span class="eng">${esc(s.app_key ? `Claude ${s.app_key}` : "Claude")}</span>` : `<span class="eng az">עזריה</span>`;
    const fresh = unread(s);
    const state = s.failed ? `<span class="dot bad"></span><span class="unsent">${s.maybe ? "לא ידוע אם נשלח" : "לא נשלח"}</span>`
      : s.waiting ? `<span class="dot wait"></span><span class="wait">ממתין לך</span>` : s.running ? `<span class="dot run" title="עובד עכשיו"></span>`
      : fresh ? `<span class="dot new" title="הסתיים מאז שהסתכלת"></span>` : "";
    return `<div class="rowwrap"><button type="button" class="row${fresh ? " unread" : ""}" data-s="${esc(s.id)}" aria-current="${st.cur === s.id}" title="${esc(s.title || "")}">
      <span class="t" dir="auto">${st.pins.has(s.id) ? ic("pin", "sm pinmark") : ""}${esc(s.title || "שיחה ללא שם")}</span><span class="w">${esc(ago(s.updated_at))}</span>
      <span class="m">${tag}${state}<span><bdi>${esc(modelOf(s))}</bdi></span></span></button>
      <button type="button" class="icbtn rmenu" data-act="rowmenu" data-id="${esc(s.id)}" title="פעולות על השיחה" aria-label="פעולות על השיחה">${ic("more", "sm")}</button></div>`;
  }
  function renderList() {
    // archived conversations leave the list and wait in their own chip, from which they come back
    const every = st.sessions || [];
    const all = every.filter((s) => !s.archived), shelf = every.filter((s) => s.archived);
    if (st.filter === "archived" && !shelf.length) st.filter = "all";
    const n = { all: all.length, azaria: all.filter((s) => s.engine === "azaria").length, claude: all.filter((s) => s.engine === "claude").length, archived: shelf.length };
    const chip = (k, t) => `<button type="button" class="chip" data-f="${k}" aria-pressed="${st.filter === k}">${t}<span class="n">${n[k]}</span></button>`;
    el.chips.innerHTML = chip("all", "הכל") + chip("azaria", "עזריה") + chip("claude", "Claude") + (shelf.length ? chip("archived", "ארכיון") : "");
    if (st.sessions === null) { el.rows.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`; return; }
    const q = st.q.toLowerCase();
    const pool = st.filter === "archived" ? shelf : all;
    const vis = pool.filter((s) => (st.filter === "all" || st.filter === "archived" || s.engine === st.filter) && (!q || (s.title || "").toLowerCase().includes(q)));
    let h = "";
    for (const g of Object.keys(GROUPS)) {
      const rows = vis.filter((s) => groupOf(s) === g);
      if (rows.length) h += `<div class="grp">${GROUPS[g]}</div>` + rows.map(rowHTML).join("");
    }
    // whose conversations did not come: Azaria's, and each Claude app that runs (one that is not running is no news)
    const eng = st.engines || {}, down = [];
    if (eng.azaria && !eng.azaria.ok) down.push("עזריה");
    if (eng.claudes) { for (const [id, v] of Object.entries(eng.claudes)) if (v && !v.ok && (claudeApp(id) || {}).installed !== false) down.push(claudeName(id)); }
    else if (eng.claude && !eng.claude.ok) down.push("Claude");
    if (down.length) h += `<div class="empty">${esc(down.join(" ו-"))}: השיחות לא נטענו כרגע</div>`;
    el.rows.innerHTML = h || `<div class="empty">${st.q ? "אין שיחה שמתאימה לחיפוש" : "עדיין אין שיחות. התחילו שיחה חדשה."}</div>`;
  }
  function renderFoot() {
    const all = claudes(), on = all.filter((x) => x.installed && x.signed_in).length, any = all.some((x) => x.installed);
    // none answers: not run by the office at all, or run and not answering (DGO-2126)
    const state = !st.models ? "בודק…" : !any ? (all.length && all.every((x) => claudeState(x) === "absent") ? "Claude לא פועל בלשכה" : "Claude לא עונה כרגע")
      : all.length > 1 ? `${on} מתוך ${all.length} אפליקציות Claude מחוברות` : on ? "Claude מחובר" : "Claude לא מחובר";
    const dot = any ? (on ? "ok" : "wait") : "";
    el.foot.innerHTML = `
      <button type="button" class="acct" data-act="account" title="Claude בתוך עזריה">
        <span class="avatar" aria-hidden="true">${ic("msg", "sm")}</span>
        <span class="who"><b>Claude</b><small><span class="dot ${dot}"></span>${state}</small></span></button>
      <button type="button" class="acct" data-act="providers" title="ספקים, מחשבים ואפליקציות — איפה שיחה יכולה לרוץ">
        <span class="avatar" aria-hidden="true">${ic("sliders", "sm")}</span>
        <span class="who"><b>איפה זה רץ</b><small>ספקים, מחשבים ואפליקציות</small></span></button>`;
  }

  // ── the conversation ─────────────────────────────────────────────────────────────────────────
  function engineChoice() {
    // the last choice on this device, while it can still be used (Claude signed in, the provider reachable)
    const p = st.pick;
    if (p && (p.engine === "claude" ? !st.models || claudeOk(p.app) : !p.provider || routable(p.provider))) return p;
    const d = st.models && st.models.azaria && st.models.azaria.default;
    // a default whose provider cannot be reached (no key) gives way to the first model that can
    if (d && !routable(d.provider)) {
      for (const g of (st.models.azaria.groups || [])) if (routable(g.id) && (g.models || []).length) return { engine: "azaria", provider: g.id, model: g.models[0].id };
      const c = claudes().find((x) => x.installed && x.signed_in);
      if (c) return { engine: "claude", app: c.id };
    }
    return d ? { engine: "azaria", provider: d.provider, model: d.model } : { engine: "azaria" };
  }
  // a model as a person names it — «Qwen 3.5 · 4B», «DeepSeek V4 Pro»; the id is the tooltip's
  const FAMILY = { qwen: "Qwen", lfm: "LFM", gemma: "Gemma", llama: "Llama", phi: "Phi", mistral: "Mistral", granite: "Granite" };
  function prettyModel(id) {
    const s = String(id || "");
    const m = /^([a-z]+)(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)b$/i.exec(s);  // qwen3.5:4b, lfm3:1.7b
    if (m) return `${FAMILY[m[1].toLowerCase()] || m[1]} ${m[2]} · ${m[3]}B`;
    if (/^deepseek-/i.test(s)) return s.replace(/^deepseek/i, "DeepSeek").replace(/-/g, " ").replace(/\bv(\d)/i, "V$1").replace(/\b(flash|pro|chat|reasoner)\b/gi, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
    return "";
  }
  function modelName(choice) {
    if (!choice) return "";
    if (choice.engine === "claude") return claudeName(choice.app);
    const groups = (st.models && st.models.azaria && st.models.azaria.groups) || [];
    for (const g of groups) for (const m of g.models || []) if (g.id === choice.provider && m.id === choice.model) return prettyModel(m.id) || m.name || m.id;
    return prettyModel(choice.model) || choice.model || "עזריה";
  }
  // the choice as the place it runs in: a local model names its computer («Qwen 3.5 · 4B · Dell»)
  const placeName = (choice) => (choice && choice.engine === "azaria" && isLocal(choice.provider) ? `${modelName(choice)} · ${computerName(choice.provider)}` : modelName(choice));
  // a provider the harness cannot reach (no key) is shown, and cannot be chosen
  const routable = (provider) => { const r = st.models && st.models.azaria && st.models.azaria.routableProviders; return !Array.isArray(r) || r.includes(provider); };
  // a model on a computer of the office (an Ollama, here or on a linked office: `dgo-ollama-<office>`), and that
  // computer as the link named it («Dell») — the door says it, from the registry the link wrote
  const isLocal = (provider) => /^dgo-ollama-|ollama|local/.test(provider || "");
  const computerName = (provider) => (st.models && st.models.computers && st.models.computers[provider]) || String(provider || "").replace(/^dgo-ollama-/, "");
  const groupName = (id) => { for (const g of (st.models && st.models.azaria && st.models.azaria.groups) || []) if (g.id === id) return g.name || g.id; return id; };
  // WHERE A NEW CONVERSATION RUNS (DGO-2032, the owner: «אני מתחיל שיחה ובוחר איפה זה רץ»): Azaria on a model in
  // the cloud, Azaria on a computer of the office, or the official Claude app. One card each, on the new
  // conversation's screen; the model inside a place is the composer's pill. A place that cannot run now opens
  // what it needs (a key from the secrets, the app's sign-in) instead of being a dead button.
  function places() {
    const az = st.models && st.models.azaria, d = az && az.default, ch = engineChoice();
    const groups = ((az && az.groups) || []).filter((g) => (g.models || []).length);
    const out = [];
    const cloud = groups.filter((g) => !isLocal(g.id));
    if (cloud.length) {
      // the cloud card follows the choice when it is a cloud one, else the default, else the first that can run
      const g = (ch.engine === "azaria" && ch.provider && !isLocal(ch.provider) && cloud.find((x) => x.id === ch.provider))
        || (d && cloud.find((x) => x.id === d.provider && routable(x.id))) || cloud.find((x) => routable(x.id)) || cloud[0];
      const m = ch.provider === g.id && ch.model ? ch.model : d && d.provider === g.id ? d.model : g.models[0].id;
      out.push({ key: "cloud", pick: { engine: "azaria", provider: g.id, model: m }, icon: "zap", name: "עזריה", sub: `${g.name || g.id} · בענן`, ok: routable(g.id) });
    }
    for (const g of groups.filter((x) => isLocal(x.id))) {
      const m = ch.provider === g.id && ch.model ? ch.model : d && d.provider === g.id ? d.model : g.models[0].id;
      out.push({ key: g.id, pick: { engine: "azaria", provider: g.id, model: m }, icon: "cpu", name: "עזריה", sub: `מקומי · ${computerName(g.id)}`, ok: routable(g.id) });
    }
    // every Claude app of the office: the first, and each further account (DGO-1920 instances)
    for (const c of claudes()) out.push({ key: `claude:${c.id}`, pick: { engine: "claude", app: c.id }, icon: "msg", name: claudeName(c.id),
                                          sub: c.key ? "חשבון Claude נוסף" : "האפליקציה הרשמית", ok: !!(c.installed && c.signed_in),
                                          // not run by the office at all, or run and not answering: two different things (DGO-2126)
                                          off: claudeState(c) === "absent", down: !c.installed && claudeState(c) !== "absent" });
    return out;
  }
  const placeOf = (ch) => (ch.engine === "claude" ? `claude:${(claudeApp(ch.app) || claudeApp() || { id: "bina-claude" }).id}` : ch.provider && isLocal(ch.provider) ? ch.provider : "cloud");
  function placesHTML() {
    const sel = placeOf(engineChoice());
    const cards = places().map((p) => {
      const why = p.ok ? "" : p.off ? "לא פועל בלשכה" : p.down ? "לא עונה כרגע" : p.key.startsWith("claude:") ? "לא מחובר" : p.icon === "cpu" ? "לא עונה כרגע" : "צריך מפתח";
      return `<button type="button" class="place" role="radio" aria-checked="${p.ok && p.key === sel}" ${p.ok ? `data-pick='${esc(JSON.stringify(p.pick))}'` : `data-act="providers"`} title="${esc(why || p.sub)}">
        ${ic(p.icon)}<span class="pn">${esc(p.name)}</span><small dir="auto">${esc(p.sub)}</small>${why ? `<em>${esc(why)}</em>` : ""}</button>`;
    }).join("");
    return `<div class="where" role="radiogroup" aria-label="איפה השיחה תרוץ"><span class="wl">איפה זה רץ</span><div class="places">${cards}
      <button type="button" class="place add" data-act="providers" title="ספקים, מחשבים ואפליקציות">${ic("plus")}<span class="pn">עוד מקום</span><small>ספק, מחשב או אפליקציה</small></button></div></div>`;
  }
  function renderTop() {
    const s = cur();
    let ttl, sub;
    if (st.cur === "new" || !st.cur) { ttl = "שיחה חדשה"; sub = `<span class="eng ${engineChoice().engine === "claude" ? "" : "az"}">${engineChoice().engine === "claude" ? "Claude" : "עזריה"}</span><bdi>${esc(placeName(engineChoice()))}</bdi>`; }
    else if (!s) { ttl = "טוען…"; sub = ""; }
    else {
      ttl = titleOf(s);
      sub = `${s.engine === "claude" ? `<span class="eng">${esc(s.app_key ? `Claude ${s.app_key}` : "Claude")}</span>` : `<span class="eng az">עזריה</span>`}<bdi>${esc(modelOf(s))}</bdi>`;
    }
    const running = working(s);
    const outLink = s ? (s.engine === "claude" ? officialClaude(s.app) : fullUi(s.id)) : fullUi(null);
    el.top.innerHTML = `
      <button type="button" class="icbtn only-phone" data-act="drawer" title="כל השיחות" aria-label="כל השיחות">${ic("menu")}</button>
      <div class="ttl"><b dir="auto">${esc(ttl)}</b><small>${sub}</small></div>
      ${!running ? "" : s && st.queued[s.id] ? `<span class="runpill only-desk"><span class="dot wait"></span>בתור</span>`
        : `<span class="runpill only-desk"><span class="dot run"></span>עובד</span>`}
      <a class="icbtn" href="${esc(outLink)}" target="${outTarget}" rel="noopener" title="${s && s.engine === "claude" ? "פתיחה באפליקציית Claude הרשמית" : "פתיחה בממשק המלא"}" aria-label="פתיחה מחוץ למסך">${ic("ext", "sm")}</a>
      <button type="button" class="icbtn only-phone" data-act="new" title="שיחה חדשה" aria-label="שיחה חדשה">${ic("new")}</button>`;
  }
  // the message on its way: the person's bubble, and what is happening to it
  // the per-conversation actions each engine allows beyond pinning: Azaria's harness renames and archives
  // (it has no delete — an archived conversation waits in «ארכיון» and comes back from there); a Claude
  // conversation is renamed and archived in the official app itself
  const ROW_ACTIONS = (s) => s.engine === "azaria"
    ? `<button type="button" class="opt" data-act="rename" data-id="${esc(s.id)}">${ic("edit")}<span class="nm">שינוי שם</span><span class="ds">השם שמופיע ברשימה ובראש השיחה</span></button>
       <button type="button" class="opt" data-act="${s.archived ? "unarchive" : "archive"}" data-id="${esc(s.id)}">${ic("trash")}<span class="nm">${s.archived ? "החזרה מהארכיון" : "העברה לארכיון"}</span><span class="ds">${s.archived ? "השיחה תחזור לרשימה" : "השיחה יוצאת מהרשימה ונשמרת בארכיון; אפשר להחזיר אותה בכל רגע"}</span></button>`
    : `<a class="opt" href="${esc(officialClaude(s.app))}" target="${outTarget}" rel="noopener">${ic("ext")}<span class="nm">פתיחה באפליקציה הרשמית</span><span class="ds">שינוי שם, ארכיון והרשאות של שיחת Claude נעשים שם</span></a>`;
  const outboxHTML = (o) => `<div class="msg-u" dir="auto">${esc(o.text)}</div>
    <div class="typing" role="status"><span class="dot run"></span>${o.claude ? "שולחים ל-Claude…" : "שולחים לעזריה…"}</div>`;
  function renderBody() {
    if ((st.cur === "new" || !st.cur) && st.outbox && st.outbox.id === "new") {
      el.body.className = "thread";
      el.body.innerHTML = `<div class="col">${outboxHTML(st.outbox)}</div>`;
      return;
    }
    if (st.cur === "new" || !st.cur) {
      el.body.className = "hero";
      el.body.innerHTML = `<span class="mark" aria-hidden="true">ע</span><h2>במה נעבוד היום?</h2>${placesHTML()}
        <div class="sugg"><button type="button" data-say="מה פתוח ומה הבא בתור?">מה פתוח ומה הבא בתור</button>
        <button type="button" data-say="בדוק שהלשכה בריאה ודווח בקצרה.">בדוק שהלשכה בריאה</button>
        <button type="button" data-say="סכם לי את מה שקרה היום בלשכה.">סכם לי את היום</button></div>`;
      return;
    }
    el.body.className = "thread";
    if (!view.col || view.for !== st.cur || !el.body.contains(view.col)) {
      el.body.innerHTML = "";
      view.col = document.createElement("div"); view.col.className = "col";
      el.body.appendChild(view.col); view.nodes.clear(); view.for = st.cur;
    }
    const near = el.body.scrollHeight - el.body.scrollTop - el.body.clientHeight < 120;
    patchThread(threadBlocks());
    if (near || st.scrollDown) { el.body.scrollTop = el.body.scrollHeight; st.scrollDown = false; }
    el.down.hidden = el.body.scrollHeight - el.body.scrollTop - el.body.clientHeight < 240;
  }

  // ── the conversation, block by block ─────────────────────────────────────────────────────────
  // Each block is drawn once into its own node, keyed, and redrawn only when its signature changes: an open
  // row stays open, a selection stays selected, and a conversation of thousands of events stays fast while
  // its newest answer streams in.
  const view = { col: null, nodes: new Map(), for: null };
  const nodeOf = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const info = (key, html) => ({ k: "info", key, html });
  function patchThread(blocks) {
    const col = view.col, keep = new Set();
    let prev = null;
    for (const b of blocks) {
      const sig = sigOf(b);
      let n = view.nodes.get(b.key);
      if (!n || n.sig !== sig) {
        const fresh = nodeOf(blockHTML(b));
        if (!fresh) continue;
        fresh.dataset.key = b.key;
        if (n) n.el.replaceWith(fresh);
        n = { el: fresh, sig };
        view.nodes.set(b.key, n);
      }
      const want = prev ? prev.nextSibling : col.firstChild;
      if (n.el !== want) col.insertBefore(n.el, want);
      prev = n.el; keep.add(b.key);
    }
    for (const [k, n] of view.nodes) if (!keep.has(k)) { n.el.remove(); view.nodes.delete(k); }
  }
  const opened = (key) => st.openTools.has(`${st.cur}:${key}`);
  function sigOf(b) {
    switch (b.k) {
      case "u": return `u|${b.editable ? 1 : 0}|${b.text}`;
      case "a": return `a|${b.acts || ""}|${b.last ? 1 : 0}|${b.text}`;
      case "work": return `w|${b.live ? 1 : 0}|${opened(b.key) ? 1 : 0}|${b.steps.length}|${b.steps.map((s) => (s.ok === null ? "-" : s.ok ? "+" : "x")).join("")}`;
      case "sum": return `s|${opened(b.key) ? 1 : 0}|${b.text.length}`;
      case "err": case "warn": return `${b.k}|${b.retry ? 1 : 0}|${b.text}`;
      case "live": return `l|${b.think.length}|${b.text}`;
      // the free answer's words are left out: typing in it must never redraw the card under the cursor
      case "q": return `q|${b.busy ? 1 : 0}|${JSON.stringify(b.call)}|${Object.values(st.answers[b.call.call_id] || {}).map((a) => a.selected.join("\u0001")).join("\u0002")}`;
      case "todo": return `t|${JSON.stringify(b.items)}`;
      default: return `i|${b.html}`;
    }
  }
  // why a turn failed, in words; the engine's own sentence stays one tap away
  function reasonHe(raw) {
    const t = String(raw || "");
    if (/401|unauthori[sz]ed|api[ _-]?key|credential|authentication/i.test(t)) return "ספק המודל לא קיבל את המפתח.";
    if (/429|rate.?limit|quota|too many requests|overloaded|529/i.test(t)) return "ספק המודל עמוס או שהמכסה נגמרה.";
    if (/timed? ?out|timeout|deadline/i.test(t)) return "ספק המודל לא ענה בזמן.";
    if (/context|too long|maximum.*tokens|prompt is too long/i.test(t)) return "השיחה ארוכה מדי למודל הזה.";
    if (/ECONNREFUSED|ENOTFOUND|unreachable|fetch failed|network|socket/i.test(t)) return "אין חיבור לספק המודל.";
    return "המודל החזיר שגיאה.";
  }
  const STEP_IC = (name) => (/bash|shell|exec|command/i.test(name) ? "term" : /edit|write|patch|replace/i.test(name) ? "pen" : /read|view/i.test(name) ? "file" : "tool");
  function blockHTML(b) {
    switch (b.k) {
      case "u":
        return `<div class="uwrap"><div class="msg-u" dir="auto">${esc(b.text)}</div>${b.editable ? `<div class="uacts">
          <button type="button" class="icbtn" data-edit="${b.seq}" title="עריכת ההודעה — נפתחת גרסה חדשה של השיחה מהנקודה הזאת" aria-label="עריכת ההודעה">${ic("edit", "sm")}</button></div>` : ""}</div>`;
      case "a":
        return `<div class="msg-a${b.last ? " last" : ""}"><div class="md" dir="auto">${markdown(b.text)}</div>${b.acts ? `<div class="acts">
          <button type="button" class="icbtn" data-copy="${b.acts}" title="העתקת התשובה" aria-label="העתקת התשובה">${ic("copy", "sm")}</button></div>` : ""}</div>`;
      case "work": {
        const lb = workLabel(b.steps), open = opened(b.key);
        return `<div class="tools work${open ? " open" : ""}${b.live ? " live" : ""}"><button type="button" data-act="tools" data-key="${esc(`${st.cur}:${b.key}`)}" aria-expanded="${open}" title="מה נעשה בדרך">${b.live ? `<span class="dot run"></span>` : ic("tool", "sm")}<span class="wl">${esc(lb.text)}</span>${lb.extra ? `<span class="plus">+${lb.extra}</span>` : ""}${ic("left", "sm chev")}</button>
          <ol>${b.steps.map((s) => s.kind === "think"
            ? `<li class="think">${ic("zap", "sm")}<div class="md" dir="auto">${markdown(s.text)}</div></li>`
            : `<li>${ic(STEP_IC(s.name), "sm")}<span class="mono${s.ok === false ? " bad" : ""}" title="${esc(s.name)}">${esc(s.arg || s.name)}</span>${s.ok === false ? `<span class="badge">נכשל</span>` : ""}</li>`).join("")}</ol></div>`;
      }
      case "sum": {
        const open = opened(b.key);
        return `<div class="tools sum${open ? " open" : ""}"><button type="button" data-act="tools" data-key="${esc(`${st.cur}:${b.key}`)}" aria-expanded="${open}" title="הסיכום שממנו השיחה ממשיכה">${ic("file", "sm")}<span class="wl">ממשיך משיחה קודמת — הסיכום</span>${ic("left", "sm chev")}</button>
          <div class="sumbody md" dir="auto">${markdown(b.text.replace(CONTINUED, "").replace(/^[^\n]*\n/, ""))}</div></div>`;
      }
      case "err":
        return `<div class="note err"><b>התור נכשל</b><span>${esc(reasonHe(b.text))} <button type="button" class="linkish" data-act="raw" title="${esc(b.text)}">פרטים</button></span>${b.retry ? `<button type="button" class="btn sm" data-act="retry">${ic("up", "sm")}המשך מאיפה שנעצר</button>` : ""}</div>`;
      case "warn":
        return `<div class="note warn"><span>${esc(b.text)}</span>${b.retry ? `<button type="button" class="btn sm ghost" data-act="retry">המשך מאיפה שנעצר</button>` : ""}</div>`;
      case "live":
        return `<div class="msg-a streaming">${b.think && !b.text ? `<div class="tools work live"><button type="button" tabindex="-1"><span class="dot run"></span><span class="wl">חושב…</span></button></div>` : ""}${b.text ? `<div class="md" dir="auto">${markdownLive(b.text)}</div>` : ""}</div>`;
      case "q": return questionHTML(b);
      case "todo": return todoHTML(b.items);
      case "cont": return `<div class="cont" role="note">המשיך בלי הודעה חדשה ממך</div>`;
      default: return `<div class="blk">${b.html}</div>`;
    }
  }
  // the answer still being written: rendered as it grows, never remembered (it changes with every letter)
  const markdownLive = (t) => { try { return MD ? MD.render(String(t)) : `<div class="plain">${legacyMarkdown(t)}</div>`; } catch { return esc(t); } };
  // What Azaria asked (ask_user_question), answered right here: the options as buttons, a free answer beside
  // them, one send for the whole call — the harness takes one item per question.
  function questionHTML(b) {
    const ans = st.answers[b.call.call_id] || {};
    const items = (b.call.questions || []).map((q) => {
      const a = ans[q.id] || { selected: [], custom: "" };
      const opts = (q.options || []).map((o) => `<button type="button" class="qopt" data-qcall="${esc(b.call.call_id)}" data-qid="${esc(q.id)}" data-qopt="${esc(o.label)}" data-multi="${q.multiSelect ? 1 : 0}" aria-pressed="${a.selected.includes(o.label)}"><span dir="auto">${esc(o.label)}</span>${o.description ? `<small dir="auto">${esc(o.description)}</small>` : ""}</button>`).join("");
      return `<div class="qitem">${q.header ? `<span class="qh" dir="auto">${esc(q.header)}</span>` : ""}<p dir="auto">${esc(q.question)}</p>${q.detail ? `<div class="md qdetail" dir="auto">${markdown(q.detail)}</div>` : ""}
        ${opts ? `<div class="qopts" role="group">${opts}</div>` : ""}
        <input class="field qcustom" type="text" dir="auto" data-qcall="${esc(b.call.call_id)}" data-qid="${esc(q.id)}" placeholder="${opts ? "או תשובה משלך…" : "התשובה שלך…"}" value="${esc(a.custom || "")}" aria-label="תשובה חופשית"></div>`;
    }).join("");
    return `<div class="qcard" role="group" aria-label="עזריה שואל"><div class="qhead">${ic("msg", "sm")}<b>עזריה שואל</b><span class="qstate">מחכה לתשובה שלך</span></div>${items}
      <div class="btns"><button type="button" class="btn" data-act="answer" data-qcall="${esc(b.call.call_id)}" ${b.busy ? "disabled" : ""}>${b.busy ? "שולח…" : "שליחת התשובה"}</button></div></div>`;
  }
  // Azaria's plan for this turn (the harness's todo list), as Claude Code shows its checklist
  function todoHTML(items) {
    const done = items.filter((t) => t.status === "completed").length;
    return `<div class="todo"><div class="qhead">${ic("check", "sm")}<b>התוכנית</b><span class="qstate">${done} מתוך ${items.length}</span></div>
      <ol>${items.map((t) => `<li class="${esc(t.status)}">${t.status === "completed" ? ic("check", "sm") : t.status === "in_progress" ? `<span class="dot run"></span>` : `<span class="dot"></span>`}<span dir="auto">${esc(t.content)}</span></li>`).join("")}</ol></div>`;
  }
  // everything the open conversation shows, in order: the way to its beginning, its blocks, then what is
  // happening now (the live answer, a message on its way, a question waiting for the person, the plan)
  function threadBlocks() {
    const s = cur();
    if (st.loadedFor !== st.cur) return [info("loading", `<div class="typing"><span class="dot run"></span>טוען את השיחה…</div>`)];
    const out = [];
    if (st.loadingOld) out.push(info("old", `<div class="more-old" role="status"><span class="dot run"></span>טוען את כל השיחה מתחילתה…</div>`));
    else if (st.more && !st.full.has(st.cur)) out.push(info("old", `<button type="button" class="more-old" data-act="older" title="טעינת כל ההודעות הקודמות של השיחה">${ic("up", "sm")}הצגת כל השיחה מתחילתה</button>`));
    else if (st.capped && st.full.has(st.cur)) out.push(info("old", `<div class="more-old">מוצגים 3,000 האירועים האחרונים, כל מה שהדלת של Claude שומרת. השיחה כולה באפליקציה הרשמית.</div>`));
    const blocks = toBlocks(st.events);
    const live = working(s), azaria = !!(s && s.engine === "azaria");
    // one row of actions per answer, under its last text (an answer is everything between two messages of the
    // person); the answer still being written gets none yet
    let from = 0, endA = -1, newest = -1;
    const close = (i) => { if (endA >= 0) { blocks[endA].acts = `${from}-${endA}`; newest = endA; } from = i + 1; endA = -1; };
    blocks.forEach((b, i) => { if (b.k === "u" || b.k === "sum") close(i); else if (b.k === "a") endA = i; });
    if (endA >= 0 && !(live && !(st.pending && st.pending.id === st.cur))) close(blocks.length);
    if (newest >= 0) blocks[newest].last = true;
    // a message of the person can be edited into a new version of the conversation (Azaria's fork)
    if (azaria && !live) for (const b of blocks) if (b.k === "u" && b.seq > 0) b.editable = true;
    // the work still being done, and a failed turn that can go on
    const tail = blocks[blocks.length - 1];
    if (live && tail && tail.k === "work") tail.live = true;
    if (!live && azaria && s.can_retry && tail && (tail.k === "err" || tail.k === "warn")) tail.retry = true;
    out.push(...blocks);
    if (st.stream.id === st.cur && (st.stream.text || st.stream.think)) out.push({ k: "live", key: "live", text: st.stream.text, think: st.stream.think });
    if (st.pending && st.pending.id === st.cur && !arrived(st.events, st.pending)) out.push(info(`p${st.pending.at}`, `<div class="uwrap"><div class="msg-u" dir="auto">${esc(st.pending.text)}</div></div>`));
    // A message the Claude app did not take: why, in the door's words (its words back in the composer). Or one it is
    // not known to have taken: the words quoted, not offered again — and no note once the conversation shows them.
    let unsent = !st.handing.has(st.cur) ? st.unsent[st.cur] : null;
    if (unsent && unsent.maybe && unsent.text && st.events.some((e) => e.type === "user" && Number(e.seq) > unsent.since
        && String(e.text || "").trim() === unsent.text.trim())) unsent = null;
    const again = unsent && unsent.dead ? (unsent.fresh ? " ההודעה מחכה בשיחה חדשה." : " כדי לנסות שוב, פתחו שיחה חדשה.") : "";
    if (unsent) out.push(info(`x${unsent.said}`, unsent.maybe
      ? `<div class="note warn" role="status"><b>לא ידוע אם נשלח</b><span>${esc(unsent.error || "")}${esc(again)}</span>${unsent.text ? `<span class="quote" dir="auto">«${esc(unsent.text.slice(0, 300))}»</span>` : ""}</div>`
      : `<div class="note err" role="alert"><b>לא נשלח</b><span>${esc(unsent.error || "")}${unsent.back ? " ההודעה חזרה לתיבת הכתיבה." : ""}${esc(again)}</span>${!unsent.back && !unsent.fresh && unsent.text ? `<span class="quote" dir="auto">«${esc(unsent.text.slice(0, 300))}»</span>` : ""}</div>`));
    if (s && s.engine === "claude" && s.waiting) {
      // an approval is answered where Claude asks it: the official app, or claude.ai/code — the same session
      // through Remote Control, which also works from the phone
      out.push(info("ask", `<div class="note ask"><b>ממתין לך</b><span>Claude מחכה לאישור או לתשובה. <a href="${esc(officialClaude(s.app))}" target="${outTarget}" rel="noopener">פתיחה באפליקציה הרשמית</a> · <a href="https://claude.ai/code" target="_blank" rel="noopener">או ב-claude.ai/code, גם מהטלפון</a></span></div>`));
    }
    if (azaria) for (const call of s.questions || []) out.push({ k: "q", key: `q${call.call_id}`, call, busy: st.answering === call.call_id });
    if (azaria && Array.isArray(s.todos) && s.todos.length && s.todos.some((t) => t.status !== "completed")) out.push({ k: "todo", key: "todo", items: s.todos });
    if (st.outbox && st.outbox.id === st.cur) {
      out.push(info(`o${st.outbox.text.length}`, `<div class="uwrap"><div class="msg-u" dir="auto">${esc(st.outbox.text)}${st.outbox.files ? `<div class="ufiles">${st.outbox.files.map((f) => `<span>${ic("file", "sm")}${esc(f)}</span>`).join("")}</div>` : ""}</div></div>`));
      out.push(info("status", `<div class="typing" role="status"><span class="dot run"></span>${st.outbox.claude ? "שולחים ל-Claude…" : st.outbox.files ? "מעלים את הקבצים ושולחים לעזריה…" : "שולחים לעזריה…"}</div>`));
    } else if (st.handing.has(st.cur) && st.queued[st.cur]) {
      // the office's Claude runs as many turns as it may at once: this message waits its turn, and goes by itself
      const q = st.queued[st.cur];
      out.push(info(`queued${q}`, `<div class="typing" role="status"><span class="dot wait"></span>בתור ל-Claude${q > 1 ? ` · מקום ${q}` : ""} — ההודעה תיכנס לבד כשאחת השיחות שרצות עכשיו תסתיים</div>`));
    } else if (st.handing.has(st.cur)) {
      out.push(info("status", `<div class="typing" role="status"><span class="dot run"></span>מעבירים ל-Claude דרך האפליקציה הרשמית…</div>`));
    } else if (live &&!(st.stream.id === st.cur && (st.stream.text || st.stream.think)) && !(tail && tail.live) && !(s && s.waiting)) {
      out.push(info("status", `<div class="typing" role="status"><span class="dot run"></span>${s && s.engine === "claude" ? "Claude עובד" : "עזריה עובד"}…</div>`));
    }
    if (!blocks.length && !st.pending && !live && !st.outbox && !unsent) out.push(info("empty", `<div class="empty">אין עדיין הודעות בשיחה הזאת.</div>`));
    return out;
  }
  // what the composer shows depends on: which conversation, its engine and model, and whether Claude can be used
  const composerKey = () => { const s = cur(); return [st.cur, s && s.engine, modelOf(s), JSON.stringify(engineChoice()), claudeOk(s ? s.app : engineChoice().app)].join("|"); };
  function renderComposer() {
    st.ckey = composerKey();
    const s = cur();
    const isNew = st.cur === "new" || !st.cur;
    const choice = isNew ? engineChoice() : null;
    const claudeSide = isNew ? choice.engine === "claude" : s && s.engine === "claude";
    const blocked = claudeSide && !claudeOk(isNew ? choice.app : s && s.app);
    const pill = isNew
      ? `<button type="button" class="pill" data-act="models" title="בחירת המודל לשיחה">${ic(choice.engine === "claude" ? "msg" : isLocal(choice.provider) ? "cpu" : "zap", "sm")}<span><bdi>${esc(placeName(choice))}</bdi></span>${ic("down", "sm")}</button>`
      : claudeSide
        // a Claude conversation's model is chosen in the official app (no door changes it from here)
        ? `<span class="pill static" title="המודל של שיחת Claude נבחר באפליקציה הרשמית">${ic("msg", "sm")}<span><bdi>${esc(`Claude ${modelOf(s)}`.replace("Claude האפליקציה הרשמית", "Claude"))}</bdi></span></span>`
        // Azaria's: switched right here, mid-conversation, as in the Claude apps
        : `<button type="button" class="pill" data-act="switch-model" title="החלפת המודל של השיחה הזאת">${ic(/ollama|local/.test((s && s.model && s.model.provider) || (st.models && st.models.azaria && st.models.azaria.default && st.models.azaria.default.provider) || "") ? "cpu" : "zap", "sm")}<span><bdi>${esc(modelOf(s) || "עזריה")}</bdi></span>${ic("down", "sm")}</button>`;
    // Azaria takes files and images with a message (the paperclip, a paste, a drop); Claude's are attached in its app
    const files = !claudeSide && st.files.length ? `<div class="fchips">${st.files.map((f, i) => `<span class="fchip">${ic(/^image\//.test(f.type) ? "image" : "file", "sm")}<bdi>${esc(f.name)}</bdi><button type="button" class="icbtn" data-unfile="${i}" title="הסרת הקובץ" aria-label="הסרת הקובץ">${ic("x", "sm")}</button></span>`).join("")}</div>` : "";
    const editing = st.editing && st.editing.id === st.cur ? `<div class="editing">${ic("edit", "sm")}<span>עריכת הודעה — תיפתח גרסה חדשה של השיחה מהנקודה הזאת, והמקורית תישאר</span><button type="button" class="linkish" data-act="cancel-edit">ביטול</button></div>` : "";
    el.cwrap.innerHTML = `<div class="col">
      ${blocked ? `<span class="limit">Claude לא מחובר — ההתחברות נעשית באפליקציה הרשמית</span>` : ""}${editing}
      <div class="composer">${files}<textarea id="box" rows="1" placeholder="${esc(isNew ? (claudeSide ? `כתבו ל-${claudeName(choice.app)}…` : "כתבו לעזריה…") : claudeSide ? "השיבו ל-Claude…" : "השיבו לעזריה…")}" aria-label="ההודעה" ${blocked ? "disabled" : ""}></textarea>
        <div class="cbar">${claudeSide ? "" : `<button type="button" class="icbtn clip" data-act="attach" title="צירוף קובץ או תמונה" aria-label="צירוף קובץ או תמונה">${ic("clip")}</button><input type="file" id="files" multiple hidden>`}${pill}<span class="sp"></span>
          <button type="button" class="send" id="send" title="שליחה" aria-label="שליחה" disabled>${ic("up")}</button></div></div>
      <p class="cnote">${claudeSide ? "רץ באפליקציית Claude הרשמית, על מנוי Claude שלך" : "עזריה יכול לטעות. כדאי לבדוק תשובות חשובות."}</p></div>`;
    const box = document.getElementById("box");
    box.value = st.draft || "";
    box.addEventListener("input", () => { st.draft = box.value; autosize(box); updateSend(); });
    if (!claudeSide) {
      const picker = document.getElementById("files");
      picker.addEventListener("change", () => { addFiles(picker.files); picker.value = ""; });
      // an image pasted into the message is attached, as in the Claude apps
      box.addEventListener("paste", (e) => {
        const got = [...((e.clipboardData && e.clipboardData.files) || [])];
        if (got.length) { e.preventDefault(); addFiles(got); }
      });
      const comp = el.cwrap.querySelector(".composer");
      comp.addEventListener("dragover", (e) => { e.preventDefault(); comp.classList.add("drop"); });
      comp.addEventListener("dragleave", () => comp.classList.remove("drop"));
      comp.addEventListener("drop", (e) => { e.preventDefault(); comp.classList.remove("drop"); addFiles((e.dataTransfer && e.dataTransfer.files) || []); });
    }
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !coarse && !e.isComposing) {
        e.preventDefault();
        const s = cur();
        if (!working(s) || (s && s.engine === "azaria")) send();      // Azaria takes it into his queue
      }
    });
    autosize(box);
    updateSend();
  }
  // up to ten files of up to 25MB each go with one message
  function addFiles(list) {
    const room = 10 - st.files.length;
    const got = [...list].slice(0, Math.max(0, room));
    const big = got.filter((f) => f.size > 25 * 1024 * 1024);
    st.files.push(...got.filter((f) => f.size <= 25 * 1024 * 1024));
    if (big.length) toast(big.length === 1 ? `הקובץ ${big[0].name} גדול מ-25MB ולא צורף` : `${big.length} קבצים גדולים מ-25MB ולא צורפו`);
    else if (list.length > got.length) toast("עד עשרה קבצים בהודעה אחת");
    render(["composer"]);
    document.getElementById("box")?.focus();
  }
  function autosize(box) { box.style.height = "auto"; box.style.height = Math.min(box.scrollHeight, 200) + "px"; }
  function updateSend() {
    const btn = document.getElementById("send");
    if (!btn) return;
    const s = cur();
    const running = working(s);
    // while Azaria works, a written message goes to his queue (the harness reads it after the current step);
    // with nothing written the button stops him — as in the Claude apps. Claude's app refuses a busy session.
    const queue = running && !st.sending && s && s.engine === "azaria" && !!(st.draft || "").trim();
    if (queue) { btn.className = "send queue"; btn.disabled = false; btn.title = "לתור — עזריה יקרא את זה אחרי הצעד הנוכחי"; btn.setAttribute("aria-label", "שליחה לתור"); btn.innerHTML = ic("up"); btn.dataset.act = "send"; }
    // a message still being handed to the Claude app: nothing to stop yet (the app has not started the turn), and the
    // next message waits until this one is in
    else if (s && st.handing.has(s.id)) { btn.className = "send"; btn.disabled = true; btn.title = st.queued[s.id] ? "ההודעה בתור ל-Claude — אפשר לשלוח כשהיא נכנסת" : "ההודעה נמסרת ל-Claude — אפשר לשלוח כשהיא נכנסת"; btn.setAttribute("aria-label", "שליחה"); btn.innerHTML = ic("up"); btn.dataset.act = "send"; }
    // in the conversation already, but the hand-over is finishing (a second or two): stopping comes right after
    else if (s && st.landed.has(s.id)) { btn.className = "send stop"; btn.disabled = true; btn.title = "עוד רגע אפשר לעצור"; btn.setAttribute("aria-label", "עצירה"); btn.innerHTML = ic("stop"); btn.dataset.act = "stop"; }
    else if (running) { btn.className = "send stop"; btn.disabled = false; btn.title = "עצירה"; btn.setAttribute("aria-label", "עצירה"); btn.innerHTML = ic("stop"); btn.dataset.act = "stop"; }
    else { btn.className = "send"; btn.title = "שליחה"; btn.setAttribute("aria-label", "שליחה"); btn.innerHTML = ic("up"); btn.dataset.act = "send"; btn.disabled = !(st.draft || "").trim() && !st.files.length; }
  }

  // ── sheets ───────────────────────────────────────────────────────────────────────────────────
  function renderPop() {
    if (!st.pop) { el.pop.innerHTML = ""; return; }
    if (st.pop === "rename") {
      const s = sessionOf(st.popId);
      if (!s) { st.pop = null; el.pop.innerHTML = ""; return; }
      el.pop.innerHTML = `<div class="scrim" data-act="close"><div class="sheet small" role="dialog" aria-modal="true" aria-label="שינוי שם השיחה">
        <h3>${ic("edit", "sm")}שינוי שם<span class="sp"></span><button type="button" class="icbtn" data-act="close" title="סגירה" aria-label="סגירה">${ic("x")}</button></h3>
        <input id="rename-box" class="field" type="text" dir="auto" maxlength="120" value="${esc(s.title || "")}" aria-label="שם השיחה">
        <div class="btns"><button type="button" class="btn" data-act="rename-save">שמירה</button><button type="button" class="btn ghost" data-act="close">ביטול</button></div>
      </div></div>`;
      const box = document.getElementById("rename-box");
      box.focus(); box.select();
      box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); renameSave(); } });
      return;
    }
    if (st.pop === "row") {
      // one conversation's actions, as in the Claude apps' per-chat menu
      const s = sessionOf(st.popId);
      if (!s) { st.pop = null; el.pop.innerHTML = ""; return; }
      const pinned = st.pins.has(s.id);
      el.pop.innerHTML = `<div class="scrim" data-act="close"><div class="sheet small" role="dialog" aria-modal="true" aria-label="פעולות על השיחה">
        <h3><span class="ttl1" dir="auto">${esc(s.title || "שיחה ללא שם")}</span><span class="sp"></span><button type="button" class="icbtn" data-act="close" title="סגירה" aria-label="סגירה">${ic("x")}</button></h3>
        <button type="button" class="opt" data-pin="${esc(s.id)}">${ic("pin")}<span class="nm">${pinned ? "ביטול ההצמדה" : "הצמדה לראש הרשימה"}</span><span class="ds">${pinned ? "השיחה תחזור למקומה לפי הזמן" : "השיחה תופיע תמיד למעלה, במכשיר הזה"}</span></button>
        ${ROW_ACTIONS(s)}
      </div></div>`;
      el.pop.querySelector(".opt")?.focus();
      return;
    }
    if (st.pop === "models") {
      // for a new conversation (the next one's engine and model), or for THIS Azaria conversation, mid-way
      const conv = st.popId ? sessionOf(st.popId) : null;
      const dflt = st.models && st.models.azaria && st.models.azaria.default;
      const ch = conv ? { engine: "azaria", ...((conv.model && conv.model.provider) ? { provider: conv.model.provider, model: conv.model.model } : (dflt || {})) } : engineChoice();
      const groups = (st.models && st.models.azaria && st.models.azaria.groups) || [];
      let h = `<div class="scrim" data-act="close"><div class="sheet" role="dialog" aria-modal="true" aria-label="בחירת המודל"><div role="radiogroup" aria-label="המודלים" style="display:contents">
        <h3>${ic("zap", "sm")}${conv ? "המודל של השיחה הזאת" : "המודל לשיחה חדשה"}<span class="sp"></span><button type="button" class="icbtn" data-act="close" title="סגירה" aria-label="סגירה">${ic("x")}</button></h3>`;
      for (const g of groups) {
        if (!(g.models || []).length) continue;
        const local = /ollama|local/.test(g.id), open = routable(g.id);
        h += `<div class="ogrp">עזריה · ${esc(local ? `מודל מקומי · ${computerName(g.id)}` : `בענן של ${g.name || g.id}`)}</div>`;
        for (const m of g.models) {
          const on = ch.engine === "azaria" && ch.provider === g.id && ch.model === m.id;
          // the catalog's own descriptions are English marketing lines: the sheet says what the choice MEANS
          const ds = !open ? `אין מפתח ל-${g.name || g.id} — מוסיפים אותו בממשק המלא, בהגדרות המודלים`
            : local ? "פרטי ובלי עלות, על המעבד של הלשכה — איטי בשיחה ארוכה"
            : /pro|reasoner/i.test(m.id) ? "החזק ביותר: משימות מורכבות, קוד וחשיבה ארוכה" : "מהיר וזול: לרוב העבודה היומיומית";
          h += `<button type="button" class="opt" role="radio" aria-checked="${on}" ${open ? "" : "disabled"} title="${esc(m.id)}" data-pick='${esc(JSON.stringify({ engine: "azaria", provider: g.id, model: m.id }))}'>
            ${ic(local ? "cpu" : "zap")}<span class="nm" dir="auto">${esc(prettyModel(m.id) || m.name || m.id)}</span>${ic("check", "ck")}
            <span class="ds">${esc(ds)}</span></button>`;
        }
      }
      // each Claude app of the office, on its own account (DGO-1920 instances)
      const cs = claudes(), chosen = ch.engine === "claude" ? (claudeApp(ch.app) || claudeApp() || {}).id : null;
      if (!conv && cs.length) h += `<div class="ogrp">Claude · באפליקציה הרשמית</div>`;
      if (!conv) for (const c of cs) h += `<button type="button" class="opt" role="radio" aria-checked="${chosen === c.id}" data-pick='${esc(JSON.stringify({ engine: "claude", app: c.id }))}' ${c.installed && c.signed_in ? "" : "disabled"}>
          ${ic("msg")}<span class="nm" dir="auto">${esc(claudeName(c.id))}</span>${ic("check", "ck")}
          <span class="ds">${!c.installed ? "האפליקציה הזאת לא פועלת בלשכה" : !c.signed_in ? "לא מחובר — ההתחברות באפליקציה הרשמית" : c.key ? "חשבון Claude נוסף, באפליקציה הרשמית שלו" : "רץ באפליקציית Claude הרשמית, על מנוי Claude שלך"}</span></button>`;
      h += `</div><p class="why">${conv ? "מהתשובה הבאה, השיחה הזאת עונה מהמודל שנבחר. מה שכבר נכתב נשאר." : "הבחירה נשמרת במכשיר הזה לשיחות הבאות."}</p></div></div>`;
      el.pop.innerHTML = h;
      (el.pop.querySelector('[aria-checked="true"]:not([disabled])') || el.pop.querySelector(".opt:not([disabled])"))?.focus();
      return;
    }
    if (st.pop === "providers") {
      // every place a conversation can run, what each one is doing now, and the one thing it needs (DGO-2036)
      const p = st.providers, secrets = `${sibling("console")}/go/connections`;
      let h = `<div class="scrim" data-act="close"><div class="sheet" role="dialog" aria-modal="true" aria-label="איפה שיחה יכולה לרוץ">
        <h3>${ic("sliders", "sm")}איפה שיחה יכולה לרוץ<span class="sp"></span><button type="button" class="icbtn" data-act="close" title="סגירה" aria-label="סגירה">${ic("x")}</button></h3>`;
      if (!p) h += `<div class="typing" role="status"><span class="dot run"></span>בודק ספקים, מחשבים ואפליקציות…</div>`;
      else {
        h += `<div class="ogrp">בענן · עזריה על מודל של ספק</div>`;
        if (p.failed) h += `<p class="why">לא ידוע כרגע: עזריה לא ענה על הספקים. אפשר לפתוח את הדף שוב בעוד רגע.</p>`;
        for (const c of p.cloud || []) {
          // the KEY decides what is offered (second reader, DGO-2036): a provider with a working key is never offered
          // the vault — the pointer would replace that key — and what was not read is «unknown», never «not connected»
          const known = p.keys_read !== false && c.configured !== null && c.configured !== undefined;
          const state = !known ? "לא ידוע כרגע"
            : c.configured ? (c.vault ? "מחובר · המפתח מהסודות של הלשכה" : "מחובר · מפתח שהוגדר בממשק המלא")
            : c.vault ? "מחובר לסודות, אבל אין בהם מפתח" : "לא מחובר";
          const act = !known || c.configured ? ""
            : c.vault ? `<a class="btn sm ghost" href="${esc(secrets)}" target="${outTarget}" rel="noopener">${ic("key", "sm")}הוספת המפתח</a>`
            : `<button type="button" class="btn sm" data-act="bind-key" data-id="${esc(c.id)}" ${st.binding === c.id ? "disabled" : ""}>${ic("key", "sm")}${st.binding === c.id ? "מחבר…" : "חיבור מהסודות"}</button>`;
          h += `<div class="prow"><span class="pic">${ic("zap")}</span><span class="pt"><b>${esc(c.name)}</b><small><span class="dot ${known && c.configured ? "ok" : known && c.vault ? "wait" : ""}"></span>${esc(state)}${c.routable && c.models ? ` · ${c.models} מודלים` : ""}</small></span>${act}</div>`;
        }
        h += `<div class="ogrp">על המחשבים של הלשכה · מודל מקומי, פרטי ובלי עלות</div>`;
        if (p.failed) h += `<p class="why">לא ידוע כרגע.</p>`;
        else if (!(p.local || []).length) h += `<p class="why">עוד אין מחשב עם מודל מקומי. «מודלים מקומיים» שמותקנים על אחד המחשבים של הלשכה מופיעים כאן מעצמם, עם כל המודלים שלהם.</p>`;
        for (const l of p.local || []) {
          const names = l.models.slice(0, 3).map((m) => prettyModel(m) || m).join(", ");
          h += `<div class="prow"><span class="pic">${ic("cpu")}</span><span class="pt"><b><bdi>${esc(l.computer.name)}</bdi></b><small><span class="dot ${l.routable ? "ok" : "wait"}"></span>${l.routable ? (l.models.length === 1 ? "מודל אחד" : `${l.models.length} מודלים`) : "לא עונה כרגע"}${names ? ` · <bdi>${esc(names)}</bdi>` : ""}</small></span></div>`;
        }
        // each Claude app of the office: the first, and every further account
        const apps = Array.isArray(p.claudes) && p.claudes.length ? p.claudes : [{ id: "bina-claude", key: "", ...(p.claude || {}) }];
        h += `<div class="ogrp">אפליקציות</div>`;
        for (const c of apps) {
          // the app's state and the one action that fits it (claudeState above, DGO-2126)
          const state = c.installed ? (c.signed_in ? `מחובר · מנוי Claude${c.active ? ` · ${Number(c.active) === 1 ? "שיחה אחת עובדת עכשיו" : `${Number(c.active)} שיחות עובדות עכשיו`}` : ""}` : "מותקן, לא מחובר")
            : CLAUDE_WORD[claudeState(c)];
          const act = c.installed ? `<a class="btn sm ghost" href="${esc(officialClaude(c.id))}" target="${outTarget}" rel="noopener">${ic(c.signed_in ? "ext" : "login", "sm")}${c.signed_in ? "פתיחה" : "התחברות"}</a>`
            : claudeFix(c);
          h += `<div class="prow"><span class="pic">${ic("msg")}</span><span class="pt"><b dir="auto">${esc(c.key ? ((c.title && (c.title.he || c.title.en)) || `Claude ${c.key}`) : "Claude")}</b><small><span class="dot ${c.installed ? (c.signed_in ? "ok" : "wait") : ""}"></span>${state}</small></span>
          ${act}</div>`;
        }
        h += `<p class="why">מפתח לא עובר במסך הזה: הוא נשמר ב«חיבורים ומפתחות» של הלשכה, ועזריה קורא אותו משם בכל בקשה. כל הגדרות המודלים — ב<a href="${esc(fullUi(null))}" target="${outTarget}" rel="noopener">ממשק המלא</a>.</p>`;
      }
      el.pop.innerHTML = h + `</div></div>`;
      el.pop.querySelector(".btn,.icbtn")?.focus();
      return;
    }
    if (st.pop === "account") {
      // one block per Claude app of the office — each its own account, its own sign-in in its own official app
      const apps = claudes().length ? claudes() : [{ id: "bina-claude", key: "", installed: false, signed_in: false, active: 0 }];
      const blocks = apps.map((c) => {
        const n = (st.sessions || []).filter((s) => s.engine === "claude" && (s.app || "bina-claude") === c.id).length;
        return `${apps.length > 1 ? `<div class="ogrp" dir="auto">${esc(claudeName(c.id))}</div>` : ""}<div class="facts">
          <div><small>מצב</small><span>${c.installed ? (c.signed_in ? `<span class="dot ok"></span>מחובר` : `<span class="dot wait"></span>לא מחובר`) : CLAUDE_WORD[claudeState(c)]}</span></div>
          <div><small>איפה רץ</small><span>אפליקציית Claude הרשמית</span></div>
          <div><small>שיחות</small><span>${n}</span></div>
          <div><small>עובדות עכשיו</small><span>${esc(Number(c.active) || 0)}</span></div>
        </div>
        <div class="btns">${c.installed ? `<a class="btn${c.signed_in ? " ghost" : ""}" href="${esc(officialClaude(c.id))}" target="${outTarget}" rel="noopener">${ic(c.signed_in ? "ext" : "login", "sm")}${c.signed_in ? "פתיחת האפליקציה הרשמית" : "התחברות ל-Claude"}</a>` : claudeFix(c)}</div>`;
      }).join("");
      el.pop.innerHTML = `<div class="scrim" data-act="close"><div class="sheet" role="dialog" aria-modal="true" aria-label="Claude בתוך עזריה">
        <h3>${ic("msg", "sm")}Claude בתוך עזריה<span class="sp"></span><button type="button" class="icbtn" data-act="close" title="סגירה" aria-label="סגירה">${ic("x")}</button></h3>
        ${blocks}
        <p class="why">הכניסה ל-Claude נעשית במסך של Anthropic עצמה, בתוך אפליקציית Claude הרשמית של הלשכה — פעם אחת לכל אפליקציה, וכל אפליקציה על חשבון משלה. עזריה מציג את השיחות ושולח אליהן, ולא שומר סיסמה, קוד או טוקן. הודעה שנשלחת כאן נספרת במנוי של אותו חשבון.</p>
      </div></div>`;
    }
  }

  // ── render all, keep what the person is doing ────────────────────────────────────────────────
  function render(parts = "all") {
    app.classList.toggle("drawer", st.drawer);
    if (parts === "all" || parts.includes("list")) { renderList(); renderFoot(); }
    if (parts === "all" || parts.includes("top")) renderTop();
    if (parts === "all" || parts.includes("body")) renderBody();
    if (parts === "all" || parts.includes("composer")) renderComposer();
    if (parts === "all" || parts.includes("pop")) renderPop();
    updateSend();
  }
  let toastT;
  function toast(msg) {
    app.querySelector(".toast")?.remove();
    const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg; app.appendChild(t);
    clearTimeout(toastT); toastT = setTimeout(() => t.remove(), 2600);
  }
  function setUrl() {
    try {
      const u = new URL(location.href);
      if (st.cur && st.cur !== "new") u.searchParams.set("s", st.cur); else u.searchParams.delete("s");
      if (u.href !== location.href) history.replaceState(null, "", u.href);
    } catch { /* a URL we may not rewrite */ }
  }
  function open(id) {
    // each conversation keeps its own unsent text
    st.drafts[st.cur || "new"] = st.draft;
    closeStream();
    // a Claude conversation not started yet (`pending-…`) has nothing to load: it shows at once
    st.cur = id; st.drawer = false; st.events = []; st.loadedFor = id.startsWith("pending-") ? id : null; st.sig = ""; st.scrollDown = true; st.more = false;
    st.stream = { id: null, text: "", think: "" }; st.editing = null;
    if (id !== "new") markSeen(id);
    st.draft = st.drafts[id] || "";
    setUrl(); render(); if (id !== "new") loadThread(id);
    if (!coarse) document.getElementById("box")?.focus();
  }

  // ── data ─────────────────────────────────────────────────────────────────────────────────────
  async function loadList() {
    if (st.busy.list) return;                                        // one request in flight at a time
    st.busy.list = true;
    try {
      const r = await api("sessions");
      const opened = cur();
      // a promise that started is never listed again under its own id (a list asked before it started can come after)
      st.sessions = (r.sessions || []).filter((s) => !st.adopted.has(s.id)); st.engines = r.engines || {};
      // a conversation started from a promise of this screen (`from`) takes over its pin, draft and place, open or not
      for (const s of [...st.sessions]) if (s.from && !st.adopted.has(s.from)) adopt(s.from, s.id);
      // The open conversation stays on the list while the Claude app starts it: its promise (`pending-…`) leaves the
      // list once the app has started it, and its own read then says the id it goes on under — asked now. The row of
      // one just started stays too while the app's list is slow to name it (else the screen loses the conversation).
      const keep = opened && !sessionOf(opened.id) && !st.adopted.has(opened.id)
        && ((opened.id.startsWith("pending-") && (st.handing.has(opened.id) || st.unsent[opened.id])) || Date.now() - (opened.adoptedAt || 0) < 120000);
      if (keep) {
        st.sessions = [opened, ...st.sessions];
        if (opened.id.startsWith("pending-")) loadThread(opened.id);
      }
      if (st.seen === null) {                                        // the first visit on this device: all read
        st.seen = Object.fromEntries(st.sessions.map((s) => [s.id, Date.parse(s.updated_at || "") || 0]));
        store.set("azaria.seen", st.seen);
      }
      if (st.cur && st.cur !== "new" && !document.hidden) markSeen(st.cur);
      // (a page reloaded while a Claude conversation was being started opens it: its read says what it became)
      if (st.asked) { const a = st.asked; st.asked = null; if (sessionOf(a) || a.startsWith("pending-")) open(a); else { st.cur = "new"; setUrl(); render(); } return; }
      // the composer names the conversation's model: when the list brings the real one (a new conversation's
      // row is first written here, then the engine's own), it follows — never under the person's fingers
      const typing = document.activeElement && document.activeElement.id === "box";
      render(!typing && composerKey() !== st.ckey ? ["list", "top", "composer"] : ["list", "top"]);
      if (cur()) updateSend();
    } catch (e) {
      if (st.sessions === null) { st.sessions = []; st.engines = { azaria: { ok: false, error: e.message } }; render(["list"]); }
    } finally { st.busy.list = false; }
  }
  async function loadModels() {
    try {
      st.models = await api("models");
      // the composer follows what can be used now (Claude signed in or out, a provider's key), but a
      // background refresh never rebuilds it under the person's fingers; a new conversation's places follow too
      const typing = document.activeElement && document.activeElement.id === "box";
      const places = st.cur === "new" || !st.cur ? ["body"] : [];
      render(typing ? ["list", "top", ...places] : ["list", "top", "composer", ...places]);
    } catch { /* the next pass */ }
  }
  // where a conversation can run, read when the sheet opens (it asks the harness and the Claude app)
  async function loadProviders() {
    try { st.providers = await api("providers"); }
    // not read: «unknown», never an empty «no» (second reader) — the Claude apps are known from the models anyway
    catch (e) { if (!st.providers) st.providers = { failed: true, cloud: [], local: [], claudes: claudes() }; toast(e.message); }
    if (st.pop === "providers") render(["pop"]);
  }
  // a provider's key, from the office's secrets: the harness reads it there from the next request on
  async function bindKey(id) {
    st.binding = id; render(["pop"]);
    try { await api(`providers/${encodeURIComponent(id)}/vault`, { method: "POST", body: "{}" }); toast("המפתח נלקח מהסודות של הלשכה"); }
    catch (e) { toast(e.message); }
    st.binding = null;
    await Promise.all([loadProviders(), loadModels()]);
  }
  // A Claude conversation opened here before the app started it (`pending-…`) goes on under the id the app gave
  // it: its row, its place on the screen, the message on its way, its unsent words and its pin follow (DGO-2044).
  function adopt(pid, real) {
    st.adopted.set(pid, real);
    if (st.landed.delete(pid)) st.landed.add(real);
    if (pid in st.sentSeq) { st.sentSeq[real] = st.sentSeq[pid]; delete st.sentSeq[pid]; }
    if (st.sessions) {
      const known = st.sessions.some((s) => s.id === real);
      st.sessions = known ? st.sessions.filter((s) => s.id !== pid)
        : st.sessions.map((s) => (s.id === pid ? { ...s, id: real, adoptedAt: Date.now(), sending: false, failed: false } : s));
    }
    if (st.pending && st.pending.id === pid) st.pending.id = real;
    if (st.handing.delete(pid)) st.handing.add(real);
    delete st.queued[pid];                                           // started: it waits in no line any more
    delete st.unsent[pid];
    if (st.drafts[pid] !== undefined) { if (!st.drafts[real]) st.drafts[real] = st.drafts[pid]; delete st.drafts[pid]; }
    if (st.pins.has(pid)) { st.pins.delete(pid); st.pins.add(real); store.set("azaria.pins", [...st.pins]); }
    if (st.cur !== pid) return render(["list"]);
    closeStream();
    st.cur = real; st.loadedFor = real; st.events = []; st.sig = ""; setUrl(); markSeen(real);
    render(["body", "top", "list"]);
    loadThread(real);
  }
  // What Claude's door says about the message it is handing to the app: still going, or not sent — then why, and
  // the words go back to the composer they left (unless the person is already writing something else there).
  // Answers whether that changed what the conversation shows.
  function told(id, r) {
    const now = () => `${st.handing.has(id)}:${st.queued[id] || 0}:${st.unsent[id] ? st.unsent[id].at : ""}`;
    const before = now();
    // still on its way — unless the stream already showed it in the conversation (the app took it)
    if (r.sending && !st.landed.has(id)) st.handing.add(id);
    else { st.handing.delete(id); if (!r.sending) st.landed.delete(id); }
    // waiting in the Claude app's line: its place, said instead of «handing over» until the line sends it
    if (st.handing.has(id) && Number(r.queued) > 0) st.queued[id] = Number(r.queued); else delete st.queued[id];
    const f = r.failed && typeof r.failed === "object" ? r.failed : null;
    const said = f ? `${!!f.maybe}|${f.error}` : "";                  // the same verdict read again is not said again
    if (!f) delete st.unsent[id];
    else if (!(st.unsent[id] && st.unsent[id].said === said)) {
      // the words: the door's, or (after a restart of the door) the ones this screen sent, or said before
      const text = String(f.text || (st.pending && st.pending.id === id ? st.pending.text : "") || (st.unsent[id] && st.unsent[id].text) || "");
      // the message is looked for only past what the conversation held when it went
      const since = id in st.sentSeq ? st.sentSeq[id] : st.pending && st.pending.id === id ? st.pending.seq : st.unsent[id] ? st.unsent[id].since : -1;
      if (st.pending && st.pending.id === id) st.pending = null;
      const row = sessionOf(id);                                     // nothing runs: the row says so before the list comes back
      if (row) Object.assign(row, { running: false, ...(id.startsWith("pending-") ? { failed: true, maybe: !!f.maybe } : {}) });
      // A conversation the app never started and can no longer start (its start may have sent, or the app forgot
      // it) is not tried again here: the words wait in a new conversation instead (sure) or stay quoted (maybe).
      const dead = id.startsWith("pending-") && (!!f.maybe || f.code === "no-session");
      // Not sent: the words go back to the composer they left. Not KNOWN whether sent: they stay out of it (sending
      // them again could repeat the message in the conversation); the note says so, and quotes them.
      let back = false, fresh = false;
      if (!f.maybe && text) {
        if (dead) { if (!st.drafts.new) { st.drafts.new = text; fresh = true; } }
        else if (st.cur === id) { if (!(st.draft || "").trim()) { st.draft = text; back = true; render(["composer"]); } }
        else if (!st.drafts[id]) { st.drafts[id] = text; back = true; }
      }
      st.unsent[id] = { error: String(f.error || "ההודעה לא נשלחה."), at: f.at, said, back, fresh, dead, maybe: !!f.maybe, text, since };
      toast(st.unsent[id].error);
    }
    return now() !== before;
  }
  // A conversation opens on its last 400 events (fast); «כל השיחה» reads it whole, from its first message,
  // and from then on only its tail is asked for and merged by sequence — a poll never re-reads thousands.
  async function loadThread(id, all = false) {
    if (st.busy.thread === id && !all) return;                      // this conversation is already asked for
    st.busy.thread = id;
    const whole = all || st.full.has(id);
    const tailOnly = whole && !all && st.loadedFor === id && st.events.length > 0;
    try {
      const r = await api(`sessions/${encodeURIComponent(id)}/messages?limit=${tailOnly ? 200 : whole ? "all" : 400}${appQ(id)}`);
      if (st.cur !== id) return;                                      // the person moved on
      if (typeof r.resolved === "string" && r.resolved && r.resolved !== id) { st.busy.thread = false; return adopt(id, r.resolved); }
      const news = told(id, r);
      // the app could not be read, but the door said what happened to the message: what is shown stays
      if (!Array.isArray(r.events)) { if (st.loadedFor !== id) st.loadedFor = id; render(["body"]); updateSend(); return; }
      let events = r.events || [];
      if (tailOnly) {
        const first = Number(events.length ? events[0].seq : NaN);
        if (!events.length) events = st.events;
        else if (Number.isFinite(first) && first <= lastSeq(st.events)) events = st.events.filter((e) => Number(e.seq) < first).concat(events);
        else { st.busy.thread = false; return loadThread(id, true); }   // more happened than a tail holds
      } else if (st.loadedFor === id && st.events.length && events.length) {
        // A read asked before the stream brought newer events must not take them away (the person's own message
        // would vanish until the next read — the second reader): what the screen holds past the read stays. Only
        // when both count alike: the screen holds the read's last event under the same number (a parser rebuilt
        // after a quiet while numbers anew — then the read is taken whole).
        const top = lastSeq(events), last = events[events.length - 1], same = st.events.find((e) => Number(e.seq) === top);
        if (same && same.type === last.type && (same.at || "") === (last.at || "")) events = events.concat(st.events.filter((e) => Number(e.seq) > top));
      }
      if (whole) st.full.add(id);
      st.more = !whole && !!r.more;
      if (!tailOnly) st.capped = !!r.capped;
      const last = events[events.length - 1];
      // what changed is the count, the last event, and how far its text has grown — not the whole JSON
      const sig = `${events.length}:${last ? last.seq ?? last.at ?? "" : ""}:${last && last.text ? last.text.length : 0}`;
      const changed = sig !== st.sig || st.loadedFor !== id || news;
      st.events = events; st.loadedFor = id; st.sig = sig;
      const p = st.pending;
      if (p && p.id === id && arrived(events, p) && st.handing.delete(id)) { st.landed.add(id); updateSend(); }
      // the bubble goes when the message is in — or three minutes on, unless it is still on its way (a line holds it)
      if (p && p.id === id && (arrived(events, p) || (Date.now() - p.at > 180000 && !st.handing.has(id)))) st.pending = null;
      if (changed && all) {
        // earlier messages arrive ABOVE the reader: the place on the screen stays where it was
        const fromBottom = el.body.scrollHeight - el.body.scrollTop;
        render(["body", "top"]);
        el.body.scrollTop = el.body.scrollHeight - fromBottom;
      } else if (changed) render(news ? ["body", "top", "list"] : ["body", "top"]);
      updateSend();
      // from here the conversation streams: one stream for the open conversation, from its last event
      if (st.cur === id && live.id !== id) openStream(id);
    } catch (e) {
      if (st.cur === id && st.loadedFor !== id) { st.loadedFor = id; st.events = []; render(["body"]); toast(`השיחה לא נטענה: ${e.message}`); }
      else if (all && st.cur === id) toast(e.message);
    } finally { if (st.busy.thread === id) st.busy.thread = false; }
  }
  // ── live: the open conversation streams (no re-reading every few seconds) ────────────────────
  // Azaria's door sends its durable events and, while an answer is written, its text as it comes (`delta`);
  // Claude's door sends each event as the app writes it. Reconnects from the last event it holds.
  const DURABLE = ["user", "assistant", "reasoning", "tool.call", "tool.result", "turn.start", "turn.end", "step.start", "step.end", "title", "inbox", "hook"];
  const live = { es: null, id: null, ok: false, tries: 0, timer: null };
  let painting = 0;
  function paint() {
    if (painting) return;
    painting = requestAnimationFrame(() => {
      painting = 0;
      const p = st.pending;
      // the message is in the conversation: the app took it (the door's hand-over is only finishing)
      if (p && p.id === st.cur && arrived(st.events, p)) { if (st.handing.delete(p.id)) st.landed.add(p.id); st.pending = null; }
      if (st.loadedFor === st.cur) render(["body", "top"]);
      updateSend();
    });
  }
  function closeStream() {
    clearTimeout(live.timer);
    if (live.es) live.es.close();
    Object.assign(live, { es: null, id: null, ok: false });
  }
  function openStream(id) {
    closeStream();
    // a Claude conversation the app has not started yet has nothing to stream: its read (every 2.5 s while its
    // message is handed over) says when it starts, and under which id
    if (typeof EventSource !== "function" || !id || id === "new" || id.startsWith("pending-")) return;
    const es = new EventSource(new URL(`ui/sessions/${encodeURIComponent(id)}/stream?since=${lastSeq(st.events)}${appQ(id)}`, BASE));
    Object.assign(live, { es, id });
    const mine = () => live.es === es && st.cur === id && st.loadedFor === id;
    const parse = (ev) => { try { return JSON.parse(ev.data); } catch { return null; } };
    // events past the last one held, each once, in order
    const take = (list) => {
      let added = false;
      for (const e of list) {
        const n = Number(e && e.seq);
        if (!e || !Number.isFinite(n) || n <= lastSeq(st.events)) continue;
        st.events.push(e); added = true;
      }
      return added;
    };
    es.onopen = () => { if (live.es === es) { live.ok = true; live.tries = 0; } };
    es.addEventListener("snapshot", (ev) => { const d = parse(ev); if (mine() && d && take(d.events || [])) paint(); });
    for (const t of DURABLE) es.addEventListener(t, (ev) => {
      const e = parse(ev);
      if (!mine() || !e) return;
      if (e.seq === undefined && ev.lastEventId) e.seq = Number(ev.lastEventId);
      if (!take([e])) return;
      // the durable text replaces the streamed one; a turn's edges move the list (running, unread)
      if (e.type === "assistant") st.stream.text = "";
      if (e.type === "reasoning") st.stream.think = "";
      if (e.type === "turn.start" || e.type === "turn.end") setTimeout(loadList, 300);
      paint();
    });
    es.addEventListener("attempt.start", () => { if (mine()) st.stream = { id, text: "", think: "" }; });
    es.addEventListener("delta", (ev) => {
      const d = parse(ev);
      if (!mine() || !d) return;
      if (st.stream.id !== id) st.stream = { id, text: "", think: "" };
      if (d.kind === "text") st.stream.text += d.text || "";
      else if (d.kind === "reasoning") st.stream.think += d.text || "";
      paint();
    });
    es.addEventListener("attempt.end", () => { if (mine()) { st.stream = { id, text: "", think: "" }; paint(); } });
    const lost = () => {
      if (live.es !== es) return;
      es.close(); Object.assign(live, { es: null, ok: false });
      live.timer = setTimeout(() => { if (st.cur === id && st.loadedFor === id) openStream(id); }, Math.min(15000, 1000 * 2 ** live.tries++));
    };
    es.onerror = lost;
    es.addEventListener("end", lost);
  }

  // the answer to what Azaria asked: one item per question (a choice, or words of the person's own)
  async function answerQuestion(callId) {
    const s = cur(), call = s && (s.questions || []).find((q) => q.call_id === callId);
    if (!call) return;
    const given = st.answers[callId] || {};
    const answers = call.questions.map((q) => ({ id: q.id, selected: (given[q.id] && given[q.id].selected) || [], custom: (given[q.id] && given[q.id].custom) || "" }));
    if (answers.some((a) => !a.selected.length && !a.custom.trim())) return toast("חסרה תשובה לאחת השאלות");
    st.answering = callId; render(["body"]);
    try {
      await api(`sessions/${encodeURIComponent(s.id)}/answer`, { method: "POST", body: JSON.stringify({ call_id: callId, answers }) });
      s.questions = (s.questions || []).filter((q) => q.call_id !== callId);
      if (!s.questions.length) s.waiting = null;
      delete st.answers[callId]; s.running = true;
      toast("התשובה נשלחה לעזריה");
    } catch (e) { toast(e.message); }
    st.answering = null; render(["body", "list", "top"]);
  }

  // a conversation's name and its place on the shelf — Azaria's harness keeps both; the list follows at once
  async function renameSave() {
    const id = st.popId, s = sessionOf(id), input = document.getElementById("rename-box");
    const title = (input && input.value || "").trim();
    if (!s || !title || title === s.title) { st.pop = null; return render(["pop"]); }
    try {
      await api(`sessions/${encodeURIComponent(id)}/rename`, { method: "POST", body: JSON.stringify({ title }) });
      s.title = title; st.pop = null; render(["list", "top", "pop"]); toast("השם נשמר");
    } catch (e) { toast(e.message); }
  }
  async function shelve(id, on) {
    const s = sessionOf(id);
    if (!s) return;
    try {
      await api(`sessions/${encodeURIComponent(id)}/${on ? "archive" : "unarchive"}`, { method: "POST", body: "{}" });
      s.archived = on; st.pop = null;
      if (on && st.cur === id) open("new"); else render(["list", "pop"]);
      toast(on ? "השיחה הועברה לארכיון. אפשר להחזיר אותה מ«ארכיון»." : "השיחה חזרה לרשימה");
    } catch (e) { toast(e.message); }
  }
  async function loadOlder() {
    const id = st.cur;
    if (!id || id === "new" || st.loadingOld || st.full.has(id)) return;
    st.loadingOld = true; render(["body"]);
    await loadThread(id, true);
    st.loadingOld = false;
    if (st.cur === id) { const keep = el.body.scrollHeight - el.body.scrollTop; render(["body"]); el.body.scrollTop = el.body.scrollHeight - keep; }
  }
  function composerBlocked() {
    const s = cur(), isNew = st.cur === "new" || !st.cur;
    return (isNew ? engineChoice().engine === "claude" : !!(s && s.engine === "claude")) && !claudeOk(isNew ? engineChoice().app : s && s.app);
  }
  // the files attached in the composer, uploaded to a conversation of Azaria's → their receipts
  async function uploadAll(id, files) {
    const receipts = [];
    for (const f of files) {
      const r = await api(`sessions/${encodeURIComponent(id)}/upload?${new URLSearchParams({ name: f.name || "file", type: f.type || "" })}`,
        { method: "POST", body: f, headers: { "content-type": "application/octet-stream" } });
      if (r && r.receipt) receipts.push(r.receipt);
    }
    return receipts;
  }
  const TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; } })();
  async function send(text) {
    text = (text ?? st.draft ?? "").trim();
    const files = st.files.slice();
    if ((!text && !files.length) || st.sending) return;
    if (composerBlocked()) return toast("Claude לא מחובר — ההתחברות נעשית באפליקציה הרשמית");
    // the conversation this message belongs to, fixed now: the person may open another one while it goes
    const id = st.cur && st.cur !== "new" ? st.cur : "new";
    const seq = id !== "new" && st.loadedFor === id ? lastSeq(st.events) : -1;
    const here = () => (id === "new" ? st.cur === "new" || !st.cur : st.cur === id);
    // An edited message is a new version of the conversation from that point (the original stays as it was).
    const editing = st.editing && st.editing.id === id ? st.editing : null;
    // Shown at once: the message, and what is happening to it (the owner, EXU-64 07:41: «אני שולח ולא קורה כלום
    // לכמה דקות»; 19.11: «זה אמור להיות מילי שניות»). Claude's door takes it in milliseconds and hands it to the
    // app's own screen in the background, which takes seconds; the conversation then says how that went.
    const toClaude = id === "new" ? engineChoice().engine === "claude" : (sessionOf(id) || {}).engine === "claude";
    if (files.length && toClaude) return toast("אי אפשר לצרף קבצים לשיחת Claude מכאן — צרפו אותם באפליקציה הרשמית.");
    // the app takes one message of a conversation at a time: the next waits in the composer, not lost
    if (toClaude && id !== "new" && st.handing.has(id)) return toast("ההודעה הקודמת עוד נמסרת ל-Claude. אפשר לשלוח כשהיא נכנסת.");
    // a conversation the app can no longer start: the words go from a new one
    if (toClaude && st.unsent[id] && st.unsent[id].dead) {
      return toast(st.unsent[id].maybe ? "לא ידוע אם השיחה הזאת נפתחה באפליקציית Claude — בדקו ברשימה, או פתחו שיחה חדשה."
                                       : "השיחה הזאת לא נפתחה באפליקציית Claude — פתחו שיחה חדשה.");
    }
    st.sending = true; st.outbox = { id, text, claude: toClaude, files: files.length ? files.map((f) => f.name) : null };
    if (here()) { st.draft = ""; st.files = []; st.scrollDown = true; render(["body", "composer"]); }
    updateSend();
    try {
      if (editing) {
        const r = await api(`sessions/${encodeURIComponent(id)}/edit`, { method: "POST", body: JSON.stringify({ seq: editing.seq, text, tz: TZ }) });
        st.editing = null; st.outbox = null; st.sending = false;
        if (r && r.id) {
          st.pending = { id: r.id, text, seq: -1, at: Date.now() };
          const from = sessionOf(id);
          st.sessions = [{ id: r.id, engine: "azaria", title: (from && from.title) || text.slice(0, 60), running: true, updated_at: new Date().toISOString(),
                           model: from && from.model, model_label: from && from.model_label }, ...(st.sessions || [])];
          if (here()) open(r.id);
          toast("נפתחה גרסה חדשה של השיחה מההודעה הזאת; המקורית נשארה כמו שהייתה");
        }
      } else if (id === "new") {
        const ch = engineChoice();
        // the model goes with the message whenever it is not the office's default (a choice, or a fallback)
        const d = st.models && st.models.azaria && st.models.azaria.default;
        const own = ch.provider && !(d && d.provider === ch.provider && d.model === ch.model);
        const model = own ? { model: { provider: ch.provider, model: ch.model } } : {};
        let r;
        if (ch.engine === "claude") r = await api("sessions", { method: "POST", body: JSON.stringify({ engine: "claude", text, ...(ch.app ? { app: ch.app } : {}) }) });
        else if (!files.length) r = await api("sessions", { method: "POST", body: JSON.stringify({ engine: "azaria", text, tz: TZ, ...model }) });
        else {
          // files first: the conversation is opened without a message, they are uploaded to it, then they go
          r = await api("sessions", { method: "POST", body: JSON.stringify({ engine: "azaria", hold: true, ...model }) });
          const receipts = await uploadAll(r.id, files);
          await api(`sessions/${encodeURIComponent(r.id)}/messages`, { method: "POST", body: JSON.stringify({ text, receipts, tz: TZ }) });
        }
        const wasHere = here();
        st.drafts.new = ""; st.outbox = null; st.sending = false;
        if (r && r.id) {
          st.pending = { id: r.id, text: text || files.map((f) => f.name).join(", "), seq: -1, at: Date.now() };
          // the row carries the model it was started on, so the bar and the composer agree from the first moment
          // …and, for Claude, the app it runs in (its tag, its tile, its sign-in state)
          const app = ch.engine === "claude" ? claudeApp(r.app || ch.app) || claudeApp() : null;
          st.sessions = [{ id: r.id, engine: ch.engine, title: (text || files[0].name).slice(0, 60), running: true, updated_at: new Date().toISOString(),
                           ...(app ? { app: app.id, app_key: app.key || null } : {}),
                           model: ch.provider ? { provider: ch.provider, model: ch.model } : null, model_label: modelName(ch) }, ...(st.sessions || [])];
          if (r.pending) { st.handing.add(r.id); st.sentSeq[r.id] = -1; } // Claude: opened at once, its message on its way
          if (wasHere) open(r.id); else render(["list"]);
        }
      } else {
        const receipts = files.length ? await uploadAll(id, files) : [];
        const r = await api(`sessions/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify({ text, receipts, tz: TZ, ...appOfRow(id) }) });
        st.drafts[id] = ""; st.pending = { id, text, seq, at: Date.now() }; st.outbox = null; st.sending = false;
        const s = sessionOf(id); if (s) { s.running = true; s.failed = false; }
        // Claude's door took it at once; the app gets it in the background (and a conversation opened here may
        // have started meanwhile: the answer names the id it goes on under)
        if (r && r.background) {
          st.handing.add(id); st.landed.delete(id); delete st.unsent[id]; st.sentSeq[id] = seq;
          if (typeof r.id === "string" && r.id && r.id !== id) adopt(id, r.id);
        }
        if (here()) { st.scrollDown = true; render(["body", "composer", "top"]); } else render(["list"]);
      }
      setTimeout(loadList, 800);
    } catch (e) {
      // nothing went: the words go back to the composer they left, and the door says why — in Hebrew
      st.outbox = null; st.sending = false;
      if (here()) { if (!st.draft) st.draft = text; if (!st.files.length) st.files = files; render(["body", "composer"]); }
      else if (!st.drafts[id]) st.drafts[id] = text;
      toast(e.message);
    }
    st.outbox = null; st.sending = false; updateSend();
  }
  async function stop() {
    const id = st.cur; if (!id || id === "new") return;
    if (st.handing.has(id)) return toast("ההודעה עוד נמסרת ל-Claude — אפשר לעצור כשהיא נכנסת.");
    try { await api(`sessions/${encodeURIComponent(id)}/cancel`, { method: "POST", body: JSON.stringify(appOfRow(id)) }); toast("נעצר"); setTimeout(loadList, 600); }
    catch (e) { toast(`לא נעצר: ${e.message}`); }
  }

  // ── what the person does ─────────────────────────────────────────────────────────────────────
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act],[data-s],[data-f],[data-pick],[data-say],[data-copy],[data-codecopy],[data-pin],[data-edit],[data-unfile],[data-qopt]");
    if (!b) return;
    if (b.dataset.s) return open(b.dataset.s);
    if (b.dataset.f) { st.filter = b.dataset.f; return render(["list"]); }
    if (b.dataset.say) return send(b.dataset.say);
    if (b.dataset.pick && st.pop === "models" && st.popId) {
      // this conversation's model, switched mid-way (the harness answers the next turn on it)
      let pick = null; try { pick = JSON.parse(b.dataset.pick); } catch { /* a button this page wrote */ }
      const id = st.popId, s = sessionOf(id);
      st.pop = null; render(["pop"]);
      if (!pick || !s) return;
      try {
        await api(`sessions/${encodeURIComponent(id)}/model`, { method: "POST", body: JSON.stringify({ provider: pick.provider, model: pick.model }) });
        s.model = { provider: pick.provider, model: pick.model };
        render(["list", "top", "composer"]); toast(`מהתשובה הבאה: ${placeName({ engine: "azaria", provider: pick.provider, model: pick.model })}`);
      } catch (e) { toast(e.message); }
      return;
    }
    if (b.dataset.pick) {
      try { st.pick = JSON.parse(b.dataset.pick); } catch { /* a button this page wrote */ }
      try { localStorage.setItem(PICK_KEY, JSON.stringify(st.pick)); } catch { /* a private window */ }
      st.pop = null; return render(["top", "composer", "pop", ...(st.cur === "new" || !st.cur ? ["body"] : [])]);
    }
    if (b.dataset.edit) {
      // a sent message back in the composer; sending it opens a new version of the conversation from there
      const seq = Number(b.dataset.edit), u = toBlocks(st.events).find((x) => x.k === "u" && x.seq === seq);
      if (!u) return;
      st.editing = { id: st.cur, seq }; st.draft = u.text; st.files = [];
      render(["composer"]);
      const box = document.getElementById("box"); box?.focus(); box?.setSelectionRange(box.value.length, box.value.length);
      return;
    }
    if (b.dataset.unfile !== undefined) { st.files.splice(Number(b.dataset.unfile), 1); render(["composer"]); return; }
    if (b.dataset.qopt !== undefined) {
      // one option of a question: a single choice replaces, a multiple one toggles
      const call = b.dataset.qcall, qid = b.dataset.qid, label = b.dataset.qopt;
      const all = (st.answers[call] = st.answers[call] || {});
      const a = (all[qid] = all[qid] || { selected: [], custom: "" });
      if (b.dataset.multi === "1") a.selected = a.selected.includes(label) ? a.selected.filter((x) => x !== label) : [...a.selected, label];
      else a.selected = a.selected[0] === label ? [] : [label];
      return render(["body"]);
    }
    if (b.dataset.codecopy) {
      const code = b.closest(".code")?.querySelector("code")?.textContent || "";
      try { await navigator.clipboard.writeText(code); toast("הקוד הועתק"); } catch { toast("ההעתקה לא אושרה בדפדפן"); }
      return;
    }
    if (b.dataset.pin) { togglePin(b.dataset.pin); return; }
    if (b.dataset.copy !== undefined) {
      // the whole answer: every text of it, without the tool runs between them
      const [a0, a1] = b.dataset.copy.split("-").map(Number);
      const text = toBlocks(st.events).slice(a0, a1 + 1).filter((x) => x.k === "a").map((x) => x.text.trim()).join("\n\n");
      try { await navigator.clipboard.writeText(text); toast("התשובה הועתקה"); } catch { toast("ההעתקה לא אושרה בדפדפן"); }
      return;
    }
    const a = b.dataset.act;
    if (a === "close") { if (e.target !== b && !e.target.closest(".icbtn")) return; st.pop = null; return render(["pop"]); }
    if (a === "tools") {
      // remembered in the state, so a refresh of the conversation keeps what the person opened
      const k = b.dataset.key, on = !st.openTools.has(k);
      if (on) st.openTools.add(k); else st.openTools.delete(k);
      b.parentElement.classList.toggle("open", on); b.setAttribute("aria-expanded", String(on));
      return;
    }
    if (a === "older") return loadOlder();
    if (a === "attach") { document.getElementById("files")?.click(); return; }
    if (a === "cancel-edit") { st.editing = null; st.draft = ""; return render(["composer"]); }
    if (a === "raw") {
      try { await navigator.clipboard.writeText(b.title || ""); toast("פרטי השגיאה הועתקו"); } catch { toast(b.title || ""); }
      return;
    }
    if (a === "retry") {
      const id = st.cur;
      try {
        await api(`sessions/${encodeURIComponent(id)}/retry`, { method: "POST", body: "{}" });
        const s = sessionOf(id); if (s) { s.running = true; s.can_retry = false; }
        st.scrollDown = true; render(["body", "top"]); toast("ממשיך מאיפה שנעצר");
      } catch (err) { toast(err.message); }
      return;
    }
    if (a === "answer") return answerQuestion(b.dataset.qcall);
    if (a === "drawer") { st.drawer = true; return render([]); }
    if (a === "drawer-close") { st.drawer = false; return render([]); }
    if (a === "new") return open("new");
    if (a === "models") { st.pop = "models"; st.popId = null; return render(["pop"]); }
    if (a === "account") { st.pop = "account"; st.drawer = false; return render(["pop"]); }
    if (a === "providers") { st.pop = "providers"; st.popId = null; st.drawer = false; render(["pop"]); return loadProviders(); }
    if (a === "bind-key") return bindKey(b.dataset.id);
    if (a === "rowmenu") { st.pop = "row"; st.popId = b.dataset.id; return render(["pop"]); }
    if (a === "rename") { st.pop = "rename"; st.popId = b.dataset.id; return render(["pop"]); }
    if (a === "rename-save") return renameSave();
    if (a === "archive" || a === "unarchive") return shelve(b.dataset.id, a === "archive");
    if (a === "switch-model") { st.pop = "models"; st.popId = st.cur; return render(["pop"]); }
    if (a === "bottom") { el.body.scrollTo({ top: el.body.scrollHeight, behavior: "smooth" }); return; }
    if (a === "send") return send();
    if (a === "stop") return stop();
  });
  el.q.addEventListener("input", () => { st.q = el.q.value.trim(); renderList(); });
  // a free answer to Azaria's question is kept as it is typed, without redrawing the card under the cursor
  el.body.addEventListener("input", (e) => {
    const t = e.target;
    if (!t.classList || !t.classList.contains("qcustom")) return;
    const all = (st.answers[t.dataset.qcall] = st.answers[t.dataset.qcall] || {});
    (all[t.dataset.qid] = all[t.dataset.qid] || { selected: [], custom: "" }).custom = t.value;
  });
  // reading up to the first message on the screen asks for the rest of the conversation, as a chat app does
  // and reading back up shows the way down again, as the Claude apps do
  el.body.addEventListener("scroll", () => {
    if (el.body.scrollTop < 80 && st.more && !st.loadingOld) loadOlder();
    el.down.hidden = el.body.className !== "thread" || el.body.scrollHeight - el.body.scrollTop - el.body.clientHeight < 240;
  }, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && (st.pop || st.drawer)) { st.pop = null; st.drawer = false; render(["pop"]); }
  });

  // ── live: the list often, the open conversation fast while it works ──────────────────────────
  let tick = 0;
  setInterval(() => {
    if (document.hidden) return;                                     // a hidden tab asks nothing
    tick++;
    const s = cur();
    const busy = working(s) || (st.sessions || []).some((x) => x.running);
    if ((busy && tick % 2 === 0) || tick % 4 === 0) loadList();      // 5 s while anything works, 10 s at rest
    // the open conversation streams; reading it again is the safety net while its stream is down, and once a
    // minute otherwise (an event a reconnect could have missed)
    const streaming = s && live.id === s.id && live.ok;
    // a message being handed to the Claude app is followed by its read every tick, stream or not: only the read
    // says what became of it (the second reader: on a 60 s tick «מעבירים…» outlived the answer)
    if (s && (st.handing.has(s.id) || st.landed.has(s.id) || (!streaming && (working(s) || s.running)))) loadThread(s.id);
    else if (s && tick % (streaming ? 24 : 8) === 0) loadThread(s.id);
    if (tick % 24 === 0) loadModels();
  }, 2500);
  // a phone that slept dropped its stream: back on the screen, the list and the conversation catch up
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    loadList();
    const s = cur();
    if (s) { loadThread(s.id); if (!live.es) openStream(s.id); }
  });

  render();
  app.removeAttribute("aria-busy");
  loadList();
  loadModels();
})();
