// How many turns the office's Claude runs at once (DGO-2126). On 2026-11-20 09:17Z the HP starved: one manager's
// lanes ran TEN turns at once in its Claude Desktop — 3.5 of 5 GiB, load 92 on 6 CPUs, 133 MB free, swap full
// (issues/the-hps-claude-desktop-keeps-a-claude-process-per-request-and-starves-the-hp.yaml). Asking every manager to
// remember a number failed twice, and agent.v1 cannot reach a desktop turn once it runs, so the cap holds where turns
// START through this adapter: a turn asked for while N run — a new session's first message, or a message to a session
// that is idle — waits in a line here, the sender is told so (`queued`, its place, and `qid`, the line's id for it),
// and the line starts it when a turn ends. N is the office's: BINA_CLAUDE_MAX_TURNS, 4 when it says nothing, 0 for no
// cap.
//
// The line is on disk (one JSON file in the adapter's state): an adapter restart keeps it — and beside it, for a day,
// what became of what left it: the session each promise it started became, and what it gave up on (by qid), so a
// sender that asks after a deploy still learns. A turn is marked SENT on disk before its start leaves, so a restart in
// the middle of one never starts it again: it is reported «may have been delivered» instead (a drive goes on inside
// the app's container after the adapter dies). A start that pressed nothing stays in line and is tried again — 3 s,
// doubling, at most a minute apart — and never holds the line behind it; the app being away or another drive clears
// by itself, so such a start is never dropped. One refused for the owner's own work in the app (a draft in that box,
// another page up) is given up after OWNER_TRIES, reported «not sent»: trying it again pulls his screen. A start that
// may have been delivered leaves the line and is reported to its sender, never sent twice. What the line does not do:
// stop a turn that runs, or hold a turn started on the app's own screen (the owner's typing, a session's own side
// sessions) — those are counted, never queued.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const DEFAULT_CAP = 4;
// A start refused for the owner's own work in the app — a draft in that session's box, another page up — is given up
// after this many tries, reported «not sent»: each try follows the session's link and reads its box, which would
// pull the owner's screen about every minute for as long as he works.
export const OWNER_TRIES = 2;

// BINA_CLAUDE_MAX_TURNS → the cap: a whole number 0…64 (0 = no cap); nothing or anything else → the default, said once.
export function capOf(raw, log = () => {}) {
  if (raw === undefined || raw === null || String(raw).trim() === "") return DEFAULT_CAP;
  const s = String(raw).trim();
  if (/^[0-9]{1,2}$/.test(s) && Number(s) <= 64) return Number(s);
  log(`[bina-claude] BINA_CLAUDE_MAX_TURNS=${JSON.stringify(raw)} is not a whole number 0–64: the cap is ${DEFAULT_CAP}`);
  return DEFAULT_CAP;
}

// Whether a NEW turn may start now. `queued` counts the waiting turns that could start now: one of those is never
// jumped — a free slot belongs to the turn that has waited longest.
export function mayStart({ cap, active, queued }) {
  if (!cap) return true;
  return queued === 0 && active < cap;
}

// When a start that pressed nothing is tried again: 3 s, 6 s, 12 s … at most a minute after its last try.
export const backoff = (tries) => Math.min(60000, 3000 * 2 ** Math.max(0, tries - 1));

// The line. `start(item)` starts one turn (it throws what the driver threw); `retryable(error)` says a failure pressed
// nothing (the item stays, backed off — unless `owners(error)`: the owner's own work refused it, given up after
// OWNER_TRIES); any other failure may have been delivered, so the item leaves the line — never sent twice — and
// `failed(item, error)` records it for its sender. `active()` counts the turns that run now, `ready(item)` says
// whether this one can start now (a message to a session still in its own turn cannot), and `blocked()` is told when
// turns wait at the cap, or none of them can start. The first item that is ready and not backed off goes — never ahead
// of an earlier one for its own session — so one item never holds the others behind it, and one session's messages
// keep their order. Nothing is read before the first use: importing the adapter touches no file.
export function createTurnQueue({ file, cap, active, start, retryable = () => false, owners = () => false,
                                  failed = () => {}, ready = () => true, blocked = () => {}, log = console.error,
                                  every = 3000, now = () => Date.now() }) {
  let items = null;            // read from disk on first use
  let kept = {};               // promise (pending id) → { id: the session the line started it as, at }
  let gone = [];               // [{ target, qid, code, maybe, at }]: what the line gave up on
  let busy = false;
  let timer = null;
  const DAY = 86400000;

  function save(next = items) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ v: 1, items: next, kept, failed: gone }), { mode: 0o600 });
    fs.renameSync(tmp, file);
  }
  function prune() {
    const t = now();
    for (const [k, v] of Object.entries(kept)) if (!v || t - v.at > DAY) delete kept[k];
    gone = gone.filter((x) => t - x.at < DAY).slice(-2000);   // a pruned one would read as «sent»: keep a day's worth
  }
  const trySave = () => { try { save(); } catch (e) { log(`[bina-claude] the line could not be written (${e.code || e.message})`); } };
  const report = (item, code, why) => {
    try { failed(item, Object.assign(new Error(why), { code })); } catch (e) { log(`[bina-claude] a failure of the line could not be recorded: ${e.message}`); }
  };

  // A start that was under way when the adapter stopped may have been delivered: never started again, reported.
  function load() {
    if (items) return items;
    let raw = null;
    try { raw = JSON.parse(fs.readFileSync(file, "utf8")); }
    catch (e) {
      if (e.code !== "ENOENT") {
        // never written over: what it held (waiting turns, the day's outcomes) stays beside it for a person to read
        const aside = `${file}.unreadable-${now()}`;
        try { fs.renameSync(file, aside); } catch { /* the line starts empty all the same */ }
        log(`[bina-claude] the line on disk could not be read (${e.code || e.message}): kept as ${path.basename(aside)}; it starts empty`);
      }
    }
    const all = raw && Array.isArray(raw.items)
      ? raw.items.filter((i) => i && i.qid && i.kind && i.target && typeof i.text === "string") : [];
    kept = raw && raw.kept && typeof raw.kept === "object" && !Array.isArray(raw.kept) ? raw.kept : {};
    gone = raw && Array.isArray(raw.failed) ? raw.failed.filter((x) => x && x.target && x.qid && x.code && x.at) : [];
    prune();
    const lost = all.filter((i) => i.sent);
    items = all.filter((i) => !i.sent);
    for (const i of lost) {
      log(`[bina-claude] ${i.kind} ${i.target} was being started when the adapter stopped: it may have been delivered — not started again`);
      report(i, "unknown", "the adapter stopped while it was being started: it may have been delivered");
    }
    if (lost.length) trySave();
    return items;
  }

  // `kind` "new": the first message of a session promised under `target` (a pending id); "send": a message to the
  // app's session `target`. The same words for the same target while they still wait are one message (a retry whose
  // answer never came back, or the same message sent again by someone who could not see it waits): its place and id.
  // The line is written BEFORE the answer says «queued»: a write that fails queues nothing (the caller sees why).
  // → { place, qid }
  function enqueue(kind, target, text) {
    load();
    const t = now();
    let i = items.findIndex((x) => x.kind === kind && x.target === target && x.text === text);
    if (i < 0) {
      const next = [...items, { qid: crypto.randomUUID(), kind, target, text, at: t }];
      save(next);
      items = next;
      i = items.length - 1;
      log(`[bina-claude] queued: ${kind} ${target} — ${active()} turn(s) run, the cap is ${cap}; ${items.length} waiting`);
    }
    return { place: i + 1, qid: items[i].qid };
  }
  const place = (target) => { const i = load().findIndex((x) => x.target === target); return i < 0 ? 0 : i + 1; };
  const count = (target) => load().filter((x) => x.target === target).length;
  const qids = (target) => load().filter((x) => x.target === target).map((x) => x.qid);
  const placeOf = (qid) => { const i = load().findIndex((x) => x.qid === qid); return i < 0 ? 0 : i + 1; };
  // A promise the line kept: the session it became is kept for a day, and what still waits for it goes to that
  // session from now on — on disk, in one write, so a restart never starts a second session from it.
  function keep(promise, session) {
    load();
    kept[promise] = { id: session, at: now() };
    for (const x of items) if (x.target === promise) { x.kind = "send"; x.target = session; }
    trySave();
  }
  const keptOf = (promise) => { load(); const k = kept[promise]; return k && now() - k.at < DAY ? k.id : null; };
  const promiseOf = (session) => {
    load();
    for (const [k, v] of Object.entries(kept)) if (v.id === session && now() - v.at < DAY) return k;
    return null;
  };
  // What the line gave up on, by the target it was for (a session, or a promise it never started) and its qid.
  function noteFailed(target, qid, code, maybe) {
    load();
    gone.push({ target, qid, code, maybe: !!maybe, at: now() });
    prune();
    trySave();
  }
  const failedFor = (target) => { load(); const t = now(); return gone.filter((x) => x.target === target && t - x.at < DAY).map(({ qid, code, maybe, at }) => ({ qid, code, maybe, at })); };
  // What could start now, in order: an item ready and not backed off, and never ahead of an earlier one for its own
  // session (or promise) — one session's messages go in the order they came. One backed off, or one whose session is
  // in its own turn, lets the others pass — and a newcomer too.
  function startable() {
    const t = now(), held = new Set(), out = [];
    for (const x of load()) {
      if (!held.has(x.target) && !(x.after > t) && ready(x)) out.push(x);
      held.add(x.target);
    }
    return out;
  }
  const allows = () => !cap || mayStart({ cap, active: active(), queued: startable().length });

  // One turn at most per tick, and never two ticks at once: a start is visible to `active()` only after it began.
  async function tick() {
    load();
    if (busy || !items.length) return null;
    if (cap && active() >= cap) {
      try { blocked(); } catch (e) { log(`[bina-claude] the line's blocked hook failed: ${e.message}`); }
      return null;
    }
    const [head] = startable();
    if (!head) {                                       // all wait on their sessions: one may be a dead process's file
      try { blocked(); } catch (e) { log(`[bina-claude] the line's blocked hook failed: ${e.message}`); }
      return null;
    }
    const t = now();
    busy = true;
    try {
      head.sent = t;
      try { save(); } catch (e) { delete head.sent; log(`[bina-claude] the line could not be written (${e.code || e.message}): nothing started`); return null; }
      try {
        const out = await start(head);
        items = items.filter((x) => x.qid !== head.qid);
        trySave();
        log(`[bina-claude] started from the line: ${head.kind} ${head.target}; ${items.length} waiting`);
        return out;
      } catch (e) {
        if (retryable(e) && owners(e) && (head.ownerTries || 0) + 1 >= OWNER_TRIES) {
          items = items.filter((x) => x.qid !== head.qid);
          log(`[bina-claude] ${head.kind} ${head.target}: the owner works in the app (${e.code}) — given up after ${OWNER_TRIES} such refusals, nothing was sent`);
          report(head, e.code, `given up after ${OWNER_TRIES} refusals for the owner's own work — nothing was sent: ${e.message}`);
        } else if (retryable(e)) {
          delete head.sent;
          head.tries = (head.tries || 0) + 1;
          if (owners(e)) head.ownerTries = (head.ownerTries || 0) + 1;   // counted apart: another drive is not his work
          head.after = now() + backoff(head.tries);
          if (head.tries === 1 || head.tries % 10 === 0) {
            log(`[bina-claude] ${head.kind} ${head.target} pressed nothing (${e.code}); tried ${head.tries}×, again in ${backoff(head.tries) / 1000} s`);
          }
        } else {
          items = items.filter((x) => x.qid !== head.qid);
          log(`[bina-claude] a turn from the line failed (${e.code || e.message}) and left it — never sent twice: ${head.kind} ${head.target}`);
          report(head, e.code || "unknown", e.message);
        }
        trySave();
        return null;
      }
    } finally { busy = false; }
  }

  return {
    enqueue, place, placeOf, count, qids, keep, keptOf, promiseOf, noteFailed, failedFor, allows, tick,
    length: () => load().length,
    // always, even with no cap: a line kept on disk under an earlier cap still starts
    start() {
      load();
      if (!timer) timer = setInterval(() => { tick().catch((e) => log(`[bina-claude] the line's tick failed: ${e.message}`)); }, every);
      timer.unref?.();
      return this;
    },
    stop() { if (timer) clearInterval(timer); timer = null; },
  };
}
