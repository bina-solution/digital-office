/*!
 * Built by Revolist OU ❤️
 */
import { r as registerInstance, h, e as Host, d as createEvent, g as getElement } from './index-Chp_81rd.js';
import { k as getItemByIndex, b as getSourceItem, j as getItemByPosition, F as FOCUS_CLASS, I as codesLetter, R as RESIZE_INTERVAL, y as MOBILE_CLASS, z as CELL_HANDLER_CLASS, S as SELECTION_BORDER_CLASS, D as DataStore, q as ROW_HEADER_TYPE, T as TMP_SELECTION_BG_CLASS } from './dimension.helpers-CGKwSvw6.js';
import { g as getPropertyFromEvent, v as verifyTouchTarget } from './events-BvSmBueA.js';
import { g as getRange, M as ColumnService, z as getCellData, N as getCellEditor, b as isRangeSingleCell } from './column.service-C6hByxPy.js';
import { l as isShortcutModifier, m as isEditInput, c as isClear, d as isTab, f as isEnterKeyValue, h as isCopy, g as isCut, j as isPaste, k as isAll } from './edit.utils-Dnnbd0xG.js';
import { t as timeout, g as getScrollbarSize } from './index-Db3qZoW5.js';
import { d as debounce } from './debounce-PCRWZliA.js';
import { V as ViewportStore, j as calculateRowHeaderSize } from './viewport.store-_c579YyM.js';
import { H as HEADER_SLOT } from './viewport.helpers-CoCAvmZs.js';
import { L as LocalScrollTimer, a as LocalScrollService, g as getContentSize, t as throttle } from './throttle-Cpk1LoGk.js';

const Attribution = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
    }
    render() {
        return (h(Host, { key: '3d66475a019010c24b6c610ccc047e01c35178f9' }, h("a", { key: '777afddffef0309a697b9c14ee73c0001ac22b71', href: "https://rv-grid.com/guide/attribution", target: "_blank", rel: "noopener noreferrer", title: "Made with \u2764\uFE0F by Revolist OU Team", class: "value" }, "RevoGrid")));
    }
};

const RevoGridExtra = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        /**
         * Nodes to render
         */
        this.nodes = [];
        /**
         * Force component to re-render
         */
        this.update = 1;
    }
    /**
     * Refreshes the extra component. Useful if you want to manually
     * force the component to re-render.
     */
    async refresh() {
        this.update *= -1;
    }
    render() {
        var _a;
        return (_a = this.nodes) === null || _a === void 0 ? void 0 : _a.map(node => {
            // Check if node is a function or a stencil component
            // If function wrap it in a stencil component with the refresh function
            if (typeof node === 'function') {
                const config = {};
                const getNodes = () => [node({ refresh: () => { var _a; return (_a = config.refresh) === null || _a === void 0 ? void 0 : _a.call(config); } })];
                return (h("revogr-extra", { nodes: getNodes(), ref: (el) => {
                        if (el) {
                            // Update exclusively for current node
                            config.refresh = () => {
                                el.nodes = getNodes();
                            };
                        }
                    } }));
            }
            return node;
        });
    }
};

function collectModelsOfRange(data, store) {
    const models = {};
    for (let i in data) {
        const rowIndex = parseInt(i, 10);
        models[rowIndex] = getSourceItem(store, rowIndex);
    }
    return models;
}
function getFocusCellBasedOnEvent(e, data) {
    // If event default is prevented, return
    if (e.defaultPrevented) {
        return null;
    }
    // Get coordinates from event object
    const x = getPropertyFromEvent(e, 'clientX');
    const y = getPropertyFromEvent(e, 'clientY');
    // If coordinates are not available, return
    if (x === null || y === null) {
        return null;
    }
    // Get current cell based on coordinates and data
    const focusCell = getCurrentCell({ x, y }, data);
    // If current cell is not available, return
    if (isAfterLast(focusCell, data.lastCell)) {
        return null;
    }
    return focusCell;
}
/**
 * Calculate cell based on x, y position
 */
function getCurrentCell({ x, y }, { el, rows, cols }) {
    // Get the bounding rectangle of the element
    const { top, left, height, width } = el.getBoundingClientRect();
    // Calculate the cell position relative to the element
    let cellY = y - top;
    let cellX = x - left;
    // Limit the cell position to the element height
    if (cellY >= height) {
        cellY = height - 1;
    }
    // Limit the cell position to the element width
    if (cellX >= width) {
        cellX = width - 1;
    }
    // Get the row and column items based on the cell position
    const rgRow = getItemByPosition(rows, cellY + (rows.renderOffset || 0));
    const rgCol = getItemByPosition(cols, cellX + (cols.renderOffset || 0));
    // Set the row and column index to 0 if they are before the first item
    if (rgCol.itemIndex < 0) {
        rgCol.itemIndex = 0;
    }
    if (rgRow.itemIndex < 0) {
        rgRow.itemIndex = 0;
    }
    return { x: rgCol.itemIndex, y: rgRow.itemIndex };
}
function getCoordinate(range, focus, changes, isMulti = false) {
    const updateCoordinate = (c, pos = 0) => {
        const start = { x: range.x, y: range.y };
        const end = isMulti ? { x: range.x1, y: range.y1 } : start;
        const point = end[c] > focus[c] ? end : start;
        point[c] += pos;
        return { start, end };
    };
    if (changes.x) {
        return updateCoordinate('x', changes['x']);
    }
    if (changes.y) {
        return updateCoordinate('y', changes['y']);
    }
    return null;
}
/**
 * Check if the x coordinate of the cell position is after or equal to the x coordinate of the last cell position
 * or if the y coordinate of the cell position is after or equal to the y coordinate of the last cell position
 */
function isAfterLast({ x, y }, lastCell) {
    return x >= lastCell.x || y >= lastCell.y;
}
/** check if out of range */
function isBeforeFirst({ x, y }) {
    return x < 0 || y < 0;
}
/** Compare cells, only 1 coordinate difference is possible */
// export function getDirectionCoordinate(initial: Cell, last: Cell): Partial<Cell> | null {
//   const c: (keyof Cell)[] = ['x', 'y'];
//   for (let k of c) {
//     if (initial[k] !== last[k]) {
//       return { [k]: 1 };
//     }
//   }
//   return null;
// }
// export function getLargestAxis(initial: Cell, last: Cell): Partial<Cell> | null {
//   const cell: Partial<Cell> = {};
//   const c: (keyof Cell)[] = ['x', 'y'];
//   for (let k of c) {
//     cell[k] = Math.abs(initial[k] - last[k]);
//   }
//   if (cell.x > cell.y) {
//     return { x: 1 };
//   }
//   if (cell.y > cell.x) {
//     return { y: 1 };
//   }
//   return null;
// }
function styleByCellProps(styles) {
    return {
        left: `${styles.left}px`,
        top: `${styles.top}px`,
        width: `${styles.width}px`,
        height: `${styles.height}px`,
    };
}
function getCell({ x, y, x1, y1 }, dimensionRow, dimensionCol) {
    const rowOffset = dimensionRow.renderOffset || 0;
    const colOffset = dimensionCol.renderOffset || 0;
    const top = getItemByIndex(dimensionRow, y).start - rowOffset;
    const left = getItemByIndex(dimensionCol, x).start - colOffset;
    const bottom = getItemByIndex(dimensionRow, y1).end - rowOffset;
    const right = getItemByIndex(dimensionCol, x1).end - colOffset;
    return {
        left,
        right,
        top,
        bottom,
        width: right - left,
        height: bottom - top,
    };
}

const revogrFocusStyleCss = () => `revogr-focus.focused-cell{box-shadow:-1px 0 0 #0d63e8 inset, 1px 0 0 #0d63e8 inset, 0 -1px 0 #0d63e8 inset, 0 1px 0 #0d63e8 inset;position:absolute;pointer-events:none;z-index:9;display:block !important}`;

const RevogrFocus$1 = class RevogrFocus {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.beforeFocusRender = createEvent(this, "beforefocusrender", 7);
        this.beforeScrollIntoView = createEvent(this, "beforescrollintoview", 7);
        this.afterFocus = createEvent(this, "afterfocus", 7);
        /**
         * Focus template custom function. Can be used to render custom focus layer.
         */
        this.focusTemplate = null;
        this.activeFocus = null;
    }
    componentDidRender() {
        var _a, _b;
        const currentFocus = this.selectionStore.get('focus');
        if (((_a = this.activeFocus) === null || _a === void 0 ? void 0 : _a.x) === (currentFocus === null || currentFocus === void 0 ? void 0 : currentFocus.x) &&
            ((_b = this.activeFocus) === null || _b === void 0 ? void 0 : _b.y) === (currentFocus === null || currentFocus === void 0 ? void 0 : currentFocus.y)) {
            return;
        }
        this.activeFocus = currentFocus;
        if (currentFocus && this.el) {
            const beforeScrollIn = this.beforeScrollIntoView.emit({ el: this.el });
            if (!beforeScrollIn.defaultPrevented) {
                this.el.scrollIntoView({
                    block: 'nearest',
                    inline: 'nearest',
                });
            }
            const model = getSourceItem(this.dataStore, currentFocus.y);
            const column = getSourceItem(this.colData, currentFocus.x);
            this.afterFocus.emit({
                model,
                column,
                rowType: this.rowType,
                colType: this.colType,
                rowIndex: currentFocus.y,
                colIndex: currentFocus.x,
            });
        }
    }
    render() {
        var _a;
        const editCell = this.selectionStore.get('edit');
        if (editCell) {
            return;
        }
        const focusCell = this.selectionStore.get('focus');
        if (!focusCell) {
            return;
        }
        const event = this.beforeFocusRender.emit({
            range: Object.assign(Object.assign({}, focusCell), { x1: focusCell.x, y1: focusCell.y }),
            rowType: this.rowType,
            colType: this.colType,
            rowDimension: Object.assign({}, this.dimensionRow.state),
            colDimension: Object.assign({}, this.dimensionCol.state),
        });
        if (event.defaultPrevented) {
            return h("slot", null);
        }
        const { detail } = event;
        const cell = getCell(detail.range, event.detail.rowDimension, event.detail.colDimension);
        const styles = styleByCellProps(cell);
        const extra = (_a = this.focusTemplate) === null || _a === void 0 ? void 0 : _a.call(this, h, detail);
        const props = {
            class: { [FOCUS_CLASS]: true },
            style: styles,
        };
        return (h(Host, Object.assign({}, props), h("slot", null), extra));
    }
    get el() { return getElement(this); }
};
RevogrFocus$1.style = revogrFocusStyleCss();

const DIRECTION_CODES = [
    codesLetter.TAB,
    codesLetter.ARROW_UP,
    codesLetter.ARROW_DOWN,
    codesLetter.ARROW_LEFT,
    codesLetter.ARROW_RIGHT,
];
class KeyboardService {
    constructor(sv) {
        this.sv = sv;
    }
    /**
     * Appends printable key input that arrives after edit mode was requested
     * but before the editor input has mounted or received focus.
     */
    appendPendingEditValue(e) {
        if (isShortcutModifier(e) ||
            e.key.length !== 1 ||
            (e.target instanceof HTMLElement && isEditInput(e.target))) {
            return false;
        }
        const editCell = this.sv.selectionStore.get('edit');
        if (typeof (editCell === null || editCell === void 0 ? void 0 : editCell.val) !== 'string') {
            return false;
        }
        this.sv.selectionStore.set('edit', Object.assign(Object.assign({}, editCell), { val: `${editCell.val}${e.key}` }));
        return true;
    }
    async keyDown(e, canRange, isEditMode, { range, focus }) {
        // IF EDIT MODE
        if (isEditMode) {
            if (this.appendPendingEditValue(e)) {
                return;
            }
            switch (e.code) {
                case codesLetter.ESCAPE:
                    this.sv.cancel();
                    break;
                case codesLetter.TAB:
                    this.keyChangeSelection(e, canRange);
                    break;
            }
            return;
        }
        // IF NOT EDIT MODE
        // pressed clear key
        if (range && isClear(e.code)) {
            this.sv.clearCell();
            return;
        }
        // below works with focus only
        if (!focus) {
            return;
        }
        // tab key means same as arrow right
        if (isTab(e.code)) {
            this.keyChangeSelection(e, canRange);
            return;
        }
        // pressed enter
        if (isEnterKeyValue(e.key)) {
            this.sv.change();
            return;
        }
        // copy operation
        if (isCopy(e)) {
            return;
        }
        // cut operation
        if (isCut(e)) {
            return;
        }
        // paste operation
        if (isPaste(e)) {
            this.sv.internalPaste();
            return;
        }
        // select all
        if (isAll(e)) {
            if (canRange) {
                this.selectAll(e);
            }
            return;
        }
        // pressed letter key
        if (!isShortcutModifier(e) && e.key.length === 1) {
            this.sv.change(e.key);
            return;
        }
        // pressed arrow, change selection position
        if (await this.keyChangeSelection(e, canRange)) {
            return;
        }
    }
    selectAll(e) {
        const range = this.sv.selectionStore.get('range');
        const focus = this.sv.selectionStore.get('focus');
        // if no range or focus - do nothing
        if (!range || !focus) {
            return;
        }
        e.preventDefault();
        this.sv.selectAll();
    }
    async keyChangeSelection(e, canRange) {
        const data = this.changeDirectionKey(e, canRange);
        if (!data) {
            return false;
        }
        // this interval needed for several cases
        // grid could be resized before next click
        // at this case to avoid screen jump we use this interval
        await timeout(RESIZE_INTERVAL + 30);
        const range = this.sv.selectionStore.get('range');
        const focus = this.sv.selectionStore.get('focus');
        return this.keyPositionChange(data.changes, range, focus, data.isMulti);
    }
    keyPositionChange(changes, range, focus, isMulti = false) {
        if (!range || !focus) {
            return false;
        }
        const data = getCoordinate(range, focus, changes, isMulti);
        if (!data) {
            return false;
        }
        const eData = this.sv.getData();
        if (isMulti) {
            const isOutOfBounds = [data.start, data.end].some(cell => isAfterLast(cell, eData.lastCell) || isBeforeFirst(cell));
            if (isOutOfBounds) {
                return false;
            }
            const range = getRange(data.start, data.end);
            return this.sv.range(range);
        }
        return this.sv.focus(data.start, changes, isAfterLast(data.start, eData.lastCell)
            ? 1
            : isBeforeFirst(data.start)
                ? -1
                : 0);
    }
    /** Monitor key direction changes */
    changeDirectionKey(e, canRange) {
        const isMulti = canRange && e.shiftKey;
        if (DIRECTION_CODES.includes(e.code)) {
            e.preventDefault();
        }
        if (e.shiftKey) {
            switch (e.code) {
                case codesLetter.TAB:
                    return { changes: { x: -1 }, isMulti: false };
            }
        }
        switch (e.code) {
            case codesLetter.ARROW_UP:
                return { changes: { y: -1 }, isMulti };
            case codesLetter.ARROW_DOWN:
                return { changes: { y: 1 }, isMulti };
            case codesLetter.ARROW_LEFT:
                return { changes: { x: -1 }, isMulti };
            case codesLetter.TAB:
            case codesLetter.ARROW_RIGHT:
                return { changes: { x: 1 }, isMulti };
        }
    }
}

class AutoFillService {
    constructor(sv) {
        this.sv = sv;
        this.autoFillType = null;
        this.autoFillInitial = null;
        this.autoFillStart = null;
        this.autoFillLast = null;
    }
    /**
     * Render autofill box
     * @param range
     * @param selectionFocus
     */
    renderAutofill(range, selectionFocus, isMobile = false) {
        let handlerStyle;
        if (range) {
            handlerStyle = getCell(range, this.sv.dimensionRow.state, this.sv.dimensionCol.state);
        }
        else {
            handlerStyle = getCell(Object.assign(Object.assign({}, selectionFocus), { x1: selectionFocus.x, y1: selectionFocus.y }), this.sv.dimensionRow.state, this.sv.dimensionCol.state);
        }
        return (h("div", { class: {
                [CELL_HANDLER_CLASS]: true,
                [MOBILE_CLASS]: isMobile,
            }, style: {
                left: `${handlerStyle.right}px`,
                top: `${handlerStyle.bottom}px`,
            }, onMouseDown: (e) => this.autoFillHandler(e), onTouchStart: (e) => this.autoFillHandler(e) }));
    }
    autoFillHandler(e, type = "AutoFill" /* AutoFillType.autoFill */) {
        let target = null;
        if (e.target instanceof Element) {
            target = e.target;
        }
        if (!target) {
            return;
        }
        this.selectionStart(target, this.sv.getData(), type);
        e.preventDefault();
    }
    get isAutoFill() {
        return !!this.autoFillType;
    }
    /**
     * Process mouse move events
     */
    selectionMouseMove(e) {
        // initiate mouse move debounce if not present
        if (!this.onMouseMoveAutofill) {
            this.onMouseMoveAutofill = debounce((e, data) => this.doAutofillMouseMove(e, data), 5);
        }
        if (this.isAutoFill) {
            this.onMouseMoveAutofill(e, this.sv.getData());
        }
    }
    getFocus(focus, range) {
        // there was an issue that it was taking last cell from range but focus was out
        if (!focus && range) {
            focus = { x: range.x, y: range.y };
        }
        return focus || null;
    }
    /**
     * Autofill logic:
     * on mouse move apply based on previous direction (if present)
     */
    doAutofillMouseMove(event, data) {
        // if no initial - not started
        if (!this.autoFillInitial) {
            return;
        }
        const x = getPropertyFromEvent(event, 'clientX', MOBILE_CLASS);
        const y = getPropertyFromEvent(event, 'clientY', MOBILE_CLASS);
        // skip touch
        if (x === null || y === null) {
            return;
        }
        const current = getCurrentCell({ x, y }, data);
        // first time or direction equal to start(same as first time)
        if (!this.autoFillLast) {
            if (!this.autoFillLast) {
                this.autoFillLast = this.autoFillStart;
            }
        }
        // check if not the latest, if latest - do nothing
        if (isAfterLast(current, data.lastCell)) {
            return;
        }
        this.autoFillLast = current;
        const isSame = current.x === this.autoFillInitial.x &&
            current.y === this.autoFillInitial.y;
        // if same as initial - clear
        if (isSame) {
            this.sv.setTempRange(null);
        }
        else {
            const area = getRange(this.autoFillInitial, this.autoFillLast);
            this.sv.setTempRange({
                area,
                type: this.autoFillType,
            });
        }
    }
    /**
     * Range selection started
     * Mode @param type:
     * Can be triggered from MouseDown selection on element
     * Or can be triggered on corner square drag
     */
    selectionStart(target, data, type = "Selection" /* AutoFillType.selection */) {
        /** Get cell by autofill element */
        const { top, left } = target.getBoundingClientRect();
        this.autoFillInitial = this.getFocus(data.focus, data.range);
        this.autoFillType = type;
        this.autoFillStart = getCurrentCell({ x: left, y: top }, data);
    }
    /**
     * Clear current range selection on mouse up and mouse leave events
     */
    clearAutoFillSelection(focus, oldRange) {
        // If autofill was active, apply autofill values
        if (this.autoFillInitial) {
            // Fetch latest focus
            this.autoFillInitial = this.getFocus(focus, oldRange);
            // Apply range data if autofill mode is active
            if (this.autoFillType === "AutoFill" /* AutoFillType.autoFill */) {
                const range = getRange(this.autoFillInitial, this.autoFillLast);
                // If range is present, apply data
                if (range) {
                    const { defaultPrevented: stopApply, detail: { range: newRange }, } = this.sv.clearRangeDataApply({
                        range,
                    });
                    // If data apply was not prevented, apply new range
                    if (!stopApply && oldRange) {
                        this.applyRangeWithData(newRange, oldRange);
                    }
                    else {
                        // If data apply was prevented, clear temporary range
                        this.sv.setTempRange(null);
                    }
                }
            }
            else {
                // If not autofill mode, apply range only
                this.applyRangeOnly(this.autoFillInitial, this.autoFillLast);
            }
        }
        // Reset autofill state
        this.resetAutoFillState();
    }
    /**
     * Reset autofill state
     */
    resetAutoFillState() {
        this.autoFillType = null;
        this.autoFillInitial = null;
        this.autoFillLast = null;
        this.autoFillStart = null;
    }
    /**
     * Trigger range apply events and handle responses
     */
    onRangeApply(newData, newRange, oldRange) {
        this.sv.rangeDataApply({
            data: newData,
            models: collectModelsOfRange(newData, this.sv.dataStore),
            type: this.sv.dataStore.get('type'),
            oldRange,
            newRange
        });
        this.sv.setRange(newRange);
    }
    /** Apply range and copy data during range application */
    applyRangeWithData(newRange, rangeToCopy) {
        const rangeData = {
            type: this.sv.dataStore.get('type'),
            colType: this.sv.columnService.type,
            newData: {},
            mapping: {},
            newRange,
            oldRange: rangeToCopy,
        };
        const { mapping, changed } = this.sv.columnService.getRangeData(rangeData, this.sv.columnService.columns);
        rangeData.newData = changed;
        rangeData.mapping = mapping;
        let e = this.sv.selectionChanged(rangeData);
        // if default prevented - clear range
        if (e.defaultPrevented) {
            this.sv.setTempRange(null);
            return;
        }
        e = this.sv.rangeCopy(rangeData);
        if (e.defaultPrevented) {
            this.sv.setRange(newRange);
            return;
        }
        this.onRangeApply(rangeData.newData, newRange, rangeToCopy);
    }
    /**
     * Update range selection only,
     * no data change (mouse selection)
     */
    applyRangeOnly(start, end) {
        // no changes to apply
        if (!start || !end) {
            return;
        }
        const newRange = getRange(start, end);
        this.sv.setRange(newRange);
    }
}

function getRangeFillClipboardData(data, useClipboard) {
    var _a;
    if (!isClipboardRangeFillEnabled(useClipboard)) {
        return null;
    }
    const normalized = trimTrailingEmptyClipboardRows(data);
    return normalized.length === 1 && ((_a = normalized[0]) === null || _a === void 0 ? void 0 : _a.length) === 1
        ? normalized
        : null;
}
function isClipboardRangeFillEnabled(useClipboard) {
    return (typeof useClipboard === 'object' && useClipboard.rangeFill === true);
}
function trimTrailingEmptyClipboardRows(data) {
    const rows = [...data];
    while (rows.length > 1 && isEmptyClipboardRow(rows[rows.length - 1])) {
        rows.pop();
    }
    return rows;
}
function isEmptyClipboardRow(row) {
    return !row || row.every(cell => cell === '');
}

const revogrOverlayStyleCss = () => `revogr-overlay-selection{display:block;position:relative;width:100%}revogr-overlay-selection .autofill-handle{position:absolute;width:14px;height:14px;margin-left:-13px;margin-top:-13px;z-index:10;cursor:crosshair}revogr-overlay-selection .autofill-handle::before{content:"";position:absolute;right:0;bottom:0;width:10px;height:10px;background:#0d63e8;border:1px solid white;box-sizing:border-box}revogr-overlay-selection.mobile .autofill-handle{position:absolute;width:30px;height:30px;margin-left:-29px;margin-top:-29px;z-index:10;cursor:crosshair}revogr-overlay-selection.mobile .autofill-handle::before{content:"";position:absolute;right:0;bottom:0;width:12px;height:12px;background:#0d63e8;border:1px solid white;box-sizing:border-box}revogr-overlay-selection .selection-border-range{position:absolute;pointer-events:none;z-index:9;box-shadow:-1px 0 0 #0d63e8 inset, 1px 0 0 #0d63e8 inset, 0 -1px 0 #0d63e8 inset, 0 1px 0 #0d63e8 inset}revogr-overlay-selection .selection-border-range .range-handlers{height:100%;background-color:transparent;width:75%;max-width:50px;min-width:20px;left:50%;transform:translateX(-50%);position:absolute}revogr-overlay-selection .selection-border-range .range-handlers>span{pointer-events:auto;height:20px;width:20px;position:absolute;left:50%;transform:translateX(-50%)}revogr-overlay-selection .selection-border-range .range-handlers>span:before,revogr-overlay-selection .selection-border-range .range-handlers>span:after{position:absolute;border-radius:5px;width:15px;height:5px;left:50%;transform:translateX(-50%);background-color:rgba(0, 0, 0, 0.2)}revogr-overlay-selection .selection-border-range .range-handlers>span:first-child{top:-7px}revogr-overlay-selection .selection-border-range .range-handlers>span:first-child:before{content:"";top:0}revogr-overlay-selection .selection-border-range .range-handlers>span:last-child{bottom:-7px}revogr-overlay-selection .selection-border-range .range-handlers>span:last-child:after{content:"";bottom:0}revogr-overlay-selection revogr-edit{z-index:10}`;

const OverlaySelection = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.beforeCopyRegion = createEvent(this, "beforecopyregion", 7);
        this.beforeRegionPaste = createEvent(this, "beforepasteregion", 7);
        this.cellEditApply = createEvent(this, "celleditapply", 7);
        this.beforeFocusCell = createEvent(this, "beforecellfocusinit", 7);
        this.beforeNextViewportFocus = createEvent(this, "beforenextvpfocus", 7);
        this.setEdit = createEvent(this, "setedit", 7);
        this.beforeApplyRange = createEvent(this, "beforeapplyrange", 7);
        this.beforeSetRange = createEvent(this, "beforesetrange", 7);
        this.setRange = createEvent(this, "setrange", 7);
        this.beforeEditRender = createEvent(this, "beforeeditrender", 7);
        this.selectAll = createEvent(this, "selectall", 7);
        this.cancelEdit = createEvent(this, "canceledit", 7);
        this.setTempRange = createEvent(this, "settemprange", 7);
        this.beforeSetTempRange = createEvent(this, "beforesettemprange", 7);
        this.applyFocus = createEvent(this, "applyfocus", 7);
        this.focusCell = createEvent(this, "focuscell", 7);
        this.beforeRangeDataApply = createEvent(this, "beforerangedataapply", 7);
        this.selectionChange = createEvent(this, "selectionchangeinit", 7);
        this.beforeRangeCopyApply = createEvent(this, "beforerangecopyapply", 7);
        this.rangeEditApply = createEvent(this, "rangeeditapply", 7);
        this.rangeClipboardCopy = createEvent(this, "clipboardrangecopy", 7);
        this.rangeClipboardPaste = createEvent(this, "clipboardrangepaste", 7);
        this.beforeKeyDown = createEvent(this, "beforekeydown", 7);
        this.beforeKeyUp = createEvent(this, "beforekeyup", 7);
        this.beforeCellSave = createEvent(this, "beforecellsave", 7);
        this.cellEditDone = createEvent(this, "celledit", 7);
        /**
         * If true applys changes when cell closes if not Escape.
         */
        this.applyChangesOnClose = false;
        this.keyboardService = null;
        this.autoFillService = null;
        this.unsubscribeSelectionStore = [];
    }
    // #endregion
    // #region Listeners
    onMouseMove(e) {
        var _a;
        if (this.selectionStore.get('focus')) {
            (_a = this.autoFillService) === null || _a === void 0 ? void 0 : _a.selectionMouseMove(e);
        }
    }
    /**
     * Action finished inside the document.
     * Pointer left document, clear any active operation.
     */
    onMouseUp() {
        var _a;
        // Clear autofill selection
        // when pointer left document,
        // clear any active operation.
        (_a = this.autoFillService) === null || _a === void 0 ? void 0 : _a.clearAutoFillSelection(this.selectionStore.get('focus'), this.selectionStore.get('range'));
    }
    /**
     * Row drag started.
     * This event is fired when drag action started on cell.
     */
    onCellDrag(e) {
        var _a;
        // Invoke drag start on order editor.
        (_a = this.orderEditor) === null || _a === void 0 ? void 0 : _a.dragStart(e.detail);
    }
    /**
     * Get keyboard down from element.
     * This event is fired when keyboard key is released.
     */
    onKeyUp(e) {
        // Emit before key up event.
        this.beforeKeyUp.emit(Object.assign({ original: e }, this.getData()));
    }
    /**
     * Get keyboard down from element.
     * This event is fired when keyboard key is pressed.
     */
    onKeyDown(e) {
        var _a;
        // Emit before key down event and check if default prevention is set.
        const proxy = this.beforeKeyDown.emit(Object.assign({ original: e }, this.getData()));
        if (e.defaultPrevented || proxy.defaultPrevented) {
            return;
        }
        // Invoke key down on keyboard service.
        (_a = this.keyboardService) === null || _a === void 0 ? void 0 : _a.keyDown(e, this.range, !!this.selectionStore.get('edit'), {
            focus: this.selectionStore.get('focus'),
            range: this.selectionStore.get('range'),
        });
    }
    // #endregion
    /**
     * Selection & Keyboard
     */
    selectionServiceSet(selectionStore) {
        // clear subscriptions
        this.unsubscribeSelectionStore.forEach(v => v());
        this.unsubscribeSelectionStore.length = 0;
        this.unsubscribeSelectionStore.push(selectionStore.onChange('nextFocus', v => v && this.doFocus(v, v)));
        this.keyboardService = new KeyboardService({
            selectionStore,
            range: r => !!r && this.triggerRangeEvent(r),
            focus: (f, changes, focusNextViewport) => {
                if (focusNextViewport) {
                    this.beforeNextViewportFocus.emit(f);
                    return false;
                }
                else {
                    return this.doFocus(f, f, changes);
                }
            },
            change: val => {
                if (this.readonly) {
                    return;
                }
                this.doEdit(val);
            },
            cancel: async () => {
                var _a;
                await ((_a = this.revogrEdit) === null || _a === void 0 ? void 0 : _a.cancelChanges());
                this.closeEdit();
            },
            clearCell: () => !this.readonly && this.clearCell(),
            internalPaste: () => !this.readonly && this.beforeRegionPaste.emit(),
            getData: () => this.getData(),
            selectAll: () => this.selectAll.emit(),
        });
        this.createAutoFillService();
    }
    /** Autofill */
    createAutoFillService() {
        this.autoFillService = new AutoFillService({
            dimensionRow: this.dimensionRow,
            dimensionCol: this.dimensionCol,
            columnService: this.columnService,
            dataStore: this.dataStore,
            clearRangeDataApply: e => this.beforeRangeDataApply.emit(Object.assign(Object.assign(Object.assign({}, e), this.types), { rowDimension: Object.assign({}, this.dimensionRow.state), colDimension: Object.assign({}, this.dimensionCol.state) })),
            setTempRange: e => {
                const tempRangeEvent = this.beforeSetTempRange.emit(Object.assign(Object.assign({ tempRange: e }, this.getData()), this.types));
                if (tempRangeEvent.defaultPrevented) {
                    return null;
                }
                return this.setTempRange.emit(tempRangeEvent.detail.tempRange);
            },
            selectionChanged: e => this.selectionChange.emit(e),
            rangeCopy: e => this.beforeRangeCopyApply.emit(e),
            rangeDataApply: e => this.rangeEditApply.emit(e),
            setRange: e => !!e && this.triggerRangeEvent(e),
            getData: () => this.getData(),
        });
    }
    /** Columns */
    columnServiceSet() {
        var _a;
        (_a = this.columnService) === null || _a === void 0 ? void 0 : _a.destroy();
        this.columnService = new ColumnService(this.dataStore, this.colData);
        this.createAutoFillService();
    }
    connectedCallback() {
        this.columnServiceSet();
        this.selectionServiceSet(this.selectionStore);
    }
    disconnectedCallback() {
        var _a;
        // clear subscriptions
        this.unsubscribeSelectionStore.forEach(v => v());
        this.unsubscribeSelectionStore.length = 0;
        (_a = this.columnService) === null || _a === void 0 ? void 0 : _a.destroy();
    }
    async componentWillRender() {
        var _a, _b;
        const editCell = this.selectionStore.get('edit');
        if (!editCell) {
            await ((_b = (_a = this.revogrEdit) === null || _a === void 0 ? void 0 : _a.beforeDisconnect) === null || _b === void 0 ? void 0 : _b.call(_a));
        }
    }
    renderRange(range) {
        const cell = getCell(range, this.dimensionRow.state, this.dimensionCol.state);
        const styles = styleByCellProps(cell);
        return [
            h("div", { class: SELECTION_BORDER_CLASS, style: styles }, this.isMobileDevice && (h("div", { class: "range-handlers" }, h("span", { class: MOBILE_CLASS }), h("span", { class: MOBILE_CLASS })))),
        ];
    }
    renderEditor() {
        // Check if edit access
        const editCell = this.selectionStore.get('edit');
        // Readonly or Editor closed
        if (this.readonly || !editCell) {
            return null;
        }
        const enteredOrModelValue = editCell.val ||
            getCellData(this.columnService.rowDataModel(editCell.y, editCell.x).value);
        const editable = Object.assign(Object.assign({}, editCell), this.columnService.getSaveData(editCell.y, editCell.x, enteredOrModelValue));
        const renderEvent = this.beforeEditRender.emit(Object.assign(Object.assign({ range: Object.assign(Object.assign({}, editCell), { x1: editCell.x, y1: editCell.y }) }, this.types), { rowDimension: Object.assign({}, this.dimensionRow.state), colDimension: Object.assign({}, this.dimensionCol.state) }));
        // Render prevented
        if (renderEvent.defaultPrevented) {
            return null;
        }
        const cell = getCell(renderEvent.detail.range, renderEvent.detail.rowDimension, renderEvent.detail.colDimension);
        const styles = styleByCellProps(cell);
        return (h("revogr-edit", { style: styles, ref: el => (this.revogrEdit = el), additionalData: this.additionalData, editCell: editable, saveOnClose: this.applyChangesOnClose, onCelleditinit: (e) => {
                this.cellEditDone.emit(e.detail);
            }, column: this.columnService.rowDataModel(editCell.y, editCell.x), editor: getCellEditor(this.columnService.columns[editCell.x], this.editors) }));
    }
    onEditCell(e) {
        if (e.defaultPrevented) {
            return;
        }
        const saveEv = this.beforeCellSave.emit(e.detail);
        if (!saveEv.defaultPrevented) {
            this.cellEdit(saveEv.detail);
        }
        // if not clear navigate to next cell after edit
        if (!saveEv.detail.preventFocus) {
            this.focusNext();
        }
    }
    render() {
        var _a;
        const nodes = [];
        const editCell = this.renderEditor();
        // Editor
        if (editCell) {
            nodes.push(editCell);
        }
        else {
            const range = this.selectionStore.get('range');
            const focus = this.selectionStore.get('focus');
            // Clipboard
            if ((range || focus) && this.useClipboard) {
                nodes.push(h("revogr-clipboard", { readonly: this.readonly, onCopyregion: e => this.onCopy(e.detail), onClearregion: () => !this.readonly && this.clearCell(), ref: e => (this.clipboard = e), onPasteregion: e => this.onPaste(e.detail) }));
            }
            // Range
            if (range) {
                nodes.push(...this.renderRange(range));
            }
            // Autofill
            if (focus && !this.readonly && this.range) {
                nodes.push((_a = this.autoFillService) === null || _a === void 0 ? void 0 : _a.renderAutofill(range, focus, this.isMobileDevice));
            }
            // Order
            if (this.canDrag) {
                nodes.push(h("revogr-order-editor", { ref: e => (this.orderEditor = e), dataStore: this.dataStore, dimensionRow: this.dimensionRow, dimensionCol: this.dimensionCol, parent: this.element, rowType: this.types.rowType, onRowdragstartinit: e => this.rowDragStart(e) }));
            }
        }
        return (h(Host, { key: 'ff303c39d59e4ef217421fa11b9a80de07311b07', class: { mobile: this.isMobileDevice }, onDblClick: (e) => this.onElementDblClick(e), onMouseDown: (e) => this.onElementMouseDown(e), onTouchStart: (e) => this.onElementMouseDown(e, true), onCloseedit: (e) => this.closeEdit(e),
            // it's done to be able to throw events from different levels, not just from editor
            onCelledit: (e) => this.onEditCell(e) }, nodes, h("slot", { key: '3cbe4c3ad7d447f779e9e20f73eec2e3107275e0', name: "data" })));
    }
    /**
     * Executes the focus operation on the specified range of cells.
     */
    doFocus(focus, end, changes, originalEvent) {
        // 1. Trigger beforeFocus event
        const { defaultPrevented } = this.beforeFocusCell.emit(Object.assign(Object.assign({}, this.columnService.getSaveData(focus.y, focus.x)), { originalEvent }));
        if (defaultPrevented) {
            return false;
        }
        const evData = Object.assign(Object.assign({ range: Object.assign(Object.assign({}, focus), { x1: end.x, y1: end.y }), next: changes }, this.types), { rowDimension: Object.assign({}, this.dimensionRow.state), colDimension: Object.assign({}, this.dimensionCol.state), originalEvent });
        // 2. Trigger apply focus event
        const applyEvent = this.applyFocus.emit(evData);
        if (applyEvent.defaultPrevented) {
            return false;
        }
        const { range } = applyEvent.detail;
        // 3. Trigger focus event
        return !this.focusCell.emit(Object.assign({ focus: {
                x: range.x,
                y: range.y,
            }, end: {
                x: range.x1,
                y: range.y1,
            } }, applyEvent.detail)).defaultPrevented;
    }
    triggerRangeEvent(range, originalEvent) {
        const type = this.types.rowType;
        // 1. Apply range
        const applyEvent = this.beforeApplyRange.emit(Object.assign(Object.assign({ range: Object.assign({}, range) }, this.types), { rowDimension: Object.assign({}, this.dimensionRow.state), colDimension: Object.assign({}, this.dimensionCol.state), originalEvent }));
        if (applyEvent.defaultPrevented) {
            return false;
        }
        const data = this.columnService.getRangeTransformedToProps(applyEvent.detail.range, this.dataStore);
        // 2. Before set range
        let e = this.beforeSetRange.emit(data);
        if (e.defaultPrevented) {
            return false;
        }
        // 3. Set range
        e = this.setRange.emit(Object.assign(Object.assign({}, applyEvent.detail.range), { type }));
        if (e.defaultPrevented) {
            return false;
        }
        return !e.defaultPrevented;
    }
    /**
     * Open Editor on DblClick
     */
    onElementDblClick(e) {
        // DblClick prevented outside - Editor will not open
        if (e.defaultPrevented) {
            return;
        }
        // Get data from the component
        const data = this.getData();
        const focusCell = getFocusCellBasedOnEvent(e, data);
        if (!focusCell) {
            return;
        }
        this.doEdit();
    }
    /**
     * Handle mouse down event on Host element
     */
    onElementMouseDown(e, touch = false) {
        var _a;
        // Get the target element from the event object
        const targetElement = e.target;
        // Ignore focus if clicked input
        if (isEditInput(targetElement) || e.defaultPrevented) {
            return;
        }
        // Get data from the component
        const data = this.getData();
        const focusCell = getFocusCellBasedOnEvent(e, data);
        if (!focusCell) {
            return;
        }
        // Set focus on the current cell
        this.focus(focusCell, this.range && e.shiftKey, e);
        // Initiate autofill selection
        if (this.range) {
            targetElement &&
                ((_a = this.autoFillService) === null || _a === void 0 ? void 0 : _a.selectionStart(targetElement, this.getData()));
            // Prevent default behavior for mouse events,
            // but only if target element is not a mobile input
            if (!touch) {
                e.preventDefault();
            }
            else if (verifyTouchTarget(e.touches[0], MOBILE_CLASS)) {
                // Prevent default behavior for touch events
                // if target element is a mobile input
                e.preventDefault();
            }
        }
    }
    /**
     * Start cell editing
     */
    doEdit(val = '') {
        var _a;
        if (this.canEdit()) {
            const focus = this.selectionStore.get('focus');
            if (!focus) {
                return;
            }
            const data = this.columnService.getSaveData(focus.y, focus.x);
            (_a = this.setEdit) === null || _a === void 0 ? void 0 : _a.emit(Object.assign(Object.assign({}, data), { val }));
        }
    }
    /**
     * Close editor event triggered
     * @param details - if it requires focus next
     */
    async closeEdit(e) {
        this.cancelEdit.emit();
        if (e === null || e === void 0 ? void 0 : e.detail) {
            await this.focusNext();
        }
    }
    /**
     * Edit finished.
     * Close Editor and save.
     */
    cellEdit(e) {
        const dataToSave = this.columnService.getSaveData(e.rgRow, e.rgCol, e.val);
        this.cellEditApply.emit(dataToSave);
    }
    getRegion() {
        const focus = this.selectionStore.get('focus');
        let range = this.selectionStore.get('range');
        if (!range) {
            range = getRange(focus, focus);
        }
        return range;
    }
    onCopy(e) {
        var _a;
        const range = this.getRegion();
        const canCopyEvent = this.beforeCopyRegion.emit(range);
        if (canCopyEvent.defaultPrevented) {
            return false;
        }
        let rangeData;
        if (range) {
            const { data, mapping } = this.columnService.copyRangeArray(range, this.dataStore);
            const event = this.rangeClipboardCopy.emit(Object.assign({ range,
                data,
                mapping }, this.types));
            if (!event.defaultPrevented) {
                rangeData = event.detail.data;
            }
        }
        (_a = this.clipboard) === null || _a === void 0 ? void 0 : _a.doCopy(e, rangeData);
        return true;
    }
    onPaste(data) {
        var _a;
        const focus = this.selectionStore.get('focus');
        const isEditing = this.selectionStore.get('edit') !== null;
        if (!focus || isEditing) {
            return;
        }
        const rangeFillData = getRangeFillClipboardData(data, this.useClipboard);
        const targetRange = rangeFillData
            ? this.getClipboardPasteTargetRange()
            : null;
        let { changed, range } = this.columnService.getTransformedDataToApply({
            start: focus,
            data: rangeFillData || data,
            targetRange,
        });
        const { defaultPrevented: canPaste } = this.rangeClipboardPaste.emit(Object.assign({ data: changed, models: collectModelsOfRange(changed, this.dataStore), range }, this.types));
        if (canPaste) {
            return;
        }
        (_a = this.autoFillService) === null || _a === void 0 ? void 0 : _a.onRangeApply(changed, range, range);
    }
    getClipboardPasteTargetRange() {
        const range = this.selectionStore.get('range');
        return range && !isRangeSingleCell(range) ? range : null;
    }
    async focusNext() {
        var _a;
        const canFocus = await ((_a = this.keyboardService) === null || _a === void 0 ? void 0 : _a.keyChangeSelection(new KeyboardEvent('keydown', {
            code: codesLetter.ARROW_DOWN,
        }), this.range));
        if (!canFocus) {
            this.closeEdit();
        }
    }
    clearCell() {
        var _a;
        const range = this.selectionStore.get('range');
        if (range && !isRangeSingleCell(range)) {
            const data = this.columnService.getRangeStaticData(range, '');
            (_a = this.autoFillService) === null || _a === void 0 ? void 0 : _a.onRangeApply(data, range, range);
        }
        else if (this.canEdit()) {
            const focused = this.selectionStore.get('focus');
            if (!focused) {
                return;
            }
            const cell = this.columnService.getSaveData(focused.y, focused.x);
            this.cellEdit({
                rgRow: focused.y,
                rgCol: focused.x,
                val: '',
                type: cell.type,
                prop: cell.prop,
            });
        }
    }
    rowDragStart({ detail }) {
        detail.text = getCellData(this.columnService.rowDataModel(detail.cell.y, detail.cell.x).value);
    }
    /**
     * Verify if edit allowed.
     */
    canEdit() {
        var _a;
        if (this.readonly) {
            return false;
        }
        const focus = this.selectionStore.get('focus');
        return focus && !((_a = this.columnService) === null || _a === void 0 ? void 0 : _a.isReadOnly(focus.y, focus.x));
    }
    get edited() {
        return this.selectionStore.get('edit');
    }
    /**
     * Sets the focus on a cell and optionally edits a range.
     */
    focus(cell, isRangeEdit = false, originalEvent) {
        if (!cell)
            return false;
        const end = cell;
        const start = this.selectionStore.get('focus');
        if (isRangeEdit && start) {
            const range = getRange(start, end);
            if (range) {
                return this.triggerRangeEvent(range, originalEvent);
            }
        }
        return this.doFocus(cell, end, undefined, originalEvent);
    }
    get types() {
        return {
            rowType: this.dataStore.get('type'),
            colType: this.columnService.type,
        };
    }
    /**
     * Collect data
     */
    getData() {
        return {
            el: this.element,
            rows: this.dimensionRow.state,
            cols: this.dimensionCol.state,
            lastCell: this.lastCell,
            focus: this.selectionStore.get('focus'),
            range: this.selectionStore.get('range'),
            edit: this.selectionStore.get('edit'),
        };
    }
    get element() { return getElement(this); }
    static get watchers() { return {
        "selectionStore": [{
                "selectionServiceSet": 0
            }],
        "dimensionRow": [{
                "createAutoFillService": 0
            }],
        "dimensionCol": [{
                "createAutoFillService": 0
            }],
        "dataStore": [{
                "columnServiceSet": 0
            }],
        "colData": [{
                "columnServiceSet": 0
            }]
    }; }
};
OverlaySelection.style = revogrOverlayStyleCss();

const RowHeaderRender = s => (__, { rowIndex: i }) => s + i;

const RevogrRowHeaders = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.scrollViewport = createEvent(this, "scrollview", 3);
        this.elementToScroll = createEvent(this, "ref", 3);
        /**
         * Prevent rendering until job is done.
         * Can be used for initial rendering performance improvement.
         * When several plugins require initial rendering this will prevent double initial rendering.
         */
        this.jobsBeforeRender = [];
    }
    render() {
        const dataViews = [];
        const viewport = new ViewportStore('colPinStart');
        /** render viewports rows */
        let totalLength = 1;
        // todo: this part could be optimized to avoid to often re-render dataPorts can be cached
        for (let data of this.dataPorts) {
            const itemCount = data.dataStore.get('items').length;
            // initiate row data
            const dataStore = new DataStore(data.type, Object.assign({}, data.dataStore.state));
            // initiate column data
            const colData = new DataStore('colPinStart');
            const column = Object.assign({ cellTemplate: RowHeaderRender(totalLength) }, this.rowHeaderColumn);
            colData.updateData([column]);
            dataViews.push(h("revogr-data", Object.assign({}, data, { colType: "rowHeaders", jobsBeforeRender: this.jobsBeforeRender, rowClass: this.rowClass, dataStore: dataStore.store, colData: colData.store, viewportCol: viewport.store, readonly: true, range: false })));
            totalLength += itemCount;
        }
        const colSize = calculateRowHeaderSize(totalLength, this.rowHeaderColumn);
        viewport.setViewport({
            realCount: 1,
            virtualSize: 0,
            items: [
                {
                    size: colSize,
                    start: 0,
                    end: colSize,
                    itemIndex: 0,
                },
            ],
        });
        const viewportScroll = {
            contentHeight: this.height,
            contentWidth: 0,
            style: { minWidth: `${colSize}px` },
            colType: 'rowHeaders',
            ref: (el) => this.elementToScroll.emit(el),
            onScrollviewport: (e) => this.scrollViewport.emit(e.detail),
        };
        const viewportHeader = Object.assign(Object.assign({}, this.headerProp), {
            // groups not present on row headers
            groups: [], colData: typeof this.rowHeaderColumn === 'object' ? [this.rowHeaderColumn] : [], viewportCol: viewport.store, canResize: false, type: ROW_HEADER_TYPE,
            // parent,
            slot: HEADER_SLOT
        });
        return (h(Host, { class: { [ROW_HEADER_TYPE]: true }, key: ROW_HEADER_TYPE }, h("revogr-viewport-scroll", Object.assign({ key: 'c401e82e02e4bdb7afb25f2f49c6776f2e115c81' }, viewportScroll, { "row-header": true }), h("revogr-header", Object.assign({ key: '3c73d27bd96e23a34fc0cf47eda4d2e65751df98' }, viewportHeader)), dataViews)));
    }
};

/**
 * Autohide scroll for MacOS when scroll is visible only for 1 sec
 */
class AutohideScrollPlugin {
    constructor(element) {
        this.element = element;
        this.autohideScrollTimeout = 0;
    }
    /**
     * When scroll size updates set it up for autohide
     */
    setScrollSize(s) {
        if (!s) {
            this.element.setAttribute('autohide', 'true');
        }
        else {
            this.element.removeAttribute('autohide');
        }
    }
    /**
     * On each scroll check if it's time to show
     */
    checkScroll({ scrollSize, contentSize, virtualSize, }) {
        const hasScroll = contentSize > virtualSize;
        const isHidden = !scrollSize && hasScroll;
        if (isHidden) {
            this.element.setAttribute('visible', 'true');
            this.autohideScrollTimeout = this.show(this.element, this.autohideScrollTimeout);
        }
    }
    show(element, timeout) {
        clearTimeout(timeout);
        return Number(setTimeout(() => {
            element === null || element === void 0 ? void 0 : element.removeAttribute('visible');
        }, 1000));
    }
    clear() {
        clearTimeout(this.autohideScrollTimeout);
    }
}

const revogrScrollStyleCss = () => `revogr-scroll-virtual[autohide]{position:absolute;z-index:100 !important}revogr-scroll-virtual[autohide].vertical{top:0;right:0}revogr-scroll-virtual[autohide].vertical[visible]{min-width:20px !important}revogr-scroll-virtual[autohide].horizontal{bottom:0;left:0}revogr-scroll-virtual[autohide].horizontal[visible]{min-height:20px !important}revogr-scroll-virtual.vertical{overflow-y:auto;overflow-x:hidden;height:100%}revogr-scroll-virtual.vertical>div{width:1px}revogr-scroll-virtual.horizontal{overflow-x:auto;overflow-y:hidden;width:100%}revogr-scroll-virtual.horizontal>div{height:1px}`;

const RevogrScrollVirtual = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.scrollVirtual = createEvent(this, "scrollvirtual", 7);
        /**
         * Scroll dimension (`X` - `rgCol` or `Y` - `rgRow`)
         */
        this.dimension = 'rgRow';
        this.scrollSize = 0;
    }
    async setScroll(e) {
        var _a;
        if (this.dimension !== e.dimension) {
            return;
        }
        this.localScrollTimer.latestScrollUpdate(e.dimension);
        (_a = this.localScrollService) === null || _a === void 0 ? void 0 : _a.setScroll(e);
        if (e.coordinate) {
            this.autohideScrollPlugin.checkScroll({
                scrollSize: this.scrollSize,
                contentSize: this.realSize,
                virtualSize: this.virtualSize,
            });
        }
    }
    /**
     * Update if `delta` exists in case we don't know current position or if it's external change
     */
    async changeScroll(e) {
        if (e.delta) {
            const scrollProperty = e.dimension === 'rgRow' ? 'scrollTop' : 'scrollLeft';
            const currentPhysicalCoordinate = this.element[scrollProperty];
            return this.localScrollService.setScrollByDelta(e, currentPhysicalCoordinate);
        }
        return e;
    }
    connectedCallback() {
        this.autohideScrollPlugin = new AutohideScrollPlugin(this.element);
        this.localScrollTimer = new LocalScrollTimer('ontouchstart' in document.documentElement ? 0 : 10);
        this.localScrollService = new LocalScrollService({
            runScroll: e => this.scrollVirtual.emit(e),
            applyScroll: e => {
                this.localScrollTimer.setCoordinate(e);
                const type = e.dimension === 'rgRow' ? 'scrollTop' : 'scrollLeft';
                // this will trigger on scroll event
                this.element[type] = e.coordinate;
            },
        });
    }
    disconnectedCallback() {
        this.autohideScrollPlugin.clear();
    }
    componentWillLoad() {
        this.scrollSize = getScrollbarSize(document);
    }
    componentDidRender() {
        let scrollSize = 0;
        if (this.dimension === 'rgRow') {
            scrollSize = this.element.scrollHeight > this.element.clientHeight ? this.scrollSize : 0;
            this.element.style.minWidth = `${scrollSize}px`;
        }
        else {
            scrollSize = this.element.scrollWidth > this.element.clientWidth ? this.scrollSize : 0;
            this.element.style.minHeight = `${scrollSize}px`;
        }
        this.autohideScrollPlugin.setScrollSize(scrollSize);
        this.localScrollService.setParams({
            contentSize: this.realSize,
            clientSize: this.dimension === 'rgRow' ? this.element.clientHeight : this.element.clientWidth,
            virtualSize: this.clientSize,
        }, this.dimension);
    }
    onScroll(e) {
        if (!(e.target instanceof Element)) {
            return;
        }
        const target = e.target;
        let type = 'scrollLeft';
        if (this.dimension === 'rgRow') {
            type = 'scrollTop';
        }
        const setScroll = () => {
            var _a;
            (_a = this.localScrollService) === null || _a === void 0 ? void 0 : _a.scroll(target[type] || 0, this.dimension);
        };
        // apply after throttling
        if (this.localScrollTimer.isReady(this.dimension, target[type])) {
            setScroll();
        }
        else {
            this.localScrollTimer.throttleLastScrollUpdate(this.dimension, target[type] || 0, () => setScroll());
        }
    }
    render() {
        const size = getContentSize(this.realSize, this.dimension === 'rgRow' ? this.element.clientHeight : this.element.clientWidth, this.clientSize);
        return (h(Host, { key: '7213817ef941eee4050b714266598ec0c2961ee9', onScroll: (e) => this.onScroll(e) }, h("div", { key: '501da49c63253ab943172494b9dbf5399be56cee', style: {
                [this.dimension === 'rgRow' ? 'height' : 'width']: `${size}px`,
            } })));
    }
    get element() { return getElement(this); }
};
RevogrScrollVirtual.style = revogrScrollStyleCss();

const revogrTempRangeStyleCss = () => `.temp-bg-range{display:block !important;position:absolute;pointer-events:none;z-index:9;border:1px solid rgb(255, 94, 0);box-sizing:border-box}.temp-bg-range.Selection{border:1px dashed gray}.temp-bg-range>div{width:1px;height:1px;position:absolute}.temp-bg-range>div.top{top:-1px}.temp-bg-range>div.bottom{bottom:-1px}.temp-bg-range>div.left{left:-1px}.temp-bg-range>div.right{right:-1px}`;

const RevogrFocus = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.onChange = throttle((e) => this.doChange(e), 300);
    }
    doChange(e) {
        e === null || e === void 0 ? void 0 : e.scrollIntoView({
            block: 'nearest',
            inline: 'nearest',
        });
    }
    componentDidRender() {
        if (this.el) {
            this.onChange(this.el);
        }
    }
    render() {
        const data = this.selectionStore.get('tempRange');
        const type = this.selectionStore.get('tempRangeType');
        if (!data) {
            return;
        }
        let directionY = 'bottom';
        let derectionX = 'right';
        const range = this.getRange();
        if (!range) {
            return;
        }
        if (data.y < range.y) {
            directionY = 'top';
        }
        if (data.x < range.x) {
            derectionX = 'left';
        }
        const directionClass = `${derectionX} ${directionY}`;
        const cell = getCell(data, this.dimensionRow.state, this.dimensionCol.state);
        const styles = styleByCellProps(cell);
        const props = {
            class: {
                [TMP_SELECTION_BG_CLASS]: true,
                [type || '']: true,
            },
            style: styles,
            hidden: false
        };
        return (h(Host, Object.assign({}, props), h("div", { class: directionClass, ref: (e) => (this.el = e) })));
    }
    getRange() {
        const range = this.selectionStore.get('range');
        if (range) {
            return range;
        }
        const focus = this.selectionStore.get('focus');
        if (!focus) {
            return null;
        }
        return Object.assign(Object.assign({}, focus), { x1: focus.x, y1: focus.y });
    }
};
RevogrFocus.style = revogrTempRangeStyleCss();

export { Attribution as revogr_attribution, RevoGridExtra as revogr_extra, RevogrFocus$1 as revogr_focus, OverlaySelection as revogr_overlay_selection, RevogrRowHeaders as revogr_row_headers, RevogrScrollVirtual as revogr_scroll_virtual, RevogrFocus as revogr_temp_range };
