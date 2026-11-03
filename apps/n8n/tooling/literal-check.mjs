// literal-check.mjs — a template literal in a .workflow.ts must be ONE well-formed literal.
//
// The transformer reads a blueprint with ts-morph, whose parser is error-TOLERANT, and never asks
// it for diagnostics (@n8n-as-code/transformer 2.0.0, dist/compiler/typescript-parser.js:41
// `addSourceFileAtPath`, :392 `getLiteralValue()` of the literal AS THE PARSER CUT IT). So a raw
// backtick inside a Code node's jsCode — a comment quoting `a name`, a Markdown fragment — ENDS the
// literal there; the rest of the code is error-recovered away, the converter exits 0, and n8n is
// handed a shorter body that does not compile. DGO-584: 1191 of 2161 chars stored, `code validate`
// said "valid", push said "ok update+activate" — twice in one day, to two agents.
//
// This scanner reads the file the way the TS lexer does — comments, strings, regexes, template
// literals with their ${…} substitutions — and when a template literal that is a property's VALUE
// closes, asks what follows: a parameter ends in `,` `}` or `)`, and after a `,` comes the next
// key or the close. Anything else means the backtick that closed it was meant as code, and THAT
// backtick's line:col is the finding. One finding per file (the first; after it the lexer is
// reading the node's own code as TypeScript and every later position would be noise).
//
// Dependency-free. Run by wrap.mjs (compile, validate, verify) and by `node --test
// apps/n8n/tooling/test/literal-check.test.mjs`; also by hand:
//
//   node apps/n8n/tooling/literal-check.mjs <file.workflow.ts|dir> ...      exit 1 = a finding

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const ID_PART = /[\w$]/;
const SPACE = /\s/;
// After one of these a `/` starts a regular expression, not a division.
const REGEX_AFTER = new Set(["(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%", "<", ">", "~", "^", "\n"]);

function skipSpaceAndComments(text, i) {
  for (;;) {
    while (i < text.length && SPACE.test(text[i])) i++;
    if (text.startsWith("//", i)) { const e = text.indexOf("\n", i); i = e < 0 ? text.length : e; continue; }
    if (text.startsWith("/*", i)) { const e = text.indexOf("*/", i + 2); i = e < 0 ? text.length : e + 2; continue; }
    return i;
  }
}

function skipString(text, i) {            // text[i] is the opening ' or "; returns the index after the closing one
  const q = text[i++];
  while (i < text.length && text[i] !== q && text[i] !== "\n") i += text[i] === "\\" ? 2 : 1;
  return i + 1;
}

function skipRegex(text, i) {             // text[i] is the opening /
  let inClass = false;
  for (i++; i < text.length && text[i] !== "\n"; i++) {
    const c = text[i];
    if (c === "\\") { i++; continue; }
    if (inClass) { if (c === "]") inClass = false; continue; }
    if (c === "[") inClass = true;
    else if (c === "/") { i++; while (i < text.length && ID_PART.test(text[i])) i++; return i; }
  }
  return i;
}

// The key whose value starts at `i` (`key:` or `'key':` before it, over whitespace) — null when the
// text at `i` is not a property value.
function keyBefore(text, i) {
  let j = i - 1;
  while (j >= 0 && SPACE.test(text[j])) j--;
  if (text[j] !== ":") return null;
  for (j--; j >= 0 && SPACE.test(text[j]); j--);
  if (text[j] === "'" || text[j] === '"') {
    let k = j - 1;
    while (k >= 0 && text[k] !== text[j]) k--;
    return text.slice(k + 1, j);
  }
  let k = j;
  while (k >= 0 && ID_PART.test(text[k])) k--;
  return k < j ? text.slice(k + 1, j + 1) : null;
}

// Does a property start at `i`? (`key:`, `'key':`, a computed `[` or a spread `...`.)
function propertyAt(text, i) {
  if (text.startsWith("...", i) || text[i] === "[") return true;
  let j = i;
  if (text[i] === "'" || text[i] === '"') j = skipString(text, i);
  else while (j < text.length && ID_PART.test(text[j])) j++;
  if (j === i) return false;
  while (j < text.length && SPACE.test(text[j])) j++;
  return text[j] === ":";
}

function lineCol(text, offset) {
  let line = 1, last = -1;
  for (let i = text.indexOf("\n"); i >= 0 && i < offset; i = text.indexOf("\n", i + 1)) { line++; last = i; }
  return { line, col: offset - last };
}

/**
 * Scan one .workflow.ts text. Returns [] when every property-value template literal is well
 * formed, else ONE finding: {file, line, col, offset, key, node, chars, follows, message} — the
 * position of the backtick that ended the literal early.
 */
export function checkCodeLiterals(text, file = "<text>") {
  const findings = [];
  let nodeName = null;        // the last `name: '…'` read in code — the node the literal belongs to
  let lastValue = null;       // the last property-value literal that closed in order: {open, close, key, node}

  const at = (offset) => { const { line, col } = lineCol(text, offset); return `${file}:${line}:${col}`; };
  const whose = (key, node) => `the \`${key}\` literal${node ? ` of node '${node}'` : ""}`;
  const advice = "Escape every backtick inside the code as \\` (and ${ as \\${)";

  function finding(open, close, key, follows) {
    const { line, col } = lineCol(text, close);
    const chars = close - open - 1;
    findings.push({ file, line, col, offset: close, key, node: nodeName, chars, follows,
      message: `${at(close)}: ${whose(key, nodeName)} ends here, at a raw backtick, ${chars} chars in — what follows is not ` +
        `the end of a parameter: ${JSON.stringify(follows)}. ${advice}, or put each parameter on its own line (a literal must be ` +
        "followed by a newline, `}` or `)`); as written, n8n would be handed only those " + chars + " chars." });
  }

  // A property-value literal that closed at `close`: what comes next must end the parameter — a
  // `,` and then, ON A NEW LINE, the next key or the close; a `}` and then the delimiter every
  // object literal is followed by; or a `)`. A PAIR of raw backticks is lexically consistent (the
  // second reopens a literal that ends at the real closing backtick) and `` `, x: ` `` is even
  // valid TypeScript — so what follows is the tell: rendered files put each parameter on its own
  // line, and after `` `}` `` what follows the `}` is a backtick, never a delimiter.
  function judgeClose(open, close, key) {
    const j = skipSpaceAndComments(text, close + 1);
    const c = text[j];
    let ok = j >= text.length || c === "," || c === "}" || c === ")";
    if (ok && (c === "," || c === "}")) {
      const k = skipSpaceAndComments(text, j + 1);
      ok = k >= text.length || (c === ","
        ? text[k] === "}" || text[k] === ")" || (propertyAt(text, k) && text.slice(j, k).includes("\n"))
        : ",;)}]".includes(text[k]));
    }
    if (ok) lastValue = { open, close, key, node: nodeName };
    else finding(open, close, key, text.slice(close + 1, close + 41).replace(/\s+/g, " ").trim());
  }

  // text[open] is a backtick. Returns the index after the closing backtick (text.length if none).
  function scanTemplate(open) {
    const key = keyBefore(text, open);
    for (let i = open + 1; i < text.length; i++) {
      const c = text[i];
      if (c === "\\") { i++; continue; }
      if (c === "$" && text[i + 1] === "{") { i = scanCode(i + 2, true); continue; }   // lands on the closing }
      if (c === "`") {
        if (key !== null) judgeClose(open, i, key);
        return i + 1;
      }
    }
    // Never closed: the file holds an odd number of backticks. A raw one closed some literal early
    // where what followed happened to look like the end of a parameter (`}` or `)` — the shape the
    // converter accepts with exit 0 and an EMPTY parameters object), so the literal's real closing
    // backtick opened this one. The last parameter literal to close in order is the suspect.
    const { line, col } = lineCol(text, open);
    const v = lastValue;
    findings.push({ file, line, col, offset: open, key, node: v ? v.node : nodeName, chars: v ? v.close - v.open - 1 : 0, follows: "",
      message: `${at(open)}: a template literal opened here never closes — an odd backtick. ` +
        (v ? `${whose(v.key, v.node)} that ended at ${at(v.close)}, ${v.close - v.open - 1} chars in, is the likely culprit: a raw backtick ` +
          `inside it, followed by text that passed for the end of a parameter. ` : "") + `${advice}.` });
    return text.length;
  }

  // Code, from `i`. In a ${…} substitution it returns the index of the `}` that closes it;
  // otherwise it runs to the end. Stops at the first finding.
  function scanCode(i, inSubstitution) {
    let depth = 0, last = inSubstitution ? "{" : "\n";
    while (i < text.length && !findings.length) {
      const c = text[i];
      if (SPACE.test(c)) { if (c === "\n") last = c; i++; continue; }
      if (c === "/" && (text[i + 1] === "/" || text[i + 1] === "*")) { i = skipSpaceAndComments(text, i); continue; }
      if (c === "'" || c === '"') {
        const start = i;
        i = skipString(text, i);
        if (keyBefore(text, start) === "name") nodeName = text.slice(start + 1, i - 1);
        last = c; continue;
      }
      if (c === "`") { i = scanTemplate(i); last = c; continue; }
      if (c === "/" && REGEX_AFTER.has(last)) { i = skipRegex(text, i); last = c; continue; }
      if (inSubstitution) {
        if (c === "{") depth++;
        else if (c === "}") { if (depth === 0) return i; depth--; }
      }
      last = c; i++;
    }
    return text.length;
  }

  scanCode(0, false);
  return findings;
}

const listTs = (p) => fs.statSync(p).isDirectory()
  ? fs.readdirSync(p).filter((f) => f.endsWith(".workflow.ts")).sort().map((f) => path.join(p, f))
  : [p];

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const files = process.argv.slice(2).flatMap(listTs);
  if (!files.length) { console.error("usage: literal-check.mjs <file.workflow.ts|dir> ..."); process.exit(2); }
  const bad = files.flatMap((f) => checkCodeLiterals(fs.readFileSync(f, "utf8"), f));
  for (const b of bad) console.log(b.message);
  if (!bad.length) console.log(`literal-check: ${files.length} file(s), every template literal is one well-formed literal`);
  process.exit(bad.length ? 1 : 0);
}
