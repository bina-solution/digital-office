/**
 * Manages live progress updates to the WhatsApp group during agent execution.
 *
 * Strategy:
 *  - Phase 1: React 👀 to the user's @mention message immediately.
 *  - Phase 2: Send a status message (reply to @mention).
 *  - Phase 3: Throttled edits to that status message as tools run (max 1 per 3s).
 *  - Phase 4: Send final answer as a new reply. React ✅ to original.
 *             Keepalive: edit status message every 90s if no tool events arrive.
 */

const EDIT_THROTTLE_MS = 3000;    // minimum gap between edits
const KEEPALIVE_MS    = 90_000;   // edit status to show still alive

class ProgressReporter {
    constructor(sock, groupJid, originalMsgKey, senderJid, senderName) {
        this.sock = sock;
        this.groupJid = groupJid;
        this.originalMsgKey = originalMsgKey;
        this.senderJid = senderJid;
        this.senderName = senderName;

        this.statusMsgKey = null;       // key of the status message we sent
        this.completedTools = [];       // list of completed tool summaries
        this.currentTool = null;        // currently running tool label or null
        this._pendingText = null;
        this._editTimer = null;
        this._lastEditAt = 0;
        this._keepaliveTimer = null;
        this._startTs = Date.now();
        this._done = false;
    }

    /** Phase 1 — instant ACK reaction */
    async ack() {
        try {
            await this.sock.sendMessage(this.groupJid, {
                react: { text: '...', key: this.originalMsgKey }
            });
        } catch { /* non-fatal */ }
    }

    /** Phase 2 — send initial status message */
    async sendStatus(taskText) {
        const preview = taskText.length > 60 ? taskText.slice(0, 57) + '...' : taskText;
        const text = `*${this.senderName}* — ${preview}\nworking...`;
        try {
            const result = await this.sock.sendMessage(
                this.groupJid,
                { text },
                { quoted: { key: this.originalMsgKey, message: {} } }
            );
            this.statusMsgKey = result?.key || null;
            this._resetKeepalive();
        } catch { /* non-fatal */ }
    }

    /** Called by agent stream on each tool_use event */
    onToolStart(toolName, toolInput) {
        if (this.currentTool) {
            this.completedTools.push(`[ok] ${this.currentTool}`);
        }
        const ctx = summarizeInput(toolInput);
        this.currentTool = `${toolName}${ctx ? ' ' + ctx : ''}`;
        this._scheduleEdit();
    }

    /** Called when tool finishes — mark current tool as done */
    onToolDone() {
        if (this.currentTool) {
            this.completedTools.push(`[ok] ${this.currentTool}`);
            this.currentTool = null;
        }
        this._scheduleEdit();
    }

    /** Called when tool result is received — append result preview */
    onToolResult(outputPreview, isError) {
        if (!isError && outputPreview && this.completedTools.length > 0) {
            const last = this.completedTools[this.completedTools.length - 1];
            if (last.startsWith('[ok] ') && !last.includes(' -> ')) {
                const preview = outputPreview.slice(0, 60).replace(/\n/g, ' ');
                this.completedTools[this.completedTools.length - 1] = last + ' -> ' + preview;
                this._scheduleEdit();
            }
        }
    }

    /** Flush any pending edit immediately, then send the final answer */
    async sendFinalAnswer(answerText) {
        this._done = true;
        this._clearKeepalive();
        clearTimeout(this._editTimer);
        this._editTimer = null;

        const elapsed = ((Date.now() - this._startTs) / 1000).toFixed(1);

        // Finalize the status message
        if (this.statusMsgKey) {
            const toolsSummary = this.completedTools.slice(-5).join('\n') || '';
            const doneStatus = [toolsSummary, `[done] ${elapsed}s`].filter(Boolean).join('\n');
            await this._editStatus(doneStatus);
        }

        // Send final answer as new message (triggers notification)
        const mention = `@${this.senderJid.split('@')[0]}`;
        const fullText = `${mention}\n${answerText}`;
        try {
            const result = await this.sock.sendMessage(
                this.groupJid,
                { text: fullText, mentions: [this.senderJid] },
                { quoted: { key: this.originalMsgKey, message: {} } }
            );
            await this.sock.sendMessage(this.groupJid, {
                react: { text: 'ok', key: this.originalMsgKey }
            });
            return result?.key || null;
        } catch { return null; }
    }

    async sendError(errText) {
        this._done = true;
        this._clearKeepalive();
        clearTimeout(this._editTimer);

        if (this.statusMsgKey) {
            await this._editStatus(`[err] ${errText}`);
        }
        try {
            await this.sock.sendMessage(this.groupJid, {
                react: { text: 'x', key: this.originalMsgKey }
            });
        } catch { /* non-fatal */ }
    }

    // ─── internals ───────────────────────────────────────────────────────────

    _buildStatusText() {
        const lines = [...this.completedTools.slice(-5)];
        if (this.currentTool) lines.push(this.currentTool);
        const elapsed = ((Date.now() - this._startTs) / 1000).toFixed(0);
        lines.push(`${elapsed}s...`);
        return lines.join('\n');
    }

    _scheduleEdit() {
        if (this._done || !this.statusMsgKey) return;
        this._pendingText = this._buildStatusText();
        if (this._editTimer) return; // already queued
        const delay = Math.max(0, EDIT_THROTTLE_MS - (Date.now() - this._lastEditAt));
        this._editTimer = setTimeout(() => this._flush(), delay);
    }

    async _flush() {
        this._editTimer = null;
        if (!this._pendingText || !this.statusMsgKey || this._done) return;
        const text = this._pendingText;
        this._pendingText = null;
        await this._editStatus(text);
    }

    async _editStatus(text) {
        if (!this.statusMsgKey) return;
        try {
            await this.sock.sendMessage(this.groupJid, {
                edit: this.statusMsgKey,
                text
            });
            this._lastEditAt = Date.now();
        } catch (e) { /* edit may fail if message too old — non-fatal */ }
    }

    _resetKeepalive() {
        this._clearKeepalive();
        this._keepaliveTimer = setInterval(async () => {
            if (this._done) { this._clearKeepalive(); return; }
            const elapsed = ((Date.now() - this._startTs) / 1000).toFixed(0);
            const text = [...this.completedTools.slice(-3), `⏳ עדיין עובד... (${elapsed}s)`].join('\n');
            await this._editStatus(text);
        }, KEEPALIVE_MS);
    }

    _clearKeepalive() {
        if (this._keepaliveTimer) {
            clearInterval(this._keepaliveTimer);
            this._keepaliveTimer = null;
        }
    }
}

/** Produce a short human-readable summary of tool input */
const summarizeInput = (input) => {
    if (!input) return '';
    if (typeof input === 'string') return input.slice(0, 60);
    if (typeof input === 'object') {
        // Common Claude tool fields
        if (input.file_path) return `📄 ${input.file_path.split('/').pop() || input.file_path}`;
        if (input.command) return `💻 \`${String(input.command).slice(0, 40)}\``;
        if (input.pattern) return `🔍 ${String(input.pattern).slice(0, 40)}`;
        if (input.query) return `🔍 "${String(input.query).slice(0, 40)}"`;
        // Pick the first meaningful string value
        for (const v of Object.values(input)) {
            if (typeof v === 'string' && v.length > 0 && v.length < 80) return v;
        }
    }
    return '';
};

module.exports = { ProgressReporter };
