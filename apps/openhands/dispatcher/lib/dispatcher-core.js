// ── Dispatcher Core: intent classifier, session data query ─────────
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Intent classifier: returns true if this request likely needs OpenHands.
 */
export function needsOpenHands(message, hasMedia) {
  var m = message.toLowerCase();
  if (hasMedia) {
    if (/describe|what is|what.*see|look at|tell me about|identify|recognize/i.test(m)) return false;
    if (/ocr|extract text|read text|document|scan|analyze.*image|process.*image|convert|transform/i.test(m)) return true;
    return false;
  }
  if (/^run\b|^execute\b|npm |pip |install |git |commit|push|pull|merge|branch|mkdir|touch|chmod|compile|build|deploy|test\b|debug/i.test(m)) return true;
  if (/browse|navigate|go to|visit|open .*url|http|www\.|website|web page|scrape|crawl/i.test(m)) return true;
  if (/\bcreate\b.*\bfile\b|\bwrite\b.*\bcode\b|\bmake\b.*\bscript\b|\bgenerate\b.*\bapp\b/i.test(m)) return true;
  if (/\bimplement\b|\brefactor\b|\badd\b.*\bfeature\b/i.test(m)) return true;
  if (/\bscreenshot\b|\btake\b.*\bpicture\b|\bcapture\b/i.test(m)) return true;
  return false;
}

/**
 * Query session data from OpenHands DB. Used by dispatcherLLM to answer
 * questions about conversations without spawning a OpenHands session.
 */
export function querySessionData(ohDB, ohStatePath, openhandsPublicUrl, query) {
  var result = '';

  if (ohDB) {
    try {
      var cur = ohDB.prepare("SELECT conversation_id, title, created_at, last_updated_at, llm_model FROM conversation_metadata WHERE user_id = 'dispatcher' ORDER BY last_updated_at DESC LIMIT 50").all();
      if (cur && cur.length > 0) {
        result += 'RECENT OPENHANDS CONVERSATIONS (' + cur.length + ' total):\n';
        for (var i = 0; i < Math.min(cur.length, 20); i++) {
          var c = cur[i];
          var cid = Array.isArray(c) ? c[0] : c.conversation_id;
          var title = Array.isArray(c) ? c[1] : c.title;
          var model = Array.isArray(c) ? c[4] : c.llm_model;
          var eventCount = 0;
          try {
            var convDir = join(ohStatePath, 'v1_conversations', cid);
            eventCount = readdirSync(convDir).filter(function(f){return f.endsWith('.json')}).length;
          } catch(e) {}
          result += '  ' + (i+1) + '. ' + (title||'(untitled)').slice(0,50) + '\n';
          result += '     ID: ' + cid.slice(0,8) + ' | Model: ' + (model||'?') + ' | Events: ' + eventCount + '\n';
          result += '     URL: ' + openhandsPublicUrl + '/conversations/' + cid + '\n';
        }
      }
    } catch(e) { result += '(DB query error)\n'; }
  }

  // Event summary for a specific conversation ID mentioned in query
  var convIdMatch = query.match(/([a-f0-9]{8,})/i);
  if (convIdMatch) {
    var partialId = convIdMatch[1].toLowerCase();
    try {
      var allDirs = readdirSync(join(ohStatePath, 'v1_conversations'));
      var matchDir = allDirs.filter(function(d){return d.startsWith(partialId)})[0];
      if (matchDir) {
        var eventsDir = join(ohStatePath, 'v1_conversations', matchDir);
        var files = readdirSync(eventsDir).filter(function(f){return f.endsWith('.json')}).sort();
        result += '\nEVENT SUMMARY FOR ' + matchDir.slice(0,8) + ' (' + files.length + ' events):\n';
        var toolNames = {};
        for (var fi = 0; fi < files.length; fi++) {
          try {
            var e = JSON.parse(readFileSync(join(eventsDir, files[fi]), 'utf-8'));
            if (e.tool_name) { toolNames[e.tool_name] = (toolNames[e.tool_name]||0)+1; }
          } catch(x) {}
        }
        result += '  Tools: ' + JSON.stringify(toolNames) + '\n';
      }
    } catch(e) {}
  }

  return result || 'No OpenHands session data available yet.';
}
