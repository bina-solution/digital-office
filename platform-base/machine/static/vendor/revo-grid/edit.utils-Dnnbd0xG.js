/*!
 * Built by Revolist OU ❤️
 */
import { O as KeyCodesEnum, P as OsPlatform, I as codesLetter, J as keyValues, E as EDIT_INPUT_WR } from './dimension.helpers-CGKwSvw6.js';

function isMetaKey(code) {
    const keys = [
        KeyCodesEnum.ARROW_DOWN,
        KeyCodesEnum.ARROW_UP,
        KeyCodesEnum.ARROW_LEFT,
        KeyCodesEnum.ARROW_RIGHT,
        KeyCodesEnum.HOME,
        KeyCodesEnum.END,
        KeyCodesEnum.DELETE,
        KeyCodesEnum.BACKSPACE,
        KeyCodesEnum.F1,
        KeyCodesEnum.F2,
        KeyCodesEnum.F3,
        KeyCodesEnum.F4,
        KeyCodesEnum.F5,
        KeyCodesEnum.F6,
        KeyCodesEnum.F7,
        KeyCodesEnum.F8,
        KeyCodesEnum.F9,
        KeyCodesEnum.F10,
        KeyCodesEnum.F11,
        KeyCodesEnum.F12,
        KeyCodesEnum.TAB,
        KeyCodesEnum.PAGE_DOWN,
        KeyCodesEnum.PAGE_UP,
        KeyCodesEnum.ENTER,
        KeyCodesEnum.ESCAPE,
        KeyCodesEnum.SHIFT,
        KeyCodesEnum.CAPS_LOCK,
        KeyCodesEnum.ALT,
    ];
    return keys.indexOf(code) !== -1;
}
// navigator.platform
function isCtrlKey(code, platform) {
    if (platform.includes(OsPlatform.mac)) {
        return [
            KeyCodesEnum.COMMAND_LEFT,
            KeyCodesEnum.COMMAND_RIGHT,
            KeyCodesEnum.COMMAND_FIREFOX,
        ].includes(code);
    }
    return code === KeyCodesEnum.CONTROL;
}
function isCtrlMetaKey(code) {
    return [
        KeyCodesEnum.CONTROL,
        KeyCodesEnum.COMMAND_LEFT,
        KeyCodesEnum.COMMAND_RIGHT,
        KeyCodesEnum.COMMAND_FIREFOX,
    ].includes(code);
}
function isClear(code) {
    return codesLetter.BACKSPACE === code || codesLetter.DELETE === code;
}
function isTab(code) {
    return codesLetter.TAB === code;
}
function isTabKeyValue(key) {
    return keyValues.TAB === key;
}
function isEnterKeyValue(key) {
    return keyValues.ENTER === key;
}
function isCut(event) {
    return ((event.ctrlKey && event.code === 'KeyX') || // Ctrl + X on Windows
        (event.metaKey && event.code === 'KeyX')); // Cmd + X on Mac
}
function isCopy(event) {
    return ((event.ctrlKey && event.code === 'KeyC') || // Ctrl + C on Windows
        (event.metaKey && event.code === 'KeyC')); // Cmd + C on Mac
}
function isPaste(event) {
    return ((event.ctrlKey && event.code === 'KeyV') || // Ctrl + V on Windows
        (event.metaKey && event.code === 'KeyV')); // Cmd + V on Mac
}
function isAll(event) {
    return ((event.ctrlKey && event.code === 'KeyA') || // Ctrl + A on Windows
        (event.metaKey && event.code === 'KeyA')); // Cmd + A on Mac
}
/**
 * Returns true when a keyboard event represents a shortcut modifier that
 * should not start cell editing from printable `event.key` input.
 *
 * AltGr is intentionally excluded because many Windows/Linux layouts expose
 * printable AltGr characters as Ctrl+Alt key events.
 */
function isShortcutModifier(event) {
    var _a;
    if ((_a = event.getModifierState) === null || _a === void 0 ? void 0 : _a.call(event, 'AltGraph')) {
        return false;
    }
    if (event.ctrlKey &&
        event.altKey &&
        !event.metaKey &&
        event.key.length === 1) {
        return false;
    }
    return event.ctrlKey || event.metaKey;
}

// is edit input
function isEditInput(el) {
    return !!(el === null || el === void 0 ? void 0 : el.closest(`.${EDIT_INPUT_WR}`));
}
// Type guard for EditorCtrConstructible
function isEditorCtrConstructible(editor) {
    return typeof editor === 'function' && typeof editor.prototype === 'object';
}

export { isCtrlKey as a, isCtrlMetaKey as b, isClear as c, isTab as d, isTabKeyValue as e, isEnterKeyValue as f, isCut as g, isCopy as h, isMetaKey as i, isPaste as j, isAll as k, isShortcutModifier as l, isEditInput as m, isEditorCtrConstructible as n };
