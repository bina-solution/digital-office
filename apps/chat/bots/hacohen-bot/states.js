/**
 * The bot's conversation state machine + menu vocabulary.
 *
 * Its own file because index.js and agent_sessions.js both need it and a circular require between
 * those two would be the only alternative. Nothing here touches a transport — a state is a property
 * of the PERSON (stored on the subscriber record), not of the socket they arrived on, which is why
 * the whole state machine survived the port unchanged.
 */

const STATES = {
    NEW: 'new',
    AWAIT_GENERIC_DOCUMENT_FILE: 'await_generic_document_file',
    AWAIT_BALANCE_SHEET_FILE: 'await_balance_sheet_file',
    AWAIT_BALANCE_SHEET_COMPANY: 'await_balance_sheet_company',
    AWAIT_LINK_DOCUMENT: 'await_link_document',
    AGENT_CHAT: 'agent_chat',
    DISPATCHER: 'dispatcher'
};

// State timeout: reset awaiting states older than 24 hours
const STATE_TIMEOUT_MS = 24 * 60 * 60 * 1000;
const AWAITING_STATES = [
    STATES.AWAIT_GENERIC_DOCUMENT_FILE,
    STATES.AWAIT_BALANCE_SHEET_FILE,
    STATES.AWAIT_BALANCE_SHEET_COMPANY,
    STATES.AWAIT_LINK_DOCUMENT
];

// User menu choice constants
const MENU_CHOICES = {
    HELLO_BACK: '1',
    ABOUT: '2',
    BALANCE_SHEET: '10', // Admin: upload balance sheet
    GENERIC_DOCUMENT: '11', // Admin: upload generic document
    LINK_DOCUMENT: '12', // Admin: intake document from URL
    RELOAD_SETTINGS: '13', // Admin: reload settings from external source
    SUNDAY_REPORT: '14', // Admin: full Sunday deployment review (~12m)
    QUICK_HEALTH: '15', // Admin: fast health snapshot (~1-3m)
    DEPLOYMENT_REVIEW: '16', // Admin: mid-depth deployment review (~5-8m)
    AGENT_STATUS: '17', // Admin: what is the agent-runner sidecar doing right now?
    AGENT_CANCEL: '18', // Admin: cancel the currently running agent-runner job
    SECURITY_REVIEW: '19', // Admin: fast security review (~3-5m)
    STORAGE_REPORT: '20', // Admin: storage/disk/DB/volumes report (~3-5m)
    AGENT_CHAT: '21', // Admin: live read-only chat with the deployment agent
    DISPATCHER: '22' // Admin: OpenHands autonomous coding (read-write)
};

// Regex for cancellation words (Hebrew "ביטול" or English cancel / stop / exit)
const CANCEL_REGEX = /(ביטול|cancel|stop|exit)/i;

// Extract first URL from text message
const URL_REGEX = /https?:\/\/[^\s<>"']+/i;
const extractUrl = (text) => {
    if (!text) return null;
    const match = String(text).match(URL_REGEX);
    return match ? match[0] : null;
};

module.exports = {
    STATES, STATE_TIMEOUT_MS, AWAITING_STATES, MENU_CHOICES, CANCEL_REGEX, URL_REGEX, extractUrl,
};
