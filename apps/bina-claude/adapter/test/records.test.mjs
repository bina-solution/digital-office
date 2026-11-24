// node --test apps/bina-claude/adapter/test/records.test.mjs — a transcript's record never outgrows the adapter (DGO-2188).
// Synthetic records in Claude Code's own shapes; no real session's content.
import { test } from "node:test";
import assert from "node:assert/strict";
import { shrink, bounded, textOf, STRING_MAX, KEEP_MAX, TEXT_MAX } from "../records.mjs";

const toolUse = (input) => ({ type: "assistant", uuid: "u-1", timestamp: "2026-11-24T10:00:00Z",
  message: { role: "assistant", content: [{ type: "text", text: "writing it" }, { type: "tool_use", id: "toolu_1", name: "Write", input }] } });

test("a record that is not long is returned as it is — the same string, nothing copied", () => {
  const line = JSON.stringify(toolUse({ file_path: "/a/b.txt", content: "x".repeat(1000) }));
  assert.equal(shrink(line), line);
});

test("a 30 MB record: its long string is cut, and everything else of it is still there", () => {
  const big = "א".repeat(15 << 20);                          // 15M Hebrew letters: a two-byte string, as the HP's are
  const line = JSON.stringify(toolUse({ file_path: "/a/b.txt", content: big, mode: "w" }));
  assert.ok(line.length > 15 << 20);
  const small = shrink(line);
  assert.ok(small.length < STRING_MAX * 2 + 2000, `still ${small.length} chars`);
  const r = JSON.parse(small);
  assert.equal(r.type, "assistant");
  assert.equal(r.uuid, "u-1");
  assert.deepEqual(r.message.content[0], { type: "text", text: "writing it" });
  const use = r.message.content[1];
  assert.equal(use.id, "toolu_1");
  assert.equal(use.name, "Write");
  assert.equal(use.input.file_path, "/a/b.txt");
  assert.equal(use.input.mode, "w");                         // what comes AFTER the long string is read too
  assert.equal(use.input.content.length, STRING_MAX + 1);
  assert.ok(use.input.content.startsWith("אאא") && use.input.content.endsWith("…"));
});

test("several long strings in one record, and a short one between them", () => {
  const r = JSON.parse(shrink(JSON.stringify({ a: "a".repeat(200000), k: "kept", b: "b".repeat(300000), n: 7 })));
  assert.equal(r.a.length, STRING_MAX + 1);
  assert.equal(r.b.length, STRING_MAX + 1);
  assert.equal(r.k, "kept");
  assert.equal(r.n, 7);
});

test("the cut never lands inside an escape: a quote, a backslash, a newline, a \\uXXXX at the cut all parse", () => {
  for (const unit of ['"', "\\", "\n", "\u0001", "é\"\\"]) {      // JSON writes these as \" \\ \n \u0001
    for (let pad = 0; pad < 8; pad++) {
      const s = "p".repeat(pad) + unit.repeat(STRING_MAX);        // the cut falls at every phase of the escape
      const line = JSON.stringify({ type: "user", s, after: "still here" });
      const r = JSON.parse(shrink(line));                          // throws if an escape was cut in half
      assert.equal(r.after, "still here");
      assert.ok(r.s.endsWith("…") && r.s.length <= STRING_MAX + 1, `unit ${JSON.stringify(unit)} pad ${pad}`);
      assert.ok(s.startsWith(r.s.slice(0, -1)), "what is kept is the string's own beginning");
    }
  }
});

test("a long string that holds escaped quotes is one string: nothing after it is mistaken for its end", () => {
  const s = ('he said \\"yes\\" and "no" ').repeat(20000);       // quotes and backslashes all through it
  const r = JSON.parse(shrink(JSON.stringify({ s, tail: [1, "two", { three: "3" }] })));
  assert.deepEqual(r.tail, [1, "two", { three: "3" }]);
  assert.ok(s.startsWith(r.s.slice(0, -1)));
});

test("a line that is not JSON stays not JSON (the reader skips it), and never throws here", () => {
  const broken = '{"type":"user","text":"' + "x".repeat(STRING_MAX * 3);      // a write cut mid-record
  assert.doesNotThrow(() => shrink(broken));
  assert.throws(() => JSON.parse(shrink(broken)));
});

test("a 30 MB record is read in well under a second's worth of work, and without a second copy of it", () => {
  const line = JSON.stringify(toolUse({ content: "0123456789".repeat(3 << 20) }));
  global.gc?.();
  const before = process.memoryUsage().heapUsed;
  const t0 = process.hrtime.bigint();
  const small = shrink(line);
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  const grew = process.memoryUsage().heapUsed - before;
  assert.ok(ms < 2000, `${ms.toFixed(0)} ms`);
  assert.ok(small.length < 200000);
  assert.ok(grew < 8 << 20, `the heap grew ${(grew / 1048576).toFixed(1)} MB for a 30 MB line`);
});

test("what an event keeps of a tool's arguments: every string cut to KEEP_MAX, the shape kept", () => {
  const b = bounded({ file_path: "/a", content: "c".repeat(50000), edits: [{ old: "o".repeat(9000), n: 1 }], flag: true, none: null });
  assert.equal(b.file_path, "/a");
  assert.equal(b.content.length, KEEP_MAX + 1);
  assert.equal(b.edits[0].old.length, KEEP_MAX + 1);
  assert.equal(b.edits[0].n, 1);
  assert.equal(b.flag, true);
  assert.equal(b.none, null);
  assert.equal(bounded("short"), "short");
  assert.equal(bounded(undefined), undefined);
  // a thousand arguments, or a nest with no end, is bounded too
  assert.equal(Object.keys(bounded(Object.fromEntries(Array.from({ length: 1000 }, (_, i) => [`k${i}`, i])))).length, 200);
  let deep = "leaf"; for (let i = 0; i < 50; i++) deep = { deep };
  assert.doesNotThrow(() => JSON.stringify(bounded(deep)));
});

test("what an event keeps of a text", () => {
  assert.equal(textOf("short"), "short");
  assert.equal(textOf("t".repeat(TEXT_MAX + 5)).length, TEXT_MAX + 1);
  assert.equal(textOf(undefined), undefined);
});
