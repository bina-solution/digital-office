// apps/bina-claude/adapter/spans.mjs — every Claude session of this office, as spans on כל מקביל
// (any-concurrency's lane `bina_claude`, declared as SPAN_SOURCE_BINA_CLAUDE in app.json; DGO-1684).
//
// THE STORE OF RECORD IS CLAUDE CODE'S OWN TRANSCRIPT: one JSONL file per session,
// <home>/.claude/projects/<project>/<session>.jsonl, appended while the session runs — here the official
// desktop app's Claude Code sessions (its HOME, /data/desktop), the ones `bbox agent --app bina-claude`
// drives and the app's own session records name (.config/Claude/claude-code-sessions). Bina Claude is ONLY
// that app, with ONE sign-in; there is no terminal. A store may take more homes (`roots`), the tests do.
// The adapter already reads these files for agent.v1, so this reads them once more as spans and writes
// nothing. bina-ds keeps a ledger of its own (apps/bina-ds/plugins/timeline-lanes/README.md) because
// its harness HANDS it events that are gone afterwards; here the transcript already is the ledger.
//
// THE READER RULES ARE bina-ds's, so any-concurrency reads both lanes the same way:
//   GET ?hours=<h>   every span of the window (24 h when not given; 7 days at most)
//   GET ?since=<ms>  every span that started, ended or CHANGED after <ms>, plus every running one —
//                    a bracket that closes now, or turns out to have crashed, must reach the timeline
//                    now, whenever it began
//   incremental      a transcript is parsed whole once, then only the bytes appended since the last
//                    read; a file last written before the window is never opened (its spans ended
//                    before it), so the 5 s delta poll costs a directory listing and a stat per file.
//
// A session is one row (`סשן <8 chars of its id>`, stable for its whole life). On it: the session's
// own span (first line → last line, running while a turn runs), a span per turn (the owner's prompt →
// the answer's end) and per tool call (tool_use → tool_result), and an instant for an API error and
// for a compaction. A bracket the transcript leaves open is served by what its session is NOW, from
// Claude Code's live file (<home>/.claude/sessions/<pid>.json):
//   live and mid-turn    → running (waiting while it asks the owner)
//   live and idle        → error, ending at its last line (an API error or a limit ended the turn)
//   gone                 → crashed, ending at its last line — never «running» for ever
//   written in the last 30 s → running, whatever the live file says (it can lag the transcript)
//
// Nothing here throws on bad data: a line that is not JSON, or a record of a kind this file does not
// know, costs that line and nothing else. Every label is bounded.
import fs from "node:fs";
import path from "node:path";
import { StringDecoder } from "node:string_decoder";

const LABEL_MAX = 120;
const EXCERPT = 60;
const DEFAULT_HOURS = 24;
const MAX_HOURS = 24 * 7;     // the timeline's widest view («7 ימים»)
const CHUNK = 4 << 20;
const QUIET_MS = 30000;
const FORGET_MS = 26 * 3600000;
// A wide window asked for (the timeline's 7-day view polls every few seconds) keeps its transcripts parsed
// this long after the last ask — the 5 s delta poll would otherwise forget them, and the next ask parse them
// all again from the start.
const WIDE_KEEP_MS = 10 * 60000;
// A bracket whose transcript got no line for this long is not running, whatever a live file says: a Claude
// Code killed under the desktop app (its memory cap) leaves a `busy` file the adapter cannot test (bina-ds's
// lane has the same bound, BINA_TIMELINE_STALE_HOURS).
const STALE_MS = 12 * 3600000;
// A prompt after this long a silence, while a turn never closed, starts a new turn: the open one ended
// without its end being written (a process that died). A message queued into a RUNNING turn comes right
// after that turn's last line.
const SILENCE_MS = 5 * 60000;
// The most transcript one read parses before it answers. The adapter is one thread that also serves agent.v1
// and its event streams: a week of transcripts (a GB on a busy office) parsed in one request would freeze it
// past any-concurrency's 25 s. What is left is parsed by the next reads, and served as new when it is.
const BUDGET = 48 << 20;
// How an answer ENDS a turn (the API's stop reasons); `tool_use` and a missing reason go on.
const ENDS = new Set(["end_turn", "stop_sequence", "max_tokens", "refusal"]);
const MID_TURN = new Set(["busy", "waiting"]);
// The tool argument that names what a call does, in order of preference. A Bash call's own
// description comes before its command line.
const ARG_KEYS = ["description", "file_path", "path", "pattern", "url", "query", "command", "prompt", "skill", "subject"];

const clamp = (s, n = LABEL_MAX) => {
  const one = String(s ?? "").replace(/\s+/g, " ").trim();
  return one.length <= n ? one : `${one.slice(0, n - 1)}…`;
};

function promptText(content) {
  const parts = typeof content === "string" ? [content]
    : Array.isArray(content) ? content.filter((c) => c && c.type === "text").map((c) => c.text || "") : [];
  return parts.join("\n").replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, "").trim();
}

function argOf(input) {
  if (!input || typeof input !== "object") return "";
  for (const k of ARG_KEYS) if (typeof input[k] === "string" && input[k].trim()) return clamp(input[k], EXCERPT);
  return "";
}

/** Claude Code's live files under `home`, by session id: `alive(j)` says whether a file's process
 *  still runs (each home has its own way of telling). Of two files for one session, the newer. */
export function liveSessions(home, alive = () => true) {
  const out = new Map();
  const dir = path.join(home, ".claude", "sessions");
  let names = [];
  try { names = fs.readdirSync(dir); } catch { return out; }
  for (const n of names) {
    if (!n.endsWith(".json")) continue;
    try {
      const j = JSON.parse(fs.readFileSync(path.join(dir, n), "utf8"));
      if (!j || !j.sessionId || !alive(j)) continue;
      const had = out.get(j.sessionId);
      if (!had || (j.startedAt || 0) > (had.startedAt || 0)) out.set(j.sessionId, j);
    } catch { /* mid-write: the next read sees it */ }
  }
  return out;
}

// ── one transcript, folded into spans as its lines arrive ─────────────────────────────────────────
function newTrack(where, file, cli) {
  return {
    where, file, cli, offset: 0, mtime: 0, decoder: new StringDecoder("utf8"), rest: "",
    first: null, last: null, lastLine: null, title: "", prompt: "", cwd: "", model: "",
    turn: 0, turnRow: null, turnOpen: false, lastError: false,
    tools: new Map(),   // tool_use id → its open row
    rows: new Map(),    // span id → row (turns, tools, instants); the session's own row is computed
    live: null, info: null,
  };
}

const put = (t, row) => { t.rows.set(row.id, row); return row; };

function close(row, ts, status, reason) {
  row.e = Math.max(row.s, ts);
  row.status = status;
  if (reason) row.meta.reason = reason;
}

function endTurn(t, ts, status, reason) {
  if (!t.turnRow) return;
  // A tool still open when its turn ends was cut off with it.
  for (const [id, row] of t.tools) { close(row, ts, status === "success" ? "canceled" : status, "its turn ended"); t.tools.delete(id); }
  close(t.turnRow, Math.max(ts, t.turnRow.e ?? ts), status, reason);
  t.turnOpen = false;
}

function openTurn(t, ts, text) {
  t.turn += 1;
  t.turnRow = put(t, { id: `${t.cli}:turn:${t.turn}`, label: text ? `סבב ${t.turn} · ${clamp(text, EXCERPT)}` : `סבב ${t.turn}`,
                       status: "running", s: ts, e: null, meta: { kind: "turn", turn: t.turn } });
  t.turnOpen = true;
  t.lastError = false;
}

function user(t, r, ts) {
  const c = r.message.content;
  if (Array.isArray(c) && c.some((x) => x && x.type === "tool_result")) {
    for (const x of c) {
      if (!x || x.type !== "tool_result") continue;
      const row = t.tools.get(x.tool_use_id);
      if (!row) continue;
      t.tools.delete(x.tool_use_id);
      close(row, ts, x.is_error ? "error" : "success");
    }
    return;
  }
  // The app's own injections (reminders, a compaction's summary) are not a prompt of anyone's.
  if (r.isMeta || r.isCompactSummary || r.isVisibleInTranscriptOnly) return;
  const text = promptText(c);
  // Esc on the screen: a marker, not a message — it ends the turn and starts none.
  if (/^\[Request interrupted/.test(text)) { if (t.turnOpen) endTurn(t, ts, "canceled", "interrupted"); return; }
  // A slash command, a `!` shell command and their local output are not a turn of Claude's.
  if (!text || /^<(command-name|command-message|command-args|local-command-std(out|err)|bash-input|bash-std(out|err))>/.test(text)) return;
  // What the harness itself hands Claude (a background task's notice: promptSource "system", its kind in
  // `origin`) is not the owner's prompt: it is named by its kind, never by its XML. A person's own words
  // (`origin.kind: "human"`) are a prompt, whatever they start with.
  const human = r.origin && r.origin.kind === "human";
  const kind = !human && (r.promptSource === "system" || /^<[a-z][a-z-]*>/.test(text))
    ? String((r.origin && r.origin.kind) || (/^<([a-z][a-z-]*)>/.exec(text) || [])[1] || "system") : "";
  const words = kind ? `התראה · ${kind}` : text;
  if (t.turnOpen) {
    // Into a running turn — a message queued while Claude works, a notice — it is part of that turn.
    const quiet = t.lastLine !== null && ts - t.lastLine > SILENCE_MS;
    if (!t.lastError && !quiet) {
      put(t, { id: `${t.cli}:queued:${r.uuid || ts}`, label: `בתוך הסבב · ${clamp(words, EXCERPT)}`, status: "success", s: ts, e: ts,
               meta: { kind: "message", turn: t.turn } });
      return;
    }
    // …unless that turn already died: an API error it never recovered from, or a long silence.
    endTurn(t, t.lastError ? ts : t.lastLine, "error", t.lastError ? "the API gave up" : "no end was written");
  }
  if (!t.prompt && !kind) t.prompt = clamp(text, EXCERPT);
  openTurn(t, ts, words);
}

function assistant(t, r, ts) {
  const m = r.message;
  if (r.isApiErrorMessage) {
    // Claude Code's own answer when the API gave up: the turn ends there, in error.
    put(t, { id: `${t.cli}:api:${r.uuid || ts}`, label: `שגיאת API · ${clamp(promptText(m.content), EXCERPT)}`,
             status: "error", s: ts, e: ts, meta: { kind: "api-error", turn: t.turn } });
    t.lastError = true;
    if (t.turnOpen) endTurn(t, ts, "error", "the API gave up");
    return;
  }
  if (m.model && m.model !== "<synthetic>") t.model = String(m.model);
  if (!t.turnRow) openTurn(t, ts, "");                   // a transcript that starts mid-session
  for (const c of m.content || []) {
    if (!c || c.type !== "tool_use" || !c.id || t.rows.has(`${t.cli}:tool:${c.id}`)) continue;
    const arg = argOf(c.input);
    t.tools.set(c.id, put(t, { id: `${t.cli}:tool:${c.id}`, label: `${c.name || "כלי"}${arg ? ` · ${arg}` : ""}`,
                               status: "running", s: ts, e: null, meta: { kind: "tool", tool: String(c.name || ""), turn: t.turn } }));
  }
  t.lastError = false;
  if (ENDS.has(m.stop_reason)) endTurn(t, ts, "success", "completed");
  else if (!t.turnOpen) {
    // The turn went on after an answer that ended it (a Stop hook sent Claude back to work).
    t.turnRow.e = null;
    t.turnRow.status = "running";
    delete t.turnRow.meta.reason;
    t.turnOpen = true;
  }
}

function system(t, r, ts) {
  if (r.subtype === "stop_hook_summary") {
    // The app's Claude Code closes every turn with its Stop hooks' summary.
    if (t.turnRow && (t.turnOpen || t.turnRow.status === "success")) endTurn(t, ts, "success", "completed");
    return;
  }
  if (r.subtype === "api_error") {
    // A retry, not the end: the turn dies only when Claude Code gives up (isApiErrorMessage, above).
    put(t, { id: `${t.cli}:api:${r.uuid || ts}`, label: `שגיאת API · ניסיון ${r.retryAttempt ?? "?"}/${r.maxRetries ?? "?"}`,
             status: "error", s: ts, e: ts, meta: { kind: "api-error", turn: t.turn } });
    return;
  }
  if (r.subtype === "compact_boundary") {
    put(t, { id: `${t.cli}:compact:${r.uuid || ts}`, label: "דחיסת הקשר", status: "success", s: ts, e: ts,
             meta: { kind: "compaction", turn: t.turn } });
  }
}

function ingest(t, r) {
  if (!r || typeof r !== "object") return;
  if (r.type === "custom-title" && r.customTitle) { t.title = clamp(r.customTitle); return; }
  if (r.isSidechain) return;
  const ts = Date.parse(r.timestamp);
  if (!Number.isFinite(ts)) return;
  if (t.first === null || ts < t.first) t.first = ts;
  t.lastLine = t.last;                          // the line before this one
  if (t.last === null || ts > t.last) t.last = ts;
  if (r.cwd && !t.cwd) t.cwd = String(r.cwd);
  if (r.type === "user" && r.message) user(t, r, ts);
  else if (r.type === "assistant" && r.message) assistant(t, r, ts);
  else if (r.type === "system") system(t, r, ts);
}

// What an open bracket is NOW, by its session's live file.
function openState(t, to, quietMs) {
  const L = t.live;
  if (to - t.mtime > STALE_MS && !(L && L.status === "waiting")) {
    return { status: "crashed", e: t.last, reason: "no line written for 12 hours" };
  }
  if ((t.mtime && to - t.mtime < quietMs) || (L && (!L.status || MID_TURN.has(L.status)))) {
    return { status: L && L.status === "waiting" ? "waiting" : "running", e: null };
  }
  if (L) return { status: "error", e: t.last, reason: "the session is idle and this never closed" };
  return { status: "crashed", e: t.last, reason: "the session is gone" };
}

function view(t, to, quietMs) {
  const sid = (t.info && t.info.id) || t.cli;
  const base = { svc: `סשן ${t.cli.slice(0, 8)}`, svcid: t.cli };
  const out = [];
  let open = null;
  for (const row of t.rows.values()) {
    if (row.e === null) {
      open = open || openState(t, to, quietMs);
      const meta = open.reason ? { ...row.meta, reason: open.reason } : row.meta;
      out.push({ ...row, ...base, status: open.status, e: open.e, derived: true, meta: { ...meta, session: sid, where: t.where } });
    } else {
      out.push({ ...row, ...base, meta: { ...row.meta, session: sid, where: t.where } });
    }
  }
  if (t.first !== null) {
    const title = (t.info && t.info.title) || t.title || t.prompt || "";
    const busy = t.turnOpen || t.tools.size > 0;
    const st = busy ? (open || openState(t, to, quietMs)) : { status: "success", e: t.last };
    out.push({
      id: t.cli, ...base, label: clamp(title || `סשן ${t.cli.slice(0, 8)}`), status: st.status, s: t.first, e: st.e, derived: busy,
      meta: { kind: "session", session: sid, where: t.where, claude_session: t.cli, title: clamp(title),
              turns: t.turn, cwd: t.cwd, model: t.model, ...(st.reason ? { reason: st.reason } : {}) },
    });
  }
  return out;
}

/**
 * The lane's store: `roots` are the homes that write transcripts —
 *   { where, home, live?: () => Map(sessionId → live file), names?: () => Map(sessionId → {id, title}) }.
 * `read({hours})` answers a window, `read({since})` a delta (the module's header says how).
 */
export function createSpanStore({ roots, now = () => Date.now(), chunk = CHUNK, quietMs = QUIET_MS, forgetMs = FORGET_MS,
                                  budget = BUDGET } = {}) {
  const tracks = new Map();   // transcript path → track
  const served = new Map();   // span id → {sig, w}: what was served last, and when it last changed
  const stats = { opened: 0, bytes: 0 };
  let wide = { ms: 0, until: 0 };   // the widest window asked for lately, kept parsed for WIDE_KEEP_MS
  let catching = false;              // the last read left transcript unparsed (BUDGET): its spans are news

  function transcripts(home) {
    const base = path.join(home, ".claude", "projects");
    const out = [];
    let dirs = [];
    try { dirs = fs.readdirSync(base, { withFileTypes: true }); } catch { return out; }
    for (const d of dirs) {
      if (!d.isDirectory()) continue;
      let files = [];
      try { files = fs.readdirSync(path.join(base, d.name)); } catch { continue; }
      for (const f of files) if (f.endsWith(".jsonl")) out.push(path.join(base, d.name, f));
    }
    return out;
  }

  function refresh(t, size, budget) {
    let fd;
    try {
      fd = fs.openSync(t.file, "r");
      stats.opened += 1;
      while (t.offset < size && budget.left > 0) {
        const buf = Buffer.alloc(Math.min(chunk, size - t.offset));
        const n = fs.readSync(fd, buf, 0, buf.length, t.offset);
        if (!n) break;
        t.offset += n;
        stats.bytes += n;
        budget.left -= n;
        // The decoder keeps a character a read cut in half for the next read (Hebrew is two bytes a letter).
        const lines = (t.rest + t.decoder.write(n < buf.length ? buf.subarray(0, n) : buf)).split("\n");
        t.rest = lines.pop();   // a line still being written waits for its newline
        for (const line of lines) {
          if (!line.trim()) continue;
          // A line this file cannot read, or a record of a shape it does not expect, costs that line only.
          try { ingest(t, JSON.parse(line)); } catch { /* the next line */ }
        }
      }
    } catch { /* gone or unreadable now: the next read goes on from where this one stopped */ }
    finally { if (fd !== undefined) try { fs.closeSync(fd); } catch { /* closed */ } }
  }

  function forget(file, t) {
    tracks.delete(file);
    served.delete(t.cli);
    for (const id of t.rows.keys()) served.delete(id);
  }

  function read({ hours, since, limit = 20000 } = {}) {
    const to = now();
    const delta = Number.isFinite(since) && since > 0;
    const h = Math.min(MAX_HOURS, Number.isFinite(hours) && hours > 0 ? hours : DEFAULT_HOURS);
    const from = delta ? since : to - h * 3600000;
    if (to - from > forgetMs) wide = { ms: to - from, until: to + WIDE_KEEP_MS };
    const keep = Math.max(forgetMs, to - from, wide.until > to ? wide.ms : 0);
    const seen = new Set();
    const left = { left: budget };
    let behind = false;
    for (const root of roots) {
      let live = new Map(), names = new Map();
      try { live = (root.live && root.live()) || live; } catch { /* no live files: every open bracket is judged by its age */ }
      try { names = (root.names && root.names()) || names; } catch { /* no names: the transcript's own */ }
      for (const file of transcripts(root.home)) {
        seen.add(file);
        let st;
        try { st = fs.statSync(file); } catch { continue; }
        const cli = path.basename(file, ".jsonl");
        let t = tracks.get(file);
        if (!t) {
          // Last written before the window, and its session not running: nothing in it reaches the window.
          // A delta still opens the last day's transcripts it has not met: a store that starts after the
          // timeline seeded (the adapter restarted) must find the brackets that died meanwhile.
          if (st.mtimeMs < Math.min(from, to - DEFAULT_HOURS * 3600000) && !live.has(cli)) continue;
          t = newTrack(root.where, file, cli);
          tracks.set(file, t);
        }
        if (st.size < t.offset) {           // rewritten from the start: read it again from the start
          forget(file, t);
          t = newTrack(root.where, file, cli);
          tracks.set(file, t);
        }
        t.live = live.get(cli) || null;
        t.info = names.get(cli) || null;
        if (st.size > t.offset && left.left > 0) refresh(t, st.size, left);
        if (st.size > t.offset) behind = true;
        t.mtime = st.mtimeMs;
      }
    }
    const out = [];
    for (const [file, t] of tracks) {
      if (!seen.has(file) || (!t.live && to - t.mtime > keep)) { forget(file, t); continue; }
      for (const { derived, ...row } of view(t, to, quietMs)) {
        // `w`: when this span last CHANGED, which is what a delta asks about besides its start and end.
        // A span first met here changed at its own last moment — so the first deltas after a seed do not
        // send the whole window again — unless its state is the session's state NOW (a bracket the
        // transcript left open), or this store is catching up on transcript an earlier read had no budget for
        // (a window read sends what it parses itself; a delta sends only what is news): a span the timeline
        // has never been sent must reach it now.
        const sig = `${row.status}|${row.e}|${row.label}`;
        const had = served.get(row.id);
        // News only inside the delta reader's own seed window: a 7-day view that ran out of budget, or a bracket of
        // a days-old transcript that turns out closed or crashed, must not reach the timeline's live 24 h feed.
        // …except the end of a span the feed was sent OPEN: that closing is news however old it is, or the feed
        // would hold it running for ever.
        const recent = row.e === null || row.e >= to - DEFAULT_HOURS * 3600000;
        const news = row.e === null || (had && had.open) || ((had || derived || catching || (behind && delta)) && recent);
        if (!had || had.sig !== sig) served.set(row.id, { sig, w: news ? to : row.e, open: row.e === null });
        const w = served.get(row.id).w;
        if (row.s > to) continue;
        const ends = row.e === null ? to : row.e;
        if (delta ? !(row.e === null || row.s > from || ends > from || w > from) : ends < from) continue;
        out.push({ ...row, w });
      }
    }
    catching = behind;
    out.sort((a, b) => (a.s - b.s) || String(a.id).localeCompare(String(b.id)));
    const cap = Number.isFinite(limit) && limit > 0 ? limit : 20000;
    const truncated = out.length > cap;
    // Cut from the oldest, but never a session's own row: it starts first, and it is what names the row.
    const spans = truncated ? [...out.filter((r) => r.meta.kind === "session"),
                               ...out.filter((r) => r.meta.kind !== "session").slice(-cap)] : out;
    return { spans, total: out.length, truncated, files: tracks.size, ...(behind ? { behind: true } : {}) };
  }

  return { read, stats };
}
