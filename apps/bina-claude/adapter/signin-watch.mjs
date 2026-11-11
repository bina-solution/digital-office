// apps/bina-claude/adapter/signin-watch.mjs — a sign-in that is lost is never silent (DGO-1684).
//
// Bina Claude has ONE sign-in: the official desktop app's (there is no terminal). It can end without a word —
// claude.ai retires an old session, a store does not survive a recreate — and the office's Claude stops
// working. This asks once a minute. When it WAS signed in and reads signed out twice in a row (a store read
// mid-write is not a sign-out), it posts a notice to the office's notifications app at level `error` — the
// owner's phone rings — with the step that signs it in again and the tile's link. Signed in again, the
// notice is marked read. An app that was never signed in raises nothing: on a new office that is the
// setup's step, not news. What was seen is kept in the app's state folder, so a restart of the adapter
// neither forgets a sign-in nor rings twice. Presence only: no credential's value is ever read out.
import fs from "node:fs";
import path from "node:path";

const MISSES = 2;

/** The desktop app (its HOME): {state: true | false | null, why}. Its claude.ai session cookie on disk is a sign-in.
 *  The cookie's ABSENCE is not a sign-out by itself: measured on Exampleu 2026-11-09, the running app took the
 *  cookie off the disk (18:59 and 19:03) while it stayed signed in and its sessions answered — and a watcher
 *  that read that as «signed out» rang the owner's phone twice for nothing (DGO-1684). What the app records
 *  at its own start is the fact: `[startup-sign-in] state: { sign_in_cookie_present: … }` in its main.log.
 *  So no cookie is «signed out» only when the app STARTED without one; after a start with one, it is
 *  «unknown» — still signed in now, signed out at its next start if the cookie does not come back. */
export function desktopSignIn(home) {
  const dir = path.join(home, ".config", "Claude");
  let raw;
  try { raw = fs.readFileSync(path.join(dir, "Cookies"), { encoding: "latin1" }); }
  catch (e) {
    return e.code === "ENOENT" ? { state: false, why: "the app has no cookie store yet — open «בינה קלוד» in the console and sign in" }
      : { state: null, why: "the app's cookie store could not be read" };
  }
  if (raw.includes("sessionKey")) return { state: true, why: "the app holds its claude.ai session cookie" };
  let log = "";
  try { log = fs.readFileSync(path.join(dir, "logs", "main.log"), "utf8"); } catch { /* no log: unknown */ }
  const at = log.lastIndexOf("[startup-sign-in] state: {");
  const m = at < 0 ? null : /sign_in_cookie_present:\s*(true|false)/.exec(log.slice(at, at + 600));
  if (m && m[1] === "false") return { state: false, why: "the app started without a sign-in — open «בינה קלוד» in the console and sign in" };
  // claude.ai refusing to renew the sign-in after that start is a sign-out, whatever the start said (hooks/signed-in).
  if (m && log.indexOf("session_stale_relogin", at) >= 0) {
    return { state: false, why: "claude.ai refused to renew the sign-in (session_stale_relogin) — open «בינה קלוד» in the console and sign in" };
  }
  if (m) return { state: null, why: "the app started signed in; its session cookie has since left the disk — it works now, and a restart would ask for the sign-in again" };
  return { state: null, why: "no session cookie on disk, and the app's own start record is not in its log" };
}

/** What to do now, from what was seen before and what is read now (true | false | null per face). Pure. */
export function step(prev, readings) {
  const next = {};
  const actions = [];
  for (const face of Object.keys(readings)) {
    const p = { seen: false, misses: 0, notice: null, ...(prev[face] || {}) };
    const r = readings[face];
    const n = { ...p };
    if (r === true) {
      n.seen = true;
      n.misses = 0;
      if (p.notice) actions.push({ face, do: "read", id: p.notice });
      else n.incident = null;                       // an incident whose notice never got through is over too
    } else if (r === false) {
      n.misses = p.misses + 1;
      if (p.seen && n.misses >= MISSES && !p.notice) actions.push({ face, do: "post", incident: p.incident || null });
    }
    next[face] = n;
  }
  return { next, actions };
}

// The tile's link is the shell's own route, with no host: the notice is opened on the office's console, and a
// link a person is given is built by the one builder or not at all (gate G95, scripts/refactor/office-link-lint.py).
export function texts(face, { office, at }) {
  const when = new Date(at).toISOString().slice(11, 16);
  return {
    title: "בינה קלוד התנתקה מחשבון Claude",
    body: `האפליקציה «בינה קלוד» בלשכה ${office} אינה מחוברת עוד לחשבון Claude (נמדד ב-${when} UTC, פעמיים ברציפות). `
      + "הסשנים שלה עוצרים עד שתתחבר שוב. הצעד: פתח את האריח «בינה קלוד» בקונסול ← «Continue with Google» "
      + "(או «Continue with email» והקוד שבמייל).",
    link: "/#/m/bina-claude",
  };
}

/**
 * The watcher: `read()` → {desktop} reading; posts through `notifications` (a base URL).
 * `tick()` is one round; `start()` runs it every `everyMs`. Nothing here throws out of a tick.
 */
export function createWatch({ read, stateFile, notifications, office, now = () => Date.now(), log = console.error }) {
  let busy = false;
  const load = () => { try { return JSON.parse(fs.readFileSync(stateFile, "utf8")); } catch { return {}; } };
  const save = (s) => {
    try { fs.writeFileSync(`${stateFile}.tmp`, JSON.stringify(s)); fs.renameSync(`${stateFile}.tmp`, stateFile); }
    catch (e) { log(`[bina-claude] sign-in watch: cannot keep its state (${e.message})`); }
  };
  const call = async (p, body) => {
    const r = await fetch(`${notifications}${p}`, { method: "POST", headers: { "content-type": "application/json" },
                                                     body: JSON.stringify(body || {}), signal: AbortSignal.timeout(10000) });
    if (!r.ok) throw new Error(`notifications answered ${r.status}`);
    return r.json().catch(() => ({}));
  };

  async function tick() {
    if (busy) return [];
    busy = true;
    try {
      const at = now();
      const { next, actions } = step(load(), read());
      for (const a of actions) {
        try {
          if (a.do === "post") {
            // The incident keeps its first time across retries: a post that timed out after notifications took
            // it is the same notice when it is tried again, not a second one.
            const incident = a.incident || at;
            next[a.face].incident = incident;
            const t = texts(a.face, { office, at: incident });
            // One notice per incident: the same source_id would update the last one, and notifications rings an
            // update only 240 minutes after its last ring (PUSH_REPEAT_MIN) — a second sign-out the same morning
            // would be silent.
            const j = await call("/api/notifications", { source: "bina-claude", source_id: `signed-out-${a.face}-${incident}`, level: "error",
                                                          ...t, meta: { face: a.face, office } });
            next[a.face].notice = j.id || true;
            log(`[bina-claude] sign-in watch: the ${a.face} is signed out — notice ${j.id ?? "?"} posted`);
          } else {
            if (typeof a.id === "number") await call(`/api/notifications/${a.id}/read`);
            next[a.face].notice = null;
            next[a.face].incident = null;
            log(`[bina-claude] sign-in watch: the ${a.face} is signed in again — its notice is read`);
          }
        } catch (e) {
          log(`[bina-claude] sign-in watch: ${a.do} for the ${a.face} failed (${e.message}); the next round tries again`);
        }
      }
      save(next);
      return actions;
    } catch (e) {
      log(`[bina-claude] sign-in watch: ${e.message}`);
      return [];
    } finally { busy = false; }
  }

  return { tick, start: (everyMs = 60000) => setInterval(tick, everyMs).unref() };
}
