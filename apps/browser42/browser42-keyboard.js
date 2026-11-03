// browser42-keyboard.js — typing on a phone, into a screen made of pixels (DGO-575).
//
// THE DEFECT, MEASURED. The office view is noVNC 1.6: the remote desktop is drawn as PIXELS, so
// tapping a field in it is a click on a <canvas>, and a canvas has no input to focus — the phone's
// keyboard never opens. noVNC opens it from exactly two doors, and both are one call:
//   app/ui.js  showVirtualKeyboard()  ->  focuses #noVNC_keyboardinput (inside the user's gesture)
//              toggleVirtualKeyboard()      the toolbar button #noVNC_keyboard_button calls
// and both sit inside the control bar — which noVNC ITSELF closes two seconds after connecting
// (`UI.closeControlbar`, ui.js) and which collapses to a 12px handle. On the owner's phone
// (2026-10-14, DGO-575's screenshot) the bar was collapsed, so neither door was in view: he tapped a
// field and nothing happened, with no way to ask for the keyboard.
//
// WHAT THIS ADDS — touch devices only, so the agent's own Chromium and every screenshot of it are
// unchanged (and `UI.showVirtualKeyboard()` is itself a no-op off a touch device):
//
//   1. A TAP ON THE SCREEN OPENS THE KEYBOARD. The tap is still forwarded to the remote by noVNC, so
//      it also focuses the field that was tapped; `showVirtualKeyboard()` then focuses the keyboard
//      input inside the same user gesture, which is what a browser requires before it will raise a
//      keyboard — and noVNC keeps that focus (`onfocusVirtualKeyboard` turns `rfb.focusOnClick` off),
//      so typing continues to land in the remote field.
//      A DRAG IS NOT A TAP: moving the desktop, scrolling or a long press must open nothing, so a
//      touch is classified by distance and duration before it counts.
//   2. A KEYBOARD BUTTON THAT IS NOT IN THE CONTROL BAR, so it is reachable while the bar is
//      collapsed — the same `UI.toggleVirtualKeyboard()` the toolbar's button calls, drawn under the
//      bar's own handle and hidden while the bar is open (there the toolbar's button is in view).
//
// Injected into noVNC's viewer by start-browser.sh (4b), the same way browser-navigation.js and
// browser-clipboard.js are — see ai/context/browser42-cli.md.

import UI from "./ui.js";

const KEYBOARD_INPUT = "noVNC_keyboardinput";
const TAP_MAX_MS = 900;     // a tap, not a press-and-hold
const TAP_MAX_PX = 12;      // a tap, not a drag across the desktop

const isTouch = ("ontouchstart" in window) || (navigator.maxTouchPoints || 0) > 0;

// Diagnosis surface, in the shape browser-clipboard.js uses: this module's real gesture happens on
// the owner's phone, where nothing here can be observed from the server — so it reports what it did
// where a test, or his devtools console, can read it.
const state = { attached: false, isTouch, taps: 0, drags: 0, opens: 0, focused: null, lastError: null };
window.__b42keyboard = state;

// The screen itself — not the control bar, not our button. noVNC builds its canvas on connect and
// replaces it on reconnect, so this is asked of the event rather than captured at load.
function isScreen(target) {
    return target instanceof HTMLCanvasElement
        && target.closest("#noVNC_container, #noVNC_screen") !== null;
}

function openKeyboard() {
    try {
        UI.showVirtualKeyboard();                       // noVNC's own door, unchanged
        state.opens++;
        state.focused = document.activeElement ? document.activeElement.id : null;
    } catch (err) {
        state.lastError = String(err);
    }
    paint();
}

let down = null;

function onTouchStart(e) {
    down = null;
    if (e.touches.length !== 1 || !isScreen(e.target)) return;
    const t = e.touches[0];
    down = { x: t.clientX, y: t.clientY, at: Date.now() };
}

function onTouchEnd(e) {
    const started = down;
    down = null;
    if (!started) return;
    const t = e.changedTouches && e.changedTouches[0];
    if (!t) return;
    const moved = Math.hypot(t.clientX - started.x, t.clientY - started.y);
    if (moved > TAP_MAX_PX || Date.now() - started.at > TAP_MAX_MS) {
        state.drags++;
        return;
    }
    state.taps++;
    openKeyboard();
}

// ── the button ────────────────────────────────────────────────────────────────────────────────────
// Positioned under the control bar's handle, on the same edge the bar lives on, so it reads as part
// of the viewer's own controls and covers neither the remote's window buttons (top right) nor its
// tab strip (top).
function paint() {
    const el = document.getElementById("b42kb_button");
    if (!el) return;
    const active = document.activeElement && document.activeElement.id === KEYBOARD_INPUT;
    state.focused = active ? KEYBOARD_INPUT : null;
    el.style.opacity = active ? "1" : ".7";
    el.style.background = active ? "rgba(46,125,50,.85)" : "rgba(20,20,20,.5)";
}

function syncButton() {
    const el = document.getElementById("b42kb_button");
    if (!el) return;
    const bar = document.getElementById("noVNC_control_bar");
    const connected = document.documentElement.classList.contains("noVNC_connected");
    el.style.display = (connected && !(bar && bar.classList.contains("noVNC_open"))) ? "block" : "none";
}

function addButton() {
    if (document.getElementById("b42kb_button")) return;
    const el = document.createElement("img");
    el.id = "b42kb_button";
    el.src = "app/images/keyboard.svg";
    el.alt = "מקלדת";
    el.title = "מקלדת הטלפון";
    el.style.cssText = "position:fixed;left:3px;top:50%;margin-top:32px;width:38px;height:38px;"
        + "padding:6px;box-sizing:border-box;border-radius:9px;z-index:9999;cursor:pointer;"
        + "background:rgba(20,20,20,.5);opacity:.7;-webkit-tap-highlight-color:transparent";
    el.addEventListener("click", (e) => {
        e.preventDefault();
        UI.toggleVirtualKeyboard();
        paint();
    });
    document.body.appendChild(el);
    syncButton();
}

function attach() {
    addButton();
    const input = document.getElementById(KEYBOARD_INPUT);
    if (input) {
        input.addEventListener("focus", paint);
        input.addEventListener("blur", paint);
    }
    // The bar can be collapsed or dragged out at any moment; whether our button belongs on screen
    // follows it rather than being decided once.
    const bar = document.getElementById("noVNC_control_bar");
    if (bar && window.MutationObserver) {
        new MutationObserver(syncButton).observe(bar, { attributes: true, attributeFilter: ["class"] });
    }
    const root = document.documentElement;
    if (root && window.MutationObserver) {
        new MutationObserver(syncButton).observe(root, { attributes: true, attributeFilter: ["class"] });
    }
    document.addEventListener("touchstart", onTouchStart, true);
    document.addEventListener("touchend", onTouchEnd, true);
    state.attached = true;
}

if (isTouch) attach();
