// ── Issues module — GitHub-style issue tracker ────────────────────
import { randomUUID } from 'node:crypto';

// Public base of THIS dispatcher, from the deployment (apps/openhands/docker-compose.yml sets
// DISPATCH_PUBLIC_URL from ${DISPATCH_BASE_URL}, which derives from DEPLOYMENT_DOMAIN). It was a
// literal at every call site, so every link the bot handed out named the FIRST deployment's
// domain no matter which deployment sent it.
const DISPATCH_PUBLIC_URL = (process.env.DISPATCH_PUBLIC_URL || 'http://localhost:8800').replace(/\/+$/, '');

/**
 * Handle all /issue* commands. Returns { type: 'direct', text: '...' }
 * @param {string} message - full command
 * @param {string|number} chatId
 * @param {string} lower - lowercase version
 * @param {DatabaseSync} issuesDb
 */
export function handleIssueCommand(message, chatId, lower, issuesDb) {
  var parts = message.split(/\s+/);

  // /issues — list open issues
  if (lower === '/issues' || lower === '/issue list') {
    if (!issuesDb) return { type: 'direct', text: '[warn] Issue tracker unavailable.' };
    try {
      var rows = issuesDb.prepare('SELECT * FROM issues WHERE status != ? ORDER BY number DESC LIMIT 10').all('closed');
      if (rows.length === 0) return { type: 'direct', text: 'No open issues. Use <code>/issue create Title here</code> to create one.' };
      var list = '<b>Issues (' + rows.length + ' open)</b>\n\n';
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var prefix = r.priority === 'high' ? '[!]' : r.status === 'in_progress' ? '[wip]' : '[ ]';
        list += prefix + ' <b>#' + r.number + '</b> ' + r.title.slice(0, 60) + '\n';
        list += '   Status: ' + r.status + ' | ' + (r.labels ? JSON.parse(r.labels).join(', ') : '') + '\n';
      }
      list += '\n[link] <a href="' + DISPATCH_PUBLIC_URL + '/issues-ui">Open Issues UI</a>';
      return { type: 'direct', text: list };
    } catch(e) { return { type: 'direct', text: '[warn] Error: ' + e.message }; }
  }

  // /issue #N — view issue details
  var viewMatch = message.match(/^\/issue\s+#?(\d+)$/i);
  if (viewMatch) {
    if (!issuesDb) return { type: 'direct', text: '[warn] Issue tracker unavailable.' };
    try {
      var num = parseInt(viewMatch[1]);
      var issue = issuesDb.prepare('SELECT * FROM issues WHERE number = ?').get(num);
      if (!issue) return { type: 'direct', text: '[warn] Issue #' + num + ' not found.' };
      var comments = issuesDb.prepare('SELECT * FROM comments WHERE issue_id = ? ORDER BY created_at ASC').all(issue.id);
      var det = '<b>#' + issue.number + ' — ' + issue.title + '</b>\n\n';
      det += '<b>Status:</b> ' + issue.status + ' | <b>Priority:</b> ' + issue.priority + '\n';
      if (issue.labels) {
        var labels = JSON.parse(issue.labels);
        if (labels.length > 0) det += '<b>Labels:</b> ' + labels.join(', ') + '\n';
      }
      if (issue.description) det += '\n' + issue.description.slice(0, 500) + '\n';
      if (comments.length > 0) {
        det += '\n<b>Comments (' + comments.length + '):</b>\n';
        for (var ci = 0; ci < Math.min(comments.length, 5); ci++) {
          det += '  ' + (comments[ci].author || 'anon') + ': ' + comments[ci].body.slice(0, 200) + '\n';
        }
      }
      det += '\n[link] <a href="' + DISPATCH_PUBLIC_URL + '/issues-ui">Open in Web UI</a>';
      return { type: 'direct', text: det };
    } catch(e) { return { type: 'direct', text: '[warn] Error: ' + e.message }; }
  }

  // /issue create Title here | desc... | priority high | label bug
  var createMatch = message.match(/^\/issue\s+create\s+(.+)$/i);
  if (createMatch) {
    if (!issuesDb) return { type: 'direct', text: '[warn] Issue tracker unavailable.' };
    try {
      var content = createMatch[1];
      var fields = content.split(/\s*\|\s*/);
      var title = fields[0].trim();
      var desc = '';
      var priority = 'medium';
      var labels = [];
      for (var fi = 1; fi < fields.length; fi++) {
        var f = fields[fi].trim();
        if (f.startsWith('priority ')) priority = f.replace('priority ', '');
        else if (f.startsWith('label ')) labels.push(f.replace('label ', ''));
        else desc += f + '\n';
      }
      desc = desc.trim();

      var id = randomUUID();
      var now = new Date().toISOString();
      var maxNum = issuesDb.prepare('SELECT COALESCE(MAX(number),0) as mx FROM issues').get();
      var num = (maxNum.mx || 0) + 1;
      issuesDb.prepare('INSERT INTO issues (id,number,title,description,status,priority,labels,reporter,image_urls,conversation_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)').run(
        id, num, title, desc, 'open', priority, JSON.stringify(labels),
        'tg-' + chatId, '[]', '', now, now
      );
      return { type: 'direct', text: '<b>Issue #' + num + ' created!</b>\n\n' + title + '\n\n[link] <a href="' + DISPATCH_PUBLIC_URL + '/issues-ui">Open Issues UI</a>' };
    } catch(e) { return { type: 'direct', text: '[warn] Error: ' + e.message }; }
  }

  // /issue close #N or /issue fix #N
  var closeMatch = message.match(/^\/issue\s+(close|fix|resolve)\s+#?(\d+)$/i);
  if (closeMatch) {
    if (!issuesDb) return { type: 'direct', text: '[warn] Issue tracker unavailable.' };
    try {
      var num = parseInt(closeMatch[2]);
      var now = new Date().toISOString();
      issuesDb.prepare('UPDATE issues SET status = ?, updated_at = ? WHERE number = ?').run('closed', now, num);
      var cid = randomUUID();
      issuesDb.prepare('INSERT INTO comments (id,issue_id,author,body,image_urls,created_at) VALUES (?,?,?,?,?,?)').run(
        cid, issuesDb.prepare('SELECT id FROM issues WHERE number = ?').get(num).id,
        'tg-' + chatId, 'Issue closed via Telegram', '[]', now
      );
      return { type: 'direct', text: '[done] Issue #' + num + ' closed.' };
    } catch(e) { return { type: 'direct', text: '[warn] Error: ' + e.message }; }
  }

  // /issue comment #N text here
  var commentMatch = message.match(/^\/issue\s+comment\s+#?(\d+)\s+(.+)$/i);
  if (commentMatch) {
    if (!issuesDb) return { type: 'direct', text: '[warn] Issue tracker unavailable.' };
    try {
      var num = parseInt(commentMatch[1]);
      var issue = issuesDb.prepare('SELECT id FROM issues WHERE number = ?').get(num);
      if (!issue) return { type: 'direct', text: '[warn] Issue #' + num + ' not found.' };
      var cid = randomUUID();
      var now = new Date().toISOString();
      issuesDb.prepare('INSERT INTO comments (id,issue_id,author,body,image_urls,created_at) VALUES (?,?,?,?,?,?)').run(
        cid, issue.id, 'tg-' + chatId, commentMatch[2], '[]', now
      );
      issuesDb.prepare('UPDATE issues SET updated_at = ? WHERE id = ?').run(now, issue.id);
      return { type: 'direct', text: '[ok] Comment added to #' + num + '.' };
    } catch(e) { return { type: 'direct', text: '[warn] Error: ' + e.message }; }
  }

  return { type: 'direct', text: '<b>Issue Commands:</b>\n\n<code>/issues</code> — List open issues\n<code>/issue #N</code> — View issue details\n<code>/issue create Title | desc... | priority high | label bug</code> — Create issue\n<code>/issue comment #N text</code> — Add comment\n<code>/issue close #N</code> — Close issue\n\n[link] <a href="' + DISPATCH_PUBLIC_URL + '/issues-ui">Open Issues UI</a>' };
}
