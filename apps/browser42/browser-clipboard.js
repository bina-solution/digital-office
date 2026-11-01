// browser42-clipboard.js — ONE clipboard between the owner's computer and the shared Chromium.
//
// Injected into noVNC's viewer by start-browser.sh (section 4b). Design notes, and the traps this
// file exists for, are in ai/context/browser42-cli.md. Two rules govern everything here:
//
//   1. noVNC maps Cmd to Alt for a Linux remote (core/input/keyboard.js: XK_Super_L -> XK_Alt_L), so
//      a Cmd chord arrives at the remote as Alt+<key> unless it is undone first and restored after.
//      Without that, Cmd+C / Cmd+V / Cmd+X reach Linux as Alt+… and do nothing, silently.
//   2. On X11, SELECTING text is a clipboard event (the PRIMARY selection) and TigerVNC forwards it,
//      so the remote clipboard changes constantly without the owner copying anything. Writing those
//      down would replace his clipboard all day (including passwords). Only a change that follows an
//      explicit copy/cut chord may touch his computer's clipboard.
//
// Chromium-only (the async Clipboard API is what makes this possible at all); on anything else every
// path here fails quietly and noVNC's manual Clipboard panel remains the way to move text.

import UI from "./ui.js";

const XK_CTRL = 0xffe3;
const XK_ALT = 0xffe9;
const XK_SUPER = 0xffeb;

// Cmd chords that mean the Ctrl chord on a Linux remote. Cmd+V is handled separately: it also has to
// upload the clipboard first. Deliberately NOT every Cmd shortcut — Cmd+W as Ctrl+W would close a tab
// of the shared browser by accident.
const CMD_AS_CTRL = { c: [0x63, "KeyC"], x: [0x78, "KeyX"] };
const V = [0x76, "KeyV"];

// What noVNC sends for each physical Cmd key (mirrors its own mapping).
const CMD_AS_ALT = { MetaLeft: [XK_ALT, "AltLeft"], MetaRight: [XK_SUPER, "SuperLeft"] };

const SYNC_REMOTE_TO_LOCAL = true;   // false = upload only, never write to the owner's clipboard
const COPY_INTENT_MS = 3000;         // a remote change this soon after C/X is the owner's own copy
const READ_BUDGET_MS = 400;          // Chromium can leave a clipboard READ pending indefinitely

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

const heldCmd = new Set();           // physical Cmd keys currently down
let pushed = "";                     // last text sent up, so its echo is not written straight back
let lastRemote = "";
let copyIntentAt = 0;
let warned = false;

// Diagnosis surface, deliberately small: this bridge cannot be verified from the server side (the
// clipboard it reads lives in the owner's browser), so it reports what it did where a test — or the
// owner's devtools console — can see it.
const state = { attached: false, connected: false, isMac, pushes: [], remoteWrites: [], skipped: 0, lastError: null };
window.__b42clipboard = state;

const tap = (keysym, code) => {
    UI.rfb.sendKey(keysym, code, true);
    UI.rfb.sendKey(keysym, code, false);
};

const isCmdOrCtrl = (e) => (e.ctrlKey && !e.metaKey) || (e.metaKey && !e.ctrlKey);

// One short, self-erasing line at the bottom of the view — the only failure the owner cannot see.
function hint(message) {
    let el = document.getElementById("b42clip_hint");
    if (!el) {
        el = document.createElement("div");
        el.id = "b42clip_hint";
        el.style.cssText = "position:fixed;left:50%;transform:translateX(-50%);bottom:18px;z-index:9999;"
            + "background:rgba(20,20,20,.92);color:#fff;padding:8px 14px;border-radius:6px;"
            + "font:13px/1.5 sans-serif;direction:rtl;max-width:80vw;pointer-events:none;display:none";
        document.body.appendChild(el);
    }
    el.textContent = message;
    el.style.display = "block";
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.style.display = "none"; }, 7000);
}

// Undo what noVNC sent for the Cmd keys the owner is holding; returns what must be pressed again.
function releaseCmdModifiers() {
    const undone = [];
    if (!isMac) return undone;
    for (const code of heldCmd) {
        const mapped = CMD_AS_ALT[code];
        if (!mapped) continue;
        UI.rfb.sendKey(mapped[0], mapped[1], false);
        undone.push(mapped);
    }
    return undone;
}

const restoreModifiers = (undone) => undone.forEach(([keysym, code]) => UI.rfb.sendKey(keysym, code, true));

// The local clipboard is read under a budget: Chromium does not always REJECT a read it cannot serve
// — an unfocused document can leave readText() pending forever, which would freeze the paste with no
// key ever sent. Past the budget we skip the upload and forward Ctrl+V as before.
async function readLocalClipboard() {
    try {
        return await Promise.race([
            navigator.clipboard.readText(),
            new Promise((resolve) => setTimeout(() => resolve(null), READ_BUDGET_MS)),
        ]);
    } catch (err) {
        state.lastError = String((err && err.name) || err);
        return null;
    }
}

// Upload the local clipboard, then paste: the text must reach the remote before the key does, or the
// remote pastes what it already had.
async function pasteFromLocalClipboard(e) {
    const undone = releaseCmdModifiers();
    const text = await readLocalClipboard();
    if (text === null && !warned) {
        warned = true;
        hint("הדבקה מהמחשב: לא הצלחתי לקרוא את הלוח. אשר \"Allow\" לחלון של כרום (או השתמש בפאנל הלוח) ונסה שוב.");
    }
    if (text) {
        pushed = text;
        state.pushes.push(text.slice(0, 40));
        UI.rfb.clipboardPasteFrom(text);
    }
    // Ctrl is ALWAYS sent from here rather than assumed: whether noVNC already forwarded a physical
    // Ctrl-down is not something this code can rely on, a duplicate Ctrl-down is idempotent on the
    // remote, and Cmd+V has to synthesize it anyway. Skipping it when the event carried ctrlKey made
    // the up-direction test paste a literal "v" instead of the clipboard — caught 2026-09-23.
    UI.rfb.sendKey(XK_CTRL, "ControlLeft", true);
    tap(V[0], V[1]);
    UI.rfb.sendKey(XK_CTRL, "ControlLeft", false);
    restoreModifiers(undone);
}

// Cmd+C / Cmd+X: send the Ctrl chord the Linux remote understands, and remember that the clipboard
// change which follows is the owner's own copy or cut.
function sendTranslatedChord(letter) {
    copyIntentAt = Date.now();
    const undone = releaseCmdModifiers();
    const [keysym, code] = CMD_AS_CTRL[letter];
    UI.rfb.sendKey(XK_CTRL, "ControlLeft", true);
    tap(keysym, code);
    UI.rfb.sendKey(XK_CTRL, "ControlLeft", false);
    restoreModifiers(undone);
}

// Capture phase on `document`: runs before noVNC's handler (which sits on the canvas, bubble phase),
// so stopping the event here is what keeps a chord from being forwarded twice.
function onKeyDown(e) {
    const code = e.code || "";
    if (code in CMD_AS_ALT) heldCmd.add(code);
    if (!UI.rfb || e.altKey || e.shiftKey || !isCmdOrCtrl(e)) return;

    const key = (e.key || "").toLowerCase();
    if (key === "v") {
        e.stopImmediatePropagation();
        e.preventDefault();
        pasteFromLocalClipboard(e);
        return;
    }
    if (key === "c" || key === "x") {
        if (isMac) {
            // Cmd+C / Cmd+X must become Ctrl+C / Ctrl+X on the Linux remote.
            e.stopImmediatePropagation();
            e.preventDefault();
            sendTranslatedChord(key);
        } else {
            // Windows/Linux already send the right chord — but the intent still has to be recorded,
            // or a cut would never reach the owner's clipboard (2026-09-23: Ctrl+X deleted the text
            // and left his clipboard untouched, because only C set the intent).
            copyIntentAt = Date.now();
        }
    }
}

function onKeyUp(e) {
    const code = e.code || "";
    if (code in CMD_AS_ALT) heldCmd.delete(code);
    if (!UI.rfb || e.altKey || e.shiftKey || !isCmdOrCtrl(e)) return;
    const key = (e.key || "").toLowerCase();
    if (key === "v" || (isMac && (key === "c" || key === "x"))) {
        e.stopImmediatePropagation();
        e.preventDefault();
    }
}

// Remote -> local, gated on the owner having asked for a copy or a cut (rule 2 above).
function onRemoteClipboard(e) {
    if (!SYNC_REMOTE_TO_LOCAL) return;
    const text = e.detail.text;
    if (!text || text === lastRemote) return;
    lastRemote = text;
    if (text === pushed) return;                  // our own upload coming back
    if (Date.now() - copyIntentAt > COPY_INTENT_MS) {
        state.skipped++;                          // a selection, not a copy: leave the clipboard alone
        return;
    }
    state.remoteWrites.push(text.slice(0, 40));
    navigator.clipboard.writeText(text).catch((err) => { state.lastError = String(err); });
}

// UI.rfb exists only once the viewer starts connecting, and noVNC's UI emits no event of its own.
function attach() {
    if (!UI.rfb) return false;
    UI.rfb.addEventListener("clipboard", onRemoteClipboard);
    UI.rfb.addEventListener("connect", () => { state.connected = true; });
    UI.rfb.addEventListener("disconnect", () => { state.connected = false; });
    state.attached = true;
    return true;
}

document.addEventListener("keydown", onKeyDown, true);
document.addEventListener("keyup", onKeyUp, true);
if (!attach()) {
    const timer = setInterval(() => { if (attach()) clearInterval(timer); }, 250);
}
