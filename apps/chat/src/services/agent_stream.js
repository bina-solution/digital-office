// Unified NDJSON-streaming client for all agent-runner endpoints.
// Replaces: agent_chat.js, dev_agent_client.js, agent_runner.js, automations_chat.js
//
// Usage:
//   const stream = require('./services/agent_stream');
//   const result = await stream.send({
//     endpoint: '/chat-turn',  // or /dev-turn, /run-agent, /automations-turn
//     message: '...',
//     sessionId: '...',
//     model: 'deepseek-chat',
//     timeoutMs: 360000,
//     images: [...],
//     onProgress: (evt) => { ... },
//   });
//   → { sessionId, text, toolUseCount, toolNames, stats, error, errorKind }

const AGENT_RUNNER_URL = process.env.AGENT_RUNNER_URL || 'http://agent-runner:7700';
const AGENT_RUNNER_TOKEN = process.env.AGENT_RUNNER_TOKEN || '';

// Undici dispatcher (shared across all calls)
let sharedDispatcher = null;
const getDispatcher = () => {
    if (sharedDispatcher) return sharedDispatcher;
    try {
        const { Agent } = require('undici');
        sharedDispatcher = new Agent({
            bodyTimeout: 0, headersTimeout: 0,
            keepAliveTimeout: 60_000, keepAliveMaxTimeout: 600_000,
        });
    } catch (e) {
        console.warn('[agent-stream] undici Agent unavailable:', e.message);
        sharedDispatcher = null;
    }
    return sharedDispatcher;
};

class AgentBusyError extends Error {
    constructor(body, label) {
        super(`${label || 'agent'} busy`);
        this.name = 'AgentBusyError';
        this.body = body;
    }
}

const send = async ({
    endpoint,         // '/chat-turn', '/dev-turn', '/run-agent', '/automations-turn'
    message,
    sessionId,
    model,
    timeoutMs = 360000,  // default 6 min
    images,
    onProgress,
    job,              // for /run-agent
    extraPrompt,      // for /run-agent
    context,          // { senderName?, groupName?, queryType? }
} = {}) => {
    if (!AGENT_RUNNER_TOKEN) throw new Error('AGENT_RUNNER_TOKEN is not configured');
    if (!message && !job) throw new Error('message or job is required');
    if (!endpoint) throw new Error('endpoint is required');

    const label = endpoint.replace('/', '').replace('-turn', '');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(new Error(`${label} timeout`)), timeoutMs);

    let res;
    try {
        const body = { sessionId: sessionId || undefined, message, model: model || undefined };
        if (images && Array.isArray(images)) body.images = images;
        if (job) { body.job = job; if (extraPrompt) body.extraPrompt = extraPrompt; }
        if (context) body.context = context;
        const fetchOpts = {
            method: 'POST',
            headers: { 'content-type': 'application/json', authorization: `Bearer ${AGENT_RUNNER_TOKEN}` },
            body: JSON.stringify(body),
            signal: controller.signal,
        };
        const disp = getDispatcher();
        if (disp) fetchOpts.dispatcher = disp;
        res = await fetch(`${AGENT_RUNNER_URL.replace(/\/$/, '')}${endpoint}`, fetchOpts);
    } catch (e) {
        clearTimeout(timeout);
        throw new Error(`agent-runner unreachable: ${e.message}`);
    }

    if (!res.ok) {
        clearTimeout(timeout);
        const text = await res.text().catch(() => '');
        if (res.status === 429) {
            let parsed = null;
            try { parsed = JSON.parse(text); } catch { /* */ }
            throw new AgentBusyError(parsed || text, label);
        }
        throw new Error(`agent-runner ${endpoint} ${res.status}: ${text.slice(0, 200)}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '', finalText = null, stats = null, learnedSessionId = sessionId || null;
    const textChunks = [];
    let toolUseCount = 0;
    const toolNames = [];
    let lastError = null, lastErrorKind = null;

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let nl;
            while ((nl = buffer.indexOf('\n')) >= 0) {
                const line = buffer.slice(0, nl).trim();
                buffer = buffer.slice(nl + 1);
                if (!line) continue;
                let evt;
                try { evt = JSON.parse(line); } catch { continue; }
                switch (evt.type) {
                case 'ping': break;
                case 'session':
                    learnedSessionId = evt.sessionId || learnedSessionId;
                    if (onProgress) try { onProgress({ kind: 'session', sessionId: learnedSessionId }); } catch { /* */ }
                    break;
                case 'text':
                    if (typeof evt.text === 'string') textChunks.push(evt.text);
                    if (onProgress) try { onProgress({ kind: 'text', text: evt.text }); } catch { /* */ }
                    break;
                case 'tool_use':
                    toolUseCount++;
                    if (evt.name) toolNames.push(evt.name);
                    if (onProgress) try { onProgress({ kind: 'tool_use', name: evt.name, input: evt.input, toolUseCount }); } catch { /* */ }
                    break;
                case 'tool_result':
                    if (onProgress) try { onProgress({ kind: 'tool_result', name: toolNames[toolNames.length-1] || '', preview: evt.content_preview, isError: evt.is_error }); } catch { /* */ }
                    break;
                case 'final':
                    finalText = evt.text;
                    if (evt.sessionId) learnedSessionId = evt.sessionId;
                    if (evt.subtype && evt.subtype !== 'success') lastError = `result ${evt.subtype}`;
                    {
                        const { text: _, type, sessionId: __, subtype, ...rest } = evt;
                        if (rest.total_cost_usd != null && !stats) stats = rest;
                    }
                    break;
                case 'result': {
                    const { type, ...rest } = evt;
                    stats = rest;
                    if (evt.subtype && evt.subtype !== 'success') lastError = `result ${evt.subtype}: ${evt.message || ''}`;
                    break;
                }
                case 'error':
                    lastError = evt.message || 'unknown error';
                    lastErrorKind = evt.kind || 'unknown';
                    break;
                }
            }
        }
    } finally {
        clearTimeout(timeout);
        try { reader.cancel(); } catch { /* */ }
    }

    return {
        sessionId: learnedSessionId,
        text: finalText != null ? finalText : textChunks.join(''),
        toolUseCount, toolNames, stats,
        error: lastError, errorKind: lastErrorKind,
    };
};

// Backward-compatible exports
module.exports = {
    send,
    AgentBusyError,
    // Legacy aliases
    chatTurn: (opts) => send({ ...opts, endpoint: '/chat-turn', timeoutMs: parseInt(process.env.AGENT_CHAT_HTTP_TIMEOUT_MS || '360000', 10) }),
    devTurn: (opts) => send({ ...opts, endpoint: '/dev-turn', timeoutMs: parseInt(process.env.DEV_TURN_TIMEOUT_MS || '1800000', 10) }),
    runAgent: (opts) => send({ ...opts, endpoint: '/run-agent', timeoutMs: parseInt(process.env.AGENT_RUNNER_TIMEOUT_MS || '1800000', 10) }),
    automationsTurn: (opts) => send({ ...opts, endpoint: '/automations-turn', timeoutMs: 120000 }),
};
