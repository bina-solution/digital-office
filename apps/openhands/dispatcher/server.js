/**
 * Dispatcher Agent — Intelligent Bridge with Autonomous Reasoning
 *
 * Acts as the primary pilot for user requests:
 *   Answers simple questions directly via its own LLM
 *   Uses OpenHands as a tool for code, files, browsing, execution
 *   📡 Maintains live monitoring threads for OpenHands tasks
 *   🎯 Orchestrates multi-step workflows end-to-end
 *
 * Flow:
 *   User msg → Intent Router → [Direct Answer] or [OpenHands Task]
 *                                    ↑                    ↓
 *                              (instant, cheap)    (rich monitoring
 *                                                    with back-propagation)
 */
import { createServer } from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync, readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { execSync } from 'node:child_process';
import { sendMessage as telegramSendMessage, sendPhoto as telegramSendPhoto, forwardSessionImages as telegramForwardSessionImages, cacheFileForOpenHands as telegramCacheImageForOpenHands, setWebhook as telegramSetWebhook, sendChatAction as telegramSendChatAction, getImageCache, getDownloadsDir, getToken, TELEGRAM_API } from './lib/telegram.js';
import { createTask as ohCreateTask, pollTask as ohPollTask, pollTaskWithCallback, pollResponse as ohPollResponse } from './lib/openhands.js';
import { getDashboard, getIssuesUI, THEME } from './lib/dashboard.js';
import { saveSessions, loadSessions } from './lib/sessions.js';
import { loadObsidianBrainSkill, vaultRemember, vaultSearch, vaultRead, vaultRecentSessions, vaultCheckpoint, buildObsidianBrainPrompt, handleObsidianBrainCommand } from './lib/obsidian.js';
import { handleIssueCommand } from './lib/issues.js';
// ── Model profiles: dynamically loaded from OpenHands settings.json ──
// (kept inline for fallback logic and alias mapping complexity)
// ── Dispatcher Core → imported from ./lib/dispatcher-core.js ────
import { needsOpenHands, querySessionData } from './lib/dispatcher-core.js';
import { handleCleanCommand, handleFilesCommand } from './lib/commands.js';

// Public base of THIS dispatcher, from the deployment (apps/openhands/docker-compose.yml sets
// DISPATCH_PUBLIC_URL from ${DISPATCH_BASE_URL}, which derives from DEPLOYMENT_DOMAIN). It was a
// literal at every call site, so every link the bot handed out named the FIRST deployment's
// domain no matter which deployment sent it.
const DISPATCH_PUBLIC_URL = (process.env.DISPATCH_PUBLIC_URL || 'http://localhost:8800').replace(/\/+$/, '');
const DEPLOYMENT_DOMAIN = process.env.DEPLOYMENT_DOMAIN || 'localhost';

const OPENHANDS_URL = process.env.OPENHANDS_URL || 'http://openhands-bina-deployment:3000';
const OPENHANDS_PUBLIC_URL = process.env.OPENHANDS_PUBLIC_URL || 'http://localhost:3000';
const DISPATCHER_TOKEN = process.env.DISPATCHER_TOKEN || 'dispatcher-dev-token';
const MAX_CONCURRENT = parseInt(process.env.DISPATCHER_MAX_CONCURRENT || '3', 10);
const DEFAULT_MODEL = process.env.DISPATCHER_DEFAULT_MODEL || 'DeepSeek V4 Pro'; // OpenHands profile name
const PORT = parseInt(process.env.DISPATCHER_PORT || '8800', 10);
const OH_STATE_PATH = process.env.OPENHANDS_STATE_PATH || '/.openhands-state';
const VAULT_PATH = '/root/deployment-hacohen/ai/obsidian';
const SKILLS_PATH = '/root/deployment-hacohen/.github/skills';
const RESPONSE_POLL_MS = parseInt(process.env.DISPATCHER_RESPONSE_POLL_MS || '1500', 10);
const RESPONSE_POLL_MAX_MS = parseInt(process.env.DISPATCHER_RESPONSE_POLL_MAX_MS || '300000', 10); // 5 min

// ── Dispatcher Agent LLM (for direct answers) ───────────────────────
const DISPATCHER_LLM_KEY = process.env.DEEPSEEK_API_KEY || process.env.LLM_API_KEY || '';
const DISPATCHER_LLM_URL = process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com';
const DISPATCHER_LLM_MODEL = 'deepseek-chat';  // fast & cheap for text routing
const DISPATCHER_LLM_ENABLED = !!DISPATCHER_LLM_KEY;
// Vision model: auto-detect Gemini for superior image analysis, fall back to DeepSeek
const GEMINI_LLM_KEY = process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY || '';
const GEMINI_LLM_URL = 'https://generativelanguage.googleapis.com/v1beta';
const VISION_MODEL = GEMINI_LLM_KEY ? 'gemini-2.5-flash' : 'deepseek-chat';
const VISION_MODEL_URL = GEMINI_LLM_KEY ? GEMINI_LLM_URL : DISPATCHER_LLM_URL;
const VISION_MODEL_KEY = GEMINI_LLM_KEY || DISPATCHER_LLM_KEY;
console.log('[vision] model=' + VISION_MODEL + ' key=' + (VISION_MODEL_KEY ? VISION_MODEL_KEY.slice(0,8)+'...' : 'unset'));
// How the dispatcher sees itself
const DISPATCHER_SYSTEM_PROMPT = `You are the Dispatcher Agent — an autonomous AI coordinator with thinking, planning, and media analysis capabilities.

## YOUR CAPABILITIES
- **Think & Reason**: Show step-by-step reasoning before answering
- **Media Analysis**: View and describe images directly (vision-capable)
- **Planning**: Create and share plans before complex tasks
- **Direct Answers**: Answer questions, summarize sessions, explain concepts
- **OpenHands Delegation**: Route code/files/browse tasks to OpenHands agent

## THINKING PROTOCOL
Before every response:
1. Analyze the request — what does the user actually need?
2. Decide: answer directly OR delegate to OpenHands
3. If delegating: create a plan and show it to the user
4. If answering directly: reason step by step, then give the answer

## DECISION RULES — Answer Directly When:
- Questions about sessions, conversations, history, status
- Math, facts, explanations, general knowledge
- "hi", "hello", casual chat (answer warmly!)
- Summaries of past work, recent tasks
- System info (/status, /health, /help)
- Simple image description (what's in this photo?)
- Concept explanations, Q&A

## DECISION RULES — Delegate to OpenHands (<<USE_OPENHANDS>>) When:
- Creating, editing, or executing code/scripts
- File operations (create/write/read files beyond context)
- Web browsing (navigate to URLs, scrape pages)
- Terminal/CLI commands (install, git, docker, make)
- Complex image processing (OCR, document analysis)
- Multi-step development or debugging tasks
- Deployment operations (restart services, check logs, update configs)

## IMAGE HANDLING
When a user sends an image:
- If they ask "what is this?" or "describe" → ANSWER DIRECTLY using vision
- If they ask "extract text" or "OCR" → DELEGATE to OpenHands
- If they ask "analyze this document" → DELEGATE to OpenHands
- If the image needs code/processing → DELEGATE to OpenHands

## RESPONSE FORMAT
- Direct answer: Show thinking → then answer naturally and concisely
- Plan: "Plan: 1) ... 2) ... 3) ..."
- Need OpenHands: Respond with <<USE_OPENHANDS>> followed by the refined instruction
- Never mention OpenHands in direct answers — the user doesn't need to know

## PERSONALITY
Be warm, professional, and precise. Show that you're thinking about their request.
Use emojis naturally to make responses engaging.`;

// ── Session persistence (in lib/sessions.js) ──────────────────────
const SESSIONS_FILE = join(OH_STATE_PATH, 'dispatcher-sessions.json');

// ═══════════════════════════════════════════════════════════════════
// SCHEDULING MODULE — Cron-like task scheduling
// ═══════════════════════════════════════════════════════════════════
const schedules = new Map();  // scheduleId → { id, chatId, cron, task, createdAt, lastRun, nextRun, enabled }
const SCHEDULES_FILE = join(OH_STATE_PATH, 'dispatcher-schedules.json');
let scheduleIdCounter = 0;

function saveSchedules() {
  try {
    var data = [];
    for (const [id, s] of schedules) {
      data.push({
        id: s.id, chatId: s.chatId, cron: s.cron, task: s.task,
        createdAt: s.createdAt, lastRun: s.lastRun, nextRun: s.nextRun, enabled: s.enabled
      });
    }
    writeFileSync(SCHEDULES_FILE, JSON.stringify(data));
    if (scheduleIdCounter > 0) scheduleIdCounter = Math.max(scheduleIdCounter, ...Array.from(schedules.keys()).map(Number));
  } catch(e) {}
}

function loadSchedules() {
  try {
    var raw = readFileSync(SCHEDULES_FILE, 'utf-8');
    var data = JSON.parse(raw);
    if (Array.isArray(data)) {
      data.forEach(function(s) {
        schedules.set(String(s.id), {
          id: s.id, chatId: s.chatId, cron: s.cron, task: s.task,
          createdAt: s.createdAt, lastRun: s.lastRun || null,
          nextRun: s.nextRun || computeNextRun(s.cron, Date.now()),
          enabled: s.enabled !== false
        });
        scheduleIdCounter = Math.max(scheduleIdCounter, s.id);
      });
      console.log('[schedules] loaded ' + data.length + ' schedules from disk');
    }
  } catch(e) {}
}

// Parse simple schedule expressions: "every N minutes/hours", "daily HH:MM", "hourly"
function computeNextRun(cronExpr, fromTime) {
  var now = fromTime || Date.now();
  var expr = (cronExpr || '').toLowerCase().trim();
  
  // "every N minutes" or "every N hours"
  var everyMin = expr.match(/every\s+(\d+)\s*min/);
  if (everyMin) return now + parseInt(everyMin[1]) * 60000;
  var everyHr = expr.match(/every\s+(\d+)\s*hour/);
  if (everyHr) return now + parseInt(everyHr[1]) * 3600000;
  
  // "hourly"
  if (expr === 'hourly') return now + 3600000;
  
  // "daily" or "daily HH:MM"
  var dailyTime = expr.match(/daily\s*(?:at\s*)?(\d{1,2}):?(\d{2})?/);
  if (dailyTime || expr === 'daily') {
    var h = dailyTime ? parseInt(dailyTime[1]) : 9;
    var m = dailyTime && dailyTime[2] ? parseInt(dailyTime[2]) : 0;
    var d = new Date(now);
    d.setHours(h, m, 0, 0);
    if (d.getTime() <= now) d.setDate(d.getDate() + 1);
    return d.getTime();
  }
  
  // "every 5 minutes" with "every" → default to 5 min
  if (expr.startsWith('every')) return now + 300000;
  
  // Default: every 30 minutes
  return now + 1800000;
}

// Format next run time for display
function formatNextRun(timestamp) {
  if (!timestamp) return 'not scheduled';
  var diff = timestamp - Date.now();
  if (diff < 0) return 'overdue';
  var mins = Math.round(diff / 60000);
  if (mins < 60) return 'in ' + mins + ' min';
  var hrs = Math.round(mins / 60);
  if (hrs < 24) return 'in ' + hrs + ' hr';
  var days = Math.round(hrs / 24);
  return 'in ' + days + ' day' + (days > 1 ? 's' : '');
}

// Run due schedules
function runScheduleTick() {
  var now = Date.now();
  for (const [id, s] of schedules) {
    if (!s.enabled) continue;
    if (s.nextRun && s.nextRun <= now) {
      console.log('[schedule] firing #' + id + ' for chatId=' + s.chatId + ' task="' + s.task.slice(0,50) + '"');
      s.lastRun = now;
      s.nextRun = computeNextRun(s.cron, now);
      
      // Dispatch the scheduled task
      dispatchForTelegram(s.chatId, s.task, null, null).catch(function(e) {
        console.error('[schedule] error firing #' + id + ':', e.message);
      });
    }
  }
}

// Handle /schedule commands
function handleScheduleCommand(message, chatId) {
  var parts = message.trim().split(/\s+/);
  if (parts[0] !== '/schedule') return null;
  var sub = (parts[1] || '').toLowerCase();
  
  // /schedule list
  if (sub === 'list' || sub === 'ls') {
    var userSchedules = [];
    for (const [id, s] of schedules) {
      if (String(s.chatId) === String(chatId) || s.chatId === chatId) {
        userSchedules.push(s);
      }
    }
    if (userSchedules.length === 0) return { type: 'direct', text: 'No scheduled tasks. Use:\n<code>/schedule add "every 5 minutes" "your task here"</code>' };
    
    var list = '<b>Scheduled Tasks (' + userSchedules.length + ')</b>\n\n';
    userSchedules.forEach(function(s, i) {
      var status = s.enabled ? '[on]' : '[off]';
      list += status + ' <b>#' + s.id + '</b> — ' + s.cron + '\n';
      list += '   Task: ' + (s.task.length > 60 ? s.task.slice(0,57)+'...' : s.task) + '\n';
      list += '   Next: ' + formatNextRun(s.nextRun);
      if (s.lastRun) {
        var ago = Math.round((Date.now() - s.lastRun) / 60000);
        list += ' | Last: ' + (ago < 1 ? 'just now' : ago + 'm ago');
      }
      list += '\n\n';
    });
    list += '<i>Delete with: /schedule delete &lt;id&gt;</i>';
    return { type: 'direct', text: list };
  }
  
  // /schedule delete <id>
  if (sub === 'delete' || sub === 'remove' || sub === 'rm') {
    var delId = parts[2];
    if (!delId) return { type: 'direct', text: '[warn] Usage: <code>/schedule delete &lt;id&gt;</code>\nUse /schedule list to see IDs.' };
    var s = schedules.get(delId);
    if (!s) return { type: 'direct', text: '[err] Schedule #' + delId + ' not found.' };
    if (String(s.chatId) !== String(chatId)) return { type: 'direct', text: '[err] Schedule #' + delId + ' belongs to another user.' };
    schedules.delete(delId);
    saveSchedules();
    return { type: 'direct', text: '[done] Schedule #' + delId + ' deleted: <i>' + s.task.slice(0,80) + '</i>' };
  }
  
  // /schedule add "cron" "task"  OR  /schedule "cron" "task"
  if (sub === 'add' || sub === 'new' || sub === 'create') {
    parts.shift(); parts.shift(); // remove /schedule and add
  } else {
    parts.shift(); // remove /schedule only
  }
  
  var rest = parts.join(' ');
  // Parse: "every 5 minutes" "the task text"
  var match = rest.match(/^"([^"]+)"\s+"([^"]+)"/);
  if (!match) match = rest.match(/^'([^']+)'\s+'([^']+)'/);
  if (!match) {
    return { type: 'direct', text: '[warn] Usage:\n<code>/schedule add "every 5 minutes" "your task"</code>\n<code>/schedule add "daily 09:00" "morning report"</code>\n<code>/schedule add "hourly" "check status"</code>\n\nExamples:\n• every 30 minutes\n• every 2 hours\n• hourly\n• daily 09:00\n• daily' };
  }
  
  var cronExpr = match[1];
  var task = match[2];
  scheduleIdCounter++;
  var newId = String(scheduleIdCounter);
  var nextRun = computeNextRun(cronExpr, Date.now());
  
  schedules.set(newId, {
    id: newId, chatId: chatId, cron: cronExpr, task: task,
    createdAt: Date.now(), lastRun: null, nextRun: nextRun, enabled: true
  });
  saveSchedules();
  
  return { type: 'direct', text: '<b>Schedule #' + newId + ' created!</b>\n\n' + cronExpr + '\n' + task + '\nNext run: ' + formatNextRun(nextRun) + '\n\n<i>Use /schedule list to view all schedules</i>' };
}

// ═══════════════════════════════════════════════════════════════════
function handleSystemCommand(message, chatId) {
  var m = message.toLowerCase().trim();
  
  // /status — show system health
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
    status += '• LLM: ' + (DISPATCHER_LLM_ENABLED ? 'Connected' : 'Unavailable') + '\n';
    status += '• OpenHands: ' + OPENHANDS_URL + '\n';
    status += '• Public URL: ' + OPENHANDS_PUBLIC_URL + '\n';
    return { type: 'direct', text: status };
  }
  
  // /help
  if (m === '/help' || m === 'help' || m === '?') {
    var help = '<b>Dispatcher Agent — Help</b>\n\n';
    help += '<b>Commands:</b>\n';
    help += '/status — System health\n';
    help += '/help — This message\n';
    help += '/sessions — Active sessions\n';
    help += '/retry — Retry last failed request\n';
    help += '/schedule add "every 5 min" "task" — Schedule a task\n';
    help += '/schedule list — View scheduled tasks\n';
    help += '/schedule delete &lt;id&gt; — Remove a schedule\n';
    help += '/clean — Clean old sandboxes\n';
    help += '/files — List shared downloads folder\n';
    help += '/issues — List open issues\n';
    help += '/issue #N — View issue details\n';
    help += '/issue create Title | priority high | label bug — Create issue\n';
    help += '/issue comment #N text — Add comment\n';
    help += '/issue close #N — Close issue\n';
    help += '/obsidian-brain remember that X — Store a fact in AI brain\n';
    help += '/obsidian-brain search X — Search the AI brain vault\n';
    help += '/obsidian-brain &lt;task&gt; — Execute with full brain access\n\n';
    help += '<b>Schedule examples:</b>\n';
    help += '• "every 30 minutes"\n• "every 2 hours"\n• "hourly"\n';
    help += '• "daily 09:00"\n• "daily"\n\n';
    help += '<b>Capabilities:</b>\n';
    help += '• Direct answers (math, facts, status)\n';
    help += '• Code creation & editing\n';
    help += '• File operations\n• Web browsing\n';
    help += '• Terminal commands\n• Git operations\n';
    help += '• Image analysis\n\n';
    help += 'Just ask me anything!';
    return { type: 'direct', text: help };
  }
  
  // /retry — re-send the last failed message
  if (m === '/retry' || m === 'retry') {
    var userId = 'tg-' + chatId;
    var sess = sessions.get(userId);
    if (!sess || !sess.lastFailedMessage) {
      return { type: 'direct', text: '[warn] No failed request to retry. Send a new message.' };
    }
    var retryMsg = sess.lastFailedMessage;
    sess.lastFailedMessage = null;
    // Re-dispatch asynchronously
    dispatchForTelegram(chatId, retryMsg, null, null).catch(function(e) {
      console.error('[telegram] retry error:', e.message);
    });
    return { type: 'direct', text: '[retry] Retrying: <i>' + retryMsg.slice(0, 80).replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</i>...' };
  }
  
  // /clean — remove dead and old agent sandbox containers
  if (m === '/clean' || m === 'clean') {
    return handleCleanCommand(AGENT_MAX_AGE_MS);
  }

  // /files — list shared downloads folder
  if (m === '/files' || m === 'files') {
    return handleFilesCommand(DOWNLOADS_DIR);
  }

  // /sessions
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
  
  // ── /schedule commands ──
  if (m.startsWith('/schedule')) {
    var result = handleScheduleCommand(message, chatId);
    if (result) return result;
  }
  
  // ── /issue commands ──────────────────────────────────────────
  if (m.startsWith('/issue')) {
    return handleIssueCommand(message, chatId, m, issuesDb);
  }
  if (m === '/issues') {
    return handleIssueCommand(message, chatId, m, issuesDb);
  }
  
  // ── /obsidian-brain commands ──
  if (m.startsWith('/obsidian-brain')) {
    return handleObsidianBrainCommand(message, chatId);
  }
  
  return null; // not a system command
}

// ── Cleanup / Files → imported from ./lib/commands.js ─────────────
// handleCleanCommand(agentMaxAgeMs), handleFilesCommand(downloadsDir)

// ── Issue Tracker → imported from ./lib/issues.js ────────────────

// ── Obsidian Brain → imported from ./lib/obsidian.js ─────────────

// ── Telegram ─────────────────────────────────────────────────────────
const TELEGRAM_TOKEN = getToken();
const TELEGRAM_WEBHOOK_URL = process.env.TELEGRAM_WEBHOOK_URL || '';
const DOWNLOADS_DIR = getDownloadsDir();
const imageCache = getImageCache();

// ── Model profiles → imported from ./lib/models.js ──────────────
// MODEL_MAP, PROFILE_TO_LITELLM, AVAILABLE_MODELS, DEFAULT_PROFILE
// loadOpenHandsProfiles (called on import, reloaded every 5min)
// resolveModel, resolveLiteLLMModel

// ── Session Context Builder ─────────────────────────────────────────
// Builds a summary of the user's sessions and all active dispatcher sessions.
// This is prepended to AI messages so the agent can answer questions about
// "my sessions", "list all sessions", "what's the progress", etc.
function buildSessionContext(userId) {
  var ctx = '[SYSTEM CONTEXT — DISPATCHER SESSIONS]\n';
  
  // 1. This user's session
  var mySession = sessions.get(userId);
  if (mySession) {
    ctx += 'Your session: userId=' + userId + ', model=' + (mySession.model || 'default') +
      ', turnCount=' + mySession.turnCount + ', currentConversationId=' + (mySession.ohConvId || 'none') +
      ', lastActive=' + Math.round((Date.now() - mySession.lastActiveAt) / 1000) + 's ago\n';
  } else {
    ctx += 'Your session: userId=' + userId + ' (new session, no prior history)\n';
  }
  
  // 2. All active sessions summary
  ctx += '\nAll active dispatcher sessions (' + sessions.size + ' total):\n';
  var idx = 0;
  for (const [uid, s] of sessions) {
    idx++;
    var url = s.ohConvId ? '' + DISPATCH_PUBLIC_URL + '/chat?uid=' + userId : 'no conversation yet';
    var ago = Math.round((Date.now() - s.lastActiveAt) / 1000);
    ctx += '  ' + idx + '. userId=' + uid + ', model=' + (s.model || 'default') +
      ', turns=' + s.turnCount + ', lastActive=' + ago + 's ago, conversationUrl=' + url + '\n';
  }
  
  // 3. Recent conversations from OpenHands DB
  ctx += '\nRecent OpenHands conversations (via dispatcher):\n';
  try {
    if (ohDB) {
      var cur = ohDB.prepare("SELECT conversation_id, title, created_at FROM conversation_metadata WHERE user_id = 'dispatcher' ORDER BY created_at DESC LIMIT 10").all();
      for (var i = 0; i < cur.length; i++) {
        var c = cur[i];
        var cid = Array.isArray(c) ? c[0] : c.conversation_id;
        var ctitle = Array.isArray(c) ? c[1] : c.title;
        var ccreated = Array.isArray(c) ? c[2] : c.created_at;
        ctx += '  ' + (i+1) + '. ' + (ctitle||'(untitled)').slice(0,60) + ' | ' + (ccreated||'') + ' | ' + OPENHANDS_PUBLIC_URL + '/conversations/' + cid + '\n';
      }
    }
  } catch(e) { ctx += '  (DB unavailable)\n'; }
  
  ctx += '\n[/SYSTEM CONTEXT]\n\n';
  return ctx;
}

const sessions = new Map();
let inFlight = 0;

// load sessions on startup + auto-save every 60 seconds
loadSessions(sessions);
var saveInterval = setInterval(function() { saveSessions(sessions); saveSchedules(); runScheduleTick(); }, 60000);
if (saveInterval.unref) saveInterval.unref();

// ── Telegram helpers → imported from ./lib/telegram.js ───────────────
// telegramSendMessage, telegramSendPhoto, telegramForwardSessionImages,
// telegramCacheImageForOpenHands, telegramSetWebhook are all imported.

// ── Dispatcher Agent: Autonomous Reasoning Layer ─────────────────────
// needsOpenHands, querySessionData → imported from ./lib/dispatcher-core.js

// ── Session Context Builder ─────────────────────────────────────────
async function dispatcherLLM(userMessage, sessionContext, userId, imageUrls) {
  if (!DISPATCHER_LLM_ENABLED) return null;
  try {
    var messages = [
      { role: 'system', content: DISPATCHER_SYSTEM_PROMPT },
      { role: 'system', content: sessionContext }
    ];
    // If user is asking about sessions/conversations, inject live data
    var q = (userMessage || '').toLowerCase();
    if (/session|conversation|history|what did|what happened|summarize|list.*conv|show.*conv|recent|last.*task/i.test(q)) {
      var sessionData = querySessionData(ohDB, OH_STATE_PATH, OPENHANDS_PUBLIC_URL, userMessage);
      if (sessionData) messages.push({ role: 'system', content: 'OPENHANDS SESSION DATA:\n' + sessionData });
    }
    // If user references an issue number, inject issue details
    var issueRef = userMessage.match(/#(\d+)/);
    if (issueRef && issuesDb) {
      try {
        var refIssue = issuesDb.prepare('SELECT * FROM issues WHERE number = ?').get(parseInt(issueRef[1]));
        if (refIssue) {
          var issueJson = issueToJSON(refIssue);
          var issueCtx = 'REFERENCED ISSUE #' + issueJson.number + ':\n';
          issueCtx += 'Title: ' + issueJson.title + '\n';
          issueCtx += 'Status: ' + issueJson.status + ' | Priority: ' + issueJson.priority + '\n';
          if (issueJson.description) issueCtx += 'Description: ' + issueJson.description.slice(0, 500) + '\n';
          if (issueJson.labels.length > 0) issueCtx += 'Labels: ' + issueJson.labels.join(', ') + '\n';
          var issueComments = issuesDb.prepare('SELECT * FROM comments WHERE issue_id = ? ORDER BY created_at ASC LIMIT 10').all(refIssue.id);
          if (issueComments.length > 0) {
            issueCtx += 'Comments:\n';
            issueComments.forEach(function(c) { issueCtx += '  - ' + c.author + ': ' + c.body.slice(0, 200) + '\n'; });
          }
          messages.push({ role: 'system', content: issueCtx });
        }
      } catch(e) {}
    }
    // Include last few conversation turns for continuity
    var sess = sessions.get(userId);
    if (sess && sess.history && sess.history.length > 0) {
      for (var hi = Math.max(0, sess.history.length - 6); hi < sess.history.length; hi++) {
        messages.push(sess.history[hi]);
      }
    }
    // Build user message with optional image URLs (DeepSeek uses markdown for vision)
    var userMsgText = userMessage;
    if (imageUrls && imageUrls.length > 0) {
      for (var ii = 0; ii < imageUrls.length; ii++) {
        userMsgText += '\n\n![image](' + imageUrls[ii] + ')';
      }
    }
    messages.push({ role: 'user', content: userMsgText });
    
    var res = await fetch(DISPATCHER_LLM_URL + '/v1/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'authorization': 'Bearer ' + DISPATCHER_LLM_KEY },
      body: JSON.stringify({ model: DISPATCHER_LLM_MODEL, messages: messages, max_tokens: 1200, temperature: 0.3 }),
      signal: AbortSignal.timeout(20000)
    });
    if (!res.ok) return null;
    var data = await res.json();
    var content = data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content;
    return content || null;
  } catch(e) { return null; }
}

// Vision-only call — uses Gemini when available (superior image analysis), DeepSeek fallback
async function dispatcherVision(imageUrls, userMessage) {
  if (!VISION_MODEL_KEY || !imageUrls || imageUrls.length === 0) return null;
  try {
    var userMsg = userMessage || 'Describe what you see in this image in detail.';
    
    if (GEMINI_LLM_KEY) {
      // Gemini REST API: inlineData with base64 (camelCase per Google API spec)
      var parts = [{ text: userMsg }];
      for (var ii = 0; ii < imageUrls.length; ii++) {
        var mimeType = 'image/jpeg';
        var url = imageUrls[ii];
        if (url.endsWith('.png')) mimeType = 'image/png';
        else if (url.endsWith('.gif')) mimeType = 'image/gif';
        else if (url.endsWith('.webp')) mimeType = 'image/webp';
        parts.push({
          inlineData: { mimeType: mimeType, data: await imageUrlToBase64(url) }
        });
      }
      var res = await fetch(`${GEMINI_LLM_URL}/models/${VISION_MODEL}:generateContent?key=${GEMINI_LLM_KEY}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          contents: [{ role: 'user', parts: parts }],
          generationConfig: { maxOutputTokens: 800, temperature: 0.2 }
        }),
        signal: AbortSignal.timeout(30000)
      });
      if (!res.ok) return null;
      var data = await res.json();
      return data.candidates && data.candidates[0] && data.candidates[0].content &&
        data.candidates[0].content.parts && data.candidates[0].content.parts[0].text || null;
    }
    
    // DeepSeek fallback (markdown image format)
    for (var di = 0; di < imageUrls.length; di++) {
      userMsg += '\n\n![image](' + imageUrls[di] + ')';
    }
    var res = await fetch(DISPATCHER_LLM_URL + '/v1/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'authorization': 'Bearer ' + DISPATCHER_LLM_KEY },
      body: JSON.stringify({
        model: DISPATCHER_LLM_MODEL,
        messages: [{ role: 'user', content: userMsg }],
        max_tokens: 800,
        temperature: 0.2
      }),
      signal: AbortSignal.timeout(20000)
    });
    if (!res.ok) return null;
    var data = await res.json();
    return data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content || null;
  } catch(e) { console.error('[vision] error:', e.message); return null; }
}

// Helper: download image URL and convert to base64 (for Gemini vision)
async function imageUrlToBase64(url) {
  try {
    var r = await fetch(url, { signal: AbortSignal.timeout(15000) });
    if (!r.ok) return '';
    var buf = Buffer.from(await r.arrayBuffer());
    return buf.toString('base64');
  } catch(e) { return ''; }
}

// Delegate to OpenHands — spawns task, monitors live, propagates events
async function dispatchToOpenHands(chatId, message, model, imageUrls, sess) {
  const userId = 'tg-' + chatId;
  const startTime = Date.now();
  var resolvedModel = resolveModel(model);
  const turn = sess.turnCount;
  const hasMedia = imageUrls && imageUrls.length > 0;
  const mediaInfo = hasMedia ? '\n' + imageUrls.length + ' image(s) attached' : '';
  
  const sessionCtx = buildSessionContext(userId);
  const fullMessage = sessionCtx + message;
  
  // ── Step 1: Create OpenHands task ──
  const task = await ohCreateTask(fullMessage, resolveLiteLLMModel(resolvedModel), imageUrls);
  
  // ── Step 2: Wait for sandbox readiness ──
  const ready = await ohPollTask(task.id, 120000);
  const convId = ready.app_conversation_id;
  sess.ohConvId = convId;
  ohEnsureConversation(userId, message, convId, resolvedModel);
  ohWriteEvent(convId, { type: 'user_message', key: 'message', value: message });
  if (hasMedia) ohWriteEvent(convId, { type: 'user_media', key: 'images', value: imageUrls });
  ohUpdateTimestamp(convId);
  
  const convUrl = '' + DISPATCH_PUBLIC_URL + '/chat?uid=' + userId;
  
  // ── Step 3: Poll for agent response with rich events ──
  var responseText = null;
  var monitorEvents = [];
  
  await ohPollResponseWithTelegram(convId, RESPONSE_POLL_MAX_MS, chatId, function(event) {
    monitorEvents.push(event);
    // Events are sent via the callback; Telegram dispatch handles the UI
  });
  
  // Get final response from the polling result
  responseText = await ohPollResponse(convId, 5000); // quick final check
  
  var dur = Math.round((Date.now() - startTime) / 100) / 10;
  console.log('[agent] OpenHands done: ' + dur + 's conv=' + convId.slice(0,8));
  
  return {
    type: 'openhands',
    text: responseText,
    conversationUrl: convUrl,
    conversationId: convId,
    turn: turn,
    durationS: dur,
    model: resolvedModel,
    eventCount: monitorEvents.length
  };
}

// Main dispatcher agent entry point — routes to direct answer or OpenHands
async function dispatchAgent(chatId, message, model, imageUrls) {
  var hasMedia = imageUrls && imageUrls.length > 0;
  var resolvedModel = resolveModel(model);
  var userId = 'tg-' + chatId;
  var sess = sessions.get(userId);
  if (!sess) { sess = { lastActiveAt: Date.now(), model: resolvedModel, turnCount: 0, ohConvId: null, history: [] }; sessions.set(userId, sess); }
  
  // ── Try direct answer first ──
  if (!needsOpenHands(message, hasMedia) && DISPATCHER_LLM_ENABLED) {
    var ctx = buildSessionContext(userId);
    var directAnswer = await dispatcherLLM(message, ctx, userId, imageUrls);
    if (directAnswer && !directAnswer.includes('<<USE_OPENHANDS>>')) {
      // Record in history
      sess.history.push({ role: 'user', content: message });
      sess.history.push({ role: 'assistant', content: directAnswer });
      sess.turnCount++;
      sess.lastActiveAt = Date.now();
      console.log('[agent] direct answer (' + directAnswer.length + ' chars) for chatId=' + chatId);
      return { type: 'direct', text: directAnswer, turn: sess.turnCount };
    }
    // LLM said to use OpenHands — fall through
    if (directAnswer && directAnswer.includes('<<USE_OPENHANDS>>')) {
      var instruction = directAnswer.replace(/<<USE_OPENHANDS>>/g, '').trim();
      message = instruction || message;
      console.log('[agent] LLM routed to OpenHands: ' + message.slice(0, 80));
    }
  }
  
  // ── Delegate to OpenHands with rich monitoring ──
  var result = await dispatchToOpenHands(chatId, message, model, imageUrls, sess);
  if (result && result.text) {
    sess.history.push({ role: 'user', content: message });
    sess.history.push({ role: 'assistant', content: result.text });
  }
  return result;
}

// ── Rich status builder for Telegram (text-only, no emojis) ──────────
function rtLine(turn, model, phase, detail, extra, dur) {
  var s = '[' + phase + '] Turn ' + turn + ' · ' + model;
  if (detail) s += '\n' + detail;
  if (extra) s += '\n' + extra;
  if (dur !== undefined) s += '\n' + dur + 's';
  return s;
}

// Telegram dispatch — FULL transparency into every decision and step
async function dispatchForTelegram(chatId, message, model, imageUrls, replyToMsgId) {
  var statusMsgId = null;
  var replyOpts = replyToMsgId ? { replyToMsgId: replyToMsgId } : {};
  var ts = function(text) { return telegramSendMessage(chatId, text, replyOpts); };
  
  // Helper: edit the runtime message (Message 1)
  var rt = function(text) {
    if (!statusMsgId) return Promise.resolve();
    var opts = { editMsgId: statusMsgId, parse_mode: 'HTML' };
    return telegramSendMessage(chatId, text, opts);
  };
  
  // Helper: send final response (Message 2) with session link
  var respond = async function(text, convUrl) {
    var full = text;
    if (convUrl) full += '\n\n[link] <a href="' + convUrl + '">View session</a>';
    return ts(full);
  };
  
  const userId = 'tg-' + chatId;
  const startTime = Date.now();
  var resolvedModel = resolveModel(model);
  var turn, sess;
  
  // ── Ensure session exists ──
  {
    let s = sessions.get(userId);
    if (!s) { s = { lastActiveAt: startTime, model: resolvedModel, turnCount: 0, ohConvId: null, history: [] }; sessions.set(userId, s); }
    s.lastActiveAt = startTime;
    if (model) s.model = resolvedModel;
    s.turnCount++;
    turn = s.turnCount;
    sess = s;
  }
  
  var hasMedia = imageUrls && imageUrls.length > 0;
  var mediaInfo = hasMedia ? ' ×' + imageUrls.length : '';
  var shortMsg = message.length > 80 ? message.slice(0, 77) + '...' : message;
  
  // ═══════════════════════════════════════════════════════════════
  // STEP 0: Check for system commands (handle directly, no AI)
  // ═══════════════════════════════════════════════════════════════
  var cmdResult = handleSystemCommand(message, chatId);
  if (cmdResult) {
    // Handle obsidian-brain delegation → route to OpenHands with brain context
    if (cmdResult.type === 'obsidian-delegate') {
      var brainMessage = buildObsidianBrainPrompt(cmdResult.command);
      console.log('[obsidian-brain] delegating to OpenHands: ' + cmdResult.command.slice(0, 80));
      // Bypass the direct answer path — force route to OpenHands
      message = brainMessage;
      // Fall through to normal OpenHands dispatch below
    } else {
      sess.history.push({ role: 'user', content: message });
      sess.history.push({ role: 'assistant', content: cmdResult.text });
      await ts(cmdResult.text);
      console.log('[telegram] system command: ' + message.slice(0,30) + ' → answered directly');
      return;
    }
  }
  
  // ═══════════════════════════════════════════════════════════════
  // STEP 1: Single runtime status message (edited throughout)
  // ═══════════════════════════════════════════════════════════════
  var queuePos = (sess.queue && sess.queue.length > 0) ? ' (#'
    + sess.queue.length + ' in queue)' : '';
  try {
    var initRes = await fetch(`${TELEGRAM_API}/sendMessage`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, text: '[work] <b>Turn ' + turn + '</b> · ' + resolvedModel + '\n' + shortMsg.replace(/</g,'&lt;').replace(/>/g,'&gt;') + mediaInfo + queuePos + '\nThinking...', parse_mode: 'HTML' }),
      signal: AbortSignal.timeout(30000)
    });
    var initData = await initRes.json();
    if (initData.ok && initData.result) statusMsgId = initData.result.message_id;
  } catch(e) { /* continue without status editing */ }

  // Helper: edit the runtime message (throttled — max 1 edit per 800ms)
  var rtPending = null, rtLastFlush = 0, rtTimer = null;
  var rt = function(text) {
    if (!statusMsgId) return Promise.resolve();
    rtPending = text;
    var now = Date.now();
    var since = now - rtLastFlush;
    if (since >= 800) {
      rtLastFlush = now;
      var t = rtPending; rtPending = null;
      return telegramSendMessage(chatId, t, { editMsgId: statusMsgId, parse_mode: 'HTML' });
    }
    if (!rtTimer) {
      rtTimer = setTimeout(function() {
        rtTimer = null;
        var t = rtPending; rtPending = null;
        if (t) { rtLastFlush = Date.now(); telegramSendMessage(chatId, t, { editMsgId: statusMsgId, parse_mode: 'HTML' }).catch(function(){}); }
      }, 800 - since);
    }
    return Promise.resolve();
  };
  
  // Helper: send final response (Message 2) — links to actual OpenHands session
  var respond = async function(text, convId, openhandsUrl) {
    var full = text;
    if (convId && openhandsUrl) full += '\n\n[link] <a href="' + openhandsUrl + '/conversations/' + convId + '">View session</a>';
    return ts(full);
  };

  // ═══════════════════════════════════════════════════════════════
  // MAIN TRY BLOCK — all operations + error propagation
  // ═══════════════════════════════════════════════════════════════
  try {
    var stepStart = Date.now();
    var eventStats = { tools: 0, reasoning: 0, lifecycle: 0, total: 0, lastTool: '', lastReasoning: '' };
    var responseSent = false;
    var pollError = null;
    
    // ═══════════════════════════════════════════════════════════
    // STEP 1: Intent Classification
    // ═══════════════════════════════════════════════════════════
    var needsOH = needsOpenHands(message, hasMedia);
    var reason = '';
    
    if (hasMedia) {
      if (needsOH) reason = 'Complex image task -> routing to OpenHands';
      else reason = 'Image attached -> trying dispatcher vision';
    } else if (/code|program|script|function|class |import |export |const |let |var |def |async |await/i.test(message)) reason = 'Code-related request -> routing to OpenHands';
    else if (/npm |pip |install|git |commit|push|pull|merge/i.test(message)) reason = 'Dev operations -> routing to OpenHands';
    else if (/file|create|edit|write|read|delete|remove|mkdir/i.test(message)) reason = 'File operations -> routing to OpenHands';
    else if (/browse|navigate|go to|visit|open .*url|http|www\\.|website/i.test(message)) reason = 'Web browsing -> routing to OpenHands';
    else if (/analyze|audit|review|scan|inspect|debug|fix|implement|refactor/i.test(message)) reason = 'Analysis/debugging -> routing to OpenHands';
    else if (/^run[\\s:]|execute|compile|build|deploy|test\\b/i.test(message)) reason = 'Execution task -> routing to OpenHands';
    else reason = 'General question -> trying direct answer first';
    
    var classDur = Math.round((Date.now() - stepStart) / 100) / 10;
    await rt(rtLine(turn, resolvedModel, needsOH ? 'task' : 'think',
      'Decision: ' + (needsOH ? 'Use OpenHands' : 'Answer directly'),
      reason,
      classDur));
    stepStart = Date.now();

    // ═══════════════════════════════════════════════════════════
    // STEP 2: Try Direct Answer (skip if needs OpenHands)
    // ═══════════════════════════════════════════════════════════
    if (!needsOH && DISPATCHER_LLM_ENABLED) {
      // Show thinking indicator
          await rt(rtLine(turn, resolvedModel, 'think',
            'Thinking...',
            sess.history.length + ' prior messages' + (hasMedia ? ' + ' + imageUrls.length + ' image(s)' : ''),
            null, null,
        Math.round((Date.now() - startTime) / 100) / 10));
      
      var llmStart = Date.now();
      var ctx = buildSessionContext(userId);
      // Use Gemini vision for pure image description, dispatcherLLM for everything else
      var useVision = hasMedia && !/code|program|script|function|run |execute|compile|build|deploy|test\b|browse|navigate|go to|visit|http|www\.|website|file|create|edit|write|read|delete|remove|mkdir|implement|refactor|fix|debug|analyze|audit|review|scan|inspect/i.test(message);
      var directAnswer;
      if (useVision && GEMINI_LLM_KEY) {
        // Pure image description → use Gemini vision
        await rt(rtLine(turn, resolvedModel, 'vision',
          'Analyzing with Gemini vision...',
          imageUrls.length + ' image(s)',
          null, null,
          Math.round((Date.now() - startTime) / 100) / 10));
        directAnswer = await dispatcherVision(imageUrls, message);
        resolvedModel = 'Gemini 2.5 Flash'; // Update model name for log
      } else {
        directAnswer = await dispatcherLLM(message, ctx, userId, imageUrls);
      }
      var llmDur = Math.round((Date.now() - llmStart) / 100) / 10;
      
      if (directAnswer && !directAnswer.includes('<<USE_OPENHANDS>>')) {
        // ── DIRECT ANSWER PATH ──
        sess.history.push({ role: 'user', content: message });
        sess.history.push({ role: 'assistant', content: directAnswer });
        
        await rt(rtLine(turn, resolvedModel, 'done',
          'Done in ' + llmDur + 's',
          null,
          null, null,
          Math.round((Date.now() - startTime) / 100) / 10));
        
        // Send the answer with pagination markers
        var chunks = [];
        for (var ci = 0; ci < directAnswer.length; ci += 3900) chunks.push(directAnswer.slice(ci, ci + 3900));
        for (var ci2 = 0; ci2 < chunks.length; ci2++) {
          var marker = chunks.length > 1 ? '(' + (ci2+1) + '/' + chunks.length + ') ' : '';
          await ts(marker + chunks[ci2].trim());
        }
        
        var totalDur = Math.round((Date.now() - startTime) / 100) / 10;
        console.log('[telegram] direct: ' + totalDur + 's chatId=' + chatId + ' turn=' + turn + ' llm=' + llmDur + 's len=' + directAnswer.length);
        responseSent = true;
        
        // Auto-detect bug reports — append issue link to last message, don't send separately
        if (hasMedia && issuesDb && /bug|error|issue|broken|not working|doesn.t work|problem|fail|crash/i.test(message)) {
          try {
            var autoId = randomUUID();
            var autoNow = new Date().toISOString();
            var autoIssueNum = nextIssueNumber();
            issuesDb.prepare('INSERT INTO issues (id,number,title,description,status,priority,labels,reporter,image_urls,conversation_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)').run(
              autoId, autoIssueNum, message.slice(0, 120), directAnswer.slice(0, 500), 'open', 'medium',
              JSON.stringify(['bug', 'auto-detected']), 'tg-' + chatId,
              JSON.stringify(imageUrls || []), '', autoNow, autoNow
            );
            // Append to the last sent message chunk (edit it) or send as inline footer
            var lastChunk = chunks[chunks.length - 1];
            if (lastChunk && statusMsgId) {
              telegramSendMessage(chatId, '\n\n[bug] Auto-tracked as issue #' + autoIssueNum + ' | <a href="' + DISPATCH_PUBLIC_URL + '/issues-ui">View issues</a>', { parse_mode: 'HTML' }).catch(function(){});
            }
            console.log('[issues] auto-created #' + autoIssueNum + ' from bug report');
          } catch(e) { console.error('[issues] auto-create failed:', e.message); }
        }
        
        return;
      }
      
      if (directAnswer && directAnswer.includes('<<USE_OPENHANDS>>')) {
        message = directAnswer.replace(/<<USE_OPENHANDS>>/g, '').trim() || message;
        // Show a detailed plan before routing to OpenHands
      var redirectSteps = [];
      redirectSteps.push('Start AI agent sandbox');
      redirectSteps.push('Execute the task in the agent environment');
      redirectSteps.push('Monitor progress and forward results');
      redirectSteps.push('[done] Return final answer');
      var redirectPlan = '<b>Plan (' + redirectSteps.length + ' steps):</b>\n';
      for (var rsi = 0; rsi < redirectSteps.length; rsi++) {
        redirectPlan += '  ' + (rsi+1) + '. ' + redirectSteps[rsi] + '\n';
      }
      await rt(redirectPlan);
        console.log('[agent] LLM routed to OpenHands: ' + message.slice(0, 80));
      } else {
        // LLM call failed — fall through to OpenHands
        await rt(rtLine(turn, resolvedModel, 'warn',
          'Dispatcher LLM unavailable (took ' + llmDur + 's)',
          'Falling back to OpenHands AI agent',
          null, null,
          Math.round((Date.now() - startTime) / 100) / 10));
      }
    } else if (needsOH) {
      // Show a clear plan before launching OpenHands
      var planSteps = [];
      planSteps.push('Start AI agent sandbox');
      if (hasMedia) planSteps.push('Analyze ' + imageUrls.length + ' image(s)');
      if (/browse|navigate|go to|visit|http|www\./i.test(message)) planSteps.push('Open browser and navigate');
      if (/code|program|script|function|run |execute|compile|build/i.test(message)) planSteps.push('Execute code/commands');
      if (/file|create|edit|write|read|mkdir/i.test(message)) planSteps.push('Perform file operations');
      planSteps.push('[done] Return results to you');
      
      var planText = '<b>Plan (' + planSteps.length + ' steps):</b>\n';
      for (var psi = 0; psi < planSteps.length; psi++) {
        planText += '  ' + (psi+1) + '. ' + planSteps[psi] + '\n';
      }
      await rt(planText);
      await rt(rtLine(turn, resolvedModel, 'task',
        'Spinning up agent environment...',
        'Task: ' + (message.length > 80 ? message.slice(0,77)+'...' : message),
        null, null,
        Math.round((Date.now() - startTime) / 100) / 10));
    }

    // ═══════════════════════════════════════════════════════════
    // STEP 3: OpenHands Task Creation
    // ═══════════════════════════════════════════════════════════
    stepStart = Date.now();
    // ── Auto-select Gemini for media-heavy OpenHands tasks ──
    var ohModel = resolvedModel;
    if (hasMedia && PROFILE_TO_LITELLM['Gemini 2.5 Flash']) {
      ohModel = 'Gemini 2.5 Flash';
      await rt(rtLine(turn, ohModel, 'vision',
        'Using Gemini for media task...',
        'Model: ' + resolveLiteLLMModel(ohModel),
        imageUrls.length + ' image(s) to process',
        null, Math.round((Date.now() - startTime) / 100) / 10));
    }
    
    await rt(rtLine(turn, ohModel, 'create',
      'Creating task in OpenHands...',
      'Model: ' + resolveLiteLLMModel(ohModel),
      'Message: ' + (message.length > 60 ? message.slice(0,57)+'...' : message),
      null, Math.round((Date.now() - startTime) / 100) / 10));
    
    const fullMessage = buildSessionContext(userId) + message;
    
    // ── Inject browser screenshot instructions when browsing ──
    var isBrowseRequest = /browse|navigate|go to|visit|open .*url|http|www\.|website|screenshot|web page|scrape|crawl|google|search|research/i.test(message);
    var finalMessage = fullMessage;
    if (isBrowseRequest && !message.includes('browser_get_state')) {
      finalMessage = fullMessage + '\n\n[BROWSER INSTRUCTION: When navigating to URLs, always use browser_get_state to capture a screenshot after navigation. Do NOT use browser_get_content alone — always get the visual state with browser_get_state. This ensures the user can see the browser view.]';
    }
    
    // ── Inject deployment context for deploy/clone/setup tasks ──
    var isDeployRequest = /deploy|clone|setup|create.*service|add.*docker|configure.*traefik|add.*route|publish|serve.*static|nginx/i.test(message);
    if (isDeployRequest) {
      finalMessage += '\n\n[DEPLOYMENT CONTEXT — This is a production Docker Compose + Traefik deployment on a Debian Linux host.]';
      finalMessage += '\n\nHOW TO DEPLOY A NEW SERVICE HERE:';
      finalMessage += '\n1. Create a service directory under /workspace/project/ with a docker-compose.yml';
      finalMessage += '\n2. The docker-compose.yml must define the service with proper Traefik labels:';
      finalMessage += '\n   - "traefik.enable=true"';
      finalMessage += '\n   - "traefik.http.routers.NAME.rule=Host(\\`SUBDOMAIN.' + DEPLOYMENT_DOMAIN + '\\`)"';
      finalMessage += '\n   - "traefik.http.routers.NAME.entrypoints=websecure"';
      finalMessage += '\n   - "traefik.http.routers.NAME.tls.certresolver=myresolver"';
      finalMessage += '\n   - "traefik.http.services.NAME.loadbalancer.server.port=80"';
      finalMessage += '\n3. CRITICAL: For volume mounts in docker-compose.yml, use HOST paths not sandbox paths.';
      finalMessage += '\n   /workspace/project/ maps to /root/deployment-hacohen/ on the Docker host.';
      finalMessage += '\n   Example: volumes: ["/root/deployment-hacohen/YOUR_DIR:/usr/share/nginx/html:ro"]';
      finalMessage += '\n4. The root /workspace/project/compose.yml includes all sub-project compose files via the `include` directive. Add yours:';
      finalMessage += '\n   `  - ./YOUR_DIR/docker-compose.yml`';
      finalMessage += '\n5. After adding: run `cd /workspace/project && docker compose up -d YOUR_SERVICE` to deploy.';
      finalMessage += '\n6. Traefik will automatically detect the new service and provision SSL via Let\'s Encrypt.';
      finalMessage += '\n7. After deployment, verify by curling the URL or checking docker ps.';
    }
    var task, taskErr;
    try {
      task = await ohCreateTask(finalMessage, resolveLiteLLMModel(ohModel), imageUrls);
    } catch(te) {
      taskErr = te;
    }
    
    if (taskErr) {
      var apiDur = Math.round((Date.now() - stepStart) / 100) / 10;
      throw new Error('OpenHands API error after ' + apiDur + 's: ' + (taskErr.message || 'Unknown'));
    }
    
    var createDur = Math.round((Date.now() - stepStart) / 100) / 10;
    await rt(rtLine(turn, resolvedModel, 'wait',
      'Task created: ' + task.id.slice(0,8) + ' (' + createDur + 's)',
      'Waiting for sandbox environment...',
      hasMedia ? imageUrls.length + ' image(s) will be processed' : null,
      null, Math.round((Date.now() - startTime) / 100) / 10));
    
    // ═══════════════════════════════════════════════════════════
    // STEP 4: Sandbox Readiness Polling
    // ═══════════════════════════════════════════════════════════
    stepStart = Date.now();
    var ready, pollErr;
    try {
      ready = await ohPollTaskWithTelegram(task.id, 120000, function(status, elapsed) {
        var icon = status === 'WORKING' ? 'task' : status === 'WAITING_FOR_SANDBOX' ? 'wait' : 
                   status === 'SETTING_UP_SKILLS' ? 'setup' : status === 'STARTING_CONVERSATION' ? 'think' : 'lifecycle';
        var humanStatus = status.replace(/_/g, ' ').toLowerCase();
        rt(rtLine(turn, resolvedModel, icon,
          humanStatus + ' (' + elapsed + 's)',
          'Task: ' + task.id.slice(0,8),
          null, null,
          Math.round((Date.now() - startTime) / 100) / 10), true).catch(function(){});
      });
    } catch(pe) { pollErr = pe; }
    
    if (pollErr) {
      var pollDur = Math.round((Date.now() - stepStart) / 100) / 10;
      throw new Error('Sandbox startup failed after ' + pollDur + 's: ' + (pollErr.message || 'Unknown'));
    }
    
    var sandboxDur = Math.round((Date.now() - stepStart) / 100) / 10;
    var convId = ready.app_conversation_id;
    sess.ohConvId = convId;
    
    // Record in DB
    ohEnsureConversation(userId, message, convId, resolvedModel);
    ohWriteEvent(convId, { type: 'user_message', key: 'message', value: message });
    if (hasMedia) ohWriteEvent(convId, { type: 'user_media', key: 'images', value: imageUrls });
    
    var convUrl = '[link] <a href="' + OPENHANDS_PUBLIC_URL + '/conversations/' + convId + '">View session</a>';
    ohUpdateTimestamp(convId);
    
    await rt(rtLine(turn, resolvedModel, 'think',
      'Sandbox ready! (' + sandboxDur + 's)',
      'AI agent is now working on your request...',
      'Session: ' + convId.slice(0,8),
      convUrl, Math.round((Date.now() - startTime) / 100) / 10));
    
    // ═══════════════════════════════════════════════════════════
    // STEP 5: Live Event Monitoring + Guaranteed Final Message
    // ═══════════════════════════════════════════════════════════
    stepStart = Date.now();
    eventStats = { tools: 0, reasoning: 0, lifecycle: 0, total: 0, lastTool: '', lastReasoning: '' };
    responseSent = false;
    pollError = null;
    var pollResponse = null;
    
    // ── Inner try: polling + response delivery ──
    try {
      pollResponse = await ohPollResponseWithTelegram(convId, RESPONSE_POLL_MAX_MS, chatId, async function(event) {
        eventStats.total++;
        
        if (event.type === 'reasoning') {
          eventStats.reasoning++;
          rt(rtLine(turn, resolvedModel, 'reason',
            'Thinking: <i>' + (event.brief || '...') + '</i>',
            eventStats.tools > 0 ? 'Tools used: ' + eventStats.tools : null,
            null, convUrl, Math.round((Date.now() - startTime) / 100) / 10), true).catch(function(){});
        } else if (event.type === 'tool') {
          eventStats.tools++;
          eventStats.lastTool = event.tool;
          var toolMsg = event.icon + ' <b>' + event.tool + '</b>';
          if (event.summary) toolMsg += '\n' + (event.summary.length > 250 ? event.summary.slice(0,247)+'...' : event.summary);
          rt(rtLine(turn, resolvedModel, 'task',
            'Executing: ' + event.tool,
            'Tools: ' + eventStats.tools + ' | Events: ' + eventStats.total,
            null, convUrl, Math.round((Date.now() - startTime) / 100) / 10), true).catch(function(){});
        } else if (event.type === 'activity') {
          rt(rtLine(turn, resolvedModel, 'progress',
            (event.summary || 'Working...'),
            'Tools: ' + eventStats.tools + ' | Reasoning: ' + eventStats.reasoning + ' | Events: ' + eventStats.total,
            null, convUrl, Math.round((Date.now() - startTime) / 100) / 10), true).catch(function(){});
        } else if (event.type === 'lifecycle') {
          eventStats.lifecycle++;
          var lcIcon = event.status === 'running' ? 'lifecycle' : event.status === 'finished' ? 'done' : 'lifecycle';
          rt(rtLine(turn, resolvedModel, lcIcon,
            'Agent status: ' + (event.status || 'working'),
            'Tools: ' + eventStats.tools + ' | Events: ' + eventStats.total,
            null, convUrl, Math.round((Date.now() - startTime) / 100) / 10), true).catch(function(){});
        } else if (event.type === 'thinking') {
          rt(rtLine(turn, resolvedModel, 'agent',
            'AI processing... (' + event.count + ' events)',
            eventStats.tools > 0 ? 'Tools: ' + eventStats.tools : null,
            null, convUrl, Math.round((Date.now() - startTime) / 100) / 10), true).catch(function(){});
        } else if (event.type === 'response') {
          var txt = event.text;
          if (txt && txt.trim()) {
            responseSent = true;
            var chunks = [];
            for (var ci = 0; ci < txt.length; ci += 3900) chunks.push(txt.slice(ci, ci + 3900));
            for (var ci2 = 0; ci2 < chunks.length; ci2++) {
              var marker = chunks.length > 1 ? '(' + (ci2+1) + '/' + chunks.length + ') ' : '';
              await ts(marker + chunks[ci2].trim()).catch(function(){});
            }
          }
          // ── Forward any images (screenshots, charts) created during the session ──
          telegramForwardSessionImages(chatId, convId, statusMsgId).catch(function(){});
          await rt(rtLine(turn, resolvedModel, 'done',
            'Response ready!', null,
            null,
            convUrl, Math.round((Date.now() - startTime) / 100) / 10));
          ohWriteEvent(convId, { type: 'agent_response', message: txt });
          sess.history.push({ role: 'user', content: message });
          sess.history.push({ role: 'assistant', content: txt });
        } else if (event.type === 'error') {
          // ── LLM provider error surfaced from agent ──
          var errTxt = event.text || 'Unknown LLM error';
          var errBrief = errTxt.slice(0, 200).replace(/\n/g, ' ');
          console.error('[telegram] agent LLM error: ' + errBrief);
          var errMsg = '[err] <b>LLM Provider Error</b>\nThe AI model returned an error:\n<pre>' + errBrief.slice(0, 300) + '</pre>\n\n[hint] Use /retry to re-send. If the issue persists, try a different model.';
          // Edit the runtime message to show the error
          await rt(errMsg);
          // Also send as final message
          await ts(errMsg);
          responseSent = true;
          sess.lastFailedMessage = message;
        }
      });
    } catch(pe) {
      pollError = pe;
      console.error('[telegram] poll crashed:', pe.message);
    }
    
    // ── Fallback: if poll returned text but event didn't fire ──
    var totalDur = Math.round((Date.now() - startTime) / 100) / 10;
    if (!responseSent && pollResponse && typeof pollResponse === 'string' && pollResponse.trim()) {
      var chunks = [];
      for (var fci = 0; fci < pollResponse.length; fci += 3900) chunks.push(pollResponse.slice(fci, fci + 3900));
      for (var fci2 = 0; fci2 < chunks.length; fci2++) {
        await ts((fci2 === 0 ? '' : '') + chunks[fci2].trim()).catch(function(){});
      }
      responseSent = true;
      sess.history.push({ role: 'user', content: message });
      sess.history.push({ role: 'assistant', content: pollResponse });
    }
    
    // ── No response received: surface a meaningful error ──
    if (!responseSent) {
      var noRespMsg = '[warn] <b>No response from AI agent</b>\nThe agent started but produced no output after ' + totalDur + 's.\n[hint] This may indicate an LLM backend issue. Use /retry or try a different model.';
      await rt(noRespMsg);
      await ts(noRespMsg);
      responseSent = true;
      sess.lastFailedMessage = message;
      console.error('[telegram] agent produced no response after ' + totalDur + 's, convId=' + convId.slice(0,8));
    }
    
  } catch(e) {
    // ═══════════════════════════════════════════════════════════
    // ERROR PROPAGATION — full context to user
    // ═══════════════════════════════════════════════════════════
    console.error('[telegram] dispatch error:', e.message, e.stack && e.stack.slice(0,300));
    var errDur = Math.round((Date.now() - startTime) / 100) / 10;
    
    var errMsg = e.message || 'Unknown error';
    var errIcon = '[err]';
    var errTitle = 'Error';
    var errDetail = errMsg;
    var errHint = '';
    
    if (errMsg.includes('OpenHands API 5')) {
      errIcon = ''; errTitle = 'OpenHands Unavailable';
      errDetail = 'The AI coding service returned HTTP ' + (errMsg.match(/\d{3}/) || ['500'])[0];
      errHint = 'Try again in a moment or use /retry to re-send.';
    } else if (errMsg.includes('Timeout') || errMsg.includes('timed out')) {
      errIcon = ''; errTitle = 'Request Timed Out';
      errHint = 'Try a shorter request, or use /retry to re-send.';
    } else if (errMsg.includes('Sandbox failed') || errMsg.includes('sandbox')) {
      errIcon = ''; errTitle = 'Sandbox Startup Failed';
      errHint = 'Resource limit. Try again or use /retry.';
    } else if (errMsg.includes('fetch failed') || errMsg.includes('ECONN')) {
      errIcon = '[conn]'; errTitle = 'Connection Error';
      errHint = 'Network issue — use /retry to re-send.';
    }
    
    var fullErr = errIcon + ' <b>Turn ' + turn + '</b> · ' + resolvedModel;
    fullErr += '\n<b>' + errTitle + '</b>';
    fullErr += '\n' + errDetail.slice(0, 500);
    if (errHint) fullErr += '\n[hint] ' + errHint;
    fullErr += '\nFailed after ' + errDur + 's';
    
    rt(fullErr).catch(function(){});
    
    // Store last failed message for /retry
    sess.lastFailedMessage = message;
  } finally {
    var totalDur = Math.round((Date.now() - startTime) / 100) / 10;
    console.log('[telegram] done: ' + totalDur + 's chatId=' + chatId + ' conv=' + (typeof convId !== 'undefined' ? convId.slice(0,8) : 'direct') + ' model=' + resolvedModel + ' turn=' + turn + ' tools=' + eventStats.tools + ' events=' + eventStats.total + ' responseSent=' + responseSent);
    if (!responseSent) sess.lastFailedMessage = message;
  }
}

// ── Task polling with Telegram status callback ──────────────────────
async function ohPollTaskWithTelegram(taskId, maxMs, onStatus) {
  return pollTaskWithCallback(taskId, maxMs, onStatus);
}

// ── Agent event polling with rich Telegram back-propagation ──────
// Reads ALL event files, classifies them, and sends structured updates:
//   reasoning  |  tool calls  |  browser  |  terminal
//   file edits  |  stats  |  lifecycle  |  final response
// Tracks seen events to avoid duplicate reports.
async function ohPollResponseWithTelegram(convId, maxMs, chatId, onEvent) {
  if (!convId) return null;
  const deadline = Date.now() + maxMs;
  var seenFiles = {};          // filename → true (prevents duplicate event reports)
  var lastReportTime = 0;
  var lastStatusEditTime = 0;
  var toolSummary = '';        // accumulated tool activity for status line
  var reasoningPreview = '';   // latest reasoning snippet
  var lastStats = '';          // latest token/cost stats
  const eventsDir = join(OH_STATE_PATH, 'v1_conversations', convId);
  console.log('[oh-poll] rich polling for conv ' + convId.slice(0,8) + ' from disk');
  
  // Helper: format a tool name icon
  function toolIcon(name) {
    var n = (name || '').toLowerCase();
    if (n.includes('browser') || n.includes('browse')) return '';
    if (n.includes('terminal') || n.includes('bash') || n.includes('cmd')) return '';
    if (n.includes('file') || n.includes('editor') || n.includes('write') || n.includes('edit')) return '';
    if (n.includes('think') || n.includes('finish') || n.includes('respond')) return '';
    return '';
  }
  
  // Helper: truncate for status line
  function brief(s, max) { s = (s||'').replace(/\n/g,' ').trim(); return s.length > max ? s.slice(0,max-3)+'...' : s; }
  
  while (Date.now() < deadline) {
    try {
      var files = [];
      try { files = readdirSync(eventsDir).filter(function(f) { return f.endsWith('.json'); }); } catch(e) { files = []; }
      files.sort();
      
      // Process only new files since last check
      var foundResponse = null;
      for (var fi = 0; fi < files.length; fi++) {
        var fname = files[fi];
        if (seenFiles[fname]) continue;
        seenFiles[fname] = true;
        
        try {
          var raw = readFileSync(join(eventsDir, fname), 'utf-8');
          var e = JSON.parse(raw);
          var src = e.source || '';
          
          // ── AGENT reasoning (llm_message with reasoning_content) ──
          if (src === 'agent' && e.llm_message) {
            var lm = e.llm_message;
            // Reasoning / thinking content
            if (lm.reasoning_content && lm.reasoning_content.trim()) {
              reasoningPreview = brief(lm.reasoning_content, 120);
              if (onEvent) onEvent({ type: 'reasoning', text: lm.reasoning_content, brief: reasoningPreview });
            }
            // Final text response (assistant content) — collect but don't return yet
            var content = lm.content;
            if (Array.isArray(content)) {
              var texts = [];
              for (var ci = 0; ci < content.length; ci++) {
                if (content[ci] && content[ci].text) texts.push(content[ci].text);
              }
              var fullText = texts.join('').trim();
              if (fullText && lm.role === 'assistant') {
                // ── Error detection in structured LLM response ──
                var isError = /NotFoundError|APIError|ProviderError|AuthenticationError|RateLimitError|ServiceUnavailableError|DeepseekException|litellm\.\w+Error/i.test(fullText);
                if (isError) {
                  console.error('[oh-poll] agent llm_message contains provider error');
                  foundResponse = null;
                  if (onEvent) onEvent({ type: 'error', text: fullText, errorType: 'llm_provider' });
                } else {
                  console.log('[oh-poll] got agent response (array) len=' + fullText.length);
                  foundResponse = fullText;
                  if (onEvent) onEvent({ type: 'response', text: fullText });
                }
              }
            }
          }
          
          // ── AGENT observation (tool call results from agent events) ──
          if (src === 'agent' && e.observation) {
            var toolName = e.tool_name || e.name || 'tool';
            var obsContent = e.observation.content || e.observation.text || '';
            if (typeof obsContent === 'string' && obsContent.trim()) {
              var icon = toolIcon(toolName);
              var obsBrief = brief(obsContent, 80);
              toolSummary = icon + ' ' + toolName + ': ' + obsBrief;
              if (onEvent) onEvent({ type: 'tool', tool: toolName, icon: icon, summary: obsBrief, detail: obsContent });
            } else if (Array.isArray(obsContent)) {
              var obsTexts = [];
              for (var oi = 0; oi < obsContent.length; oi++) {
                if (obsContent[oi] && obsContent[oi].text) obsTexts.push(obsContent[oi].text);
              }
              var obsFull = obsTexts.join('\n').trim();
              if (obsFull) {
                var icon2 = toolIcon(toolName);
                var obsBrief2 = brief(obsFull, 80);
                toolSummary = icon2 + ' ' + toolName + ': ' + obsBrief2;
                if (onEvent) onEvent({ type: 'tool', tool: toolName, icon: icon2, summary: obsBrief2, detail: obsFull });
              }
            }
          }
          
          // ── ENVIRONMENT events ──
          if (src === 'environment') {
            // Tool observations (browser, terminal, file — stored in environment events)
            if (e.observation && e.tool_name) {
              var toolName = e.tool_name;
              var obsContent = e.observation.content || e.observation.text || '';
              if (typeof obsContent === 'string' && obsContent.trim()) {
                var icon = toolIcon(toolName);
                var obsBrief = brief(obsContent, 120);
                toolSummary = icon + ' ' + toolName + ': ' + obsBrief;
                if (onEvent) onEvent({ type: 'tool', tool: toolName, icon: icon, summary: obsBrief, detail: obsContent });
              } else if (Array.isArray(obsContent)) {
                var obsTexts = [];
                for (var oi = 0; oi < obsContent.length; oi++) {
                  if (obsContent[oi] && obsContent[oi].text) obsTexts.push(obsContent[oi].text);
                }
                var obsFull = obsTexts.join('\n').trim();
                if (obsFull) {
                  var icon2 = toolIcon(toolName);
                  var obsBrief2 = brief(obsFull, 120);
                  toolSummary = icon2 + ' ' + toolName + ': ' + obsBrief2;
                  if (onEvent) onEvent({ type: 'tool', tool: toolName, icon: icon2, summary: obsBrief2, detail: obsFull });
                }
              }
            }
            // Execution status
            if (e.key === 'execution_status' && e.value) {
              if (onEvent) onEvent({ type: 'lifecycle', status: e.value });
            }
            // Stats (token usage, cost)
            if (e.key === 'stats' && e.value) {
              try {
                var st = typeof e.value === 'string' ? JSON.parse(e.value) : e.value;
                var tokens = (st.prompt_tokens||0) + (st.completion_tokens||0);
                var cost = st.accumulated_cost || st.cost || 0;
                lastStats = '' + tokens + ' tokens';
                if (cost > 0) lastStats += ' · $' + (typeof cost === 'number' ? cost.toFixed(4) : cost);
              } catch(se) { lastStats = 'stats updated'; }
            }
          }
          
          // ── Fallback: string content in agent events ──
          if (src === 'agent') {
            var strContent = e.content || e.message || '';
            if (typeof strContent === 'string' && strContent.trim()) {
              console.log('[oh-poll] got agent response len=' + strContent.length);
              // ── Error detection: check if response is an LLM provider error ──
              var isError = /NotFoundError|APIError|ProviderError|AuthenticationError|RateLimitError|ServiceUnavailableError|DeepseekException|litellm\.\w+Error|400\s.*Bad|401\s.*Unauthorized|403\s.*Forbidden|404\s.*Not|429\s.*Rate|500\s.*Internal|502\s.*Bad Gateway|503\s.*Service|504\s.*Gateway/i.test(strContent);
              if (isError) {
                console.error('[oh-poll] agent returned LLM error, propagating');
                foundResponse = null; // Don't treat error as success
                if (onEvent) onEvent({ type: 'error', text: strContent, errorType: 'llm_provider' });
              } else {
                foundResponse = strContent;
                if (onEvent) onEvent({ type: 'response', text: strContent });
              }
            }
          }
          
        } catch(parseErr) { console.error('[oh-poll] parse error:', fname, parseErr.message); }
      }
      
      // If we found a response during this iteration, return it now
      if (foundResponse) return foundResponse;
      
      // ── Send combined status update every 5s ──
      var now = Date.now();
      if (now - lastStatusEditTime > 5000) {
        lastStatusEditTime = now;
        var statusParts = [];
        if (toolSummary) statusParts.push(toolSummary);
        if (reasoningPreview) statusParts.push('' + reasoningPreview);
        if (lastStats) statusParts.push(lastStats);
        if (statusParts.length > 0 && onEvent) {
          onEvent({ type: 'activity', summary: statusParts.join('\n'), fileCount: files.length });
        } else if (files.length > 0 && onEvent) {
          onEvent({ type: 'thinking', count: files.length });
        }
      }
      
    } catch (err) { console.error('[oh-poll] poll iteration error:', err.message); }
    await sleep(RESPONSE_POLL_MS);
  }
  return null;
}

// ── OpenHands DB sync ────────────────────────────────────────────────
let ohDB = null;
let issuesDb = null;

function issueToJSON(row) {
  return {
    id: row.id, number: row.number, title: row.title,
    description: row.description, status: row.status, priority: row.priority,
    labels: JSON.parse(row.labels || '[]'),
    reporter: row.reporter, assignee: row.assignee,
    image_urls: JSON.parse(row.image_urls || '[]'),
    conversation_id: row.conversation_id,
    created_at: row.created_at, updated_at: row.updated_at
  };
}
try {
  ohDB = new DatabaseSync(join(OH_STATE_PATH, 'openhands.db'));
  ohDB.exec('PRAGMA journal_mode=WAL');
  console.log('[oh-sync] connected');
} catch (e) { console.warn('[oh-sync] DB unavailable:', e.message); }

function ohEnsureConversation(userId, message, ohCid, model) {
  if (!ohDB) return;
  var convId = ohCid || 'dispatcher-' + userId;
  try {
    var existing = ohDB.prepare('SELECT conversation_id FROM conversation_metadata WHERE conversation_id = ?').get(convId);
    if (!existing) {
      var now = new Date().toISOString().replace('T', ' ').slice(0, 23);
      var title = (message || 'WhatsApp session').slice(0, 80);
      ohDB.prepare(`INSERT INTO conversation_metadata (conversation_id, user_id, title, created_at, last_updated_at, llm_model, conversation_version, agent_kind, sandbox_id, accumulated_cost, prompt_tokens, completion_tokens, total_tokens, max_budget_per_task, per_turn_token) VALUES (?, 'dispatcher', ?, ?, ?, ?, 'V1', 'dispatcher', 'dispatcher-sandbox', 0, 0, 0, 0, 0, 0)`).run(convId, title, now, now, model || DEFAULT_MODEL);
    }
  } catch (e) {}
}

function ohWriteEvent(convId, data) {
  if (!ohDB || !convId) return;
  try {
    var dir = join(OH_STATE_PATH, 'v1_conversations', convId);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, randomUUID() + '.json'), JSON.stringify(Object.assign({ id: randomUUID(), timestamp: new Date().toISOString(), source: 'dispatcher' }, data)));
  } catch (e) {}
}

function ohUpdateTimestamp(convId) {
  if (!ohDB || !convId) return;
  try { ohDB.prepare('UPDATE conversation_metadata SET last_updated_at = ? WHERE conversation_id = ?').run(new Date().toISOString().replace('T', ' ').slice(0, 23), convId); } catch (e) {}
}

// ── Auth / Util ──────────────────────────────────────────────────────
function auth(req) { const h = req.headers['authorization'] || ''; return h.startsWith('Bearer ') ? h.slice(7) === DISPATCHER_TOKEN : h === DISPATCHER_TOKEN; }
async function readBody(req) { const c = []; for await (const x of req) c.push(x); try { return JSON.parse(Buffer.concat(c).toString()); } catch { return null; } }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

setInterval(() => {
  const now = Date.now(); let swept = 0;
  for (const [uid, s] of sessions) { if (now - s.lastActiveAt > 30 * 60 * 1000) { sessions.delete(uid); swept++; } }
  if (swept > 0) console.log('[sweep] ' + swept + ' sessions');
}, 60 * 1000).unref?.();

// Auto-cleanup dead and old agent sandboxes every 30 minutes
setInterval(() => {
  try {
    var out = execSync(
      'docker ps -a --filter "name=oh-agent-server" --format "{{.Names}}\\t{{.Status}}\\t{{.CreatedAt}}" 2>/dev/null',
      { timeout: 5000, encoding: 'utf-8' }
    ).trim();
    if (!out) return;
    var lines = out.split('\n');
    var removed = 0;
    for (var i = 0; i < lines.length; i++) {
      var parts = lines[i].split('\t');
      var name = parts[0], status = parts[1] || '', createdAt = parts[2] || '';
      var shouldRemove = status.startsWith('Exited') || status.startsWith('Dead');
      if (!shouldRemove) {
        var d = new Date(createdAt);
        if (!isNaN(d.getTime()) && (Date.now() - d.getTime()) > AGENT_MAX_AGE_MS) shouldRemove = true;
      }
      if (shouldRemove) {
        try { execSync('docker rm -f ' + name + ' 2>/dev/null', { timeout: 10000, encoding: 'utf-8' }); removed++; }
        catch (e) { console.error('[auto-clean] rm failed ' + name + ': ' + e.message); }
      }
    }
    if (removed > 0) console.log('[auto-clean] removed ' + removed + ' agent containers');
  } catch (e) { console.error('[auto-clean] error:', e.message); }
}, 30 * 60 * 1000).unref?.();

// ── OpenHands API → imported from ./lib/openhands.js ────────────────
// ohCreateTask, ohPollTask, ohPollResponse are imported.
// Wrappers below add Telegram status callbacks.

// ── Main Dispatch ────────────────────────────────────────────────────
async function streamDispatch(userId, message, model, imageUrls, res) {
  const startTime = Date.now();
  var resolvedModel = resolveModel(model);
  let sess = sessions.get(userId);
  if (!sess) { sess = { lastActiveAt: startTime, model: resolvedModel, turnCount: 0, ohConvId: null }; sessions.set(userId, sess); }
  sess.lastActiveAt = startTime;
  if (model) sess.model = resolvedModel;
  sess.turnCount++;
  const turn = sess.turnCount;
  const hasMedia = imageUrls && imageUrls.length > 0;
  
  // ── Obsidian Brain detection: prepend skill context ──
  var isObsidian = /^\/obsidian-brain\b/i.test(message);
  if (isObsidian) {
    var rest = message.replace(/^\/obsidian-brain\s*/i, '').trim();
    var restLower = rest.toLowerCase();
    // Handle simple commands directly
    var rememberMatch = restLower.match(/^remember\s+(?:that\s+)?(.+)/i);
    if (rememberMatch) {
      var fact = rememberMatch[1].trim();
      var result = vaultRemember(fact);
      var msg = result.error ? '[err] Failed: ' + result.error :
        result.existed ? 'Already known: ' + fact :
        'Remembered: ' + fact;
      res.write(JSON.stringify({ type: 'result', status: 'done', message: msg, turn }) + '\n');
      res.write(JSON.stringify({ type: 'final', durationMs: Date.now() - startTime, turn }) + '\n');
      res.end();
      return;
    }
    var searchMatch = restLower.match(/^search\s+(.+)/i);
    if (searchMatch) {
      var kw = searchMatch[1].trim();
      res.write(JSON.stringify({ type: 'result', status: 'done', message: vaultSearch(kw), turn }) + '\n');
      res.write(JSON.stringify({ type: 'final', durationMs: Date.now() - startTime, turn }) + '\n');
      res.end();
      return;
    }
    // Complex command → prepend brain prompt
    var brainMsg = buildObsidianBrainPrompt(rest || message);
    message = brainMsg;
    console.log('[obsidian-brain] web dispatch: delegating to OpenHands: ' + rest.slice(0, 80));
  }
  
  // Build full message with session context so the AI can answer session questions
  const sessionCtx = buildSessionContext(userId);
  const fullMessage = sessionCtx + message;

  res.write(JSON.stringify({ type: 'start', userId, model: resolvedModel, turn, hasMedia: !!hasMedia }) + '\n');
  let convId = null;
  try {
    const modelMsg = hasMedia ? 
      `Creating session with ${imageUrls.length} image(s) (${resolvedModel})...` :
      `Creating session (${resolvedModel})...`;
    res.write(JSON.stringify({ type: 'status', message: modelMsg, turn }) + '\n');
    const task = await ohCreateTask(fullMessage, resolveLiteLLMModel(resolvedModel), imageUrls);
    res.write(JSON.stringify({ type: 'status', message: 'Starting sandbox environment...', turn }) + '\n');
    const ready = await ohPollTask(task.id, 120000);
    convId = ready.app_conversation_id;
    sess.ohConvId = convId;
    ohEnsureConversation(userId, message, convId, resolvedModel);
    ohWriteEvent(convId, { type: 'user_message', key: 'message', value: message });
    if (hasMedia) ohWriteEvent(convId, { type: 'user_media', key: 'images', value: imageUrls });
    const convUrl = '' + DISPATCH_PUBLIC_URL + '/chat?uid=' + userId;
    res.write(JSON.stringify({ type: 'status', message: 'AI agent is processing your request...', turn }) + '\n');
    res.write(JSON.stringify({ type: 'result', status: 'started', message: '[link] Open your session:', conversationUrl: convUrl, conversationId: convId, turn }) + '\n');
    ohUpdateTimestamp(convId);
    
    ohPollResponse(convId, RESPONSE_POLL_MAX_MS).then(response => {
      if (response) {
        ohWriteEvent(convId, { type: 'agent_response', message: response });
        res.write(JSON.stringify({ type: 'result', status: 'done', message: response, conversationUrl: OPENHANDS_PUBLIC_URL + '/conversations/' + convId, conversationId: convId, turn }) + '\n');
        res.write(JSON.stringify({ type: 'final', durationMs: Date.now() - startTime, turn }) + '\n');
        res.end();
      } else {
        res.write(JSON.stringify({ type: 'error', message: 'Agent produced no response. The LLM may be experiencing issues. Use /retry.', turn }) + '\n');
        res.write(JSON.stringify({ type: 'final', durationMs: Date.now() - startTime, turn }) + '\n');
        res.end();
      }
    }).catch(err => {
      console.error('[dispatch] poll error:', err.message);
      res.write(JSON.stringify({ type: 'error', message: 'Failed to get agent response: ' + err.message.slice(0, 200), turn }) + '\n');
      res.write(JSON.stringify({ type: 'final', durationMs: Date.now() - startTime, turn }) + '\n');
      res.end();
    });
  } catch (e) {
    console.error('[dispatch] error:', e.message);
    var errMsg = e.message;
    if (errMsg.includes('OpenHands API 5')) errMsg = 'OpenHands is temporarily unavailable. Please try again in a moment.';
    else if (errMsg.includes('Timeout')) errMsg = 'Session timed out. The server may be busy. Try a shorter request or try again later.';
    else if (errMsg.includes('Sandbox failed')) errMsg = errMsg;
    else errMsg = errMsg;
    res.write(JSON.stringify({ type: 'error', message: errMsg, turn }) + '\n');
  }
  const dur = Date.now() - startTime;
  console.log('[dispatch] done: ' + dur + 'ms userId=' + userId + (convId ? ' conv=' + convId.slice(0,8) : '') + ' model=' + resolvedModel + (hasMedia ? ' media' : ''));
  res.write(JSON.stringify({ type: 'final', durationMs: dur, turn }) + '\n');
}

// ── Dashboard → imported from ./lib/dashboard.js ──────────────────
// getDashboard() and getIssuesUI() are imported.
// Called in HTTP route handlers below.

// ── HTTP Server ──────────────────────────────────────────────────────
function log(method, path, status, dur, extra) { console.log(`[${new Date().toISOString().slice(11,19)}] ${method} ${path} → ${status} ${dur}ms${extra ? ' ' + extra : ''}`); }

const server = createServer(async (req, res) => {
  const start = Date.now();
  const u = new URL(req.url, 'http://localhost:' + PORT);
  res.setHeader('access-control-allow-origin', '*');
  res.setHeader('access-control-allow-headers', 'authorization, content-type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
  if (u.pathname === '/healthz') { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: true, inFlight, sessions: sessions.size })); return; }

  // ── File proxy for shared downloads (images, documents, etc.) ──
  if (u.pathname.startsWith('/image/') && req.method === 'GET') {
    var imgKey = u.pathname.replace('/image/', '').replace(/\.[a-z]+$/, '');
    // Try in-memory cache first (fast)
    var cached = imageCache.get(imgKey);
    if (cached) {
      res.writeHead(200, { 'content-type': cached.contentType, 'cache-control': 'public, max-age=3600' });
      res.end(cached.data);
      return;
    }
    // Fallback: serve from disk (survives restarts)
    try {
      var files = readdirSync(DOWNLOADS_DIR);
      for (var fi = 0; fi < files.length; fi++) {
        if (files[fi].includes(imgKey) || files[fi].startsWith('tg_')) {
          var fpath = join(DOWNLOADS_DIR, files[fi]);
          var fbuf = readFileSync(fpath);
          var ctype = 'image/jpeg';
          if (files[fi].endsWith('.png')) ctype = 'image/png';
          else if (files[fi].endsWith('.gif')) ctype = 'image/gif';
          else if (files[fi].endsWith('.webp')) ctype = 'image/webp';
          else if (files[fi].endsWith('.mp4')) ctype = 'video/mp4';
          else if (files[fi].endsWith('.pdf')) ctype = 'application/pdf';
          res.writeHead(200, { 'content-type': ctype, 'cache-control': 'public, max-age=3600' });
          res.end(fbuf);
          return;
        }
      }
    } catch(e) {}
    res.writeHead(404); res.end('image not found');
    return;
  }
  
  // ── Downloads file server (direct path access) ──
  if (u.pathname.startsWith('/downloads/') && req.method === 'GET') {
    var fname = u.pathname.replace('/downloads/', '').replace(/\.\./g, '').replace(/[^a-zA-Z0-9_.-]/g, '');
    try {
      var fpath = join(DOWNLOADS_DIR, fname);
      var fbuf = readFileSync(fpath);
      var ctype = 'application/octet-stream';
      if (fname.endsWith('.png')) ctype = 'image/png';
      else if (fname.endsWith('.jpg') || fname.endsWith('.jpeg')) ctype = 'image/jpeg';
      else if (fname.endsWith('.gif')) ctype = 'image/gif';
      else if (fname.endsWith('.webp')) ctype = 'image/webp';
      else if (fname.endsWith('.mp4')) ctype = 'video/mp4';
      else if (fname.endsWith('.pdf')) ctype = 'application/pdf';
      else if (fname.endsWith('.zip')) ctype = 'application/zip';
      res.writeHead(200, { 'content-type': ctype, 'cache-control': 'public, max-age=3600' });
      res.end(fbuf);
    } catch(e) { res.writeHead(404); res.end('file not found'); }
    return;
  }

  // ── Live VNC Browser View ───────────────────────────────────────
  if (u.pathname === '/vnc' && req.method === 'GET') {
    try {
      // Find the agent container and get its VNC port via Docker
      var vncPort = null;
      try {
        var agentCid = execSync("docker ps -q --filter 'name=oh-agent' | head -1", { timeout: 3000 }).toString().trim();
        if (agentCid) {
          var portOutput = execSync('docker port ' + agentCid + ' 8011', { timeout: 3000 }).toString().trim();
          var portMatch = portOutput.match(/:(\d+)/);
          if (portMatch) vncPort = portMatch[1];
        }
      } catch(e) { /* Docker not available from dispatcher — fall back to OpenHands API */ }
      
      // Fallback: try OpenHands sandbox API with known sandbox IDs from sessions
      if (!vncPort) {
        for (const [uid, s] of sessions) {
          if (!s.ohConvId) continue;
          try {
            // Get conversation details to find sandbox_id
            var convRes = await fetch(`${OPENHANDS_URL}/api/v1/app-conversations/start-tasks?ids=&conversation_id=${s.ohConvId}`, { signal: AbortSignal.timeout(3000) });
            // This won't work — try direct sandbox lookup from known IDs
          } catch(e) {}
        }
      }
      
      if (!vncPort) {
        res.writeHead(503, { 'content-type': 'text/html' });
        res.end(`<!DOCTYPE html><html><head><title>VNC - No Agent</title><meta http-equiv="refresh" content="10"><style>${THEME}</style></head><body style="font-family:sans-serif;padding:40px;text-align:center;background:var(--bg);color:var(--ink)"><h2>No active agent sandbox found</h2><p>Start an OpenHands task first, then refresh this page.</p><p style="color:var(--muted)">Auto-refreshing in 10s...</p></body></html>`);
        return;
      }
      
      var vncUrl = `${OPENHANDS_PUBLIC_URL}/agent/${vncPort}/vnc.html?autoconnect=1&resize=remote`;
      res.writeHead(200, { 'content-type': 'text/html' });
      res.end(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Live Browser View</title>
<style>${THEME}
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); }
  iframe { width: 100vw; height: 100vh; border: none; }
</style>
</head>
<body>
  <iframe src="${vncUrl}" allow="clipboard-read; clipboard-write"></iframe>
</body>
</html>`);
      console.log('[http] /vnc → port ' + vncPort);
    } catch(e) {
      res.writeHead(500, { 'content-type': 'text/plain' });
      res.end('VNC error: ' + e.message);
    }
    return;
  }

  if (u.pathname === '/telegram-webhook' && req.method === 'POST') {
    var body = await readBody(req);
    if (!body || !body.message) { res.writeHead(200); res.end('ok'); return; }
    var msg = body.message;
    var chatId = msg.chat && msg.chat.id;
    var text = msg.text || msg.caption || '';
    var replyToMsgId = msg.message_id || null;
    var imageUrls = [];
    var sandboxPaths = [];
    var attachmentInfo = [];
    // Unified: all attachment types saved to shared downloads folder
    if (msg.photo && msg.photo.length > 0) {
      var c = await telegramCacheImageForOpenHands(msg.photo[msg.photo.length - 1].file_id, 'photo');
      if (c && c.url) { imageUrls.push(c.url); sandboxPaths.push(c.path); attachmentInfo.push('[photo] ' + c.fileName); }
      if (!text) text = 'Look at this image and describe it.';
    }
    if (msg.document && msg.document.file_id) {
      var c = await telegramCacheImageForOpenHands(msg.document.file_id, 'doc');
      if (c && c.url) { imageUrls.push(c.url); sandboxPaths.push(c.path); attachmentInfo.push('[doc] ' + (msg.document.file_name || c.fileName)); }
      if (!text) text = 'Analyze this document.';
    }
    if (msg.video && msg.video.file_id) {
      var c = await telegramCacheImageForOpenHands(msg.video.file_id, 'video');
      if (c && c.url) { imageUrls.push(c.url); sandboxPaths.push(c.path); attachmentInfo.push('[video] ' + c.fileName); }
      if (!text) text = 'Analyze this video.';
    }
    if (msg.video_note && msg.video_note.file_id) {
      var c = await telegramCacheImageForOpenHands(msg.video_note.file_id, 'video_note');
      if (c && c.url) { imageUrls.push(c.url); sandboxPaths.push(c.path); attachmentInfo.push('[video_note]'); }
    }
    if (msg.audio && msg.audio.file_id) {
      var c = await telegramCacheImageForOpenHands(msg.audio.file_id, 'audio');
      if (c && c.url) { imageUrls.push(c.url); sandboxPaths.push(c.path); attachmentInfo.push('[audio]'); }
    }
    if (msg.voice && msg.voice.file_id) {
      var c = await telegramCacheImageForOpenHands(msg.voice.file_id, 'voice');
      if (c && c.url) { imageUrls.push(c.url); sandboxPaths.push(c.path); attachmentInfo.push('[voice]'); }
    }
    if (msg.image_url) { imageUrls.push(msg.image_url); }
    if (attachmentInfo.length > 0) {
      text = (text || 'Analyze the attached files.') + '\n\n[Attachments: ' + attachmentInfo.join(', ') + ']';
      text += '\n[Paths: ' + sandboxPaths.join(', ') + ']';
    }
    if (!chatId || !text) { res.writeHead(200); res.end('ok'); return; }
    
    // ── Typing indicator — instant feedback ──
    telegramSendChatAction(chatId, 'typing').catch(function(){});
    
    // ── Rate limiting: queue messages instead of dropping ──
    var lockKey = 'tg-' + chatId;
    var existingSess = sessions.get(lockKey);
    if (existingSess && existingSess.processing) {
      if (!existingSess.queue) existingSess.queue = [];
      existingSess.queue.push({ text: text, imageUrls: imageUrls, replyToMsgId: replyToMsgId, sandboxPaths: sandboxPaths });
      console.log('[telegram] queued chatId=' + chatId + ' (queue size=' + existingSess.queue.length + ')');
      res.writeHead(200); res.end('ok');
      // Queue info folded into runtime message — no separate message
      return;
    }
    
    res.writeHead(200); res.end('ok');
    
    // Ensure session exists and mark processing
    if (!sessions.get(lockKey)) {
      sessions.set(lockKey, { lastActiveAt: Date.now(), model: DEFAULT_MODEL, turnCount: 0, ohConvId: null, history: [], processing: false });
    }
    sessions.get(lockKey).processing = true;
    console.log('[telegram] processing start chatId=' + chatId + ' msg="' + text.slice(0,60).replace(/\n/g,' ') + '"');
    
    // Process async — release lock in finally regardless of outcome
    dispatchForTelegram(chatId, text, null, imageUrls.length > 0 ? imageUrls : null, replyToMsgId, sandboxPaths.length > 0 ? sandboxPaths : null).catch(function(e) {
      console.error('[telegram] dispatch error:', e.message);
      telegramSendMessage(chatId, '[err] <b>Dispatch error:</b> ' + (e.message || 'Unknown').slice(0, 300),
        replyToMsgId ? { replyToMsgId: replyToMsgId } : {}).catch(function(){});
    }).finally(function() {
      var s = sessions.get(lockKey);
      if (s) {
        s.processing = false;
        console.log('[telegram] processing done chatId=' + chatId);
        // Process next queued message if any
        if (s.queue && s.queue.length > 0) {
          var next = s.queue.shift();
          console.log('[telegram] dequeued chatId=' + chatId + ' (remaining=' + s.queue.length + ')');
          s.processing = true;
          dispatchForTelegram(chatId, next.text, null, next.imageUrls && next.imageUrls.length > 0 ? next.imageUrls : null, next.replyToMsgId, next.sandboxPaths && next.sandboxPaths.length > 0 ? next.sandboxPaths : null).catch(function(e2) {
            console.error('[telegram] queued dispatch error:', e2.message);
          }).finally(function() {
            // Recursive: this will process next in queue via the same finally pattern
            if (s) s.processing = false;
          });
        }
      }
    });
    return;
  }

  if (u.pathname === '/dispatch' && req.method === 'POST') {
    if (!auth(req) && req.headers['x-from-dashboard'] !== '1') { res.writeHead(401); res.end('{"error":"unauthorized"}'); return; }
    if (inFlight >= MAX_CONCURRENT) { res.writeHead(429); res.end('{"error":"too_many_requests"}'); return; }
    const b = await readBody(req);
    if (!b || !b.userId || !b.message) { res.writeHead(400); res.end('{"error":"userId and message required"}'); return; }
    console.log('[dispatch] ' + b.userId + ' msg="' + b.message.slice(0,80).replace(/\n/g,' ') + '"' + (b.imageUrls ? ' images=' + b.imageUrls.length : ''));
    inFlight++;
    res.writeHead(200, { 'content-type': 'application/x-ndjson', 'cache-control': 'no-store', 'x-accel-buffering': 'no' });
    try { await streamDispatch(b.userId, b.message, b.model, b.imageUrls, res); } catch (e) { if (!res.writableEnded) res.end(); }
    inFlight--;
    log('POST', '/dispatch', 200, Date.now() - start, 'userId=' + b.userId);
    return;
  }

  if (u.pathname === '/dashboard' || u.pathname === '/' || u.pathname === '/chat') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
    res.end(getDashboard(sessions, ohDB, OPENHANDS_PUBLIC_URL, inFlight, DEFAULT_PROFILE, AVAILABLE_MODELS));
    return;
  }

  if (u.pathname === '/sessions' && req.method === 'GET') {
    if (!auth(req) && req.headers['x-from-dashboard'] !== '1') { res.writeHead(401); res.end('{"error":"unauthorized"}'); return; }
    const list = [];
    for (const [uid, s] of sessions) {
      list.push({
        userId: uid,
        model: s.model || 'default',
        turnCount: s.turnCount,
        lastActiveAgo: Math.round((Date.now() - s.lastActiveAt) / 1000),
        conversationId: s.ohConvId || null,
        conversationUrl: s.ohConvId ? '' + DISPATCH_PUBLIC_URL + '/chat?uid=' + uid : null
      });
    }
    // Add recent DB conversations
    var dbConvs = [];
    try {
      if (ohDB) {
        var cur = ohDB.prepare("SELECT conversation_id, title, created_at FROM conversation_metadata WHERE user_id = 'dispatcher' ORDER BY created_at DESC LIMIT 20").all();
        for (var i = 0; i < cur.length; i++) {
          var c = cur[i];
          dbConvs.push({
            conversationId: Array.isArray(c) ? c[0] : c.conversation_id,
            title: Array.isArray(c) ? c[1] : c.title,
            createdAt: Array.isArray(c) ? c[2] : c.created_at,
            url: OPENHANDS_PUBLIC_URL + '/conversations/' + (Array.isArray(c) ? c[0] : c.conversation_id)
          });
        }
      }
    } catch(e) {}
    res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
    res.end(JSON.stringify({ activeSessions: list, totalActive: sessions.size, inFlight, recentConversations: dbConvs }));
    return;
  }

  // ═══════════════════════════════════════════════════════════════════
  // ISSUES MODULE — fully local issue tracker with images & comments
  // ═══════════════════════════════════════════════════════════════════
  if (!issuesDb) { try {
    issuesDb = new DatabaseSync(join(OH_STATE_PATH, 'dispatcher-issues.db'));
    issuesDb.exec('PRAGMA journal_mode=WAL');
    issuesDb.exec(`CREATE TABLE IF NOT EXISTS issues (
      id TEXT PRIMARY KEY,
      number INTEGER UNIQUE NOT NULL,
      title TEXT NOT NULL,
      description TEXT DEFAULT '',
      status TEXT DEFAULT 'open',
      priority TEXT DEFAULT 'medium',
      labels TEXT DEFAULT '[]',
      reporter TEXT DEFAULT '',
      assignee TEXT DEFAULT '',
      image_urls TEXT DEFAULT '[]',
      conversation_id TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )`);
    issuesDb.exec(`CREATE TABLE IF NOT EXISTS comments (
      id TEXT PRIMARY KEY,
      issue_id TEXT NOT NULL,
      author TEXT DEFAULT '',
      body TEXT NOT NULL,
      image_urls TEXT DEFAULT '[]',
      created_at TEXT NOT NULL,
      FOREIGN KEY (issue_id) REFERENCES issues(id)
    )`);
    console.log('[issues] DB ready');
  } catch(e) { console.warn('[issues] DB init failed:', e.message); } }

  function nextIssueNumber() {
    if (!issuesDb) return 1;
    var row = issuesDb.prepare('SELECT COALESCE(MAX(number),0) as mx FROM issues').get();
    return (row && row.mx || 0) + 1;
  }

  // GET /issues
  if (u.pathname === '/issues' && req.method === 'GET') {
    try {
      var filter = u.searchParams.get('status') || '';
      var sql = 'SELECT * FROM issues';
      var params = [];
      if (filter) { sql += ' WHERE status = ?'; params.push(filter); }
      sql += ' ORDER BY number DESC LIMIT 100';
      var rows = issuesDb.prepare(sql).all(...params);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(rows.map(issueToJSON)));
    } catch(e) { res.writeHead(500); res.end(JSON.stringify({ error: e.message })); }
    return;
  }

  // POST /issues — create new issue
  if (u.pathname === '/issues' && req.method === 'POST') {
    try {
      var b = await readBody(req);
      if (!b || !b.title) { res.writeHead(400); res.end(JSON.stringify({ error: 'title required' })); return; }
      var id = randomUUID();
      var num = nextIssueNumber();
      var now = new Date().toISOString();
      issuesDb.prepare(`INSERT INTO issues (id,number,title,description,status,priority,labels,reporter,image_urls,conversation_id,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`).run(
        id, num, b.title, b.description || '', b.status || 'open',
        b.priority || 'medium', JSON.stringify(b.labels || []),
        b.reporter || '', JSON.stringify(b.image_urls || []),
        b.conversation_id || '', now, now
      );
      var issue = issueToJSON(issuesDb.prepare('SELECT * FROM issues WHERE id = ?').get(id));
      console.log('[issues] created #' + num + ': ' + b.title.slice(0, 60));
      res.writeHead(201, { 'content-type': 'application/json' });
      res.end(JSON.stringify(issue));
    } catch(e) { res.writeHead(500); res.end(JSON.stringify({ error: e.message })); }
    return;
  }

  // GET /issues/:id — single issue with comments
  var issueMatch = u.pathname.match(/^\/issues\/([a-f0-9-]+)$/);
  if (issueMatch && req.method === 'GET') {
    try {
      var issue = issuesDb.prepare('SELECT * FROM issues WHERE id = ?').get(issueMatch[1]);
      if (!issue) { res.writeHead(404); res.end(JSON.stringify({ error: 'not found' })); return; }
      var comments = issuesDb.prepare('SELECT * FROM comments WHERE issue_id = ? ORDER BY created_at ASC').all(issueMatch[1]);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({
        issue: issueToJSON(issue),
        comments: comments.map(function(c) { return {
          id: c.id, author: c.author, body: c.body,
          image_urls: JSON.parse(c.image_urls || '[]'), created_at: c.created_at
        };})
      }));
    } catch(e) { res.writeHead(500); res.end(JSON.stringify({ error: e.message })); }
    return;
  }

  // POST /issues/:id/comments
  var issueCommentMatch = u.pathname.match(/^\/issues\/([a-f0-9-]+)\/comments$/);
  if (issueCommentMatch && req.method === 'POST') {
    try {
      var b = await readBody(req);
      if (!b || !b.body) { res.writeHead(400); res.end(JSON.stringify({ error: 'body required' })); return; }
      var issue = issuesDb.prepare('SELECT id FROM issues WHERE id = ?').get(issueCommentMatch[1]);
      if (!issue) { res.writeHead(404); res.end(JSON.stringify({ error: 'not found' })); return; }
      var cid = randomUUID();
      var now = new Date().toISOString();
      issuesDb.prepare('INSERT INTO comments (id,issue_id,author,body,image_urls,created_at) VALUES (?,?,?,?,?,?)').run(
        cid, issueCommentMatch[1], b.author || '', b.body, JSON.stringify(b.image_urls || []), now
      );
      issuesDb.prepare('UPDATE issues SET updated_at = ? WHERE id = ?').run(now, issueCommentMatch[1]);
      res.writeHead(201, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ id: cid, created_at: now }));
    } catch(e) { res.writeHead(500); res.end(JSON.stringify({ error: e.message })); }
    return;
  }

  // PATCH /issues/:id — update status, priority, labels, assignee
  if (issueMatch && req.method === 'PATCH') {
    try {
      var b = await readBody(req);
      var issue = issuesDb.prepare('SELECT * FROM issues WHERE id = ?').get(issueMatch[1]);
      if (!issue) { res.writeHead(404); res.end(JSON.stringify({ error: 'not found' })); return; }
      var now = new Date().toISOString();
      if (b.status) issuesDb.prepare('UPDATE issues SET status = ?, updated_at = ? WHERE id = ?').run(b.status, now, issueMatch[1]);
      if (b.priority) issuesDb.prepare('UPDATE issues SET priority = ?, updated_at = ? WHERE id = ?').run(b.priority, now, issueMatch[1]);
      if (b.labels) issuesDb.prepare('UPDATE issues SET labels = ?, updated_at = ? WHERE id = ?').run(JSON.stringify(b.labels), now, issueMatch[1]);
      if (b.assignee !== undefined) issuesDb.prepare('UPDATE issues SET assignee = ?, updated_at = ? WHERE id = ?').run(b.assignee, now, issueMatch[1]);
      if (b.title) issuesDb.prepare('UPDATE issues SET title = ?, updated_at = ? WHERE id = ?').run(b.title, now, issueMatch[1]);
      var updated = issueToJSON(issuesDb.prepare('SELECT * FROM issues WHERE id = ?').get(issueMatch[1]));
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(updated));
    } catch(e) { res.writeHead(500); res.end(JSON.stringify({ error: e.message })); }
    return;
  }

  // GET /issues-ui — dedicated issues web UI
  if (u.pathname === '/issues-ui' && req.method === 'GET') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
    res.end(getIssuesUI());
    return;
  }

  res.writeHead(404); res.end('{"error":"not_found"}');
});

server.listen(PORT, '0.0.0.0', () => {
  loadSessions();   // restore conversation history from disk
  loadSchedules();  // restore scheduled tasks from disk
  console.log(`dispatcher :${PORT} -> OpenHands ${OPENHANDS_URL}`);
  if (TELEGRAM_TOKEN) { telegramSetWebhook(TELEGRAM_WEBHOOK_URL); console.log('[telegram] bot active, webhook pending'); }
});
