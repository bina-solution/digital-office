// ── System commands: /status, /help, /retry, /clean, /files ────────
import { execSync } from 'node:child_process';
import { readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

// Public base of THIS dispatcher, from the deployment (apps/openhands/docker-compose.yml sets
// DISPATCH_PUBLIC_URL from ${DISPATCH_BASE_URL}, which derives from DEPLOYMENT_DOMAIN). It was a
// literal at every call site, so every link the bot handed out named the FIRST deployment's
// domain no matter which deployment sent it.
const DISPATCH_PUBLIC_URL = (process.env.DISPATCH_PUBLIC_URL || 'http://localhost:8800').replace(/\/+$/, '');

/**
 * Handle system commands that don't need AI. Returns { type, text } or null.
 */
export function handleSystemCommand(message, chatId, ctx) {
  const m = message.toLowerCase().trim();
  const { sessions, inFlight, issuesDb, dispatcherLLMEnabled, openhandsUrl,
    openhandsPublicUrl, agentMaxAgeMs, downloadsDir, dispatchForTelegram,
    handleScheduleCommand, handleIssueCommand, handleObsidianBrainCommand } = ctx;

  if (m === '/status' || m === 'status' || m === 'health') {
    var agentCount = 0;
    try {
      var dockerPs = execSync('docker ps --filter "name=oh-agent-server" --format "{{.Names}}" 2>/dev/null | wc -l', { timeout: 3000, encoding: 'utf-8' }).trim();
      agentCount = parseInt(dockerPs) || 0;
    } catch(e) {}
    var status = '<b>Dispatcher Agent Status</b>\n\n';
    status += '• Active sessions: ' + sessions.size + '\n';
    status += '• In-flight tasks: ' + inFlight + '\n';
    status += '• Agent sandboxes: ' + agentCount + '\n';
    status += '• LLM: ' + (dispatcherLLMEnabled ? 'Connected' : 'Unavailable') + '\n';
    status += '• OpenHands: ' + openhandsUrl + '\n';
    status += '• Public URL: ' + openhandsPublicUrl + '\n';
    return { type: 'direct', text: status };
  }

  if (m === '/help' || m === 'help' || m === '?') {
    var help = '<b>Dispatcher Agent — Help</b>\n\n';
    help += '<b>Commands:</b>\n';
    help += '/status — System health\n/help — This message\n/sessions — Active sessions\n';
    help += '/retry — Retry last failed request\n';
    help += '/schedule add "every 5 min" "task" — Schedule a task\n';
    help += '/schedule list — View scheduled tasks\n/schedule delete &lt;id&gt; — Remove a schedule\n';
    help += '/clean — Clean old sandboxes\n/files — List shared downloads folder\n';
    help += '/issues — List open issues\n/issue #N — View issue details\n';
    help += '/issue create Title | priority high | label bug — Create issue\n';
    help += '/issue comment #N text — Add comment\n/issue close #N — Close issue\n';
    help += '/obsidian-brain remember that X — Store a fact in AI brain\n';
    help += '/obsidian-brain search X — Search the AI brain vault\n';
    help += '/obsidian-brain &lt;task&gt; — Execute with full brain access\n\n';
    help += '<b>Capabilities:</b>\n• Direct answers (math, facts, status)\n• Code creation & editing\n';
    help += '• File operations\n• Web browsing\n• Terminal commands\n• Git operations\n• Image analysis\n\n';
    help += 'Just ask me anything!';
    return { type: 'direct', text: help };
  }

  if (m === '/retry' || m === 'retry') {
    var userId = 'tg-' + chatId;
    var sess = sessions.get(userId);
    if (!sess || !sess.lastFailedMessage) {
      return { type: 'direct', text: '[warn] No failed request to retry. Send a new message.' };
    }
    var retryMsg = sess.lastFailedMessage;
    sess.lastFailedMessage = null;
    dispatchForTelegram(chatId, retryMsg, null, null).catch(function(e) {
      console.error('[telegram] retry error:', e.message);
    });
    return { type: 'direct', text: '[retry] Retrying: <i>' + retryMsg.slice(0, 80).replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</i>...' };
  }

  if (m === '/clean' || m === 'clean') {
    return handleCleanCommand(agentMaxAgeMs);
  }

  if (m === '/files' || m === 'files') {
    return handleFilesCommand(downloadsDir);
  }

  if (m === '/sessions' || m === 'sessions') {
    var list = '<b>Active Sessions (' + sessions.size + ')</b>\n\n';
    var idx = 0;
    for (const [uid, s] of sessions) {
      idx++;
      var ago = Math.round((Date.now() - s.lastActiveAt) / 1000);
      var agoStr = ago < 60 ? ago + 's ago' : ago < 3600 ? Math.round(ago/60) + 'm ago' : Math.round(ago/3600) + 'h ago';
      list += idx + '. ' + uid + ' — ' + (s.model || 'default') + ', ' + s.turnCount + ' turns, ' + agoStr;
      if (s.ohConvId) list += '\n   [link] ' + '' + DISPATCH_PUBLIC_URL + '/chat?uid=' + userId;
      list += '\n';
    }
    if (sessions.size === 0) list += '(no active sessions)\n';
    return { type: 'direct', text: list };
  }

  if (m.startsWith('/schedule')) {
    return handleScheduleCommand(message, chatId);
  }

  if (m.startsWith('/issue')) {
    return handleIssueCommand(message, chatId, m, issuesDb);
  }
  if (m === '/issues') {
    return handleIssueCommand(message, chatId, m, issuesDb);
  }

  if (m.startsWith('/obsidian-brain')) {
    return handleObsidianBrainCommand(message, chatId);
  }

  return null;
}

/**
 * Clean up dead/old agent sandbox containers.
 */
export function handleCleanCommand(agentMaxAgeMs) {
  var removed = 0;
  var kept = 0;
  try {
    var out = execSync(
      'docker ps -a --filter "name=oh-agent-server" --format "{{.Names}}\\t{{.Status}}\\t{{.CreatedAt}}" 2>/dev/null',
      { timeout: 5000, encoding: 'utf-8' }
    ).trim();
    if (!out) return { type: 'direct', text: 'No agent sandboxes found.' };

    var lines = out.split('\n');
    var toRemove = [];
    for (var i = 0; i < lines.length; i++) {
      var parts = lines[i].split('\t');
      var name = parts[0];
      var status = parts[1] || '';
      var createdAt = parts[2] || '';
      if (status.startsWith('Exited') || status.startsWith('Dead')) { toRemove.push(name); continue; }
      var createdDate = new Date(createdAt);
      if (!isNaN(createdDate.getTime()) && (Date.now() - createdDate.getTime()) > agentMaxAgeMs) {
        toRemove.push(name);
      } else { kept++; }
    }

    for (var j = 0; j < toRemove.length; j++) {
      try { execSync('docker rm -f ' + toRemove[j] + ' 2>/dev/null', { timeout: 10000, encoding: 'utf-8' }); removed++; }
      catch(e) { console.error('[clean] failed to remove ' + toRemove[j] + ': ' + e.message); }
    }

    return { type: 'direct', text: '<b>Agent Cleanup</b>\n• Removed: ' + removed + ' containers\n• Kept: ' + kept + ' active agents\n• Max agent age: ' + (agentMaxAgeMs / 3600000) + 'h' };
  } catch(e) { console.error('[clean] error:', e.message); return { type: 'direct', text: '[warn] Cleanup failed: ' + e.message }; }
}

/**
 * List shared downloads folder.
 */
export function handleFilesCommand(downloadsDir) {
  try {
    if (!existsSync(downloadsDir)) return { type: 'direct', text: 'Downloads folder not found: ' + downloadsDir };
    var files = readdirSync(downloadsDir);
    if (files.length === 0) return { type: 'direct', text: 'Downloads folder is empty.\n' + downloadsDir };
    var list = '<b>Shared Downloads (' + files.length + ' files)</b>\n<pre>';
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      var fp = join(downloadsDir, f);
      var stat = statSync(fp);
      var size = stat.size;
      var sizeStr = size < 1024 ? size + 'B' : size < 1048576 ? (size/1024).toFixed(1) + 'KB' : (size/1048576).toFixed(1) + 'MB';
      var mtime = stat.mtime.toISOString().slice(0, 19).replace('T', ' ');
      list += '\n' + sizeStr.padStart(8) + '  ' + mtime + '  ' + f;
    }
    list += '</pre>';
    return { type: 'direct', text: list };
  } catch(e) { console.error('[files] error:', e.message); return { type: 'direct', text: '[warn] Failed to list files: ' + e.message }; }
}
