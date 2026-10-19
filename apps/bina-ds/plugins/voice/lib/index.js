/**
 * voice — the Host half of the office's dictation: a relay, and nothing else.
 *
 * WHY THIS FILE EXISTS AT ALL. The browser can reach exactly one origin — the console's — and the
 * speech service (`apitools-asr:8987`) deliberately has no edge route of its own ("no public door",
 * apps/apitools/docker-compose.yml). So the audio has to cross the harness, and the harness has a
 * supported way to do that: `ctx.connection.fetch.register()` claims an EXACT path below `/api`,
 * served by the same handler the browser is already authenticated against, next to the `/api`
 * prefix bina-ds already root-mounts on the console host. That is the whole reason this plugin is
 * server-side: one hop of relay, no new route, no new credential, no CORS.
 *
 * WHAT THE CLIENT OWNS: where an utterance ends. The browser cuts ~30 s segments and posts them;
 * each one becomes an ordinary job in the speech service's bounded queue. Nothing here holds a
 * socket open, so a dropped connection costs one segment, not a session. (Measured, 2026-10-07:
 * 30 s segments run at ~1.4× real time on the office box, 10 s segments at ~0.5× — Whisper pads
 * every window to 30 s of mel frames, so short segments pay the encoder for audio they do not have.)
 *
 * The `send` route is the only one that talks to the harness's own RPC: `session/prompt` is how
 * everything else in this office puts a user message into a conversation (`bbox agent send` does it
 * through adapter/server.mjs), and the action token it needs never reaches the browser.
 */
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

export const name = "@bina/dsh-plugin-voice";
export const inject = ["connection"];

const ASR = process.env.SPEECH_URL || "http://apitools-asr:8987";
const HARNESS = `http://127.0.0.1:${process.env.DSH_PORT || 3080}`;
const TOKEN_FILE = process.env.AGENT_TOKEN_FILE || "/data/dsh/api-token";
const TZ = process.env.TZ || "Asia/Jerusalem";
const LANGUAGE = process.env.VOICE_LANGUAGE || "he";

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: JSON_HEADERS });

async function token() {
  try {
    return (await readFile(TOKEN_FILE, "utf8")).trim();
  } catch {
    return "";
  }
}

async function rpc(method, args, timeoutMs = 30000) {
  const bearer = await token();
  const response = await fetch(`${HARNESS}/api/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(bearer ? { authorization: `Bearer ${bearer}` } : {}) },
    body: JSON.stringify({ type: "client-request", rpcId: randomUUID(), method, payload: { args } }),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`harness/http-${response.status}: ${body.slice(0, 200)}`);
  const result = JSON.parse(body).result || {};
  if (result.ok === false) throw new Error(result.error?.message || result.error?.code || "harness/error");
  return result.value;
}

/** The service's answer, passed through unchanged so the client can show the real status code. */
async function relay(path, init, timeoutMs) {
  const response = await fetch(`${ASR}${path}`, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  const body = await response.text();
  return new Response(body, {
    status: response.status,
    headers: { "content-type": response.headers.get("content-type") || "application/json; charset=utf-8" },
  });
}

export function apply(ctx) {
  const register = (path, methods, requestBody, fetch) =>
    ctx.connection.fetch.register({ path, methods, requestBody, fetch });

  // ── open a live session ────────────────────────────────────────────────────────────────
  register("/api/voice/session", ["POST"], "buffered", async (request) => {
    const language = new URL(request.url).searchParams.get("language") || LANGUAGE;
    return relay(`/v1/voice/sessions?language=${encodeURIComponent(language)}`, { method: "POST" }, 20000);
  });

  // ── one recorded segment: raw audio bytes in, a queued job out ─────────────────────────
  register("/api/voice/segment", ["POST"], "buffered", async (request) => {
    const url = new URL(request.url);
    const session = url.searchParams.get("session");
    const index = url.searchParams.get("index") ?? "0";
    if (!session) return json({ error: "session is required" }, 400);
    const type = request.headers.get("content-type") || "audio/webm";
    const bytes = await request.arrayBuffer();
    if (!bytes.byteLength) return json({ error: "empty segment" }, 400);
    const form = new FormData();
    form.set("file", new Blob([bytes], { type }), `segment-${index}.${type.includes("ogg") ? "ogg" : "webm"}`);
    form.set("index", String(index));
    form.set("language", url.searchParams.get("language") || LANGUAGE);
    return relay(`/v1/voice/sessions/${encodeURIComponent(session)}/segments`, { method: "POST", body: form }, 180000);
  });

  // ── the growing transcript ─────────────────────────────────────────────────────────────
  register("/api/voice/status", ["GET"], "buffered", async (request) => {
    const session = new URL(request.url).searchParams.get("session");
    if (!session) return json({ error: "session is required" }, 400);
    return relay(`/v1/voice/sessions/${encodeURIComponent(session)}`, { method: "GET" }, 20000);
  });

  // ── the accurate second pass over the whole recording ──────────────────────────────────
  register("/api/voice/finish", ["POST"], "buffered", async (request) => {
    const session = new URL(request.url).searchParams.get("session");
    if (!session) return json({ error: "session is required" }, 400);
    return relay(`/v1/voice/sessions/${encodeURIComponent(session)}/finish`, { method: "POST" }, 180000);
  });

  register("/api/voice/cancel", ["POST"], "buffered", async (request) => {
    const session = new URL(request.url).searchParams.get("session");
    if (!session) return json({ error: "session is required" }, 400);
    return relay(`/v1/voice/sessions/${encodeURIComponent(session)}/cancel`, { method: "POST" }, 20000);
  });

  // ── which conversation will receive the text, and the sending itself ───────────────────
  register("/api/voice/current", ["GET"], "buffered", async () => {
    try {
      const list = await rpc("session/list", { _request: {} }, 15000);
      // the harness answers {items:[{sessionId, updatedAt(ms), projections:{values:{title}}}]}
      const rows = Array.isArray(list) ? list : list?.items || list?.sessions || [];
      const newest = [...rows].sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0))[0];
      if (!newest) return json({ id: null, title: null });
      return json({
        id: newest.sessionId || newest.id || null,
        title: newest.projections?.values?.title || newest.title || null,
      });
    } catch (error) {
      return json({ id: null, title: null, error: String(error?.message || error) }, 200);
    }
  });

  // ── a conversation to send into, even from the blank hero ─────────────────────────────
  // The microphone is the composer's primary action now, so it can be pressed before any
  // conversation exists. `session/create` is what the harness does when the first message is sent;
  // doing it here means the recording always has somewhere to land.
  register("/api/voice/ensure-session", ["POST"], "buffered", async (request) => {
    const wanted = String(new URL(request.url).searchParams.get("session") || "").trim();
    if (wanted) return json({ id: wanted, created: false });
    try {
      const created = await rpc("session/create", { request: { cwd: process.env.DSH_OFFICE_ROOT || "/root/deployment-hacohen" } }, 30000);
      return json({ id: created?.sessionId || null, created: true });
    } catch (error) {
      return json({ error: String(error?.message || error) }, 502);
    }
  });

  // ── send the recording ITSELF, not only its transcript ────────────────────────────────
  // Why this exists: on a 2-core box the first transcript is tens of seconds away, and the owner's
  // expectation (rightly) is WhatsApp's — press stop, send. So the audio can be delivered
  // immediately: the joined recording is uploaded to the conversation as a real attachment
  // (`session/uploadFileBinary`, exactly what `bbox agent upload` does) and the message carries
  // whatever transcript exists at that moment. The agent can transcribe the file itself if the text
  // is not there yet — it has the skill for it.
  register("/api/voice/send-recording", ["POST"], "buffered", async (request) => {
    const url = new URL(request.url);
    let sessionId = String(url.searchParams.get("session") || "").trim();
    const asrId = String(url.searchParams.get("asr") || "").trim();
    const text = String(url.searchParams.get("text") || "").trim();
    if (!asrId) return json({ error: "asr is required" }, 400);
    try {
      if (!sessionId) {
        const created = await rpc("session/create", { request: { cwd: process.env.DSH_OFFICE_ROOT || "/root/deployment-hacohen" } }, 30000);
        sessionId = created?.sessionId || "";
        if (!sessionId) throw new Error("could not create a conversation for the recording");
      }
      const audio = await fetch(`${ASR}/v1/voice/sessions/${encodeURIComponent(asrId)}/export`, {
        method: "POST",
        signal: AbortSignal.timeout(120000),
      });
      if (!audio.ok) throw new Error(`the recording could not be joined (HTTP ${audio.status})`);
      const bytes = Buffer.from(await audio.arrayBuffer());
      const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
      const name = `הקלטה ${stamp}.wav`;
      const bearer = await token();
      const upload = await fetch(
        `${HARNESS}/api/session/uploadFileBinary?${new URLSearchParams({ sessionId, name })}`,
        {
          method: "POST",
          headers: { "content-type": "application/octet-stream", ...(bearer ? { authorization: `Bearer ${bearer}` } : {}) },
          body: bytes,
          signal: AbortSignal.timeout(60000),
        },
      );
      const uploaded = JSON.parse(await upload.text());
      if (uploaded.ok === false) throw new Error(uploaded.error?.message || "upload rejected");
      const attachment = uploaded.value?.file;
      if (!attachment) throw new Error("the harness returned no attachment");
      const content = [];
      if (text) content.push({ type: "text", text });
      else content.push({ type: "text", text: "🎤 הקלטה (התמלול עוד בדרך)" });
      content.push({ type: "file", attachment });
      await rpc("session/prompt", {
        request: { requestId: randomUUID(), sessionId, mode: "queue", content, clientTimeZone: TZ },
      }, 30000);
      return json({ ok: true, session: sessionId, bytes: bytes.length, name });
    } catch (error) {
      return json({ error: String(error?.message || error) }, 502);
    }
  });

  register("/api/voice/send", ["POST"], "buffered", async (request) => {
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const sessionId = String(body?.session || "").trim();
    const text = String(body?.text || "").trim();
    if (!sessionId) return json({ error: "session is required — the panel prints which conversation it will use" }, 400);
    if (!text) return json({ error: "text is required" }, 400);
    try {
      await rpc("session/prompt", {
        request: {
          requestId: randomUUID(),
          sessionId,
          mode: "queue",
          content: [{ type: "text", text }],
          clientTimeZone: TZ,
        },
      }, 30000);
      return json({ ok: true, session: sessionId, chars: text.length });
    } catch (error) {
      return json({ error: String(error?.message || error) }, 502);
    }
  });

  ctx.logger?.info?.("voice: dictation routes registered on /api/voice/* (service %s)", ASR);
}
