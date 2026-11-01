/* computers — the fleet screen. Hebrew RTL, relative URLs only.
 *
 * Two rules this file follows because breaking them is invisible until it is expensive:
 *
 *   · EVERY request is RELATIVE (`api/computers`, not `/api/computers`). The console embeds this app
 *     at /a/computers/ and injects <base href>; an absolute path addresses the CONSOLE's origin, so
 *     the app would silently talk to the shell's routes instead of its own.
 *   · a machine's state is never optimistic. Nothing here paints green because a POST returned 200:
 *     green is what the SSH probe answered, and the probe is re-run after every change.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = { computers: [], key: null, local: null, execId: null, authId: null, busy: false, at: 0 };

const STATE = {
  ok: { cls: "ok", he: "מחובר" },
  needs_action: { cls: "need", he: "ממתין לאישור" },   // waits for a PERSON: violet, as its figure above is
  error: { cls: "bad", he: "שגיאה" },
  no_ssh: { cls: "unset", he: "ללא SSH" },        // the office's own machine, by the office's choice
  missing: { cls: "bad", he: "לא זמין" },
  unknown: { cls: "unset", he: "לא נבדק" },
};
const stateOf = (c) => STATE[c.state] || (c.ok ? STATE.ok : STATE.unknown);

function bytes(n) {
  if (n == null) return "—";
  const g = n / 1073741824;
  if (g >= 1) return g.toFixed(1).replace(/\.0$/, "") + " GB";
  return Math.round(n / 1048576) + " MB";
}
const pct = (n) => (n == null ? "" : Number(n).toFixed(0) + "%");
// (one is said as one: a machine of one core read «1 ליבות»)
const cores = (n) => (Number(n) === 1 ? "ליבה אחת" : `<bdi>${n}</bdi> ליבות`);
function bar(percent) {
  if (percent == null) return "";
  const cls = percent >= 90 ? "bad" : percent >= 75 ? "warn" : "";
  return `<div class="bar"><i class="${cls}" style="width:${Math.min(100, percent)}%"></i></div>`;
}
/** "up 13 weeks, 6 days, 19 hours" -> "13 ש׳ 6 י׳ 19 ש׳" — Hebrew, abbreviated.
 *
 * The raw value is `uptime -p` (or /proc/uptime seconds) and it is ENGLISH on every machine, because
 * it is a program's output and not a fact: a Hebrew screen printing "1 hour, 17 minutes" is showing
 * the operator a language the rest of the page is not in. So the string is PARSED and re-rendered,
 * and one we cannot parse is passed through unchanged rather than blanked — a machine whose uptime we
 * cannot name is still a machine with an uptime.
 *
 * The output is returned as HTML with EACH value+unit wrapped in .num (direction:ltr, isolate),
 * never the whole string: the cell is Hebrew, and setting `direction:ltr` on the cell itself is what
 * turns "1 ש׳ 20 דק׳" into a reordered jumble. Isolation per pair keeps every number intact and the
 * reading order Hebrew.
 */
const HE_UNITS = [[/^years?/, "שנים"], [/^months?/, "חוד׳"], [/^weeks?/, "שב׳"], [/^days?/, "ימ׳"],
                  [/^hours?/, "שע׳"], [/^minutes?/, "דק׳"], [/^mins?/, "דק׳"], [/^seconds?/, "שנ׳"]];
const hePart = (n, unit) => `<bdi>${n} ${unit}</bdi>`;
function uptimeHe(raw) {
  const s = (raw == null ? "" : String(raw)).trim();
  if (!s) return "—";
  // `uptime` prints a CLOCK before the interesting part (" 14:13:55 up 97 days, 19:47, 1 user, load
  // average: …"), and the fields after it are not durations either. So the uptime is defined as what
  // sits between `up` and the first of `user`/`load average` — reading the first HH:MM in the whole
  // string instead reported the time of day as "hours of uptime".
  let n = s.replace(/^up\s+/i, "").split(/\d+\s*users?|load\s+average/i)[0].trim();
  const afterUp = s.match(/(?:^|\sup)\s+(.+)$/i);
  if (afterUp) n = afterUp[1].split(/\d+\s*users?|load\s+average/i)[0].trim();
  if (/^\d+$/.test(n)) {                        // bare seconds: the /proc/uptime fallback
    const secs = +n, d = Math.floor(secs / 86400), h = Math.floor((secs % 86400) / 3600),
          mi = Math.floor((secs % 3600) / 60);
    if (d) return `${hePart(d, "ימ׳")} ${hePart(h, "שע׳")}`;
    return h ? `${hePart(h, "שע׳")} ${hePart(mi, "דק׳")}` : hePart(mi, "דק׳");
  }
  const parts = [];
  // A unit can arrive with punctuation welded to it ("days,") — match letters only. Matching the
  // comma makes the unit unrecognisable and the field then vanishes with no error anywhere.
  const re = /(\d+)\s*([A-Za-z]+)/g;
  let m;
  while ((m = re.exec(n))) {
    const unit = HE_UNITS.find(([rx]) => rx.test(m[2].toLowerCase()));
    if (unit) parts.push(hePart(m[1], unit[1]));
  }
  const hm = n.match(/(\d+):(\d{2})/);          // "19:47" — hours and minutes in one token
  if (hm) parts.push(hePart(+hm[1], "שע׳"), hePart(+hm[2], "דק׳"));
  return parts.length ? parts.slice(0, 2).join(" ") : esc(s);      // the two leading units say it
}
const shortLoad = (l) => (l == null || l === "" ? "—" : String(l).trim().split(/\s+/).slice(0, 3).join(" · "));

function alertBox(kind, html) {
  const cls = kind === "bad" ? "bad" : kind === "warn" ? "warn" : kind === "ok" ? "ok" : "";
  return `<div class="callout ${cls}">${html}</div>`;
}

/* @bina-said:start */
var binaSaid = (status) => (!status ? "אין תשובה מהשירות"
  : status < 300 ? "התשובה אינה מה שהמסך ציפה לו — רענן את הדף"
  : status === 401 ? "הכניסה פגה — רענן את הדף" : status === 403 ? "אין הרשאה לפעולה הזאת"
  : status === 404 ? "השירות לא מכיר את הבקשה הזאת"
  : status > 501 && status < 505 ? "השירות אינו זמין כרגע" : status >= 500 ? "השירות נתקל בשגיאה"
  : "הבקשה נדחתה");
// a request that could not even be sent answers like one that was refused, with status 0
var binaNoAnswer = () => ({ ok: false, status: 0, json: async () => ({}), text: async () => "" });
/* @bina-said:end */
/* @bina-ask:start */
var binaAsk, binaTell;
(function () {
  var doc = document;
  var CSS = ".bask{position:fixed;inset:0;z-index:2147483000;display:grid;grid-template:minmax(0,1fr)/minmax(0,1fr);place-items:center;padding:16px;background:var(--scrim)}"
    + ".bask-card{display:flex;flex-direction:column;width:min(440px,100%);max-height:100%;overflow:auto;box-sizing:border-box;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow-lg);font:14px/1.5 var(--font,system-ui,sans-serif);text-align:start;outline:0}"
    + ".bask-card h2{margin:0 0 8px;font-size:16px;font-weight:800;line-height:1.35}"
    + ".bask-read{overflow:auto}.bask-read:not(:empty){min-height:19px}"   // never squeezed to nothing: a line of it stays, and past that the card itself scrolls
    + ".bask-card p{margin:0 0 6px;font-size:13px;color:var(--muted)}"
    + ".bask-read p:last-child{margin:0}"
    + ".bask-facts{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:10px 0 0;padding:10px 12px;background:var(--surface-2);border:1px solid var(--line);border-radius:9px}"
    + ".bask-facts dt{color:var(--muted);font-size:11px;font-weight:600;line-height:1.7}"
    + ".bask-facts dd{margin:0;font-size:12.5px;font-weight:600;overflow-wrap:anywhere;unicode-bidi:plaintext;text-align:right}"
    + ".bask-field{display:grid;gap:5px;margin-top:10px;font-size:12px;font-weight:600;color:var(--muted)}"
    + ".bask-field input{font:inherit;font-size:13px;font-weight:400;height:36px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink)}"
    + ".bask-said{margin-top:10px;padding:8px 12px;border-radius:9px;border-inline-start:4px solid var(--red);background:color-mix(in srgb,var(--red) 14%,var(--surface));font-size:12.5px;overflow-wrap:anywhere}"
    + ".bask-said:empty{display:none}"
    + ".bask-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}"
    + ".bask-btn{height:34px;padding:0 16px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;font-size:13px;font-weight:700;cursor:pointer}"
    + ".bask-btn.primary{background:var(--accent);border-color:transparent;color:var(--accent-ink)}"
    + ".bask-btn.danger{background:var(--red);border-color:transparent;color:var(--surface)}"
    + ".bask-btn:disabled{opacity:.5;cursor:default}"
    + ".bask-field input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}"
    + "@media (pointer:coarse){.bask-btn{height:44px}.bask-field input{height:44px}}"
    + "@media (max-height:399px){.bask{padding:8px}.bask-card{padding:12px}.bask-acts{margin-top:10px}}"   // the side menu's own short frame
    + "#bina-tell{position:fixed;inset-block-end:16px;inset-inline-start:16px;z-index:2147483001;display:grid;gap:8px;max-width:min(420px,calc(100vw - 32px))}"
    + ".btell{--c:var(--ok);padding:10px 14px;border-radius:12px;background:color-mix(in srgb,var(--c) 14%,var(--surface));color:var(--ink);border:1px solid color-mix(in srgb,var(--c) 38%,var(--surface));border-inline-start:4px solid var(--c);font:13px/1.45 var(--font,system-ui,sans-serif);box-shadow:var(--shadow-lg);cursor:pointer;text-align:start}"
    + ".btell.warn{--c:var(--lime)}.btell.bad{--c:var(--red)}"   // --ok and --red, not the bare hues: they are the steps that are lifted on the dark ground
    + ".btell small{display:block;margin-top:2px;font-size:11.5px;color:var(--muted);overflow-wrap:anywhere;unicode-bidi:plaintext}"
    + ".btell button{margin-inline-start:12px;padding:0;border:0;background:none;font:inherit;font-weight:800;color:var(--blue);text-decoration:underline;cursor:pointer}";

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function style() {
    if (doc.getElementById("bina-ask-css")) return;
    var s = el("style", "", CSS);
    s.id = "bina-ask-css";
    doc.head.appendChild(s);
  }

  binaAsk = function (q) {
    style();
    return new Promise(function (resolve) {
      var back = doc.activeElement, field = null, must = q.input && q.input.must;
      var scrim = el("div", "bask"), card = el("div", "bask-card"), read = el("div", "bask-read"), said = el("div", "bask-said");
      card.setAttribute("role", "alertdialog");
      card.setAttribute("aria-modal", "true");
      card.setAttribute("dir", "rtl");
      card.setAttribute("tabindex", "-1");
      said.setAttribute("role", "alert");
      card.appendChild(el("h2", "", q.title));
      card.appendChild(read);
      String(q.body || "").split(/\n+/).forEach(function (line) { if (line.trim()) read.appendChild(el("p", "", line)); });
      if (q.facts && q.facts.length) {
        var dl = el("dl", "bask-facts");
        q.facts.forEach(function (f) { dl.appendChild(el("dt", "", f[0])); dl.appendChild(el("dd", "", f[1])); });
        read.appendChild(dl);
      }
      if (q.input) {
        var lab = el("label", "bask-field", q.input.label || "");
        field = el("input");
        field.value = q.input.value || "";
        if (q.input.dir) field.setAttribute("dir", q.input.dir);
        lab.appendChild(field);
        card.appendChild(lab);
      }
      var acts = el("div", "bask-acts"), no = el("button", "bask-btn", q.cancel || "ביטול"),
          yes = el("button", "bask-btn " + (q.danger ? "danger" : "primary"), q.ok || "אישור");
      no.setAttribute("type", "button");
      yes.setAttribute("type", "button");
      acts.appendChild(no);
      acts.appendChild(yes);
      card.appendChild(said);
      card.appendChild(acts);
      scrim.appendChild(card);
      doc.body.appendChild(scrim);

      function fit() { if (must) yes.disabled = field.value.trim() !== must; }
      function home() { (field || (q.danger ? no : yes)).focus(); }
      function done(v) {
        doc.removeEventListener("keydown", key, true);
        scrim.remove();
        if (back && back.focus) back.focus();
        resolve(v);
      }
      function cancel() { if (!no.disabled) done(field ? null : false); }
      function agree() {
        if (yes.disabled) return;
        var v = field ? field.value : true;
        if (!q.run) return done(v);
        yes.disabled = no.disabled = true;                // in flight: busy, and there is nothing left to cancel
        yes.textContent = "מבצע…";
        said.textContent = "";
        card.focus();
        Promise.resolve(v).then(q.run).then(function () { done(v); }, function (e) {
          yes.textContent = q.ok || "אישור";
          yes.disabled = no.disabled = false;
          fit();
          said.textContent = (e && e.message) || "הפעולה נכשלה";
          home();
        });
      }
      function key(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
        else if (e.key === "Enter" && field && doc.activeElement === field) { e.preventDefault(); agree(); }
        else if (e.key === "Tab") {                       // the page behind is not reachable while asked
          var ring = [field, no, yes].filter(function (n) { return n && !n.disabled; });
          var i = ring.indexOf(doc.activeElement);
          e.preventDefault();
          if (ring.length) ring[(i + (e.shiftKey ? ring.length - 1 : 1)) % ring.length].focus();
        }
        else if (/^(Arrow|Page)(Up|Down)$/.test(e.key) && doc.activeElement !== field && read.scrollHeight > read.clientHeight) {
          e.preventDefault();                               // the focus lives on the buttons, outside what scrolls
          read.scrollTop += (/Up$/.test(e.key) ? -1 : 1) * (/^Page/.test(e.key) ? read.clientHeight : 40);
        }
      }
      yes.addEventListener("click", agree);
      no.addEventListener("click", cancel);
      scrim.addEventListener("mousedown", function (e) { if (e.target === scrim) cancel(); });
      if (field) field.addEventListener("input", fit);
      doc.addEventListener("keydown", key, true);
      fit();
      home();
    });
  };

  // The third word is how long the notice stays (ms) — or what more it carries: { ms, more, act, stay }.
  //   more  the service's own sentence, on a line of its own under the notice's words
  //   act   [label, fn] — one way on from the notice (an undo, a refresh): pressing it runs fn and takes the notice down
  //   stay  no clock: the notice is there until it is pressed
  binaTell = function (text, kind, opt) {
    style();
    var o = opt && typeof opt === "object" ? opt : { ms: opt };
    var box = doc.getElementById("bina-tell");
    if (!box) { box = el("div"); box.id = "bina-tell"; doc.body.appendChild(box); }
    var n = el("div", "btell " + (kind || "ok"), text);
    n.setAttribute("role", kind === "bad" ? "alert" : "status");
    n.setAttribute("dir", "rtl");
    if (o.more) n.appendChild(el("small", "", o.more));
    if (o.act) {
      var go = el("button", "", o.act[0]);
      go.setAttribute("type", "button");
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); });
    box.appendChild(n);
    if (!o.stay) setTimeout(function () { n.remove(); }, o.ms || (kind === "bad" ? 9000 : 5200));
    return n;
  };
})();
/* @bina-ask:end */
async function api(path, opt) {
  const r = await fetch(path, opt).catch(binaNoAnswer);
  const body = await r.json().catch(() => null);
  return { ok: r.ok, status: r.status, d: r.status ? body : { error: binaSaid(0) } };
}
const postJson = (path, body) => api(path,
  { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// What a row can do. The FIRST action of a row's state is worded and the rest are icon buttons
// whose title says what will happen: four worded buttons stood in three lines beside one-line cells.
const ACTS = {
  exec: { he: "הרצת פקודה", tip: "הרצת פקודה במחשב הזה ב־SSH" },
  auth: { he: "אישור המפתח", tip: "הפקודה שמאשרת את מפתח הלשכה במחשב הזה",
          d: "M21 2l-2 2m-7.6 7.6a5.5 5.5 0 1 1-7.8 7.8 5.5 5.5 0 0 1 7.8-7.8zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" },
  audit: { he: "אבטחה", tip: "בדיקת האבטחה של המחשב עצמו: SSH, חומת אש, עדכונים ופורטים פתוחים",
           d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" },
  probe: { he: "בדיקה", tip: "קריאה מחודשת של מצב המחשב הזה עכשיו", d: "M21 12a9 9 0 1 1-3-6.7M21 4v4h-4" },
  del: { he: "מחיקה", tip: "הסרת המחשב מהרשימה — המחשב עצמו לא נגע", cls: "danger",
         d: "M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6" },
};

// ── the table ───────────────────────────────────────────────────────────────────
function render() {
  const list = S.computers || [];
  const count = (state) => list.filter((c) => c.state === state).length;
  const ready = list.filter((c) => c.ok).length;
  const cpu = list.reduce((n, c) => n + (c.ok && c.ncpu ? c.ncpu : 0), 0);
  const ram = list.reduce((n, c) => n + (c.ok && c.memory && c.memory.total ? c.memory.total : 0), 0);
  // the office's tile: a state only when there is something in it (a zero is grey, with no bar)
  const figure = (id, n, state) => {
    const tile = $(id).parentNode;
    $(id).textContent = n;
    tile.classList.toggle("is-zero", !n);
    if (n) tile.dataset.state = state; else delete tile.dataset.state;
  };
  figure("kOk", ready, "done");
  figure("kWait", count("needs_action"), "person");
  figure("kErr", count("error") + count("missing"), "failed");
  $("kRes").innerHTML = ready ? `${cores(cpu)} · <bdi>${bytes(ram)}</bdi>` : `<span class="none">אין מחשב מחובר</span>`;
  $("tblHint").textContent = list.length === 1 ? "מחשב אחד ברשימה" : list.length ? `${list.length} מחשבים ברשימה` : "";

  const alerts = [];
  if (S.key && !S.key.public_key) {
    alerts.push(alertBox("warn", "<b>מפתח הלשכה עדיין לא נוצר.</b> " +
      "הוא נוצר עם עליית השירות — רענן את הדף בעוד רגע."));
  }
  if (S.vaultError) {
    alerts.push(alertBox("bad", "<b>כספת החיבורים אינה זמינה.</b> " + esc(S.vaultError) +
      " — רשימת המחשבים נשמרת שם, ולכן היא לא תוצג עד שהשירות יחזור."));
  }
  if (list.some((c) => c.state === "needs_action")) {
    alerts.push(alertBox("warn", "<b>יש מחשב שממתין לאישור המפתח.</b> " +
      "לחץ על „אישור המפתח” בשורה שלו — תוצג הפקודה המדויקת שמריצים בתוך המחשב."));
  }
  $("alerts").innerHTML = alerts.join("");

  const mount = $("tableMount");
  if (!list.length && !S.vaultError) {
    mount.innerHTML = `<div class="spin">אין מחשבים ברשימה עדיין.</div>`;
    return;
  }
  const rows = list.map((c) => {
    const st = stateOf(c);
    const mem = c.memory || {}, disk = c.disk || {};
    const uptime = c.ok ? uptimeHe(c.uptime) : "—";
    const names = c.state === "no_ssh" ? ["probe"] : c.state === "needs_action" ? ["auth", "probe"]
      : c.ok ? ["exec", "audit", "probe"] : ["probe", "auth"];
    if (c.removable) names.push("del");
    const acts = names.map((name, i) => {
      const a = ACTS[name], lead = !i, filled = lead && c.state === "needs_action";
      return `<button type="button" class="btn sm ${filled ? "" : "ghost"} ${a.cls || ""} ${lead ? "" : "ic"}" data-act="${name}"
        data-id="${esc(c.id)}" title="${a.tip}"${lead ? "" : ` aria-label="${a.he}"`}>${lead ? a.he
        : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${a.d}"/></svg>`}</button>`;
    });
    const cpuCell = c.ok ? shortLoad(c.load) : "—";
    // the share, then used / total on a line of its own that never breaks inside a value
    const use = (m) => (c.ok && m.total
      ? `<span class="num">${pct(m.used_percent)}</span><div class="small muted nw"><span class="num">${bytes(m.used)} / ${bytes(m.total)}</span></div>${bar(m.used_percent)}`
      : "—");
    return `<tr data-id="${esc(c.id)}">
      <td data-th="מצב"><div class="cell"><span class="pill ${st.cls}">${esc(st.he)}</span></div></td>
      <td data-th="מחשב"><div class="cell"><span class="name">${esc(c.label || c.host)}</span>
        ${c.builtin ? (c.note ? `<div class="small muted">${esc(c.note)}</div>` : "")
          : `<div><span class="addr" title="${esc(c.user)}@${esc(c.host)}:${esc(c.port)}">${esc(c.host)}</span></div>`}
        ${c.ok && c.hostname && c.hostname !== c.host ? `<div class="small muted"><bdi>${esc(c.hostname)}</bdi></div>` : ""}</div></td>
      <td data-th="מערכת"><div class="cell">${c.ok && c.os ? `<bdi>${esc(c.os)}</bdi>` : "—"}
        ${c.ok ? `<div class="small muted">פועל ${uptime}</div>` : ""}</div></td>
      <td data-th="עומס"><div class="cell"><span class="num nw">${cpuCell}</span>
        ${c.ok && c.ncpu ? `<div class="small muted">${cores(c.ncpu)}</div>` : ""}</div></td>
      <td data-th="זיכרון"><div class="cell">${use(mem)}</div></td>
      <td data-th="דיסק"><div class="cell">${use(disk)}</div></td>
      <td data-th="פעולות"><div class="cell rowacts">${acts.join("")}</div></td>
    </tr>`;
  }).join("");
  mount.innerHTML = `<table class="table"><thead><tr>
      <th>מצב</th><th>מחשב</th><th>מערכת</th><th>עומס</th>
      <th>זיכרון</th><th>דיסק</th><th>פעולות</th>
    </tr></thead><tbody>${rows}</tbody></table>`;

  // a machine that is not ok carries its own explanation and its own next step — never a raw error
  const broken = list.filter((c) => !c.ok && c.reason);
  if (broken.length) {
    mount.insertAdjacentHTML("beforeend", broken.map((c) =>
      alertBox(c.state === "no_ssh" ? "" : c.state === "needs_action" ? "warn" : "bad",
        `<b>${esc(c.label || c.host)}:</b> ${esc(c.reason)}` +
        (c.action ? `<div class="small">${esc(c.action)}</div>` : "") +
        (c.stderr ? `<details class="raw"><summary>הפלט של SSH</summary><pre class="out err">${esc(c.stderr)}</pre></details>` : ""))).join(""));
  }
}

function renderKey() {
  const k = S.key || {};
  $("pubKey").textContent = k.public_key || "—";
  $("keyFp").innerHTML = k.fingerprint ? `טביעת אצבע: <span class="mono">${esc(k.fingerprint)}</span>` : "";
  $("btnCopyKey").disabled = !k.public_key;
  $("keyState").textContent = k.public_key ? "מוכן" : "טרם נוצר";
}

async function load(probe) {
  const r = await api("api/computers" + (probe ? "" : "?probe=0"));
  if (!r.ok) {
    S.vaultError = (r.d && r.d.error) || "שגיאה בקריאת רשימת המחשבים";
    if (!S.computers.length) $("tableMount").innerHTML = `<div class="spin">${esc(S.vaultError)}</div>`;
    render();
    setLive(false);
    return;
  }
  S.vaultError = null;
  S.computers = r.d.computers || [];
  S.key = r.d.office_key || {};
  S.at = Date.now();
  render();
  renderKey();
  setLive(true);
}

function setLive(fresh) {
  const el = $("live");
  // the shared page-chrome chip reads `data-stale`, not a class: one attribute an app can set
  // without knowing any of the component's CSS (see platform-base/bina-ui/bina-page.css)
  el.dataset.stale = fresh ? "0" : "1";
  const t = S.at ? new Date(S.at).toLocaleTimeString("he-IL") : "";
  $("liveText").textContent = fresh ? "עודכן " + t : "אין תשובה מהשרת";
}

// ── actions ─────────────────────────────────────────────────────────────────────
const findComputer = (id) => (S.computers || []).find((c) => c.id === id);

async function probeOne(id) {
  const r = await api("api/computers/" + encodeURIComponent(id) + "/status?fresh=1");
  if (r.d && r.d.id) {
    S.computers = S.computers.map((c) => (c.id === id ? Object.assign({}, c, r.d) : c));
    render();
  }
  return r;
}

async function del(id) {
  const c = findComputer(id) || {};
  if (!await binaAsk({ title: "להסיר את המחשב מהרשימה?", ok: "הסרה", danger: true,
                       body: "המחשב עצמו לא נגע — רק הרשומה נמחקת מכספת החיבורים. אפשר להוסיף אותו שוב בכל רגע.",
                       facts: [["מחשב", c.label || c.host || id], ["כתובת", c.host || "—"]] })) return;
  const r = await api("api/computers/" + encodeURIComponent(id), { method: "DELETE" });
  if (!r.ok) { binaTell((r.d && r.d.error) || "המחיקה נכשלה", "bad"); return; }
  await load(true);
}

function openModal(id) { $(id).classList.remove("hidden"); }
function closeModal(id) { $(id).classList.add("hidden"); }
document.addEventListener("click", (e) => {
  const closer = e.target.closest("[data-close]");
  if (closer) closeModal(closer.dataset.close);
  if (e.target.classList && e.target.classList.contains("modal-ov")) e.target.classList.add("hidden");
  const act = e.target.closest("[data-act]");
  if (!act) return;
  const id = act.dataset.id;
  if (act.dataset.act === "exec") openExec(id);
  else if (act.dataset.act === "auth") openAuth(id);
  else if (act.dataset.act === "del") del(id);
  else if (act.dataset.act === "probe") {
    const worded = !act.querySelector("svg");
    act.disabled = true; act.classList.add("busy");
    if (worded) act.textContent = "בודק…";
    probeOne(id).finally(() => {             // a row that answered was redrawn; one that did not gets its button back
      act.disabled = false; act.classList.remove("busy");
      if (worded) act.textContent = ACTS.probe.he;
    });
  }
  else if (act.dataset.act === "audit") openAudit(id);
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const open = document.querySelector(".modal-ov:not(.hidden)");
  if (open) { open.classList.add("hidden"); e.preventDefault(); }
});

async function copyText(text, label, el) {
  try {
    await navigator.clipboard.writeText(text);
    const old = el.textContent; el.textContent = "הועתק";
    setTimeout(() => { el.textContent = old; }, 1600);
  } catch (err) {
    binaTell("ההעתקה האוטומטית נחסמה בדפדפן — סמן את הטקסט והעתק ידנית.", "warn");
  }
}

// ── exec ────────────────────────────────────────────────────────────────────────
function openExec(id) {
  const c = findComputer(id) || {};
  S.execId = id;
  $("execTitle").textContent = "הרצת פקודה ב־" + (c.label || c.host);
  $("execStatus").textContent = "";
  $("execResult").innerHTML = "";
  $("fCmd").value = "";
  openModal("execModal");
  $("fCmd").focus();
}

async function run() {
  if (S.busy) return;
  const cmd = $("fCmd").value;
  if (!cmd.trim()) { $("execStatus").textContent = "צריך לכתוב פקודה."; return; }
  S.busy = true;
  $("btnRun").disabled = true;
  $("execStatus").textContent = "מריץ…";
  $("execResult").innerHTML = "";
  const timeout = parseInt($("fTimeout").value, 10) || 60;
  const r = await postJson("api/computers/" + encodeURIComponent(S.execId) + "/exec",
                           { command: cmd, timeout: timeout });
  S.busy = false;
  $("btnRun").disabled = false;
  const d = r.d || {};
  if (!r.ok) {
    $("execStatus").textContent = "";
    $("execResult").innerHTML = alertBox("bad", esc(d.error || "ההרצה נכשלה"));
    return;
  }
  const code = d.code == null ? "—" : d.code;
  $("execStatus").textContent = `קוד יציאה ${code}` + (d.elapsed != null ? ` · ${d.elapsed}s` : "");
  const body = [];
  if (d.reason) body.push(alertBox(d.state === "needs_action" ? "warn" : "bad", esc(d.reason) +
    (d.action ? `<div class="small">${esc(d.action)}</div>` : "")));
  body.push(`<div class="small muted">stdout</div><pre class="out">${esc(d.stdout || "(ריק)")}</pre>`);
  if (d.stderr) body.push(`<div class="small muted" style="margin-top:10px">stderr</div><pre class="out err">${esc(d.stderr)}</pre>`);
  $("execResult").innerHTML = body.join("");
  // the command may have changed the machine (a reboot, a service restart) — re-probe it
  probeOne(S.execId);
}

// ── approve the key ─────────────────────────────────────────────────────────────
async function openAuth(id) {
  const c = findComputer(id) || {};
  S.authId = id;
  $("authTitle").textContent = "אישור המפתח ב־" + (c.label || c.host);
  $("authStatus").textContent = "";
  $("authKey").textContent = "טוען…";
  $("authCmd").textContent = "";
  openModal("authModal");
  const r = await postJson("api/computers/" + encodeURIComponent(id) + "/authorize-command");
  if (!r.ok) {
    $("authKey").textContent = "—";
    $("authCmd").textContent = (r.d && r.d.error) || "לא ניתן להפיק את הפקודה";
    return;
  }
  $("authKey").textContent = r.d.public_key || "—";
  $("authCmd").textContent = r.d.command || "—";
}

// ── add a computer ──────────────────────────────────────────────────────────────
async function add() {
  if (S.busy) return;
  const host = $("fHost").value.trim();
  if (!host) { $("addErr").innerHTML = alertBox("bad", "צריך כתובת."); return; }
  S.busy = true;
  $("btnAddGo").disabled = true;
  $("addStatus").textContent = "מוסיף ובודק…";
  $("addErr").innerHTML = "";
  const r = await postJson("api/computers", {
    host: host,
    user: $("fUser").value.trim() || "root",
    port: parseInt($("fPort").value, 10) || 22,
    label: $("fLabel").value.trim(),
    private_key: $("fKey").value,
  });
  S.busy = false;
  $("btnAddGo").disabled = false;
  $("addStatus").textContent = "";
  if (!r.ok) {
    $("addErr").innerHTML = alertBox("bad", esc((r.d && r.d.error) || "ההוספה נכשלה"));
    return;
  }
  const id = r.d.id;
  closeModal("addModal");
  ["fHost", "fLabel", "fKey"].forEach((f) => { $(f).value = ""; });
  await load(true);
  const c = findComputer(id);
  if (c && !c.ok) openAuth(id);        // the useful next step, not a dead end
}

// ── wiring ──────────────────────────────────────────────────────────────────────
$("btnRefresh").onclick = () => { setLive(false); load(true); };
$("btnAdd").onclick = () => { $("addErr").innerHTML = ""; openModal("addModal"); $("fHost").focus(); };
$("btnAddGo").onclick = add;
$("btnRun").onclick = run;
$("btnCopyKey").onclick = (e) => copyText(S.key && S.key.public_key || "", "key", e.target);
$("btnCopyAuth").onclick = (e) => copyText($("authCmd").textContent || "", "cmd", e.target);
$("btnAuthProbe").onclick = async () => {
  $("authStatus").textContent = "בודק…";
  const r = await probeOne(S.authId);
  const ok = r.d && r.d.ok;
  $("authStatus").textContent = ok ? "המחשב מחובר" : ((r.d && r.d.reason) || "עדיין לא");
  if (ok) setTimeout(() => closeModal("authModal"), 1200);
};
$("fCmd").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
});

load(true);
// the fleet is polled, not watched: one SSH round trip per machine per cycle (the server caches it
// for 20s), and NOTHING while the tab is hidden — a background dashboard must not keep waking
// remote machines.
setInterval(() => { if (!document.hidden) load(true); }, 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(true); });

/* ── the machine's OWN security ────────────────────────────────────────────────────────────────────
 *
 * The sites app asks whether a WEBSITE is safe to expose; this asks whether the MACHINE it runs on
 * is. The two are different questions with different fixes, and this one is the half nobody looks at
 * until an SSH password or an open Redis has already been found by somebody else.
 *
 * Every finding carries what it means and what to do; the raw facts stay one click away because an
 * audit you cannot argue with is an audit people learn to ignore.
 */
async function openAudit(id) {
  const c = (S.computers || []).find((x) => x.id === id) || {};
  $("auditTitle").textContent = "אבטחת המחשב — " + (c.label || c.host || id);
  $("auditBody").innerHTML = '<div class="spin">בודק את המחשב… (סריקה של הגדרות, חומת אש, עדכונים ופורטים)</div>';
  openModal("auditModal");
  const r = await api("api/computers/" + encodeURIComponent(id) + "/audit");
  if (!r.ok) {
    $("auditBody").innerHTML = alertBox("bad", "<b>הבדיקה לא רצה.</b> " +
      esc((r.d && (r.d.error || r.d.reason)) || binaSaid(r.status)) +
      (r.d && r.d.stderr ? `<pre class="out err">${esc(r.d.stderr)}</pre>` : ""));
    return;
  }
  const d = r.d;
  const order = { error: 0, warn: 1, info: 2, ok: 3 };
  const he = { error: "שגיאה", warn: "אזהרה", info: "מידע", ok: "תקין" };
  const cls = { error: "bad", warn: "warn", info: "unset", ok: "ok" };
  const rows = (d.findings || []).slice().sort((a, b) => order[a.severity] - order[b.severity])
    .map((f) => `<div class="audit-row ${esc(f.severity)}">
      <div class="audit-top"><span class="pill ${cls[f.severity]}">${esc(he[f.severity] || f.severity)}</span>
        <b>${esc(f.title)}</b></div>
      ${f.detail ? `<div class="small muted">${esc(f.detail)}</div>` : ""}
      ${f.fix ? `<div class="small fix">מה עושים: ${esc(f.fix)}</div>` : ""}
    </div>`).join("");
  const facts = Object.entries(d.facts || {}).map(([k, v]) =>
    `<tr><td class="mono small">${esc(k)}</td><td class="mono small">${esc(v)}</td></tr>`).join("");
  $("auditBody").innerHTML = `
    <div class="callout ${d.state === "ok" ? "" : d.state === "warn" ? "warn" : "bad"}">
      <b>${esc(d.label || d.host)}</b> — ${[["error", "שגיאה אחת", "שגיאות"], ["warn", "אזהרה אחת", "אזהרות"],
        ["info", "הערה אחת", "הערות"]].map(([k, one, many]) => (d.counts[k] === 1 ? one : `${d.counts[k]} ${many}`)).join(", ")}.
      ${d.cached ? "תוצאה מהבדיקה האחרונה (עד 5 דקות)." : ""}
    </div>
    ${rows}
    <details><summary>הנתונים הגולמיים מהמחשב</summary>
      <table class="table small"><tbody>${facts}</tbody></table></details>`;
}

window.openAudit = openAudit;
