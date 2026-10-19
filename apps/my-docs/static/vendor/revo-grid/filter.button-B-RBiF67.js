/*!
 * Built by Revolist OU ❤️
 */
import { h } from './index-Chp_81rd.js';

const FILTER_BUTTON_CLASS = 'rv-filter';
const FILTER_BUTTON_ACTIVE = 'active';
const FILTER_PROP = 'hasFilter';
const AND_OR_BUTTON = 'and-or-button';
const TRASH_BUTTON = 'trash-button';
const REORDER_BUTTON = 'reorder-button';
const FilterButton = ({ column }) => {
    return (h("span", null, h("button", { class: {
            [FILTER_BUTTON_CLASS]: true,
            [FILTER_BUTTON_ACTIVE]: column && !!column[FILTER_PROP],
        } }, h("svg", { class: "filter-img", viewBox: "0 0 64 64" }, h("g", { stroke: "none", "stroke-width": "1", fill: "none", "fill-rule": "evenodd" }, h("path", { d: "M43,48 L43,56 L21,56 L21,48 L43,48 Z M53,28 L53,36 L12,36 L12,28 L53,28 Z M64,8 L64,16 L0,16 L0,8 L64,8 Z", fill: "currentColor" }))))));
};
const TrashButton = ({ ariaLabel, onClick }) => {
    return (h("button", { type: "button", class: { [TRASH_BUTTON]: true }, "aria-label": ariaLabel, onClick: onClick }, h("svg", { class: "trash-img", viewBox: "0 0 24 24" }, h("path", { fill: "currentColor", d: "M9,3V4H4V6H5V19A2,2 0 0,0 7,21H17A2,2 0 0,0 19,19V6H20V4H15V3H9M7,6H17V19H7V6M9,8V17H11V8H9M13,8V17H15V8H13Z" }))));
};
const AndOrButton = ({ text, onClick }) => {
    return h("button", { type: "button", class: { [AND_OR_BUTTON]: true, 'light revo-button': true }, onClick: onClick }, text);
};
const ReorderButton = ({ ariaLabel, dragging, dragOver, onDragStart, onDragEnd, onDragOver, onDragLeave, onDrop, onKeyDown, }) => {
    return (h("button", { type: "button", class: {
            [REORDER_BUTTON]: true,
            'filter-row-dragging': !!dragging,
            'filter-row-drag-over': !!dragOver,
        }, draggable: true, title: ariaLabel, "aria-label": ariaLabel, onDragStart: onDragStart, onDragEnd: onDragEnd, onDragOver: onDragOver, onDragLeave: onDragLeave, onDrop: onDrop, onKeyDown: onKeyDown }, "::"));
};
function isFilterBtn(e) {
    if (e.classList.contains(FILTER_BUTTON_CLASS)) {
        return true;
    }
    return e === null || e === void 0 ? void 0 : e.closest(`.${FILTER_BUTTON_CLASS}`);
}

export { AND_OR_BUTTON as A, FILTER_BUTTON_CLASS as F, REORDER_BUTTON as R, TRASH_BUTTON as T, FILTER_BUTTON_ACTIVE as a, FILTER_PROP as b, FilterButton as c, TrashButton as d, AndOrButton as e, ReorderButton as f, isFilterBtn as i };
