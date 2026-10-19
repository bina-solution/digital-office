/*!
 * Built by Revolist OU ❤️
 */
import { d as isTab, f as isEnterKeyValue } from './edit.utils-Dnnbd0xG.js';
import { t as timeout } from './index-Db3qZoW5.js';

class TextEditor {
    constructor(data, saveCallback) {
        this.data = data;
        this.saveCallback = saveCallback;
        this.editInput = null;
        this.element = null;
        this.editCell = undefined;
    }
    /**
     * Callback triggered on cell editor render
     */
    async componentDidRender() {
        var _a;
        if (this.editInput) {
            await timeout();
            (_a = this.editInput) === null || _a === void 0 ? void 0 : _a.focus();
        }
    }
    onKeyDown(e) {
        const isEnter = isEnterKeyValue(e.key);
        const isKeyTab = isTab(e.key);
        if ((isKeyTab || isEnter) &&
            e.target &&
            this.saveCallback &&
            !e.isComposing) {
            // blur is needed to avoid autoscroll
            this.beforeDisconnect();
            // request callback which will close cell after all
            this.saveCallback(this.getValue(), isKeyTab);
        }
    }
    /**
     * IMPORTANT: Prevent scroll glitches when editor is closed and focus is on current input element.
     */
    beforeDisconnect() {
        var _a;
        (_a = this.editInput) === null || _a === void 0 ? void 0 : _a.blur();
    }
    /**
     * Get value from input
     */
    getValue() {
        var _a;
        return (_a = this.editInput) === null || _a === void 0 ? void 0 : _a.value;
    }
    /**
     * Render method for Editor plugin.
     * Renders input element with passed data from cell.
     * @param {Function} h - h function from stencil render.
     * @param {Object} _additionalData - additional data from plugin.
     * @returns {VNode} - input element.
     */
    render(h, _additionalData) {
        var _a, _b;
        return h('input', {
            type: 'text',
            enterKeyHint: 'enter',
            // set input value from cell data
            value: (_b = (_a = this.editCell) === null || _a === void 0 ? void 0 : _a.val) !== null && _b !== void 0 ? _b : '',
            // save input element as ref for further usage
            ref: (el) => {
                this.editInput = el;
            },
            // listen to keydown event on input element
            onKeyDown: (e) => this.onKeyDown(e),
        });
    }
}

export { TextEditor as T };
