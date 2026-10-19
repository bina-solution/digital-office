/* rules-lib.js — the label engine's helper library, lifted into a shared file.
 *
 * The rule editor's preview ("of the last N messages these would match") must evaluate a rule with
 * EXACTLY the functions the engine evaluates it with, or the preview lies. So the two blocks marked
 * below are copied VERBATIM from apps/mail/blueprint/n8n/mailLabelEngine01.workflow.ts (the
 * `Lable Engine` Code node): PART 1 (the 20 helpers) and the data-object builders of PART 2.
 * scripts/refactor/rules-lib-parity-lint.py fails the build when the copies drift — edit the engine,
 * then mirror the change here (or the other way round), never one without the other.
 *
 * Everything OUTSIDE the two marked regions is this file's own: a strict evaluator that THROWS
 * instead of swallowing (the engine returns false on an exception, which is right for a batch job
 * and wrong for a preview whose whole point is to show the author what the rule does), and the
 * adapters that shape a mailview message into the object the builders expect.
 *
 * Plain script, no modules: it is loaded by index.html before app.js and exposes one global,
 * window.RulesLib.
 *
 * EDITING NOTE: the verbatim regions contain backslash-u escapes (U+0590..U+05FF, hasHebrew /
 * hasNonHebrewChars / HEBREW_REGEX). Some editors and agent tools
 * silently turn a `\uXXXX` escape into the literal character on save; the lint then fails on those
 * three lines. Keep the escapes as written in the engine (run the lint after every save). */
(function (global) {
  "use strict";

// @rules-lib:helpers:start — VERBATIM from mailLabelEngine01.workflow.ts (PART 1: UTILITY FUNCTIONS)
// ─── STRING UTILITIES ───────────────────────────────────────────────────────
const contains = (str, search) =>
  !!(str && search) && String(str).toLowerCase().includes(String(search).toLowerCase());

const containsAny = (str, searches) =>
  Array.isArray(searches) && searches.some(s => contains(str, s));

const containsAll = (str, searches) =>
  Array.isArray(searches) && searches.every(s => contains(str, s));

const startsWith = (str, prefix) =>
  !!(str && prefix) && String(str).toLowerCase().startsWith(String(prefix).toLowerCase());

const endsWith = (str, suffix) =>
  !!(str && suffix) && String(str).toLowerCase().endsWith(String(suffix).toLowerCase());

const matches = (str, regex) => {
  try {
    return new RegExp(regex, "i").test(str || "");
  } catch (e) {
    console.error("Invalid regex:", regex, e);
    return false;
  }
};

const isEmpty = (val) =>
  !val || (Array.isArray(val) && val.length === 0) || val === "";

const isNotEmpty = (val) => !isEmpty(val);

const hasHebrew = (str) => /[\u0590-\u05FF]/.test(str || "");

const hasNonHebrewChars = (str) => /[^\u0590-\u05FF0-9]/.test(str || "");

const noHebrew = (str) => !hasHebrew(str) && hasNonHebrewChars(str);

// ─── ARRAY UTILITIES ────────────────────────────────────────────────────────
const includes = (arr, item) =>
  Array.isArray(arr) && arr.includes(item);

const includesAny = (arr, items) =>
  Array.isArray(arr) && Array.isArray(items) && items.some(i => arr.includes(i));

const includesAll = (arr, items) =>
  Array.isArray(arr) && Array.isArray(items) && items.every(i => arr.includes(i));

const len = (arr) => (Array.isArray(arr) ? arr.length : 0);

// Note: filter, some, every are native JS and work directly

// ─── EMAIL UTILITIES ────────────────────────────────────────────────────────
const isDomain = (emailAddr, domain) => {
  if (!emailAddr || !domain) return false;
  const cleanDomain = String(domain).replace(/^@/, "").toLowerCase();
  return String(emailAddr).toLowerCase().endsWith(cleanDomain);
};

const isAnyDomain = (emailAddr, domains) =>
  Array.isArray(domains) && domains.some(d => isDomain(emailAddr, d));

const inList = (emailAddr, list) => {
  if (!emailAddr || !Array.isArray(list)) return false;
  const lower = String(emailAddr).toLowerCase();
  return list.some(item => {
    const itemStr = String(item);
    return itemStr.includes("@")
      ? lower === itemStr.toLowerCase()
      : isDomain(emailAddr, itemStr);
  });
};
// @rules-lib:helpers:end

// @rules-lib:builders:start — VERBATIM from mailLabelEngine01.workflow.ts (PART 2: DATA OBJECT BUILDERS)
// ─── ATTACHMENT ENRICHMENT (From v5) ───────────────────────────────────────
const HEBREW_REGEX = /[\u0590-\u05FF]/;
const UNITS = Object.freeze({
  b: 1, kb: 1024, mb: 1024 * 1024, gb: 1024 * 1024 * 1024, tb: 1024 * 1024 * 1024 * 1024
});

const EXT_TO_MIME = Object.freeze({
  ".pdf": "application/pdf", ".doc": "application/msword",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xls": "application/vnd.ms-excel",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
  ".svg": "image/svg+xml", ".zip": "application/zip",
  ".rar": "application/x-rar-compressed", ".7z": "application/x-7z-compressed",
  ".tar": "application/x-tar", ".gz": "application/gzip"
});

const TYPE_RULES = Object.freeze([
  ["logo", (name) => /logo|brand/i.test(name)],
  ["signature", (name) => /signature|\bsig\b/i.test(name)],
  ["pdf", (name, mime) => name.endsWith(".pdf") || mime === "application/pdf"],
  ["doc", (name, mime) => /\.docx?$/.test(name) || /word/i.test(mime)],
  ["excel", (name, mime) => /\.xlsx?$/.test(name) || /spreadsheet|excel/i.test(mime)],
  ["image", (name, mime) => /\.(png|jpe?g|gif|bmp|webp|svg|tiff?)$/i.test(name) || /^image\//i.test(mime)],
  ["archive", (name, mime) => /\.(zip|rar|7z|tar|gz)$/i.test(name) || /zip|archive/i.test(mime)]
]);

function parseFileSize(raw) {
  if (typeof raw === "number") return raw;
  if (!raw || typeof raw !== "string") return 0;
  const match = raw.trim().match(/^([\d.]+)\s*(b|kb|mb|gb|tb)?$/i);
  if (!match) return 0;
  const value = parseFloat(match[1]);
  const unit = (match[2] || "b").toLowerCase();
  return Math.round(value * (UNITS[unit] || 1));
}

function isLikelyInline(att) {
  const name = String(att.fileName || att.filename || "").toLowerCase();
  const mime = String(att.mimeType || "").toLowerCase();
  const size = parseFileSize(att.fileSize || att.size);

  let score = 0;
  if (/\b(logo|brand|company|corp)\b/.test(name)) score += 80;
  if (/\b(signature|signed|\bsig\b)\b/.test(name)) score += 80;
  if (/^(image\d+|cid_|ii_)/.test(name)) score += 75;
  if (mime.startsWith("image/")) score += 20;
  if (size > 0 && size < 20 * 1024) score += 15;
  if (size > 0 && size < 50 * 1024) score += 10;
  if (!mime.startsWith("image/")) score -= 50;
  if (size > 200 * 1024) score -= 30;
  if (size > 500 * 1024) score -= 40;

  return score >= 60;
}

function enrichAttachments(rawAttachments) {
  return (rawAttachments || []).map((att) => {
    const rawName = att.fileName || att.filename || "";
    const name = String(rawName).toLowerCase();
    const extMatch = name.match(/(\.[^.]+)$/);
    const ext = extMatch ? extMatch[1] : (att.fileExtension ? `.${att.fileExtension}` : "");
    const mime = String(att.mimeType || EXT_TO_MIME[ext] || "application/octet-stream").toLowerCase();
    const size = parseFileSize(att.fileSize || att.size);

    let type = "other";
    for (const [typeName, testFn] of TYPE_RULES) {
      if (testFn(name, mime)) {
        type = typeName;
        break;
      }
    }

    const inline = isLikelyInline(att);

    return { name, ext, mime, size, type, inline };
  });
}

// ─── BUILD EMAIL OBJECT ─────────────────────────────────────────────────────
function buildEmail(emailJson, labelIdToName) {
  const resolvedLabels = (emailJson.labelIds || [])
    .map(id => labelIdToName[id])
    .filter(Boolean);

  const subject = emailJson.subject || "";
  const body = emailJson.text || emailJson.textPlain || "";
  const html = emailJson.html || emailJson.textHtml || "";
  const text = emailJson.text || emailJson.textPlain || emailJson.textHtml || "";
  const fullText = [subject, text].filter(Boolean).join(" ");

  return {
    // Text content
    subject,
    body,
    html,
    text: fullText,
    full_text: fullText, // Alias for easier rule writing

    // Participants
    from: emailJson.from?.value?.[0]?.address || "",
    to: (emailJson.to?.value || []).map(t => t.address || ""),
    cc: (emailJson.cc?.value || []).map(t => t.address || ""),
    bcc: (emailJson.bcc?.value || []).map(t => t.address || ""),
    replyTo: emailJson.replyTo?.value?.[0]?.address || "",

    // Metadata
    date: emailJson.date ? new Date(emailJson.date) : new Date(),
    age: emailJson.date ? Math.floor((Date.now() - new Date(emailJson.date)) / (1000 * 60 * 60)) : 0,
    ageDays: emailJson.date ? Math.floor((Date.now() - new Date(emailJson.date)) / (1000 * 60 * 60 * 24)) : 0,
    size: emailJson.sizeEstimate || 0,

    // Labels
    labels: resolvedLabels,

    // IDs
    threadId: emailJson.threadId || "",
    messageId: emailJson.id || ""
  };
}

// ─── BUILD THREAD OBJECT ────────────────────────────────────────────────────
function buildThread(threadJson) {
  const messages = threadJson?.messages || [];
  const firstMsg = messages[0] || {};

  let threadFrom = "";
  if (typeof firstMsg.From === "string") {
    const match = firstMsg.From.match(/<([^>]+)>/);
    threadFrom = match ? match[1] : firstMsg.From.replace(/["'\s]/g, "");
  } else if (firstMsg.from) {
    threadFrom = firstMsg.from;
  } else if (firstMsg.FROM) {
    threadFrom = firstMsg.FROM;
  }

  const firstDate = firstMsg.date ? new Date(firstMsg.date) : new Date();

  // Build enriched messages array with full text access
  const enrichedMessages = messages.map((msg) => ({
    from: msg.from || msg.From || msg.FROM || "",
    subject: msg.subject || msg.Subject || msg.SUBJECT || "",
    body: msg.text || msg.textPlain || msg.body || "",
    html: msg.html || msg.textHtml || "",
    text: [
      msg.subject || msg.Subject || msg.SUBJECT,
      msg.text || msg.textPlain || msg.body,
      msg.html || msg.textHtml
    ].filter(Boolean).join(" "),
    date: msg.date ? new Date(msg.date) : new Date(),
    id: msg.id || msg.messageId || ""
  }));

  return {
    id: threadJson?.id || "",
    from: threadFrom,
    count: messages.length,
    age: Math.floor((Date.now() - firstDate) / (1000 * 60 * 60)),
    ageDays: Math.floor((Date.now() - firstDate) / (1000 * 60 * 60 * 24)),
    isFirst: messages.length === 1,
    participants: [...new Set(messages.map(m => m.from || m.From || m.FROM || "").filter(Boolean))],
    messages: enrichedMessages
  };
}
// @rules-lib:builders:end

  /* ── this file's own part ─────────────────────────────────────────────────────────────────────── */

  /* The helper names, in the ORDER the engine's evaluateRule() binds them (PART 3). Same names,
     same order, same positions — a rule that compiles here compiles there. */
  const HELPER_NAMES = [
    "contains", "containsAny", "containsAll", "startsWith", "endsWith",
    "matches", "isEmpty", "isNotEmpty", "hasHebrew", "hasNonHebrewChars", "noHebrew",
    "includes", "includesAny", "includesAll", "len",
    "isDomain", "isAnyDomain", "inList",
  ];
  const HELPER_FNS = [
    contains, containsAny, containsAll, startsWith, endsWith,
    matches, isEmpty, isNotEmpty, hasHebrew, hasNonHebrewChars, noHebrew,
    includes, includesAny, includesAll, len,
    isDomain, isAnyDomain, inList,
  ];

  /* Compile a rule string exactly as the engine does. Throws a SyntaxError for a rule that cannot
     parse — the editor calls this before a save so a broken rule is caught at the keyboard, not by
     the server's 400 (which still stands behind it). */
  function compileRule(ruleString) {
    return new Function("email", "thread", "attachments", ...HELPER_NAMES,
                        `"use strict"; return (${ruleString});`);
  }

  /* Evaluate — and THROW. The engine's evaluateRule() wraps this in try/catch and returns false,
     which is the correct behaviour for a scheduled batch (one bad rule must not stall the pass) and
     the wrong one for a preview, whose job is to show the author what the rule does — including
     "it throws on this message". The preview shows the exception per message instead. */
  function evaluateRuleStrict(ruleString, email, thread, attachments) {
    const fn = compileRule(ruleString);
    return !!fn(email, thread, attachments, ...HELPER_FNS);
  }

  /* "Name <addr>, Other <b@c>" -> ["addr", "b@c"]; a bare address stays itself. */
  function splitAddresses(s) {
    return String(s || "").split(",").map(p => {
      const m = p.match(/<([^>]+)>/);
      return (m ? m[1] : p).trim();
    }).filter(Boolean);
  }

  /* A mailview meta message (GET api/message/<id>: from/to/subject/date/labels/body_text/body_html/
     attachments[{filename,mimeType,size}]) shaped into what buildEmail() reads — the Gmail-API-like
     envelope the engine's `Start Mail Item` carries. `text` is the PLAIN body; when a message has
     no plain part, buildEmail falls through to `textHtml` exactly as it does in the engine. */
  function emailJsonFromMessage(m) {
    const val = s => splitAddresses(s).map(address => ({ address }));
    return {
      id: m.id || "", threadId: m.threadId || "",
      subject: m.subject || "",
      text: m.body_text || "", textHtml: m.body_html || "", html: m.body_html || "",
      from: { value: val(m.from) }, to: { value: val(m.to) }, cc: { value: val(m.cc) },
      date: m.date || "", sizeEstimate: m.size || 0,
      labelIds: (m.labels || []).slice(),
      attachmentsMeta: m.attachments || [],
    };
  }

  /* The engine resolves labelIds through a name map built from the mailbox's label ids; mailview
     already has NAMES on the message, so the map is the identity over them. */
  function identityLabelMap(labels) {
    const out = {};
    for (const l of labels || []) out[l] = l;
    return out;
  }

  /* mailapi's /thread payload IS what the engine hands buildThread (the `Get Mail Thread` node reads
     the same endpoint), so it passes through. A list-derived stand-in — summaries of the thread's
     rows from the message list, no bodies — has the same keys minus body text. */
  function threadJsonFromMessages(tid, msgs) {
    return { id: tid || "", messages: (msgs || []).map(x => ({
      id: x.id || "", from: x.from || "", subject: x.subject || "",
      text: x.body_text || "", html: x.body_html || "", date: x.date || "",
    })) };
  }

  /* Build the three objects a rule sees, from mailview's shapes. */
  function contextFor(message, threadJson) {
    const emailJson = emailJsonFromMessage(message);
    const attachments = enrichAttachments(emailJson.attachmentsMeta);
    const email = buildEmail(emailJson, identityLabelMap(emailJson.labelIds));
    const thread = buildThread(threadJson || threadJsonFromMessages(message.threadId || message.id, [message]));
    return { email, thread, attachments };
  }

  /* The legend the editor prints: every helper with a one-line Hebrew description, and the fields
     of email / thread / attachments — copied from buildEmail() / buildThread() / enrichAttachments()
     above so the legend can never name a field that does not exist. */
  const LEGEND = {
    helpers: [
      ["contains(str, search)", "האם המחרוזת מכילה את הטקסט (ללא הבחנה בין אותיות גדולות/קטנות)"],
      ["containsAny(str, [a, b])", "מכילה לפחות אחד מהטקסטים"],
      ["containsAll(str, [a, b])", "מכילה את כל הטקסטים"],
      ["startsWith(str, prefix)", "מתחילה ב־"],
      ["endsWith(str, suffix)", "מסתיימת ב־"],
      ["matches(str, regex)", "תואמת לביטוי רגולרי (ביטוי לא תקין = false)"],
      ["isEmpty(val)", "ריק / רשימה ריקה"],
      ["isNotEmpty(val)", "לא ריק"],
      ["hasHebrew(str)", "מכילה עברית"],
      ["hasNonHebrewChars(str)", "מכילה תווים שאינם עברית או ספרות"],
      ["noHebrew(str)", "ללא עברית כלל (ויש תווים אחרים)"],
      ["includes(arr, item)", "הרשימה מכילה את הפריט (התאמה מדויקת)"],
      ["includesAny(arr, [a, b])", "הרשימה מכילה לפחות אחד"],
      ["includesAll(arr, [a, b])", "הרשימה מכילה את כולם"],
      ["len(arr)", "אורך הרשימה"],
      ["isDomain(addr, domain)", "הכתובת שייכת לדומיין"],
      ["isAnyDomain(addr, [d1, d2])", "הכתובת שייכת לאחד הדומיינים"],
      ["inList(addr, [\"a@b.c\", \"dom.il\"])", "הכתובת ברשימה — כתובת מלאה (עם @) מושווית במדויק, אחרת לפי דומיין"],
    ],
    email: [
      ["email.subject", "נושא"], ["email.body", "גוף ההודעה (טקסט)"], ["email.html", "גוף ההודעה (HTML)"],
      ["email.text / email.full_text", "נושא + גוף, יחד"],
      ["email.from", "כתובת השולח"], ["email.to", "רשימת נמענים"], ["email.cc", "רשימת עותקים"],
      ["email.bcc", "עותקים נסתרים"], ["email.replyTo", "כתובת למענה"],
      ["email.date", "תאריך (Date)"], ["email.age", "גיל בשעות"], ["email.ageDays", "גיל בימים"],
      ["email.size", "גודל משוער"], ["email.labels", "רשימת התוויות הנוכחיות (כולל אלו שחוקים קודמים הוסיפו)"],
      ["email.threadId", "מזהה השיחה"], ["email.messageId", "מזהה ההודעה"],
    ],
    thread: [
      ["thread.id", "מזהה השיחה"], ["thread.from", "השולח של ההודעה הראשונה בשיחה"],
      ["thread.count", "מספר ההודעות בשיחה"], ["thread.age / thread.ageDays", "גיל השיחה בשעות / בימים"],
      ["thread.isFirst", "זו ההודעה הראשונה בשיחה"], ["thread.participants", "כל המשתתפים"],
      ["thread.messages[i].from / .subject / .body / .html / .text / .date / .id", "ההודעות בשיחה, מהישנה לחדשה"],
    ],
    attachments: [
      ["attachments.length", "מספר הקבצים המצורפים"],
      ["attachments[i].name", "שם הקובץ (אותיות קטנות)"], ["attachments[i].ext", "סיומת"],
      ["attachments[i].mime", "סוג MIME"], ["attachments[i].size", "גודל בבייטים"],
      ["attachments[i].type", "pdf · doc · excel · image · archive · logo · signature · other"],
      ["attachments[i].inline", "כנראה תמונה מוטבעת (לוגו / חתימה)"],
    ],
  };

  global.RulesLib = {
    helpers: { contains, containsAny, containsAll, startsWith, endsWith, matches, isEmpty, isNotEmpty,
               hasHebrew, hasNonHebrewChars, noHebrew, includes, includesAny, includesAll, len,
               isDomain, isAnyDomain, inList },
    HELPER_NAMES, HEBREW_REGEX,
    enrichAttachments, buildEmail, buildThread,
    compileRule, evaluateRuleStrict,
    emailJsonFromMessage, threadJsonFromMessages, identityLabelMap, contextFor, splitAddresses,
    LEGEND,
  };
})(typeof window !== "undefined" ? window : globalThis);
