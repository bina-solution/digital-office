// ── Session persistence and context building ──────────────────────
import { writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const OH_STATE_PATH = process.env.OPENHANDS_STATE_PATH || '/.openhands-state';
const SESSIONS_FILE = join(OH_STATE_PATH, 'dispatcher-sessions.json');
const DEFAULT_MODEL = process.env.DISPATCHER_DEFAULT_MODEL || 'DeepSeek V4 Pro';

/**
 * Persist sessions map to disk (last 20 messages per session)
 */
export function saveSessions(sessions) {
  try {
    var data = [];
    for (const [uid, s] of sessions) {
      data.push({
        userId: uid,
        model: s.model || DEFAULT_MODEL,
        turnCount: s.turnCount,
        ohConvId: s.ohConvId || null,
        lastActiveAt: s.lastActiveAt,
        history: (s.history || []).slice(-20)
      });
    }
    writeFileSync(SESSIONS_FILE, JSON.stringify(data));
  } catch(e) { console.error('[sessions] save error:', e.message); }
}

/**
 * Load sessions from disk into the provided sessions Map
 */
export function loadSessions(sessions) {
  try {
    var raw = readFileSync(SESSIONS_FILE, 'utf-8');
    var data = JSON.parse(raw);
    if (Array.isArray(data)) {
      data.forEach(function(s) {
        sessions.set(s.userId, {
          model: s.model || DEFAULT_MODEL,
          turnCount: s.turnCount || 0,
          ohConvId: s.ohConvId || null,
          lastActiveAt: s.lastActiveAt || Date.now(),
          history: s.history || [],
          processing: false
        });
      });
      console.log('[sessions] loaded ' + data.length + ' sessions from disk');
    }
  } catch(e) { /* file doesn't exist yet — normal on first run */ }
}

/**
 * Build session context string for LLM calls
 */
export function buildSessionContext(userId, sessions, ohDB) {
  var s = sessions.get(userId);
  if (!s) return 'No prior session context.';
  
  var lines = ['Session context for ' + userId + ':'];
  lines.push('Turn count: ' + (s.turnCount || 0));
  lines.push('Model: ' + (s.model || DEFAULT_MODEL));
  
  // Recent history
  if (s.history && s.history.length > 0) {
    lines.push('Recent messages:');
    var recent = s.history.slice(-6);
    recent.forEach(function(h) {
      lines.push('  [' + h.role + ']: ' + (h.content || '').slice(0, 200));
    });
  }
  
  // OpenHands conversation link
  if (s.ohConvId) {
    lines.push('OpenHands session: ' + s.ohConvId);
  }
  
  // Active tasks
  if (ohDB) {
    try {
      var tasks = ohDB.prepare('SELECT conversation_id, title, created_at FROM conversation_metadata WHERE user_id=? ORDER BY created_at DESC LIMIT 3').all(userId);
      if (tasks && tasks.length > 0) {
        lines.push('Recent OpenHands tasks:');
        tasks.forEach(function(t) {
          lines.push('  - ' + (t.title || t.conversation_id));
        });
      }
    } catch(e) {}
  }
  
  return lines.join('\n');
}
