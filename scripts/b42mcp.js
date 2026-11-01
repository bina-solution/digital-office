#!/usr/bin/env node
// Minimal Playwright-MCP (streamable HTTP) client for driving browser42.
// Session id is persisted to /tmp so sequential CLI calls share one browser
// context. Usage:
//   node b42mcp.js init
//   node b42mcp.js tool <toolName> '<jsonArgs>'
//   node b42mcp.js list
const fs = require('fs');
const path = require('path');

const ENV_PATH = path.join(__dirname, '..', '.env');
const SESS_FILE = process.env.B42_SESS_FILE || (process.env.TEMP || '/tmp') + '/b42_session.txt';

function readEnv(key) {
    try {
        const line = fs.readFileSync(ENV_PATH, 'utf8').split(/\r?\n/).find((l) => l.startsWith(key + '='));
        return line ? line.slice(key.length + 1).replace(/^["']|["']$/g, '').trim() : '';
    } catch { return ''; }
}

const TOKEN = process.env.BROWSER42_MCP_TOKEN || readEnv('BROWSER42_MCP_TOKEN');
const URL = process.env.B42_MCP_URL || 'http://127.0.0.1:8931/mcp';

async function rpc(method, params, sessionId) {
    const headers = {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
        authorization: `Bearer ${TOKEN}`,
    };
    if (sessionId) headers['mcp-session-id'] = sessionId;
    const res = await fetch(URL, {
        method: 'POST',
        headers,
        body: JSON.stringify({ jsonrpc: '2.0', id: Date.now(), method, params }),
    });
    const newSession = res.headers.get('mcp-session-id');
    const ct = res.headers.get('content-type') || '';
    let payload;
    const raw = await res.text();
    if (ct.includes('text/event-stream')) {
        // parse SSE frames: collect last data: {json}
        const datas = raw.split(/\r?\n/).filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim());
        payload = datas.length ? JSON.parse(datas[datas.length - 1]) : null;
    } else if (raw) {
        try { payload = JSON.parse(raw); } catch { payload = { raw }; }
    }
    return { status: res.status, session: newSession, payload };
}

async function notify(method, params, sessionId) {
    const headers = {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
        authorization: `Bearer ${TOKEN}`,
    };
    if (sessionId) headers['mcp-session-id'] = sessionId;
    await fetch(URL, { method: 'POST', headers, body: JSON.stringify({ jsonrpc: '2.0', method, params }) });
}

function saveSession(id) { fs.writeFileSync(SESS_FILE, id || ''); }
function loadSession() { try { return fs.readFileSync(SESS_FILE, 'utf8').trim(); } catch { return ''; } }

async function initSession() {
    const r = await rpc('initialize', {
        protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'claude-code', version: '1.0' },
    });
    if (r.session) { saveSession(r.session); await notify('notifications/initialized', {}, r.session); }
    return r.session;
}

async function callTool(name, args, sess) {
    const r = await rpc('tools/call', { name, arguments: args || {} }, sess);
    const content = r.payload?.result?.content || [];
    const text = content.filter((c) => c.type === 'text').map((c) => c.text).join('\n');
    return { status: r.status, isError: r.payload?.result?.isError || false, text, error: r.payload?.error };
}

(async () => {
    const [cmd, a1, a2] = process.argv.slice(2);
    if (!TOKEN) { console.error('No BROWSER42_MCP_TOKEN'); process.exit(2); }

    // flow mode: one session, many steps, from a JSON file:
    //   [{ "tool": "...", "args": {...} } | { "sleep": 1500 } | { "print": "snapshot", "tool":"browser_snapshot" }]
    if (cmd === 'flow') {
        const steps = JSON.parse(fs.readFileSync(a1, 'utf8'));
        const sess = await initSession();
        console.log(`[flow] session=${sess ? 'ok' : 'FAILED'} steps=${steps.length}`);
        for (let i = 0; i < steps.length; i++) {
            const s = steps[i];
            if (s.sleep) { await new Promise((r) => setTimeout(r, s.sleep)); console.log(`  [${i}] slept ${s.sleep}ms`); continue; }
            const res = await callTool(s.tool, s.args, sess);
            const label = s.label || s.tool;
            console.log(`  [${i}] ${label} -> status=${res.status} err=${res.isError}`);
            if (s.show !== false && res.text) console.log(res.text.slice(0, s.max || 2500));
            if (res.error) console.log('  ERR ' + JSON.stringify(res.error));
            if (res.isError && s.stopOnError) { console.log('[flow] stop on error'); break; }
        }
        return;
    }

    if (cmd === 'init') {
        const r = await rpc('initialize', {
            protocolVersion: '2025-06-18',
            capabilities: {},
            clientInfo: { name: 'claude-code', version: '1.0' },
        });
        if (r.session) { saveSession(r.session); await notify('notifications/initialized', {}, r.session); }
        console.log(JSON.stringify({ status: r.status, session: r.session, server: r.payload?.result?.serverInfo }, null, 2));
        return;
    }

    if (cmd === 'schemas') {
        const sess = await initSession();
        const r = await rpc('tools/list', {}, sess);
        const tools = r.payload?.result?.tools || [];
        const want = process.argv.slice(3);
        for (const n of want) {
            const t = tools.find((x) => x.name === n);
            if (!t) { console.log(`\n### ${n} — NOT FOUND`); continue; }
            const props = t.inputSchema?.properties || {};
            const flat = Object.fromEntries(Object.entries(props).map(([k, v]) => [k, v.type || (v.enum ? 'enum:' + v.enum.join('|') : '?')]));
            console.log(`\n### ${n}\nprops=${JSON.stringify(flat)}\nrequired=${JSON.stringify(t.inputSchema?.required || [])}`);
        }
        return;
    }

    const sess = loadSession();
    if (cmd === 'list') {
        const r = await rpc('tools/list', {}, sess);
        const names = (r.payload?.result?.tools || []).map((t) => t.name);
        console.log(JSON.stringify({ status: r.status, count: names.length, names }, null, 2));
        return;
    }
    if (cmd === 'tool') {
        const args = a2 ? JSON.parse(a2) : {};
        const r = await rpc('tools/call', { name: a1, arguments: args }, sess);
        // Print text content blocks compactly; full payload to stderr for debugging.
        const content = r.payload?.result?.content || [];
        const text = content.filter((c) => c.type === 'text').map((c) => c.text).join('\n');
        console.log(JSON.stringify({ status: r.status, isError: r.payload?.result?.isError || false }, null, 2));
        if (text) console.log('--- content ---\n' + text.slice(0, 6000));
        if (r.payload?.error) console.log('--- error ---\n' + JSON.stringify(r.payload.error));
        return;
    }
    console.error('usage: init | list | tool <name> <jsonArgs>');
    process.exit(2);
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
