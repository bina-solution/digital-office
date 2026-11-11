/* terminal — the screen. A shell is a SESSION here: open, type, poll (see apps/computers/shell.py
   for why the transport is HTTP and not a websocket — short version: the console's /a/<alias>/
   proxy does not carry an upgrade, so a socket would never open in the office's own framing).

   Served by COMPUTERS itself (DGO-1800): the app that owns the machines' key, the sessions and the caller check, so
   the person (through the console) or the linked office (through the door) is who computers sees — there is no relay
   between them whose word it would have to take. Every URL below is RELATIVE to computers' root: the console points
   the page's base at /a/computers/, and served alone the page is /terminal — an absolute "/api/..." would leave it. */
"use strict";

/** What the screen says about a session goes to the page (`mHint`, the alert band), never into xterm: it has no
 *  right-to-left, and a Hebrew line written into it is drawn reversed («רבחתמ…»). The terminal itself gets only the
 *  machine's own bytes and this neutral rule where a session ends. */
const MARK = "\r\n\u001b[90m" + "─".repeat(24) + "\u001b[0m\r\n";

/** computers' own shell routes for one machine: open (no rest), `/<sid>/input`, `/<sid>?cursor=`, `/<sid>/resize`. */
const shellUrl = (id, rest = "") => `api/computers/${encodeURIComponent(id)}/shell${rest}`;

const $ = (id) => document.getElementById(id);
const S = { machines: [], machine: null, session: null, cursor: 0, term: null, fit: null,
            sending: false, polling: false, timer: null, alive: false, last: "" };

function alertBox(kind, text) {
  const el = $("mAlert");
  el.className = "tt-alert" + (kind === "warn" ? " warn" : "");
  el.innerHTML = text;
}
function hideAlert() { $("mAlert").className = "tt-alert hidden"; }

function stateLabel(m) {
  if (!m) return { he: "לא מחובר", cls: "muted" };
  if (m.ok) return { he: "מחובר", cls: "ok" };
  if (m.state === "no_ssh") return { he: "ללא SSH", cls: "muted" };
  if (m.state === "needs_action") return { he: "ממתין לאישור", cls: "warn" };
  if (m.state === "error" || m.state === "missing") return { he: "שגיאה", cls: "bad" };
  return { he: "לא ידוע", cls: "muted" };
}

function paintMachine() {
  const m = S.machine;
  const st = stateLabel(m);
  const pill = $("mState");
  pill.className = "pill " + st.cls;
  pill.textContent = st.he;
  $("mHost").textContent = m ? `${m.user || ""}@${m.host || ""}` : "";
  const hint = $("mHint");
  if (!m) hint.textContent = "בחר מחשב ולחץ «התחברות»";
  else if (S.alive) hint.textContent = "מחובר — הקלד כדי לעבוד";
  else if (S.note) hint.textContent = S.note;                  // how the last session ended, or that one is opening
  else if (m.state === "no_ssh") hint.textContent = "אין SSH במחשב הזה — שרת SSH לא מותקן או לא מאזין";
  else if (m.state === "needs_action") hint.textContent = "מפתח הלשכה טרם אושר במחשב — «אישור המפתח» במסך מחשבים";
  else if (m.shell === false) hint.textContent = "הלשכה הזו עדיין לא תומכת בטרמינל מרחוק — צריך לעדכן אותה";
  else hint.textContent = "לחץ «התחברות» כדי לפתוח שורה";
  $("btnConn").disabled = !m || m.shell === false || !!S.session;   // no machine yet: nothing to connect to
  if (S.term && !S.session) {
    $("termMount").innerHTML = `<div class="tt-off">${m
      ? "אין טרמינל פתוח"
      : "בחר מחשב כדי להתחיל"}</div>`;
  }
}

async function api(path, opt) {
  const r = await fetch(path, opt).catch(() => null);
  if (!r) return { ok: false, status: 0, d: { error: "השרת לא ענה" } };
  const d = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, d: d || {} };
}
const postJson = (p, b) => api(p, { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify(b || {}) });

function fillSelect() {
  const sel = $("mSel");
  sel.innerHTML = "";
  if (!S.machines.length) {
    sel.innerHTML = `<option value="">אין מחשבים ברשימה</option>`;
    return;
  }
  for (const m of S.machines) {
    const o = document.createElement("option");
    o.value = m.id;
    const st = stateLabel(m);
    o.textContent = `${m.label || m.host} — ${st.he}`;
    sel.appendChild(o);
  }
  const want = S.machine && S.machines.some((m) => m.id === S.machine.id) ? S.machine.id
    : (S.machines.find((m) => m.ok) || S.machines[0]).id;
  sel.value = want;
  pick(want);
}

function pick(id) {
  S.machine = S.machines.find((m) => m.id === id) || null;
  if (S.session) disconnect(true);
  S.note = "";                                               // the last session's note belonged to another machine
  paintMachine();
}

async function loadMachines() {
  // `probe=0`: the screen opens in a fraction of a second even when a machine far away does not answer; each row's
  // state is the probe cache's. Mapped here as apps/terminal's server did before the screen moved.
  const r = await api("api/computers?probe=0");
  if (!r.ok) {
    // escaped: through the door this sentence is another office's computers' (the page runs on the console's origin)
    alertBox("bad", `<b>רשימת המחשבים לא נטענה.</b> ${esc((r.d && r.d.error) || "")}`);
    return;
  }
  S.machines = (r.d.computers || []).map((c) => ({
    id: c.id, label: c.label || c.host, host: c.host, user: c.user, port: c.port, state: c.state,
    ok: !!c.ok, builtin: !!c.builtin, note: c.note || "", reason: c.reason || "", action: c.action || "",
    ssh: c.state !== "no_ssh",
    // a machine of a linked office whose app is older than `shell` cannot take a terminal: said, not offered
    shell: c.remote ? (c.remote.shell ?? null) : null,
  }));
  if (r.d.office_key && r.d.office_key.fingerprint) S.last = r.d.office_key.fingerprint;
  // WHOSE MACHINES THESE ARE — and which sharing office did not answer. Without it a link that
  // blipped simply removes a peer's machines from the picker, which reads as "sharing was withdrawn"
  // (apps/computers draws the same line, for the same reason).
  const shared = (r.d.shared_from || []).map((s) =>
    (s.ok === false ? `${s.label} (${s.why || "לא ענתה"})` : s.label));
  const sub = $("ttSub");
  if (sub) {
    sub.textContent = "שורת פקודה על מחשבי הלשכה"
      + (shared.length ? ` · משותף עם ${shared.join(" · ")}` : "");
  }
  fillSelect();
}

function makeTerm() {
  if (S.term) {
    // paintMachine() puts «אין טרמינל פתוח» in the mount once a session ends, which takes xterm's element out; xterm 5
    // will not open() twice, so the element is put back — or the next session's output and keys go nowhere (the
    // second reader; the terminal app had the same)
    if (S.term.element && !S.term.element.isConnected) {
      $("termMount").replaceChildren(S.term.element);
      try { S.fit.fit(); } catch (e) { /* not sized yet */ }
    }
    return S.term;
  }
  const term = new window.Terminal({
    cursorBlink: true,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontSize: 14,
    lineHeight: 1.15,
    convertEol: false,
    scrollback: 4000,
    // xterm takes colour strings, not CSS, so its theme is read off the office's palette where it
    // mounts (G82): the dark ground of .tt-term (style.css says why it is dark on both grounds), the
    // light ink written on the palette's fills, lime for the cursor, olive under a selection — tokens
    // that are the same in light and dark, so reading them once is enough. A token that is not there
    // leaves xterm its own default (also dark) rather than a second palette.
    theme: (() => {
      const css = getComputedStyle($("termMount"));
      const tok = (name) => css.getPropertyValue(name).trim() || undefined;
      return { background: tok("--lime-ink"), foreground: tok("--olive-ink"), cursor: tok("--lime"),
               selectionBackground: tok("--olive") };
    })(),
  });
  const fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  $("termMount").innerHTML = "";
  term.open($("termMount"));
  S.term = term; S.fit = fit;
  try { fit.fit(); } catch (e) { /* the element may still be zero-sized */ }
  term.onData((data) => sendInput(data));
  window.addEventListener("resize", () => {
    if (!S.session) return;
    try { fit.fit(); } catch (e) { return; }
    postJson(shellUrl(S.machine.id, `/${encodeURIComponent(S.session)}/resize`), { cols: term.cols, rows: term.rows });
  });
  return term;
}

async function connect() {
  if (!S.machine) { alertBox("warn", "בחר מחשב קודם."); return; }
  // THE SAME RULE AS THE BUTTON, for the door that does not go through it. «טרמינל» on a row of
  // «מחשבים» opens this screen with `?machine=…` and calls connect() directly, so a machine of a
  // linked office whose app predates `shell` used to be attempted anyway: a "מתחבר…" in the pane and
  // then a 501. The button is disabled for it; the deep link has to say the same thing without the
  // round trip.
  if (S.machine.shell === false) {
    const why = "הלשכה הזו עדיין לא תומכת בטרמינל מרחוק — צריך לעדכן אותה";
    alertBox("warn", why);                                   // said above the terminal, never into it
    return;
  }
  const btn = $("btnConn");
  btn.disabled = true; btn.textContent = "מתחבר…";
  const term = makeTerm();
  term.reset();
  // said on the hint line only: paintMachine() here, before the session exists, would put «אין טרמינל פתוח» over
  // the terminal just mounted (seen in the DGO-1800 demo)
  $("mHint").textContent = "מתחבר…";
  const r = await postJson(shellUrl(S.machine.id), { cols: term.cols, rows: term.rows });
  btn.disabled = false; btn.textContent = "התחברות";
  if (!r.ok) {
    S.session = null; S.alive = false;
    S.note = (r.d && r.d.error) || "הפתיחה נכשלה";
    const extra = r.d && (r.d.action || r.d.detail) ? "\n" + (r.d.action || r.d.detail) : "";
    alertBox("bad", `<b>${esc((r.d && r.d.error) || "הפתיחה נכשלה")}</b>${extra ? " — " + esc(extra.trim()) : ""}`);
    paintMachine();
    return;
  }
  S.session = r.d.session;
  S.cursor = r.d.cursor || 0;
  S.alive = r.d.alive !== false;
  S.note = "";
  hideAlert();
  if (r.d.output) term.write(r.d.output);
  $("btnDisc").disabled = false;
  paintMachine();
  pollLoop();
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;",
    ">": "&gt;", '"': "&quot;" }[c]));
}

// `at` is the cursor the request asked from. A poll and a keystroke can be in flight at once from the same
// cursor, and each answer carries the same new bytes: writing both drew every echo twice (the second reader,
// 2026-11-10). An answer from a cursor that has moved on since is dropped — nothing is lost by it, because the
// next poll asks from the cursor as it is now. An answer for a session that is no longer this screen's (a
// disconnect and a new connect in between) is dropped too, whatever its cursor.
function absorb(d, at, sid) {
  if (!d) return;
  if (typeof at === "number" && (at !== S.cursor || sid !== S.session)) return;
  if (typeof d.cursor === "number") S.cursor = d.cursor;
  if (d.lost) {
    alertBox("warn", "<b>חלק מהפלט אבד</b> — החיבור היה איטי מדי");
    if (S.term) S.term.write(MARK);
  }
  if (d.output) S.term.write(d.output);
  if (d.alive === false && S.alive) {
    S.alive = false;
    $("btnDisc").disabled = true;
    S.note = "הטרמינל נסגר" + (d.reason ? ": " + d.reason : "");
    if (S.term) S.term.write(MARK);
    paintMachine();
  }
}

async function sendInput(data) {
  if (!S.session || !S.machine) return;
  if (S.sending) {                        // one request in flight: the next keystroke joins the queue
    S.queue = (S.queue || "") + data;
    return;
  }
  S.sending = true;
  const out = data, at = S.cursor, sid = S.session;
  const r = await postJson(shellUrl(S.machine.id, `/${encodeURIComponent(S.session)}/input`), { data: out, cursor: at });
  S.sending = false;
  if (!r.ok) {
    alertBox("bad", `<b>${esc((r.d && r.d.error) || "השליחה נכשלה")}</b>`);
    if (r.status === 404 || r.status === 409) { S.session = null; $("btnDisc").disabled = true; }
    return;
  }
  absorb(r.d, at, sid);
  if (S.queue) { const q = S.queue; S.queue = ""; sendInput(q); }
}

async function poll() {
  if (!S.session || !S.machine) return;
  const at = S.cursor, sid = S.session;
  const r = await api(shellUrl(S.machine.id, `/${encodeURIComponent(S.session)}?cursor=${at}`));
  if (!r.ok) {
    if (r.status === 404) {
      S.session = null; S.alive = false; $("btnDisc").disabled = true;
      S.note = "הטרמינל הזה אינו פתוח יותר";
      if (S.term) S.term.write(MARK);
      paintMachine();
      return;
    }
  } else {
    absorb(r.d, at, sid);
    // A FINISHED SHELL IS NOT POLLED AGAIN. `absorb` writes «הטרמינל נסגר» the moment the answer says
    // `alive: false`, and the loop used to keep asking every 320 ms until a person pressed a button
    // that is already disabled — a closed session answering the same nothing several times a second
    // (found reading the loop, 2026-11-02).
    if (S.alive === false) return;
  }
  pollLoop();
}

function pollLoop() {
  clearTimeout(S.timer);
  if (!S.session) return;
  // 320 ms is the cost of not having a socket: fast enough that typing feels direct, slow enough
  // that an idle terminal is ~3 requests a second and not a busy loop.
  S.timer = setTimeout(poll, 320);
}

async function disconnect(silent) {
  const m = S.machine, sid = S.session;
  clearTimeout(S.timer);
  S.session = null; S.alive = false;
  $("btnDisc").disabled = true;
  if (m && sid) await api(shellUrl(m.id, `/${encodeURIComponent(sid)}`), { method: "DELETE" });
  if (!silent) {
    S.note = "התנתקת";
    if (S.term) S.term.write(MARK);
  }
  paintMachine();
}

// leaving the page ends its session: a shell to somebody's machine is not left open for the idle reaper's half hour
window.addEventListener("pagehide", () => {
  if (S.machine && S.session) {
    fetch(shellUrl(S.machine.id, `/${encodeURIComponent(S.session)}`), { method: "DELETE", keepalive: true }).catch(() => {});
  }
});

$("btnConn").addEventListener("click", connect);
$("btnDisc").addEventListener("click", () => disconnect(false));
$("mSel").addEventListener("change", (e) => pick(e.target.value));

(async function boot() {
  const want = new URLSearchParams(location.search).get("machine");
  await loadMachines();
  if (want) {
    const sel = $("mSel");
    if (S.machines.some((m) => m.id === want)) { sel.value = want; pick(want); connect(); }
  } else {
    paintMachine();
  }
})();
