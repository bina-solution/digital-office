// records.mjs — a transcript's record, read so that it can never be larger than the adapter (DGO-2188).
//
// Claude Code's transcript is one JSON object a line, and a line holds whatever the turn held: a file a tool wrote,
// a screenshot as base64, a page a tool read. Measured on the HP, 2026-11-24: the live session's transcript was
// 289 MB in 17,290 lines — the longest 26.6 MB, nine over 8 MB. The adapter parsed each whole and kept the
// arguments of every tool call among its last 3,000 events, in a container whose node heap is 259 MB (384m) —
// and died of «JavaScript heap out of memory» once a minute, 59 times in the hour after it started; at 1 GiB
// (heap 560 MB) it died just the same. A bigger heap moves the line; a record that is cut does not need one.
//
//   shrink(line)   the same JSON with every string longer than STRING_MAX cut to it (its end marked «…»). The
//                  record keeps its shape — its type, its ids, the head of each text — so everything read from it
//                  (a turn's start, a tool's call and its result) is still there. A line that is not long is
//                  returned as it is: nothing is copied.
//   bounded(v)     what an EVENT keeps of a value: every string cut to KEEP_MAX, like a tool's result already is.
//   textOf(s)      what an event keeps of a text.
export const STRING_MAX = 65536;      // a string inside a record, as it is parsed
export const KEEP_MAX = 8000;         // a string inside an event that is kept (a tool's result was always 8000)
export const TEXT_MAX = 64000;        // a message's text inside an event that is kept

const BACKSLASH = 92;

// Is the quote at `at` escaped? An odd run of backslashes before it.
function escaped(line, at, from) {
  let run = 0;
  for (let k = at - 1; k > from && line.charCodeAt(k) === BACKSLASH; k--) run++;
  return run % 2 === 1;
}

export function shrink(line, max = STRING_MAX) {
  if (line.length <= max * 2) return line;                 // no string in it can be worth cutting
  const parts = [];
  let i = 0;
  const n = line.length;
  while (i < n) {
    const open = line.indexOf('"', i);
    if (open < 0) { parts.push(line.slice(i)); break; }
    let close = open + 1;
    for (;;) {
      close = line.indexOf('"', close);
      if (close < 0 || !escaped(line, close, open)) break;
      close++;
    }
    if (close < 0) {                                       // a string that never ends: not a record — as it is,
      parts.push(line.slice(i)); break;                    // for JSON.parse to refuse (the caller skips it)
    }
    if (close - open - 1 <= max) parts.push(line.slice(i, close + 1));
    else {
      let cut = open + 1 + max;
      if (escaped(line, cut, open)) cut--;                 // never between a backslash and what it escapes
      const u = line.lastIndexOf("\\u", cut);              // …nor inside a \uXXXX
      if (u > open && cut - u < 6 && !escaped(line, u, open)) cut = u;
      parts.push(line.slice(i, cut), '…"');
    }
    i = close + 1;
  }
  return parts.join("");
}

export function textOf(s, max = TEXT_MAX) {
  return typeof s === "string" && s.length > max ? `${s.slice(0, max)}…` : s;
}

export function bounded(v, max = KEEP_MAX, depth = 0) {
  if (typeof v === "string") return v.length > max ? `${v.slice(0, max)}…` : v;
  if (!v || typeof v !== "object") return v;
  if (depth >= 8) return Array.isArray(v) ? [] : {};       // deeper than any tool's arguments: its shape, not its weight
  if (Array.isArray(v)) return v.slice(0, 200).map((x) => bounded(x, max, depth + 1));
  const out = {};
  for (const k of Object.keys(v).slice(0, 200)) out[k] = bounded(v[k], max, depth + 1);
  return out;
}
