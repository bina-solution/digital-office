#!/usr/bin/env node
/* pair-screens — TWO OFFICES PAIRING THROUGH THEIR OWN SCREENS, IN A REAL BROWSER, ON VIDEO.

   `tests/fresh-offices.sh` walks the pairing API of two brand-new offices; this walks what a PERSON
   walks: the /connect page of each office, the same buttons the owner presses — הצגת קוד / הדבקת קוד /
   פענוח הקוד / אישור — with the codes carried between the two screens by hand, exactly as two people
   carry them. It exists because the API being right is not the same as the screen being usable: on
   2026-10-11 the owner exchanged both codes, pressed אישור, and the joining screen answered a 409 with
   nothing to press and no way on. Every such dead end is invisible to an API test.

   Runs INSIDE the Playwright image (tests/pair-video.sh starts the containers and calls it):

     node pair-screens.mjs --a http://office-a:8983 --b http://office-b:8983 --out /out

   What it proves, in one run, on two throwaway offices:
     · round 1 — a fresh pair: A offers, B reads it and answers, A reads the answer, the SAME six
       digits stand on both screens, each office confirms on its own screen, both say "the pairing was
       written";
     · round 2 — THE RETRY after a link died (the owner's own case, 2026-10-11): A offers again, B
       (which already holds a record for A) is refused and MUST offer the replace press, A is refused
       too, and both finish. A screen that cannot answer that refusal fails this run by name.

   Evidence, never a claim: every step is screenshotted into <out>/steps/, the two screens are RECORDED
   as video (<out>/a.webm, <out>/b.webm — the wrapper muxes them side by side), and a JS error anywhere
   on either page fails the run (a flow that only works because the page swallowed an exception is a
   flow that does not work).
*/
import { chromium } from "playwright-core";
import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const argv = process.argv.slice(2);
const arg = (name, dflt = "") => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};
const A = arg("a").replace(/\/$/, "");          // the joining office: shows the offer
const B = arg("b").replace(/\/$/, "");          // the hosting office: reads it, shows the reply
const OUT = arg("out", "/out");
const STEPS = join(OUT, "steps");
const VIEW = { width: 1360, height: 940 };

mkdirSync(STEPS, { recursive: true });
const log = [];
const fails = [];
const say = (m) => { console.log(m); log.push(m); };

/** One screen: its own context (its own video), its own page, and its own console errors. */
async function screen(browser, base, who) {
  const ctx = await browser.newContext({ viewport: VIEW, recordVideo: { dir: OUT, size: VIEW },
                                         locale: "he-IL" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`${who}: ${e.message}`));
  // A 409 on a pairing route IS the flow working: round 2 is refused by design and answered with the
  // replace press. Anything else in the console — and every uncaught exception — is a defect.
  page.on("console", (m) => {
    if (m.type() === "error" && !/\b409\b/.test(m.text())) errors.push(`${who} console: ${m.text()}`);
  });
  await page.goto(`${base}/connect`, { waitUntil: "domcontentloaded" });
  // the office's own line (its id and fingerprint) is what the other operator compares aloud
  await page.waitForFunction(() => (document.getElementById("selfLine")?.textContent || "").trim().length > 3,
                             null, { timeout: 20000 });
  return { ctx, page, errors, who };
}

const idOf = (page) => page.evaluate(() => (document.getElementById("selfLine")?.textContent || "").trim());

/** Switch doors the way a person does: the tab on the page, by its own label. */
async function door(page, label) {
  await page.evaluate((text) => {
    const all = [...document.querySelectorAll("#ways *")];
    const leaf = all.find((e) => e.children.length === 0 && e.textContent.trim() === text);
    const any = all.find((e) => e.textContent.includes(text));
    const el = leaf || any;
    (el?.closest("button,[role=tab],a,li") || el)?.click();
  }, label);
  await page.waitForTimeout(250);
}
const text = (page, sel) => page.evaluate((s) => (document.querySelector(s)?.textContent || "").trim(), sel);
const codes = (s) => String(s || "").replace(/\D/g, "");
const squeeze = (s) => String(s || "").replace(/\s+/g, "");

async function shot(page, name) {
  await page.screenshot({ path: join(STEPS, `${name}.png`) });
  // A beat after every marked step: this run is also the FILM the owner watches, and a flow that
  // flashes past at API speed is a flow nobody can follow. Half a second, not a performance.
  await page.waitForTimeout(650);
}

/** Wait for an ANSWER from the office: the six digits, or the sentence it refused with.
 *  A refusal that is not the replace press is reported here, by text — the alternative is a timeout
 *  that says nothing and sends the reader to the video to find out what the office said. */
async function answer(page, who, round, what) {
  await page.waitForSelector("#sasCode, #alerts .callout", { timeout: 25000 }).catch(() => {});
  if (await page.locator("#sasCode").count()) return true;
  const said = (await text(page, "#alerts")).replace(/\s+/g, " ").slice(0, 220);
  fails.push(`round ${round}: ${who} did not answer while ${what} — the office said: ${said || "(nothing)"}`);
  await shot(page, `r${round}-ERROR-${who.split("(")[1]?.replace(")", "") || "office"}`);
  return false;
}

/** Press the "replace the existing record" press when the office refuses with that refusal.
 *  Only an ENABLED button: the press disables itself while the second attempt runs, and a disabled
 *  copy is the SAME decision already taken. */
async function replaceIfAsked(page, who, step) {
  const btn = page.locator("#btnReplace:not([disabled])");
  if (await btn.count()) {
    say(`  ${step}: ${who} is offered the replace press (a record under that name is already here) — pressing it`);
    await shot(page, step);
    await btn.first().click();
    return true;
  }
  return false;
}

async function confirm(page, who, step) {
  for (let i = 0; i < 2; i++) {
    // a confirm that is already gone is a round that is already written — not a failure
    await page.locator("#btnConfirm").first().click({ timeout: 4000 }).catch(() => {});
    await page.waitForTimeout(900);
    if (!(await replaceIfAsked(page, who, `${step}-replace${i ? "-2" : ""}`))) break;
    await page.waitForTimeout(1200);
  }
}

async function pairing(browser, round) {
  const a = await screen(browser, A, "A(joiner)");
  const b = await screen(browser, B, "B(host)");
  say(`round ${round}: A=${await idOf(a.page)}`); 
  say(`round ${round}: B=${await idOf(b.page)}`);

  // 1. the joining office shows an offer (public material: its keys, its address, ten minutes)
  await a.page.locator("#btnOffer").click();
  await a.page.waitForSelector("#offerText", { state: "visible", timeout: 20000 });
  const offer = squeeze(await text(a.page, "#offerText"));
  await shot(a.page, `r${round}-01-joiner-offer`);
  say(`round ${round}: the offer is on screen (${offer.length} chars, QR drawn)`);

  // 2. the hosting office reads it — the pasted-text door of the same one flow
  await door(b.page, "הדבקת קוד");
  await b.page.fill("#pasteText", offer);
  await shot(b.page, `r${round}-02-host-pasted-offer`);
  await b.page.locator("#btnParse").click();
  // the office answers with the OFFER's summary and its own press — or refuses, in words or with the
  // replace press. Two rounds exercise both: round 1 goes straight on, round 2 meets the record.
  await b.page.waitForSelector("#btnClaim, #btnReplace, #alerts .callout", { timeout: 25000 }).catch(() => {});
  await replaceIfAsked(b.page, "B(host)", `r${round}-03-host-refused-replace`);
  await b.page.waitForTimeout(900);
  await replaceIfAsked(b.page, "B(host)", `r${round}-03b-host-refused-replace`);
  if (await b.page.locator("#btnClaim").count()) {
    // …the host MINTS the answer: the reply and the six digits exist only after this press, and on a
    // retry the same press is REFUSED first (409) and answered with the replace press
    await b.page.locator("#btnClaim").click();
    await b.page.waitForSelector("#sasCode, #btnReplace, #alerts .callout", { timeout: 25000 }).catch(() => {});
    await replaceIfAsked(b.page, "B(host)", `r${round}-03c-host-refused-replace`);
  }
  await answer(b.page, "B(host)", round, "the reply being on screen");
  const reply = squeeze(await text(b.page, "#replyText"));
  const codeB = codes(await text(b.page, "#sasCode"));
  await shot(b.page, `r${round}-04-host-reply-and-code`);
  say(`round ${round}: the host shows a reply (${reply.length} chars) and the code ${codeB}`);

  // 3. the joining office reads the answer: the SAME six digits must stand on both screens
  await door(a.page, "הדבקת קוד");
  await a.page.fill("#pasteText", reply);
  await shot(a.page, `r${round}-05-joiner-pasted-reply`);
  await a.page.locator("#btnParse").click();
  await answer(a.page, "A(joiner)", round, "reading the reply");
  const codeA = codes(await text(a.page, "#sasCode"));
  await shot(a.page, `r${round}-06-joiner-code`);
  if (!codeA || codeA !== codeB) fails.push(`round ${round}: the six digits differ (joiner ${codeA} vs host ${codeB})`);
  say(`round ${round}: the joiner shows ${codeA} — ${codeA === codeB ? "identical" : "DIFFERENT"}`);

  // 4. each office confirms ON ITS OWN SCREEN — this is where the owner's dead end was
  await confirm(a.page, "A(joiner)", `r${round}-07-joiner-confirm`);
  await confirm(b.page, "B(host)", `r${round}-08-host-confirm`);

  // 5. both screens say the pairing was written
  for (const [who, s] of [["A(joiner)", a], ["B(host)", b]]) {
    await s.page.waitForFunction(() => (document.getElementById("doneOut")?.textContent || "").includes("נכתב"),
                                 null, { timeout: 20000 }).catch(() => {});
    const done = (await text(s.page, "#doneOut")).slice(0, 200);
    if (!done.includes("נכתב")) fails.push(`round ${round}: ${who} never said the pairing was written`);
    else say(`round ${round}: ${who} — ${done.split("\n")[0]}`);
    await shot(s.page, `r${round}-09-${who.startsWith("A") ? "joiner" : "host"}-done`);
  }

  for (const s of [a, b]) {
    for (const e of s.errors) fails.push(e);
    await s.ctx.close();                       // closing the context is what writes the video
  }
  // deterministic video names: the wrapper muxes a-r1+a-r2 beside b-r1+b-r2 into one film
  for (const [side, s] of [["a", a], ["b", b]]) {
    const v = s.page.video();
    if (!v) continue;
    const p = await v.path().catch(() => null);
    if (p) { try { renameSync(p, join(OUT, `${side}-r${round}.webm`)); } catch { /* already named */ } }
  }
  return { a, b };
}

const browser = await chromium.launch({ args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  const one = await pairing(browser, 1);
  say("round 1 done — the two offices are paired.");
  await new Promise((r) => setTimeout(r, 1200));
  // THE RETRY: the same two offices again, which is the case the owner met (a link died; pair again).
  await pairing(browser, 2);
  say("round 2 done — the retry after a dead link finished from both screens.");
} finally {
  await browser.close();
}

const ok = fails.length === 0;
writeFileSync(join(OUT, "pair-screens.json"),
              JSON.stringify({ ok, a: A, b: B, steps: log, failures: fails }, null, 2));
console.log("");
console.log(ok ? "pair-screens: PASS — two offices paired through their own screens, twice (fresh + retry)"
               : `pair-screens: ${fails.length} FAILED\n` + fails.map((f) => `  - ${f}`).join("\n"));
process.exit(ok ? 0 : 1);
