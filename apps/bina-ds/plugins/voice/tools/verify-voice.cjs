/**
 * verify-voice.cjs — the end-to-end check for this plugin, in a real browser.
 *
 * The microphone is A FILE: chromium is launched with `--use-file-for-fake-audio-capture`, so the page
 * records real Hebrew audio through the same getUserMedia → MediaRecorder → /api/voice/segment path a
 * person uses. Nothing in the app is stubbed. What counts as proof: the mic button exists in the
 * composer, a live session is created, at least one segment is uploaded, the panel shows text the
 * model actually produced, and "שלח לבינה" lands it in the conversation.
 *
 * How to run it (the office's own box, from the checkout):
 *
 *   docker run -d --name voice-verify --network traefik-network mcr.microsoft.com/playwright:v1.49.1-noble sleep 900
 *   docker exec voice-verify sh -c 'cd /tmp && npm i playwright-core@1.49.1'
 *   docker cp this-file voice-verify:/verify-voice.cjs
 *   docker cp note16k.wav voice-verify:/tmp/note16k.wav        # 16 kHz mono PCM WAV, the "microphone"
 *   TOKEN=$(./scripts/dc logs bina-ds | grep -o "dsh web: http://127.0.0.1:3080/?token=[A-Za-z0-9_-]*" | tail -1 | sed 's/.*token=//')
 *   docker exec -e BASE_URL=http://bina.localhost:3080 -e TOKEN=$TOKEN \
 *     -e HOST_MAP="bina.localhost $(getent hosts bina-ds | awk '{print $1}')" \
 *     voice-verify node /verify-voice.cjs
 *
 * The token is the harness's LAUNCH token (printed at boot), not the agent API token; the harness
 * refuses any Host it was not told about, hence HOST_MAP + `--host-resolver-rules`.
 */
const { chromium } = require("/tmp/node_modules/playwright-core");

const BASE = process.env.BASE_URL || "http://bina.localhost:3080";
const WAS = process.env.WAIT_AFTER_STOP_MS || "90000";
// MOBILE=1 reproduces the office owner's own screen: a phone viewport in the dark theme, which is
// where the first (overlay) design fell apart — the panel painted white-on-white over the chat.
const MOBILE = process.env.MOBILE !== "0";           // phone by default: that is where it is used
const SHORT_MS = Number(process.env.SHORT_MS || 8000);   // the gesture that was broken: stop early
const MODE = process.env.MODE || "short";              // short | long | both
const ORIGIN = process.env.ORIGIN || "app";            // app (bina.localhost) | console (the iframe)

function log(...args) {
  console.log("[verify]", ...args);
}

(async () => {
  const results = { steps: [], texts: {}, errors: [] };
  const map = process.env.HOST_MAP;           // "bina.localhost 172.18.0.41" — the harness only answers trusted Hosts
  const browser = await chromium.launch({
    args: [
      "--no-sandbox",
      ...(map ? [`--host-resolver-rules=MAP ${map.split(" ")[0]} ${map.split(" ")[1]}`] : []),
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      "--use-file-for-fake-audio-capture=/tmp/note16k.wav",
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  const context = await browser.newContext({
    permissions: ["microphone"],
    extraHTTPHeaders: ORIGIN === "console" ? { "x-authentik-username": "owner" } : {},
    locale: "he-IL",
    colorScheme: process.env.SCHEME || "dark",
    ...(MOBILE
      ? { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }
      : {}),
  });
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") results.errors.push(m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => results.errors.push(String(e).slice(0, 300)));

  const url = process.env.TOKEN ? `${BASE}/?token=${process.env.TOKEN}` : BASE;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(6000);
  results.steps.push({ step: "page", title: await page.title(), url: page.url() });

  // the developer-preview notice covers the page on a fresh profile and swallows clicks
  const dismiss = page.locator('button:has-text("המשך")').first();
  if (await dismiss.count()) { await dismiss.click({ force: true }).catch(() => {}); await page.waitForTimeout(1500); }

  const micSel = 'button[aria-label="הקלטה"]';
  const stopSel = 'button[aria-label="שלח הקלטה"]';
  const harnessSend = 'button[aria-label="שליחת הודעה"]';
  if ((await page.locator(micSel).count()) === 0) {
    const fresh = page.locator('button:has-text("שיחה חדשה")').first();
    if (await fresh.count()) { await fresh.click().catch(() => {}); await page.waitForTimeout(7000); }
  }

  // ── A. the primary action IS the microphone while there is nothing to send ─────────────
  const micCount = await page.locator(micSel).count();
  const sendHidden = await page.evaluate((sel) => {
    const b = [...document.querySelectorAll(sel)];
    return b.length ? getComputedStyle(b[0]).display === "none" : null;
  }, harnessSend);
  results.steps.push({ step: "primary-is-microphone", found: micCount, sendButtonHidden: sendHidden });
  if (!micCount) {
    await page.screenshot({ path: "/out/01-no-button.png" });
    results.errors.push("the microphone is not the composer's primary action");
  }

  const composerText = () => page.evaluate(() => {
    const editable = document.querySelector('[contenteditable="true"]');
    return editable ? editable.innerText.trim() : "";
  });

  // ── B. record a few seconds and press again: the DEFAULT is sending the audio ───────────
  await page.locator(micSel).first().click({ force: true, timeout: 15000 });
  log(`recording ${SHORT_MS}ms…`);
  await page.waitForTimeout(SHORT_MS);
  await page.screenshot({ path: "/out/02-recording.png" });
  const stopCount = await page.locator(stopSel).count();
  results.steps.push({ step: "recording", stopButton: stopCount });
  await page.locator(stopSel).first().click({ force: true, timeout: 15000 });
  log("stopped — the recording should go to the agent…");
  await page.waitForTimeout(Number(process.env.AUDIO_WAIT_MS || 30000));
  const bodyAfterAudio = await page.locator("body").innerText().catch(() => "");
  results.steps.push({
    step: "audio-sent",
    attachmentInConversation: /הקלטה/.test(bodyAfterAudio),
  });
  await page.screenshot({ path: "/out/03-audio-sent.png" });

  // ── C. the same gesture, but asking for the transcript instead of the audio ─────────────
  let shortText = "";
  if (MODE !== "audio-only") {
    await page.locator(micSel).first().click({ force: true, timeout: 15000 });
    await page.waitForTimeout(SHORT_MS);
    const asText = page.locator('button:has-text("תמלול במקום")').first();
    results.steps.push({ step: "transcribe-offered", found: await asText.count() });
    if (await asText.count()) await asText.click({ force: true, timeout: 15000 });
    log("asked for the transcript…");
    await page.waitForTimeout(Number(process.env.WAIT_AFTER_STOP_MS || 120000));
    shortText = await composerText();
    results.steps.push({ step: "short-recording", chars: shortText.length, hebrew: /[\u0590-\u05FF]/.test(shortText) });
    await page.screenshot({ path: "/out/04-transcript.png" });

    if (shortText) {
      // the send button is back (there is text), and it must deliver it
      await page.locator(harnessSend).first().click({ force: true, timeout: 15000 });
      await page.waitForTimeout(12000);
      const bodyAfterText = await page.locator("body").innerText().catch(() => "");
      results.steps.push({
        step: "in-conversation",
        hasTranscript: bodyAfterText.includes(shortText.slice(0, 30)),
      });
      await page.screenshot({ path: "/out/05-text-sent.png" });
    }
  }

  results.texts = { composer: shortText.slice(0, 300) };
  results.errors = results.errors || [];
  // ── the assertions, as an exit code ─────────────────────────────────────────────────────
  const checks = [
    ["the primary action is the microphone", results.steps.some((x) => x.step === "primary-is-microphone" && x.found === 1 && x.sendButtonHidden === true)],
    ["recording offers stop-and-send", results.steps.some((x) => x.step === "recording" && x.stopButton === 1)],
    ["the recording reached the conversation", results.steps.some((x) => x.step === "audio-sent" && x.attachmentInConversation === true)],
    ["\"תמלול במקום\" produced Hebrew text in the composer", results.steps.some((x) => x.step === "short-recording" && x.hebrew)],
    ["the harness send button delivered the text", results.steps.some((x) => x.step === "in-conversation" && x.hasTranscript)],
    ["no console errors", results.errors.length === 0],
  ];
  results.checks = checks.map(([name, ok]) => ({ name, ok }));
  const failed = checks.filter(([, ok]) => !ok);
  console.log(`${failed.length ? "FAIL" : "PASS"}: ${checks.map(([n, ok]) => `${ok ? "✓" : "✗"} ${n}`).join(" · ")}`);
  log(JSON.stringify(results, null, 1));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch((error) => {
  console.log(JSON.stringify({ fatal: String(error).slice(0, 500) }, null, 1));
  process.exit(1);
});
