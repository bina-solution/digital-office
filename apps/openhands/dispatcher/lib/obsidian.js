// ── Obsidian Brain Vault module ──────────────────────────────────
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { execSync } from 'node:child_process';

const VAULT_PATH = '/root/deployment-hacohen/ai/obsidian';
const SKILLS_PATH = '/root/deployment-hacohen/.github/skills';

var obsidianBrainSkill = null;

export function loadObsidianBrainSkill() {
  if (obsidianBrainSkill) return obsidianBrainSkill;
  try {
    var skillPath = join(SKILLS_PATH, 'obsidian-brain', 'SKILL.md');
    obsidianBrainSkill = readFileSync(skillPath, 'utf-8');
    console.log('[obsidian-brain] skill loaded (' + obsidianBrainSkill.length + ' chars)');
  } catch(e) { obsidianBrainSkill = '# Obsidian Brain skill unavailable'; }
  return obsidianBrainSkill;
}

export function vaultRemember(fact) {
  var profilePath = join(VAULT_PATH, 'Memory', 'User Profile.md');
  var today = new Date().toISOString().slice(0, 10);
  try {
    var existing = readFileSync(profilePath, 'utf-8');
    if (existing.includes(fact)) return { existed: true, path: profilePath };
    var lines = existing.split('\n');
    var insertAt = lines.length;
    for (var i = lines.length - 1; i >= 0; i--) {
      if (lines[i].trim() && !lines[i].startsWith('---')) { insertAt = i + 1; break; }
    }
    lines.splice(insertAt, 0, '', '- **' + today + ':** ' + fact);
    writeFileSync(profilePath, lines.join('\n'));
    return { existed: false, path: profilePath, fact: fact };
  } catch(e) { return { error: e.message }; }
}

export function vaultSearch(keyword) {
  try {
    var result = execSync('grep -rli "' + keyword.replace(/"/g, '\\"') + '" "' + VAULT_PATH + '/" --include="*.md" 2>/dev/null | head -20',
      { timeout: 3000, encoding: 'utf-8' }).trim();
    if (!result) return 'No matches found in vault for: ' + keyword;
    var files = result.split('\n');
    var out = '<b>Vault search: "' + keyword.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '"</b>\n';
    for (var i = 0; i < Math.min(files.length, 10); i++) {
      var f = files[i].trim();
      if (!f) continue;
      out += '• ' + f.replace(VAULT_PATH + '/', '') + '\n';
    }
    return out;
  } catch(e) { return 'Vault search error: ' + e.message; }
}

export function vaultRead(relPath) {
  try {
    var fullPath = join(VAULT_PATH, relPath);
    var content = readFileSync(fullPath, 'utf-8');
    if (content.length > 3000) content = content.slice(0, 3000) + '\n\n... (truncated, ' + (content.length - 3000) + ' more chars)';
    return '<b>' + relPath + '</b>\n<pre>' + content.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</pre>';
  } catch(e) { return '[err] Cannot read ' + relPath + ': ' + e.message; }
}

export function vaultRecentSessions(count) {
  count = count || 3;
  try {
    var logPath = join(VAULT_PATH, 'Sessions', 'Session Log.md');
    var content = readFileSync(logPath, 'utf-8');
    var entries = content.split('## ').slice(1, count + 1);
    if (entries.length === 0) return 'No session entries found.';
    return '<b>Recent sessions:</b>\n\n' + entries.map(function(e) {
      return '## ' + e.split('\n').slice(0, 3).join('\n');
    }).join('\n\n');
  } catch(e) { return 'Session log unavailable: ' + e.message; }
}

export function vaultCheckpoint(slug, summary) {
  try {
    var cpPath = join(VAULT_PATH, 'Checkpoints', (slug || 'manual') + '.md');
    var content = '---\ndate: ' + new Date().toISOString().slice(0, 10) + '\nstatus: paused\n---\n\n# ' + (slug || 'Checkpoint') + '\n\n' + (summary || 'No summary provided.') + '\n';
    writeFileSync(cpPath, content);
    return '[done] Checkpoint created: Checkpoints/' + (slug || 'manual') + '.md';
  } catch(e) { return '[err] Checkpoint failed: ' + e.message; }
}

export function buildObsidianBrainPrompt(userCommand) {
  var skill = loadObsidianBrainSkill();
  var bootSection = '';
  try {
    bootSection = readFileSync(join(VAULT_PATH, '00 - START HERE.md'), 'utf-8').slice(0, 500);
    bootSection += '\n\n' + readFileSync(join(VAULT_PATH, '_Hooks', 'ONBOARDING.md'), 'utf-8').slice(0, 300);
  } catch(e) {}

  var prompt = '[OBSIDIAN BRAIN SKILL — LOADED]\n';
  prompt += 'You have FULL access to the Obsidian Brain vault.\n';
  prompt += 'The vault on the HOST is at /root/deployment-hacohen/ai/obsidian/.\n';
  prompt += 'In YOUR sandbox, the workspace is at /workspace/project/ so the vault is at /workspace/project/ai/obsidian/.\n';
  prompt += 'This is the AI\'s persistent cross-session memory system.\n\n';
  prompt += '## Vault Quick Reference\n';
  prompt += '| Path | Purpose |\n|------|---------|\n';
  prompt += '| 00 - START HERE.md | Session bootstrap + navigation |\n';
  prompt += '| _Hooks/ | Behavioral rules loaded every session |\n';
  prompt += '| Memory/User Profile.md | Facts about the user |\n';
  prompt += '| Memory/Working Style.md | How the user prefers to work |\n';
  prompt += '| Memory/Important Decisions.md | Architectural decisions |\n';
  prompt += '| Sessions/Session Log.md | Dated log, newest on top |\n';
  prompt += '| Checkpoints/ | Mid-task snapshots |\n';
  prompt += '| Projects/<name>/00 - Overview.md | Per-project state |\n';
  prompt += '| References/ | API specs, cheat sheets |\n\n';
  prompt += '## Write Format\n';
  prompt += 'Every entry MUST carry: date heading (YYYY-MM-DD), tags, project marker.\n';
  prompt += 'See Memory/User Profile.md for existing format examples.\n\n';
  prompt += '## Rules\n';
  prompt += '- ALWAYS read relevant vault files before starting work\n';
  prompt += '- Write to vault during work, not after\n';
  prompt += '- NEVER put passwords, API keys, or PII in vault\n';
  prompt += '- Search vault before creating new files\n\n';
  prompt += '## START HERE (boot):\n' + bootSection + '\n\n';
  prompt += '## USER COMMAND:\n' + userCommand + '\n\n';
  prompt += 'REMEMBER: Read relevant vault files FIRST, then execute the command. Write results back to vault.\n';
  return prompt;
}

export function handleObsidianBrainCommand(message, chatId) {
  var rest = message.replace(/^\/obsidian-brain\s*/i, '').trim();
  var restLower = rest.toLowerCase();

  var rememberMatch = restLower.match(/^remember\s+(?:that\s+)?(.+)/i);
  if (rememberMatch) {
    var fact = rememberMatch[1].trim();
    var result = vaultRemember(fact);
    if (result.error) return { type: 'direct', text: '[err] Failed to write to vault: ' + result.error };
    if (result.existed) return { type: 'direct', text: 'Already known: <i>' + fact.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</i>' };
    return { type: 'direct', text: '<b>Remembered!</b>\n\n' + fact.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '\nWritten to Memory/User Profile.md' };
  }

  var searchMatch = restLower.match(/^search\s+(.+)/i);
  if (searchMatch) return { type: 'direct', text: vaultSearch(searchMatch[1].trim()) };

  var readMatch = restLower.match(/^read\s+(.+)/i);
  if (readMatch) return { type: 'direct', text: vaultRead(readMatch[1].trim()) };

  if (restLower === 'sessions' || restLower === 'log' || restLower === 'recent') {
    return { type: 'direct', text: vaultRecentSessions(5) };
  }

  var cpMatch = restLower.match(/^checkpoint\s+(\S+)\s*(.*)/i);
  if (cpMatch) return { type: 'direct', text: vaultCheckpoint(cpMatch[1], cpMatch[2]) };

  if (!rest) {
    return { type: 'direct', text: '<b>Obsidian Brain — Commands</b>\n\n' +
      '/obsidian-brain remember that &lt;fact&gt; — Store a fact in vault\n' +
      '/obsidian-brain search &lt;keyword&gt; — Search vault\n' +
      '/obsidian-brain read &lt;path&gt; — Read a vault file\n' +
      '/obsidian-brain sessions — Recent session log\n' +
      '/obsidian-brain checkpoint &lt;slug&gt; &lt;summary&gt; — Save progress\n' +
      '/obsidian-brain &lt;any task&gt; — Execute with full brain access\n\n' +
      '<i>The vault lives at ' + VAULT_PATH + '</i>' };
  }

  return { type: 'obsidian-delegate', command: rest };
}
