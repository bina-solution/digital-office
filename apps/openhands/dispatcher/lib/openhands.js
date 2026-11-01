// OpenHands API client — task creation, sandbox polling, response extraction
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const OH_URL = process.env.OPENHANDS_URL || 'http://openhands-bina-deployment:3000';
const OH_STATE = process.env.OPENHANDS_STATE_PATH || '/.openhands-state';
const POLL_MS = parseInt(process.env.DISPATCHER_RESPONSE_POLL_MS || '1500', 10);

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// Create a new OpenHands task (headless API)
export async function createTask(message, resolvedModel, imageUrls) {
  var content = [{ type: 'text', text: message }];
  if (imageUrls && imageUrls.length > 0) {
    content.push({ type: 'image', image_urls: imageUrls });
  }
  const res = await fetch(`${OH_URL}/api/v1/app-conversations`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ initial_message: { content, run: true }, llm_model: resolvedModel }),
    signal: AbortSignal.timeout(30000)
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`OpenHands API ${res.status}: ${txt.slice(0, 200)}`);
  }
  const task = await res.json();
  console.log('[oh-api] task ' + task.id + ' model=' + resolvedModel + (imageUrls && imageUrls.length ? ' images=' + imageUrls.length : ''));
  return task;
}

// Poll task until READY or ERROR
export async function pollTask(taskId, maxMs) {
  const deadline = Date.now() + (maxMs || 120000);
  var lastStatus = '';
  while (Date.now() < deadline) {
    const res = await fetch(`${OH_URL}/api/v1/app-conversations/start-tasks?ids=${taskId}`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) { await sleep(2000); continue; }
    const tasks = await res.json();
    const task = tasks && tasks[0];
    if (!task) { await sleep(2000); continue; }
    if (task.status && task.status !== lastStatus) {
      lastStatus = task.status;
      console.log('[oh-api] task ' + taskId + ' status=' + task.status);
    }
    if (task.status === 'READY' && task.app_conversation_id) {
      console.log('[oh-api] conv ' + task.app_conversation_id.slice(0,8));
      return task;
    }
    if (task.status === 'ERROR') {
      throw new Error('Sandbox failed to start (status=ERROR). The AI agent may be experiencing issues. Try again.');
    }
    await sleep(2000);
  }
  throw new Error('Timeout: sandbox did not start within ' + (maxMs/1000) + 's. OpenHands may be overloaded.');
}

// Poll task with Telegram status callback
export async function pollTaskWithCallback(taskId, maxMs, onStatus) {
  const deadline = Date.now() + (maxMs || 120000);
  var lastStatus = '';
  while (Date.now() < deadline) {
    const res = await fetch(`${OH_URL}/api/v1/app-conversations/start-tasks?ids=${taskId}`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) { await sleep(2000); continue; }
    const tasks = await res.json();
    const task = tasks && tasks[0];
    if (!task) { await sleep(2000); continue; }
    if (task.status && task.status !== lastStatus) {
      lastStatus = task.status;
      var elapsed = Math.round((Date.now() - (deadline - maxMs)) / 1000);
      if (onStatus) onStatus(task.status, elapsed);
      console.log('[oh-api] task ' + taskId + ' status=' + task.status);
    }
    if (task.status === 'READY' && task.app_conversation_id) {
      console.log('[oh-api] conv ' + task.app_conversation_id.slice(0,8));
      return task;
    }
    if (task.status === 'ERROR') {
      throw new Error('Sandbox failed to start (status=ERROR). The AI agent may be experiencing issues. Try again.');
    }
    await sleep(2000);
  }
  throw new Error('Timeout: sandbox did not start within ' + (maxMs/1000) + 's. OpenHands may be overloaded.');
}

// Poll for agent response by reading conversation event files from disk
export async function pollResponse(convId, maxMs) {
  if (!convId) return null;
  const deadline = Date.now() + maxMs;
  var seenFiles = {};
  const eventsDir = join(OH_STATE, 'v1_conversations', convId);
  console.log('[oh-poll] rich polling for conv ' + convId.slice(0,8) + ' from disk');
  while (Date.now() < deadline) {
    try {
      var files = [];
      try { files = readdirSync(eventsDir).filter(f => f.endsWith('.json')); } catch(e) { files = []; }
      files.sort();
      for (var fi = 0; fi < files.length; fi++) {
        var fname = files[fi];
        if (seenFiles[fname]) continue;
        seenFiles[fname] = true;
        try {
          var raw = readFileSync(join(eventsDir, fname), 'utf-8');
          var e = JSON.parse(raw);
          if (e.source === 'agent' && e.llm_message) {
            var lm = e.llm_message;
            if (Array.isArray(lm.content) && lm.role === 'assistant') {
              var texts = lm.content.filter(c => c && c.text).map(c => c.text);
              var fullText = texts.join('').trim();
              if (fullText) {
                console.log('[oh-poll] got agent response (array) len=' + fullText.length);
                return fullText;
              }
            }
          }
          // ── Error detection: check if response is an LLM provider error ──
          if (e.source === 'agent') {
            var sc = e.content || e.message || '';
            if (typeof sc === 'string' && sc.trim()) {
              var isError = /NotFoundError|APIError|ProviderError|AuthenticationError|RateLimitError|ServiceUnavailableError|DeepseekException|litellm\.\w+Error/i.test(sc);
              if (isError) {
                console.error('[oh-poll] agent response contains LLM provider error');
                return null; // Don't return error text as success
              }
              console.log('[oh-poll] got agent response len=' + sc.length);
              return sc;
            }
          }
          if (e.observation && e.observation.content) {
            var obs = e.observation.content;
            if (Array.isArray(obs)) {
              var obsText = obs.filter(c => c && c.text).map(c => c.text).join('').trim();
              if (obsText && e.source === 'agent') return obsText;
            }
          }
        } catch(parseErr) { console.error('[oh-poll] parse error:', fname, parseErr.message); }
      }
    } catch(err) { console.error('[oh-poll] dir read error:', err.message); }
    await sleep(POLL_MS);
  }
  return null;
}

export { OH_URL, OH_STATE };
