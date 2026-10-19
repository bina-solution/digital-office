/**
 * Dispatcher Client — WhatsApp → OpenHands Bridge Client
 * =======================================================
 * Calls the dispatcher service which proxies to OpenHands headless sessions.
 * Mirrors agent_stream.js API for seamless integration with chat_bot.js.
 */

const DISPATCHER_URL = process.env.DISPATCHER_URL || 'http://dispatcher:8800';
const DISPATCHER_TOKEN = process.env.DISPATCHER_TOKEN || 'dispatcher-dev-token';

class DispatcherBusyError extends Error {
    constructor(body, label) {
        super(`${label || 'dispatcher'} busy`);
        this.name = 'DispatcherBusyError';
        this.body = body;
    }
}

/**
 * Send a dispatch request to the OpenHands dispatcher.
 *
 * @param {Object} opts
 * @param {string} opts.userId - WhatsApp phone number (used as session key)
 * @param {string} opts.message - The task/message to send
 * @param {string} [opts.sessionId] - Optional session ID to resume
 * @param {string} [opts.model] - Model override (deepseek-v4-pro, etc.)
 * @param {string[]} [opts.imageUrls] - Optional image URLs for vision
 * @param {Function} [opts.onProgress] - Callback for each NDJSON event
 * @param {number} [opts.timeoutMs] - Timeout in ms (default 30min)
 * @returns {Promise<{sessionId, text, toolUseCount, stats, error}>}
 */
async function dispatch({
    userId,
    message,
    sessionId,
    model,
    imageUrls,
    onProgress,
    timeoutMs = 1800000,
} = {}) {
    if (!DISPATCHER_TOKEN) throw new Error('DISPATCHER_TOKEN is not configured');
    if (!userId) throw new Error('userId is required');
    if (!message) throw new Error('message is required');

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(new Error('dispatch timeout')), timeoutMs);

    let res;
    try {
        res = await fetch(`${DISPATCHER_URL.replace(/\/$/, '')}/dispatch`, {
            method: 'POST',
            headers: {
                'content-type': 'application/json',
                authorization: `Bearer ${DISPATCHER_TOKEN}`,
            },
            body: JSON.stringify({
                userId,
                message,
                sessionId: sessionId || undefined,
                model: model || undefined,
                imageUrls: imageUrls || undefined,
            }),
            signal: controller.signal,
        });
    } catch (e) {
        clearTimeout(timeout);
        throw new Error(`dispatcher unreachable: ${e.message}`);
    }

    if (!res.ok) {
        clearTimeout(timeout);
        const text = await res.text().catch(() => '');
        if (res.status === 429) {
            let parsed = null;
            try { parsed = JSON.parse(text); } catch { /* */ }
            throw new DispatcherBusyError(parsed || text, 'dispatcher');
        }
        throw new Error(`dispatcher ${res.status}: ${text.slice(0, 200)}`);
    }

    // Stream NDJSON events
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let learnedSessionId = sessionId || null;
    const textChunks = [];
    let toolUseCount = 0;
    let stats = null;
    let finalEvent = null;
    let errorEvent = null;

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const event = JSON.parse(line);
                    const et = event.type;

                    if (et === 'start') {
                        learnedSessionId = event.conversationId || event.sessionId;
                    } else if (et === 'text' || et === 'result') {
                        // New dispatcher format: result.message + conversationUrl
                        // Old format: text.text
                        var txt = event.text || event.message || '';
                        if (event.conversationUrl) txt += '\n' + event.conversationUrl;
                        if (txt) textChunks.push(txt);
                        if (event.conversationId) learnedSessionId = event.conversationId;
                        if (onProgress) onProgress(event);
                    } else if (et === 'conversation_url') {
                        textChunks.push(event.url || '');
                        if (onProgress) onProgress(event);
                    } else if (et === 'status') {
                        if (onProgress) onProgress(event);
                    } else if (et === 'tool_use') {
                        toolUseCount++;
                        if (onProgress) onProgress(event);
                    } else if (et === 'tool_result') {
                        if (onProgress) onProgress(event);
                    } else if (et === 'finish') {
                        finalEvent = event;
                    } else if (et === 'final') {
                        finalEvent = event;
                        stats = event;
                    } else if (et === 'error') {
                        errorEvent = event;
                        if (onProgress) onProgress(event);
                    } else if (onProgress) {
                        onProgress(event);
                    }
                } catch {
                    // Skip malformed lines
                }
            }
        }
    } finally {
        clearTimeout(timeout);
        reader.releaseLock();
    }

    if (errorEvent && !textChunks.length) {
        return {
            sessionId: learnedSessionId,
            text: null,
            toolUseCount: 0,
            stats: null,
            error: errorEvent.message,
            errorKind: 'dispatch_error',
        };
    }

    return {
        sessionId: learnedSessionId,
        text: textChunks.join(''),
        toolUseCount,
        stats,
        error: null,
    };
}

module.exports = { dispatch, DispatcherBusyError };
