/**
 * Node.js webhook integration example for any-concurrency.
 *
 * Usage (Node 18+):
 *   node examples/node-webhook.js
 */

const BASE_URL = "http://localhost:8080";

const post = (path, body) =>
  fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());

const spanId = () => crypto.randomUUID();
const nowMs = () => Date.now();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Example 1: simple open/close ─────────────────────────────────────────────

async function exampleSimple() {
  const id = spanId();
  await post("/ingest/span", {
    id,
    src: "node-app",
    svc: "data-import",
    label: "Import customer CSV",
    status: "running",
    s: nowMs(),
    meta: { file: "customers.csv" },
  });

  await sleep(1200);

  const result = await post(`/ingest/span/${id}/close`, { status: "success" });
  console.log("[exampleSimple] closed:", result);
}

// ── Example 2: withSpan helper ────────────────────────────────────────────────

async function withSpan(src, svc, label, fn) {
  const id = spanId();
  const s = nowMs();
  await post("/ingest/span", { id, src, svc, label, status: "running", s });
  let status = "success";
  let meta = {};
  try {
    const result = await fn();
    if (result && typeof result === "object") meta = result;
  } catch (err) {
    status = "error";
    meta = { error: String(err) };
  } finally {
    await post(`/ingest/span/${id}/close`, { status, meta });
  }
}

async function exampleWithSpan() {
  await withSpan("node-app", "send-email", "Welcome email", async () => {
    await sleep(300);
    console.log("[exampleWithSpan] email sent");
    return { recipient: "user@example.com" };
  });
}

// ── Example 3: batch ingest ───────────────────────────────────────────────────

async function exampleBatch() {
  const t = nowMs();
  const spans = Array.from({ length: 5 }, (_, i) => ({
    id: spanId(),
    src: "pipeline",
    svc: `step-${i}`,
    label: `Step ${i}`,
    s: t + i * 200,
    e: t + i * 200 + 180,
    status: "success",
  }));
  const result = await post("/ingest/spans", spans);
  console.log("[exampleBatch] ingested:", result);
}

// ── Example 4: error span ─────────────────────────────────────────────────────

async function exampleError() {
  await withSpan("node-app", "risky-job", "Risky operation", async () => {
    await sleep(200);
    throw new Error("something went wrong");
  }).catch(() => {}); // error is captured inside withSpan
  console.log("[exampleError] error span submitted");
}

// ── Run all examples ──────────────────────────────────────────────────────────

(async () => {
  console.log("any-concurrency Node.js webhook examples");
  console.log(`Target: ${BASE_URL}\n`);

  await exampleSimple();
  await exampleWithSpan();
  await exampleBatch();
  await exampleError();

  console.log("\nDone — open http://localhost:8080 to see the spans");
})();
