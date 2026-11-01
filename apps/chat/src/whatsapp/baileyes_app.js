// Baileys v7 is ESM-only, use dynamic import
const { join } = require('path');
const fs = require('fs');

const { onMessage } = require('./chat_bot');
const { appProperties, onWhatsAppConnected } = require('../globals');
const { CONFIG } = require('../config');
const { attachWhatsAppArchive, getMessageForBaileys, upsertGroup } = require('../data/wa_archive');
const { handleGroupMention } = require('./group_agent/group_agent');
const { handleDevMention } = require('./group_agent/dev_agent');

// Group metadata cache (Baileys best practice — avoids repeated fetches)
let groupMetadataCache = null;
const getGroupCache = async () => {
    if (!groupMetadataCache) {
        const NodeCache = (await import('node-cache')).default;
        groupMetadataCache = new NodeCache({ stdTTL: 5 * 60, useClones: false });
    }
    return groupMetadataCache;
};


const AUTH_INFO_PATH = join(__dirname, '../../data/auth_info');


let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 60_000; // 1 minute cap

// Cache for Baileys module (loaded once)
let baileysModule = null;

const loadBaileys = async () => {
    if (!baileysModule) {
        baileysModule = await import('baileys');
    }
    return baileysModule;
};

const runBaileyesApp = async () => {
    const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, Browsers } = await loadBaileys();
    let waVersion;
    try {
        const { version, isLatest } = await fetchLatestBaileysVersion();
        waVersion = version;
        console.log('[Baileys] Using WA version', version, 'isLatest?', isLatest);
    } catch (e) {
        console.log('[Baileys] Failed to fetch latest version, using default embedded version. Err:', e?.message);
    }

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_INFO_PATH);

    // WhatsApp rejects the pairing WebSocket (connection close 428, no QR ever emitted) when a
    // FRESH/unregistered device requests full-history sync with the macOS-Desktop client identifier
    // — which is exactly the combo Baileys recommends for history sync. Isolated 2026-07:
    //   macOS('Desktop') + syncFullHistory:true  -> CLOSE 428 (no QR)
    //   macOS('Desktop') + syncFullHistory:false -> QR
    //   ubuntu('Chrome') + syncFullHistory:true  -> QR
    // So gate that combo on whether we're already registered: pair with a plain browser and no
    // history sync (WhatsApp accepts it and emits the QR), then switch to the archive-optimal
    // identifier on the post-registration reconnect (statusCode 515), where WhatsApp actually
    // delivers the history sync. This is what unblocks real pairing (was misattributed to a
    // datacenter-IP block — the raw WS + handshake are accepted; only this combo is rejected).
    const registered = !!state.creds?.registered;
    const wantFullHistory = CONFIG.WA_ARCHIVE_SYNC_FULL_HISTORY && registered;

    const socketOptions = {
        auth: state,
        version: waVersion,
        printQRInTerminal: false,
        syncFullHistory: wantFullHistory,
        markOnlineOnConnect: false,
        browser: wantFullHistory ? Browsers.macOS('Desktop') : Browsers.ubuntu('Chrome'),
        getMessage: getMessageForBaileys,
        cachedGroupMetadata: async (jid) => {
            const cache = await getGroupCache();
            return cache.get(jid);
        }
    };

    const sock = makeWASocket(socketOptions);
    appProperties.sock = sock;
    attachWhatsAppArchive(sock);

    // Reset attempts on new socket creation
    reconnectAttempts = 0;

    const scheduleReconnect = (reason, loggedOut) => {
        if (loggedOut) {
            // force a clean login quickly
            setTimeout(runBaileyesApp, 3_000);
            return;
        }
        reconnectAttempts++;
        const base = 5_000;
        const delay = Math.min(MAX_RECONNECT_DELAY, Math.round(base * Math.pow(1.5, reconnectAttempts) + Math.random() * 1_000));
        console.log(`[Baileys] Scheduling reconnect in ${delay}ms (attempt ${reconnectAttempts}) reason=${reason}`);
        setTimeout(runBaileyesApp, delay);
    }

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect } = update;

        if (update.qr) {
            console.log('QR Code received (hidden)');
        }
        appProperties.qr_text = update.qr || appProperties.qr_text;

        if (connection === 'close') {
            appProperties.is_connected = false;
            appProperties.lastDisconnect = lastDisconnect;
            appProperties.botNumber = null;

            // Extract Boom error info if present
            const err = lastDisconnect?.error;
            const statusCode = err?.output?.statusCode;
            const disconnectReason = DisconnectReason[statusCode] || statusCode;
            console.log('[Baileys] Connection closed.', { statusCode, disconnectReason });
            if (err) {
                console.log('[Baileys] Raw disconnect error stack:', err.stack || err.message);
            }

            const loggedOut = statusCode === DisconnectReason.loggedOut;

            if (loggedOut) {
                try {
                    console.log('[Baileys] Logged out -> removing auth info for fresh pairing');
                    if (fs.existsSync(AUTH_INFO_PATH)) {
                        fs.rmSync(AUTH_INFO_PATH, { recursive: true, force: true });
                    }
                } catch (e) {
                    console.log('[Baileys] Failed to remove auth info', e.message);
                }
            }
            scheduleReconnect(disconnectReason, loggedOut);
        } else if (connection === 'open') {
            console.log('✅ Connected to WhatsApp!');
            appProperties.is_connected = true;
            appProperties.botNumber = sock.user.id.split(':')[0];
            reconnectAttempts = 0;
            if (CONFIG.WA_ARCHIVE_ENABLED && sock.groupFetchAllParticipating) {
                sock.groupFetchAllParticipating()
                    .then(async (groups) => {
                        const cache = await getGroupCache();
                        for (const group of Object.values(groups || {})) {
                            await upsertGroup(group);
                            cache.set(group.id, group);
                        }
                        console.log(`[wa-archive] refreshed ${Object.keys(groups || {}).length} group metadata records`);
                    })
                    .catch((e) => console.error('[wa-archive] group metadata refresh:', e.message));
            }
            onWhatsAppConnected();
        } else if (connection) {
            // intermediate states: connecting, etc.
            console.log('[Baileys] Connection state update:', connection);
        }
    });

    // Keep group metadata cache updated (Baileys best practice)
    sock.ev.on('groups.update', async ([event]) => {
        try { const cache = await getGroupCache(); cache.set(event.id, await sock.groupMetadata(event.id)); } catch {}
    });
    sock.ev.on('group-participants.update', async (event) => {
        try { const cache = await getGroupCache(); cache.set(event.id, await sock.groupMetadata(event.id)); } catch {}
    });

    sock.ev.on('messages.upsert', async (msg) => {
        for (let message of msg.messages) {
            const _waSpanId = (message?.key?.id || Math.random().toString(36).slice(2)) + ':' + Date.now();
            const _waFrom = message?.key?.remoteJid || 'unknown';
            const _waFromMe = !!message?.key?.fromMe;
            const _waType = message?.message ? Object.keys(message.message)[0] : 'unknown';
            const _waStart = Date.now();
            console.log('WA_SPAN ' + JSON.stringify({ evt: 'msg_start', id: _waSpanId, from: _waFrom, fromMe: _waFromMe, type: _waType, ts: _waStart }));
            let _waOk = true, _waErr = null;
            try {
                // Dev agent group — full dev access, takes highest priority
                const handledByDev = await handleDevMention(sock, message);
                if (handledByDev) {
                    // handled by dev agent, skip other handlers
                } else {
                    // Group @mention agent — takes priority over normal bot logic
                    const handledByAgent = await handleGroupMention(sock, message);
                    if (!handledByAgent) {
                        await onMessage(sock, message);
                    }
                }
            } catch (e) {
                _waOk = false; _waErr = e.message;
                console.log('[Baileys] onMessage handler error:', e.message);
            } finally {
                const _waEnd = Date.now();
                console.log('WA_SPAN ' + JSON.stringify({ evt: 'msg_end', id: _waSpanId, ok: _waOk, err: _waErr, dur: _waEnd - _waStart, ts: _waEnd }));
            }
        }
    });
};

module.exports = { runBaileyesApp };