/*!
 * Built by Revolist OU ❤️
 */
import { h, f as Build } from './index-Chp_81rd.js';
import { n as DATA_ROW, w as DRAG_ICON_CLASS, x as DRAGGABLE_CLASS } from './dimension.helpers-CGKwSvw6.js';
import { l as GROUP_EXPAND_BTN, m as GROUP_EXPAND_EVENT, G as GROUP_DEPTH, h as GROUP_EXPANDED, P as PSEUDO_GROUP_ITEM, O as isRowDragService, B as getCellDataParsed } from './column.service-C6hByxPy.js';

/**
 * Renders sorting direction and optional additive sorting rank.
 */
const SortingSign = ({ column }) => {
    var _a;
    const indicatorAttrs = { class: 'sort-indicator' };
    const iconAttrs = { class: (_a = column === null || column === void 0 ? void 0 : column.order) !== null && _a !== void 0 ? _a : 'sort-off' };
    const orderIndexAttrs = { class: 'sort-order-index' };
    return (h("span", Object.assign({}, indicatorAttrs), h("i", Object.assign({}, iconAttrs)), (column === null || column === void 0 ? void 0 : column.sortIndex) ? (h("sup", Object.assign({}, orderIndexAttrs), column.sortIndex)) : null));
};

var __rest = (undefined && undefined.__rest) || function (s, e) {
    var t = {};
    for (var p in s)
        if (Object.prototype.hasOwnProperty.call(s, p) && e.indexOf(p) < 0)
            t[p] = s[p];
    if (s != null && typeof Object.getOwnPropertySymbols === "function")
        for (var i = 0, p = Object.getOwnPropertySymbols(s); i < p.length; i++) {
            if (e.indexOf(p[i]) < 0 && Object.prototype.propertyIsEnumerable.call(s, p[i]))
                t[p[i]] = s[p[i]];
        }
    return t;
};
const PADDING_DEPTH = 10;
const RowRenderer = (_a, cells) => {
    var { rowClass, index, size, start, depth, groupingLevel } = _a, attrs = __rest(_a, ["rowClass", "index", "size", "start", "depth", "groupingLevel"]);
    const props = Object.assign(Object.assign(Object.assign({}, attrs), { [DATA_ROW]: index }), (typeof groupingLevel === 'number'
        ? { 'data-level': groupingLevel }
        : {}));
    return (h("div", Object.assign({}, props, { class: `rgRow ${rowClass || ''}`, style: {
            height: `${size}px`,
            transform: `translateY(${start}px)`,
            paddingLeft: depth ? `${PADDING_DEPTH * depth}px` : undefined,
        } }), cells));
};

function expandEvent(e, model, virtualIndex) {
    var _a;
    const event = new CustomEvent(GROUP_EXPAND_EVENT, {
        detail: {
            model,
            virtualIndex,
        },
        cancelable: true,
        bubbles: true,
    });
    (_a = e.target) === null || _a === void 0 ? void 0 : _a.dispatchEvent(event);
}
const GroupingRowRenderer = (props) => {
    const { model, itemIndex, hasExpand, groupingCustomRenderer } = props;
    const name = model[PSEUDO_GROUP_ITEM];
    const expanded = model[GROUP_EXPANDED];
    const depth = parseInt(model[GROUP_DEPTH], 10) || 0;
    const groupRowAttrs = {
        rowClass: 'groupingRow',
        depth,
        expanded,
    };
    if (groupingCustomRenderer) {
        return (h(RowRenderer, Object.assign({}, props, groupRowAttrs), h("div", { onClick: e => expandEvent(e, model, itemIndex) }, groupingCustomRenderer(h, Object.assign(Object.assign({}, props), { colType: props.providers.colType, name,
            expanded,
            depth })))));
    }
    return (h(RowRenderer, Object.assign({}, props, groupRowAttrs), hasExpand && [
        h("button", { class: { [GROUP_EXPAND_BTN]: true }, onClick: e => expandEvent(e, model, itemIndex) }, expandSvgIconVNode(expanded)),
        name,
    ]));
};
const expandSvgIconVNode = (expanded = false) => {
    return (h("svg", { "aria-hidden": "true", style: { transform: `rotate(${!expanded ? -90 : 0}deg)` }, focusable: "false", viewBox: "0 0 448 512" }, h("path", { fill: "currentColor", d: "M207.029 381.476L12.686 187.132c-9.373-9.373-9.373-24.569 0-33.941l22.667-22.667c9.357-9.357 24.522-9.375 33.901-.04L224 284.505l154.745-154.021c9.379-9.335 24.544-9.317 33.901.04l22.667 22.667c9.373 9.373 9.373 24.569 0 33.941L240.971 381.476c-9.373 9.372-24.569 9.372-33.942 0z" })));
};

function renderCell(v) {
    var _a;
    const els = [];
    // #region Custom cell
    const template = (_a = v.schemaModel.column) === null || _a === void 0 ? void 0 : _a.cellTemplate;
    if (template) {
        els.push(template(h, v.schemaModel, v.additionalData));
    }
    // #endregion
    // #region Regular cell
    else {
        if (!v.schemaModel.column) {
            // something is wrong with data
            if (Build === null || Build === void 0 ? void 0 : Build.isDev) {
                console.error('Investigate column problem.', v.schemaModel);
            }
            return '';
        }
        // Row drag
        if (v.schemaModel.column.rowDrag &&
            isRowDragService(v.schemaModel.column.rowDrag, v.schemaModel)) {
            els.push(h("span", { class: DRAGGABLE_CLASS, onMouseDown: originalEvent => {
                    var _a;
                    return (_a = v.dragStartCell) === null || _a === void 0 ? void 0 : _a.emit({
                        originalEvent,
                        model: v.schemaModel,
                    });
                } }, h("span", { class: DRAG_ICON_CLASS })));
        }
        els.push(`${getCellDataParsed(v.schemaModel.model, v.schemaModel.column)}`);
    }
    return els;
}
const CellRenderer = ({ renderProps, cellProps, }) => {
    const render = renderCell.bind(null, renderProps);
    return (h("div", Object.assign({}, cellProps, { redraw: render }), render()));
};

export { CellRenderer as C, GroupingRowRenderer as G, PADDING_DEPTH as P, RowRenderer as R, SortingSign as S, expandSvgIconVNode as a, expandEvent as e };
