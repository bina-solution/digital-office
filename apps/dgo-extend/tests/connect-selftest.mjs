#!/usr/bin/env node
/* connect-selftest — the pairing offer's FORMAT, executed.

   `apps/dgo-extend/static/connect.js` makes one promise to the rest of the pairing work: one offer
   format, one parser, three doors (QR, camera, pasted text). The promise is only worth what checks
   it, and the browser half cannot run in node — so this file loads the same script, takes the PURE
   half it exports on `module.exports`, and asserts the behaviour every screen depends on:

     · an offer survives encode → parse unchanged (the QR carries exactly what the other side read)
     · the grouped text form parses back — a person who typed it with different spacing is not an
       error, and a code that was truncated IS one, with a reason
     · the six-digit confirmation code is compared as DIGITS (123456 == "123 456"), and an empty
       code never matches: the confirm button's whole safety is this function
     · an expired offer is refused by the reader, not by the network

       node apps/dgo-extend/tests/connect-selftest.mjs

   Non-zero exit on the first broken promise. It is a contract test, not a browser test: it says
   nothing about pixels; the server's half and the two languages against each other are
   tests/pair_contract.py. */

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const require = createRequire(import.meta.url);
const C = require(join(ROOT, "apps/dgo-extend/static/connect.js"));

let fails = 0;
function ok(name, cond, detail) {
  if (cond) { console.log(`ok    ${name}`); return; }
  fails++;
  console.log(`FAIL  ${name}${detail ? `  — ${detail}` : ""}`);
}
function throws(name, fn, re) {
  try { fn(); ok(name, false, "it did not throw"); }
  catch (e) { ok(name, re.test(e.message), `message: ${e.message}`); }
}

/* The WIRE offer — the object apps/dgo-extend/pairing.py mints (`new_offer`). This file checks the
   page's own half; tests/pair_contract.py is the one that runs both languages against each other. */
const WIRE = {
  v: 1,
  offer_id: "7f3a91c2d4e5f60718293a4b5c6d7e8f",
  office: "hp-laptop",
  label: "הלפטופ",
  identity: { ed25519: "r1QoNoPc9DH0vFFq2GMHhASMM9oBJQQcMCxSMjxB6Pk=",
              wg: "OUBWvxLVZJDWW19J9sZPePVPi3i1rickvdqcXagbbns=", fingerprint: "3A4B-3343-4492-5A1A" },
  ephemeral: "MCowBQYDK2VuAyEAq1x1x1x1x1x1x1x1x1x1x1x1x1x1x1x1x1x1x1x1x1w=",
  endpoints: ["192.168.16.102:51830"],
  listen: { endpoint: "192.168.16.102", port: 51830 },
  used_slots: [1],
  created_at: Math.floor(Date.now() / 1000),
  expires_at: Math.floor(Date.now() / 1000) + 600,
};
const OFFER = {
  office_id: "hp-laptop", label: "הלפטופ", identity_pubkey: WIRE.identity.ed25519,
  fingerprint: "3A4B-3343-4492-5A1A", ephemeral_pubkey: WIRE.ephemeral,
  endpoints: ["192.168.16.102:51830"], rendezvous_id: WIRE.offer_id, expires_at: WIRE.expires_at,
  direction: "",
};
const view = (o) => { const { wire, ...rest } = o; return JSON.stringify(rest); };

/* ── one format, round trip ─────────────────────────────────────────────────── */
const text = C.encodeOffer(WIRE);
ok("the offer text carries the version prefix", text.startsWith("DGOPAIR1:"), text.slice(0, 12));
const back = C.parseOffer(text);
ok("the screen's view names what the wire carried",
  view(back) === JSON.stringify(OFFER), view(back));
ok("the untouched wire object rides along", JSON.stringify(back.wire) === JSON.stringify(WIRE));

const grouped = C.groupText(text);
ok("the display form is the same characters in six groups",
  C.stripSpace(grouped) === text && grouped.split(" ").length === C.OFFER_GROUPS,
  grouped.slice(0, 40));
ok("a code typed back with different spacing still parses",
  view(C.parseOffer(grouped.replace(/ /g, "\n  "))) === JSON.stringify(OFFER));

/* ── two codes, told apart by prefix before anything is parsed ──────────────── */
ok("an offer is an offer", C.kindOf(grouped) === "offer");
ok("a reply is a reply, whatever its spacing", C.kindOf("DGOPAIRR1: eyJ2 IjoxfQ") === "reply");
ok("anything else is neither", C.kindOf("hello") === "" && C.kindOf("") === "");
throws("a reply is never read as an offer", () => C.parseOffer("DGOPAIRR1:eyJ2IjoxfQ"), /קוד תשובה/);

/* ── refusals: each one names its own reason ────────────────────────────────── */
throws("an empty paste is refused", () => C.parseOffer("   "), /לא הודבק/);
throws("a code with no prefix is refused", () => C.parseOffer("hello world"), /לא קוד הצטרפות/);
{
  const html = C.hebrewWithTokens("אמור להתחיל ב־DGOPAIR1: ולא ב־<b> & HTTP 502");
  ok("a Latin token in a Hebrew sentence is ONE left-to-right word, colon included",
     html.includes('<span class="tok">DGOPAIR1:</span>'));
  ok("a status keeps its number inside the same token", html.includes('<span class="tok">HTTP 502</span>'));
  ok("markup in the sentence is escaped, and an entity is never cut by a token",
     html.includes("&lt;") && html.includes("&amp;") && !/&<span/.test(html));
}
{
  // a sentence the server worded: only what IT marked is a token, and the mark never survives
  const html = C.ticks("מוסיפים `networkingMode=mirrored` תחת `[wsl2]`, ואז `wsl --shutdown` <b>&");
  ok("a backticked run is one token, with its own punctuation inside it",
     html.includes('<span class="tok">networkingMode=mirrored</span>') &&
     html.includes('<span class="tok">[wsl2]</span>') && html.includes('<span class="tok">wsl --shutdown</span>'));
  ok("the marks are gone and the rest of the sentence is escaped", !html.includes("`") && html.includes("&lt;b&gt;&amp;"));
  ok("a sentence with nothing marked has no token", !C.ticks("כך הוגדר לה.").includes("<span"));
  // whichever way the server marks it: its own marks win (a command of several words is ONE token)
  ok("a marked sentence keeps a several-word command whole",
     C.sentence("הרץ `bbox dgo identity mint` על המכונה").includes('<span class="tok">bbox dgo identity mint</span>'));
  ok("an unmarked sentence is still read for Latin runs",
     C.sentence("אמור להתחיל ב־DGOPAIR1: כאן").includes('<span class="tok">DGOPAIR1:</span>'));
}
throws("a future format is refused BY NAME, not mis-parsed",
  () => C.parseOffer("DGOPAIR2:eyJhIjoxfQ"), /DGOPAIR2/);
throws("the page's first format is refused by name too",
  () => C.parseOffer("dgo1:eyJhIjoxfQ"), /dgo1/);
throws("a truncated code says it was truncated",
  () => C.parseOffer(text.slice(0, Math.floor(text.length * 0.8))), /חסר|אינו קריא/);
throws("a payload that is not an object is refused",
  () => C.parseOffer("DGOPAIR1:" + Buffer.from("[1,2,3]").toString("base64url")), /אינו הצעה/);
throws("a missing field is named",
  () => {
    const o = { ...WIRE }; delete o.offer_id;
    C.parseOffer(C.encodeOffer(o));
  }, /offer_id/);
throws("an offer with no identity is refused",
  () => C.parseOffer(C.encodeOffer({ ...WIRE, identity: { wg: "x" } })), /זהות/);
ok("an office that only dials publishes no address, and that is a legitimate offer",
  C.parseOffer(C.encodeOffer({ ...WIRE, endpoints: [], listen: undefined })).endpoints.length === 0);

/* ── expiry: the reader refuses it, the network is not asked ────────────────── */
ok("an offer inside its ten minutes is live", C.offerExpired(OFFER) === false);
ok("an offer past its expiry is expired",
  C.offerExpired({ ...OFFER, expires_at: Math.floor(Date.now() / 1000) - 1 }) === true);
ok("an offer with no expiry is not treated as expired",
  C.offerExpired({ ...OFFER, expires_at: 0 }) === false);

/* ── the six digits: the one function the confirm button rests on ───────────── */
ok("the same code in different renderings matches", C.codesMatch("123456", "123 456") === true);
ok("a different code does not match", C.codesMatch("123456", "654321") === false);
ok("an empty code never matches", C.codesMatch("", "") === false && C.codesMatch(null, undefined) === false);
ok("a partial code is not a match", C.codesMatch("12345", "123456") === false);
ok("non-digits are ignored when reading the code", C.digitsOf("12-34-56") === "123456");

/* ── what the screen shows before anyone agrees ─────────────────────────────── */
const d = C.describeOffer(OFFER);
ok("the summary names the office, its tunnel address and the rendezvous",
  d.office_id === "hp-laptop" && d.endpoints.length === 1 && d.rendezvous_id === WIRE.offer_id,
  JSON.stringify(d));
ok("the fingerprint shown is the office's own, as its identity states it",
  d.fingerprint === "3A4B-3343-4492-5A1A", d.fingerprint);
ok("an offer without one falls back to a short form of the key",
  /^[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(C.describeOffer({ ...OFFER, fingerprint: "" }).fingerprint));
ok("the countdown renders as m:ss", C.formatCountdown(600) === "10:00" && C.formatCountdown(-5) === "0:00");

/* ── the refusal that is a decision, and the screen that must offer it ──────── */
/* `pair_api._guard_replace` answers 409 with the platform's own sentence plus a protocol
   instruction ("כדי להחליף אותה שלחו replace: true"). BOTH confirm screens have to read that as
   a decision and offer the second, explicit press; the joining screen had no way forward at all
   until 2026-10-11, at the END of the flow, after both codes had been exchanged. */
const REFUSAL = { status: 409,
  message: "כבר קיימת כאן רשומה בשם hp-laptop — צימוד קודם. כדי להחליף אותה שלחו replace: true." };
const said = C.replaceRefusal(REFUSAL);
ok("a record-already-here refusal is recognised, whichever screen met it",
  said === "כבר קיימת כאן רשומה בשם hp-laptop — צימוד קודם.", JSON.stringify(said));
ok("the protocol instruction is never what a person reads", !/replace/.test(said), said);
ok("a 409 that names no replace is not that refusal",
  C.replaceRefusal({ status: 409, message: "אין slot פנוי (1–254) בשתי הלשכות" }) === "");
ok("another status is not that refusal",
  C.replaceRefusal({ status: 400, message: "כדי להחליף אותה שלחו replace: true." }) === "");
ok("a refusal with no body at all is not that refusal",
  C.replaceRefusal(new Error("Failed to fetch")) === "" && C.replaceRefusal(null) === "");

console.log(fails ? `\n${fails} broken promise(s).` : "\nall promises kept.");
process.exit(fails ? 1 : 0);
