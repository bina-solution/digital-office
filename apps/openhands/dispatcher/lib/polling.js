// ── OpenHands polling: task readiness + agent response monitoring ──
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Wait for an OpenHands task to be ready (sandbox up). Thin wrapper over pollTaskWithCallback.
 */
export async function ohPollTaskWithTelegram(taskId, maxMs, onStatus, pollTaskWithCallback) {
  return pollTaskWithCallback(taskId, maxMs, onStatus);
}

/**
 * Poll event files from an OpenHands conversation directory. Classifies events
 * into typed callbacks: reasoning, tool, lifecycle, response, error.
 * Returns the final response text or null on timeout.
 */
export async function ohPollResponseWithTelegram(convId, maxMs, chatId, onEvent, opts) {
  if (!convId) return null;
  const { ohStatePath, responsePollMs } = opts;
  const deadline = Date.now() + maxMs;
  var seenFiles = {};
  var lastStatusEditTime = 0;
  var toolSummary = '';
  var reasoningPreview = '';
  var lastStats = '';
  const eventsDir = join(ohStatePath, 'v1_conversations', convId);

  function toolIcon(name) {
    var n = (name || '').toLowerCase();
    if (n.includes('browser') || n.includes('browse')) return '[browse]';
    if (n.includes('terminal') || n.includes('bash') || n.includes('cmd')) return '[term]';
    if (n.includes('file') || n.includes('editor') || n.includes('write') || n.includes('edit')) return '[file]';
    if (n.includes('think') || n.includes('finish') || n.includes('respond')) return '[think]';
    return '[tool]';
  }

  function brief(s, max) { s = (s||'').replace(/\n/g,' ').trim(); return s.length > max ? s.slice(0,max-3)+'...' : s; }

  while (Date.now() < deadline) {
    try {
      var files = [];
      try { files = readdirSync(eventsDir).filter(function(f) { return f.endsWith('.json'); }); } catch(e) { files = []; }
      files.sort();

      var foundResponse = null;
      for (var fi = 0; fi < files.length; fi++) {
        var fname = files[fi];
        if (seenFiles[fname]) continue;
        seenFiles[fname] = true;

        try {
          var raw = readFileSync(join(eventsDir, fname), 'utf-8');
          var e = JSON.parse(raw);
          var src = e.source || '';

          // AGENT reasoning (llm_message)
          if (src === 'agent' && e.llm_message) {
            var lm = e.llm_message;
            if (lm.reasoning_content && lm.reasoning_content.trim()) {
              reasoningPreview = brief(lm.reasoning_content, 120);
              if (onEvent) onEvent({ type: 'reasoning', text: lm.reasoning_content, brief: reasoningPreview });
            }
            var content = lm.content;
            if (Array.isArray(content)) {
              var texts = [];
              for (var ci = 0; ci < content.length; ci++) {
                if (content[ci] && content[ci].text) texts.push(content[ci].text);
              }
              var fullText = texts.join('').trim();
              if (fullText && lm.role === 'assistant') {
                var isError = /NotFoundError|APIError|ProviderError|AuthenticationError|RateLimitError|ServiceUnavailableError|litellm\.\w+Error/i.test(fullText);
                if (isError) {
                  foundResponse = null;
                  if (onEvent) onEvent({ type: 'error', text: fullText, errorType: 'llm_provider' });
                } else {
                  foundResponse = fullText;
                  if (onEvent) onEvent({ type: 'response', text: fullText });
                }
              }
            }
          }

          // AGENT observation (tool results)
          if (src === 'agent' && e.observation) {
            var toolName = e.tool_name || e.name || 'tool';
            var obsContent = e.observation.content || e.observation.text || '';
            var obsBrief = brief(obsContent, 80);
            toolSummary = toolIcon(toolName) + ' ' + toolName + ': ' + obsBrief;
            if (onEvent) onEvent({ type: 'tool', tool: toolName, icon: toolIcon(toolName), summary: obsBrief });
          }

          // ENVIRONMENT events (browser, terminal, lifecycle, stats)
          if (src === 'environment') {
            if (e.observation && e.tool_name) {
              var tn = e.tool_name;
              var oc = e.observation.content || e.observation.text || '';
              var ob = brief(oc, 120);
              toolSummary = toolIcon(tn) + ' ' + tn + ': ' + ob;
              if (onEvent) onEvent({ type: 'tool', tool: tn, icon: toolIcon(tn), summary: ob });
            }
            if (e.key === 'execution_status' && e.value && onEvent) {
              onEvent({ type: 'lifecycle', status: e.value });
            }
            if (e.key === 'stats' && e.value) {
              try {
                var st = typeof e.value === 'string' ? JSON.parse(e.value) : e.value;
                var tokens = (st.prompt_tokens||0) + (st.completion_tokens||0);
                var cost = st.accumulated_cost || st.cost || 0;
                lastStats = tokens + ' tokens';
                if (cost > 0) lastStats += ' · $' + (typeof cost === 'number' ? cost.toFixed(4) : cost);
              } catch(se) { lastStats = 'stats updated'; }
            }
          }

          // Fallback: string content in agent events
          if (src === 'agent') {
            var strContent = e.content || e.message || '';
            if (typeof strContent === 'string' && strContent.trim()) {
              var isError = /NotFoundError|APIError|ProviderError|AuthenticationError|RateLimitError|ServiceUnavailableError|litellm\.\w+Error/i.test(strContent);
              if (isError) {
                foundResponse = null;
                if (onEvent) onEvent({ type: 'error', text: strContent, errorType: 'llm_provider' });
              } else {
                foundResponse = strContent;
                if (onEvent) onEvent({ type: 'response', text: strContent });
              }
            }
          }

        } catch(parseErr) { /* skip unparseable files */ }
      }

      if (foundResponse) return foundResponse;

      // Combined status update every 5s
      var now = Date.now();
      if (now - lastStatusEditTime > 5000) {
        lastStatusEditTime = now;
        var statusParts = [];
        if (toolSummary) statusParts.push(toolSummary);
        if (reasoningPreview) statusParts.push('[reason] ' + reasoningPreview);
        if (lastStats) statusParts.push(lastStats);
        if (statusParts.length > 0 && onEvent) {
          onEvent({ type: 'activity', summary: statusParts.join('\n'), fileCount: files.length });
        } else if (files.length > 0 && onEvent) {
          onEvent({ type: 'thinking', count: files.length });
        }
      }

    } catch (err) { console.error('[oh-poll] poll iteration error:', err.message); }
    await new Promise(r => setTimeout(r, responsePollMs));
  }
  return null;
}
