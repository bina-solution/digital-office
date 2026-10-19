/*!
 * Built by Revolist OU ❤️
 */
import { r as registerInstance, d as createEvent, h, e as Host, g as getElement } from './index-Chp_81rd.js';
import { d as debounce } from './debounce-PCRWZliA.js';
import { e as AndOrButton, f as ReorderButton, d as TrashButton, i as isFilterBtn } from './filter.button-B-RBiF67.js';

(function closest() {
    if (!Element.prototype.matches) {
        Element.prototype.matches =
            Element.prototype.msMatchesSelector || Element.prototype.webkitMatchesSelector;
    }
    if (!Element.prototype.closest) {
        Element.prototype.closest = function (s) {
            let el = this;
            do {
                if (Element.prototype.matches.call(el, s)) {
                    return el;
                }
                el = el.parentElement || el.parentNode;
            } while (el !== null && el.nodeType === 1);
            return null;
        };
    }
})();

const FILTER_REORDER_MIME = 'text/revogrid-filter-id';
function setFilterReorderData(dataTransfer, id) {
    if (!dataTransfer) {
        return;
    }
    dataTransfer.effectAllowed = 'move';
    dataTransfer.setData(FILTER_REORDER_MIME, String(id));
    dataTransfer.setData('text/plain', String(id));
}
function getFilterReorderId(dataTransfer) {
    if (!dataTransfer) {
        return;
    }
    const rawId = dataTransfer.getData(FILTER_REORDER_MIME) || dataTransfer.getData('text/plain');
    const normalizedId = rawId.trim();
    if (!normalizedId) {
        return;
    }
    const id = Number(normalizedId);
    return Number.isFinite(id) ? id : undefined;
}
function moveFilterItem(items, sourceId, targetId) {
    if (sourceId === targetId) {
        return false;
    }
    const sourceIndex = items.findIndex(item => item.id === sourceId);
    const targetIndex = items.findIndex(item => item.id === targetId);
    if (sourceIndex === -1 || targetIndex === -1 || sourceIndex === targetIndex) {
        return false;
    }
    const relationsByPosition = items.map(item => { var _a; return (_a = item.relation) !== null && _a !== void 0 ? _a : 'and'; });
    const [movedItem] = items.splice(sourceIndex, 1);
    items.splice(targetIndex, 0, movedItem);
    items.forEach((item, index) => {
        var _a;
        item.relation = index === items.length - 1
            ? 'and'
            : (_a = relationsByPosition[index]) !== null && _a !== void 0 ? _a : 'and';
    });
    return true;
}

const filterStyleCss = () => `.revo-button{position:relative;overflow:hidden;color:#fff;background-color:#4545ff;height:32px;line-height:32px;padding:0 15px;outline:0;border:0;border-radius:7px;box-sizing:border-box;cursor:pointer}.revo-button.green{background-color:#009037}.revo-button.red{background-color:#E0662E}.revo-button:disabled,.revo-button[disabled]{cursor:not-allowed !important;filter:opacity(0.35) !important}.revo-button.outline{border:1px solid #dbdbdb;line-height:30px;background:none;color:#000;box-shadow:none}revo-grid[theme^=dark] .revo-button.outline{border:1px solid #404040;color:#d8d8d8}revogr-filter-panel{display:block}revogr-filter-panel .filter-panel-dialog{position:fixed;top:0;left:0;z-index:100;max-height:calc(100vh - 16px);overflow:auto;opacity:1;transform:none;background-color:var(--revo-grid-filter-panel-bg, #fff);border:1px solid var(--revo-grid-filter-panel-border, #cecece);transform-origin:62px 0px;box-shadow:0 5px 18px -2px var(--revo-grid-filter-panel-shadow, rgba(0, 0, 0, 0.15));box-sizing:border-box;padding:10px;border-radius:8px;margin:0;min-width:220px;text-align:left;animation:revogr-filter-panel-open 140ms cubic-bezier(0.2, 0, 0, 1)}revogr-filter-panel .filter-panel-dialog .filter-holder>div{display:flex;flex-direction:column}revogr-filter-panel .filter-panel-dialog label{font-size:13px;display:block;padding:8px 0}revogr-filter-panel .filter-panel-dialog select{width:100%}revogr-filter-panel .filter-panel-dialog input[type=text]{border:0;min-height:34px;margin:5px 0;background:var(--revo-grid-filter-panel-input-bg, #f3f3f3);border-radius:5px;padding:0 10px;box-sizing:border-box;width:100%}revogr-filter-panel .filter-panel-dialog .filter-actions{position:sticky;right:0;bottom:-10px;left:0;z-index:1;text-align:right;margin:10px -10px -10px;padding:0 5px 10px 10px;background:var(--revo-grid-filter-panel-bg, #fff);border-top:1px solid var(--revo-grid-filter-panel-divider, #d9d9d9)}revogr-filter-panel .filter-panel-dialog .filter-actions button{margin-top:10px;margin-right:5px}@keyframes revogr-filter-panel-open{from{opacity:0;transform:translateY(-4px) scale(0.98)}to{opacity:1;transform:none}}@media (prefers-reduced-motion: reduce){revogr-filter-panel .filter-panel-dialog{animation:none}}.rgHeaderCell:hover .rv-filter{transition:opacity 267ms cubic-bezier(0.4, 0, 0.2, 1) 0ms, transform 178ms cubic-bezier(0.4, 0, 0.2, 1) 0ms}.rgHeaderCell:hover .rv-filter,.rgHeaderCell .rv-filter.active{opacity:1}.rgHeaderCell .rv-filter{height:24px;width:24px;background:none;border:0;opacity:0;visibility:visible;cursor:pointer;border-radius:4px}.rgHeaderCell .rv-filter.active{color:#10224a}.rgHeaderCell .rv-filter .filter-img{color:gray;width:11px}.select-css{display:block;font-family:sans-serif;line-height:1.3;padding:0.6em 1.4em 0.5em 0.8em;width:100%;max-width:100%;box-sizing:border-box;margin:0;border:1px solid var(--revo-grid-filter-panel-select-border, #d9d9d9);box-shadow:transparent;border-radius:0.5em;appearance:none;background-color:var(--revo-grid-filter-panel-input-bg, #f3f3f3);background-image:url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23007CB2%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E");background-repeat:no-repeat, repeat;background-position:right 0.7em top 50%, 0 0;background-size:0.65em auto, 100%;}.select-css::-ms-expand{display:none}.select-css:hover{border-color:var(--revo-grid-filter-panel-select-border, #d9d9d9)}.select-css:focus{border-color:var(--revo-grid-filter-panel-select-border-hover, #d9d9d9);box-shadow:0 0 1px 3px rgba(59, 153, 252, 0.7);box-shadow:0 0 0 3px -moz-mac-focusring;outline:none}.select-css option{font-weight:normal}.select-css:disabled,.select-css[aria-disabled=true]{color:gray;background-image:url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22graytext%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E"), linear-gradient(to bottom, #ffffff 0%, #ffffff 100%)}.select-css:disabled:hover,.select-css[aria-disabled=true]{border-color:var(--revo-grid-filter-panel-select-border, #d9d9d9)}.multi-filter-list{margin-top:5px;margin-bottom:5px}.multi-filter-list div{white-space:nowrap}.multi-filter-list .multi-filter-list-row{display:flex;align-items:center;gap:6px;position:relative}.multi-filter-list .multi-filter-list-row.filter-row-dragging{opacity:0.65}.multi-filter-list .multi-filter-list-row.filter-row-drag-over::before{content:"";position:absolute;top:-4px;right:0;left:0;z-index:2;height:2px;background:var(--revo-grid-filter-panel-reorder-accent, #007cb2);border-radius:999px;box-shadow:0 0 0 2px var(--revo-grid-filter-panel-bg, #fff)}.multi-filter-list .multi-filter-list-row.filter-row-drop-active .filter-row-drop-target{pointer-events:auto}.multi-filter-list .filter-row-drop-target{position:absolute;inset:0;z-index:1;padding:0;pointer-events:none;background:transparent;border:0}.multi-filter-list .multi-filter-list-action{display:flex;align-self:stretch;flex:0 0 auto;justify-content:flex-end;align-items:center}.multi-filter-list .and-or-button{margin:0 0 0 10px;min-width:58px;cursor:pointer}.multi-filter-list .trash-button{margin:0 0 -2px 6px;padding:0;border:0;background:transparent;color:inherit;cursor:pointer;width:22px;height:100%;font-size:16px}.multi-filter-list .trash-button .trash-img{width:1em}.multi-filter-list .reorder-button{border:0;background:transparent;color:var(--revo-grid-filter-panel-reorder-color, #6b7280);cursor:grab;font-family:monospace;font-size:12px;letter-spacing:0;line-height:1;padding:6px 2px;transform:scaleX(0.8);width:16px}.multi-filter-list .reorder-button.filter-row-drag-over{color:var(--revo-grid-filter-panel-reorder-accent, #007cb2)}.multi-filter-list .reorder-button:active{cursor:grabbing}.multi-filter-list-container{padding:0;margin:0;list-style:none}.add-filter-divider{display:block;margin:0 -10px 10px -10px;border-bottom:1px solid var(--revo-grid-filter-panel-divider, #d9d9d9);height:10px}.select-input{display:flex;align-items:center;flex:1 1 auto;gap:6px;min-width:0}.select-input .select-filter,.select-input .filter-extra{flex:1 1 0;min-width:0}.select-input .select-filter{width:auto}.select-input .filter-extra{display:flex}.select-input .filter-extra>*{width:100%}.select-input input[type=text],.select-input input[type=date]{margin:0}`;

const defaultType = 'none';
const FILTER_LIST_CLASS = 'multi-filter-list';
const FILTER_LIST_CLASS_ACTION = 'multi-filter-list-action';
const FILTER_ID = 'add-filter';
const VIEWPORT_PADDING = 8;
const FilterPanel = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.filterChange = createEvent(this, "filterChange", 7);
        this.resetChange = createEvent(this, "resetChange", 7);
        this.filterCaptionsInternal = {
            title: 'Filter by',
            ok: 'Close',
            save: 'Save',
            // drops the filter
            reset: 'Reset',
            cancel: 'Cancel',
            add: 'Add condition',
            placeholder: 'Enter value...',
            and: 'and',
            or: 'or',
            filterCondition: 'Filter condition',
            removeFilter: 'Remove filter',
            reorderFilter: 'Reorder filter',
        };
        this.isFilterIdSet = false;
        this.filterId = 0;
        this.currentFilterId = -1;
        this.currentFilterType = defaultType;
        this.filterItems = {};
        this.filterNames = {};
        this.filterEntities = {};
        /**
         * Disables dynamic filtering. A way to apply filters on Save only
         */
        this.disableDynamicFiltering = false;
        /**
         * If true, closes the filter panel when clicking outside
         */
        this.closeOnOutsideClick = true;
        this.debouncedApplyFilter = debounce(() => {
            this.filterChange.emit(this.filterItems);
        }, 400);
    }
    onMouseDown(e) {
        // click on anything then select drops values to default
        if (!this.changes) {
            return;
        }
        const path = e.composedPath();
        const select = this.getAddFilterSelect();
        if (select instanceof HTMLSelectElement) {
            // click on select should be skipped
            if (path.includes(select)) {
                return;
            }
            select.value = defaultType;
        }
        this.currentFilterType = defaultType;
        if (this.changes) {
            this.changes.type = defaultType;
        }
        this.currentFilterId = -1;
        const isOutside = !path.includes(this.element);
        if (isOutside &&
            !this.isOwnFilterButton(e.target) &&
            this.closeOnOutsideClick) {
            this.changes = undefined;
        }
    }
    async show(newEntity) {
        this.changes = newEntity;
        this.filterItems = (newEntity === null || newEntity === void 0 ? void 0 : newEntity.filterItems) || {};
        if (this.changes) {
            this.changes.type = this.changes.type || defaultType;
        }
    }
    async getChanges() {
        return this.changes;
    }
    componentWillRender() {
        if (!this.isFilterIdSet) {
            this.isFilterIdSet = true;
            const filterItems = Object.keys(this.filterItems);
            for (const prop of filterItems) {
                // we set the proper filterId so there won't be any conflict when removing filters
                this.filterId += this.filterItems[prop].length;
            }
        }
    }
    getFilterItemsList() {
        var _a, _b;
        const prop = (_a = this.changes) === null || _a === void 0 ? void 0 : _a.prop;
        if (typeof prop === 'undefined')
            return '';
        const propFilters = (_b = this.filterItems[prop]) !== null && _b !== void 0 ? _b : [];
        const visibleFilterCount = propFilters.filter(filter => !filter.hidden).length;
        const capts = Object.assign(Object.assign({}, this.filterCaptionsInternal), this.filterCaptions);
        return (h("div", { key: this.filterId }, h("ul", { class: "multi-filter-list-container" }, propFilters.map((filter, index) => {
            let andOrButton;
            if (filter.hidden) {
                return;
            }
            // hide toggle button if there is only one filter and the last one
            if (index !== this.filterItems[prop].length - 1) {
                andOrButton = (h(AndOrButton, { text: filter.relation === 'and' ? capts.and : capts.or, onClick: () => this.toggleFilterAndOr(filter.id) }));
            }
            const extra = this.renderExtra(prop, index);
            const isDragging = this.draggedFilterId === filter.id;
            const isDragOver = this.dragOverFilterId === filter.id && !isDragging;
            const canReorder = visibleFilterCount > 1;
            return (h("li", { key: filter.id, class: FILTER_LIST_CLASS, "aria-label": `${capts.filterCondition} ${index + 1}` }, h("div", { class: {
                    'multi-filter-list-row': true,
                    'filter-row-drop-active': this.draggedFilterId !== undefined && !isDragging,
                    'filter-row-dragging': isDragging,
                    'filter-row-drag-over': isDragOver,
                } }, canReorder ? (h("button", { type: "button", class: "filter-row-drop-target", tabIndex: -1, "aria-label": `${capts.filterCondition} ${index + 1}`, onDragOver: e => this.onFilterDragOver(e, filter.id), onDragLeave: () => this.onFilterDragLeave(filter.id), onDrop: e => this.onFilterDrop(e, prop, filter.id) })) : '', canReorder ? (h(ReorderButton, { ariaLabel: capts.reorderFilter, dragging: isDragging, dragOver: isDragOver, onDragStart: e => this.onFilterDragStart(e, filter.id), onDragEnd: () => this.onFilterDragEnd(), onKeyDown: e => this.onFilterReorderKeyDown(e, prop, filter.id) })) : '', h("div", { class: { 'select-input': true } }, h("select", { class: "select-css select-filter", onChange: e => this.onFilterTypeChange(e, prop, index) }, this.renderSelectOptions(this.filterItems[prop][index].type, true)), extra ? h("div", { class: "filter-extra" }, extra) : ''), h("div", { class: FILTER_LIST_CLASS_ACTION }, andOrButton, h(TrashButton, { ariaLabel: capts.removeFilter, onClick: () => this.onRemoveFilter(filter.id) })))));
        })), propFilters.filter(f => !f.hidden).length > 0 ? h("div", { class: "add-filter-divider" }) : ''));
    }
    componentDidRender() {
        this.syncDialog();
    }
    syncDialog() {
        if (!this.dialog) {
            return;
        }
        if (!this.changes) {
            if (this.dialog.open) {
                this.dialog.close();
            }
            return;
        }
        if (!this.dialog.open) {
            this.dialog.show();
        }
        if (this.changes.autoCorrect !== false) {
            this.autoCorrect(this.dialog);
            requestAnimationFrame(() => this.autoCorrect(this.dialog));
        }
    }
    autoCorrect(el) {
        var _a;
        if (!el || !this.changes) {
            return;
        }
        el.style.maxHeight = '';
        el.style.left = `${this.changes.x}px`;
        el.style.top = `${this.changes.y}px`;
        const pos = el.getBoundingClientRect();
        const anchorTop = (_a = this.changes.anchorY) !== null && _a !== void 0 ? _a : this.changes.y;
        const anchorBottom = this.changes.y;
        const spaceAbove = Math.max(0, anchorTop - VIEWPORT_PADDING);
        const spaceBelow = Math.max(0, window.innerHeight - anchorBottom - VIEWPORT_PADDING);
        const openAbove = pos.height > spaceBelow && spaceAbove > spaceBelow;
        const availableHeight = Math.max(VIEWPORT_PADDING, openAbove ? spaceAbove : spaceBelow);
        el.style.maxHeight = `${availableHeight}px`;
        const adjustedPos = el.getBoundingClientRect();
        const maxLeft = Math.max(VIEWPORT_PADDING, window.innerWidth - adjustedPos.width - VIEWPORT_PADDING);
        const maxTop = Math.max(VIEWPORT_PADDING, window.innerHeight - adjustedPos.height - VIEWPORT_PADDING);
        const left = Math.min(Math.max(VIEWPORT_PADDING, this.changes.x), maxLeft);
        const top = openAbove
            ? Math.min(Math.max(VIEWPORT_PADDING, anchorTop - adjustedPos.height), maxTop)
            : Math.min(Math.max(VIEWPORT_PADDING, anchorBottom), maxTop);
        el.style.left = `${left}px`;
        el.style.top = `${top}px`;
    }
    onFilterTypeChange(e, prop, index) {
        if (!(e.target instanceof HTMLSelectElement)) {
            return;
        }
        this.filterItems[prop][index].type = e.target.value;
        // this re-renders the input to know if we need extra input
        this.filterId++;
        // adding setTimeout will wait for the next tick DOM update then focus on input
        setTimeout(() => {
            const input = document.getElementById('filter-input-' + this.filterItems[prop][index].id);
            if (input instanceof HTMLInputElement) {
                input.focus();
            }
        }, 0);
        if (!this.disableDynamicFiltering) {
            this.debouncedApplyFilter();
        }
    }
    onAddNewFilter(e) {
        const el = e.target;
        this.currentFilterType = el.value;
        this.addNewFilterToProp();
        // reset value after adding new filter
        const select = this.getAddFilterSelect();
        if (select) {
            select.value = defaultType;
            this.currentFilterType = defaultType;
        }
        if (!this.disableDynamicFiltering) {
            this.debouncedApplyFilter();
        }
    }
    addNewFilterToProp() {
        var _a;
        const prop = (_a = this.changes) === null || _a === void 0 ? void 0 : _a.prop;
        if (!(prop || prop === 0))
            return;
        if (!this.filterItems[prop]) {
            this.filterItems[prop] = [];
        }
        if (this.currentFilterType === 'none')
            return;
        this.filterId++;
        this.currentFilterId = this.filterId;
        this.filterItems[prop].push({
            id: this.currentFilterId,
            type: this.currentFilterType,
            value: '',
            relation: 'and',
        });
        // adding setTimeout will wait for the next tick DOM update then focus on input
        setTimeout(() => {
            const input = document.getElementById('filter-input-' + this.currentFilterId);
            if (input)
                input.focus();
        }, 0);
    }
    onSave() {
        this.filterChange.emit(this.filterItems);
    }
    onCancel() {
        this.changes = undefined;
    }
    onReset() {
        var _a;
        this.assertChanges();
        this.resetChange.emit((_a = this.changes) === null || _a === void 0 ? void 0 : _a.prop);
        // this updates the DOM which is used by getFilterItemsList() key
        this.filterId++;
    }
    onRemoveFilter(id) {
        var _a;
        this.assertChanges();
        // this is for reactivity issues for getFilterItemsList()
        this.filterId++;
        const prop = (_a = this.changes) === null || _a === void 0 ? void 0 : _a.prop;
        const items = this.filterItems[prop !== null && prop !== void 0 ? prop : ''];
        if (!items)
            return;
        const index = items.findIndex(d => d.id === id);
        if (index === -1)
            return;
        items.splice(index, 1);
        // let's remove the prop if no more filters so the filter icon will be removed
        if (items.length === 0)
            delete this.filterItems[prop !== null && prop !== void 0 ? prop : ''];
        if (!this.disableDynamicFiltering) {
            this.debouncedApplyFilter();
        }
    }
    onFilterDragStart(e, id) {
        this.draggedFilterId = id;
        setFilterReorderData(e.dataTransfer, id);
    }
    onFilterDragOver(e, id) {
        if (this.draggedFilterId === undefined || this.draggedFilterId === id) {
            return;
        }
        e.preventDefault();
        if (e.dataTransfer) {
            e.dataTransfer.dropEffect = 'move';
        }
        this.dragOverFilterId = id;
    }
    onFilterDragLeave(id) {
        if (this.dragOverFilterId === id) {
            this.dragOverFilterId = undefined;
        }
    }
    onFilterDrop(e, prop, targetId) {
        var _a;
        e.preventDefault();
        const sourceId = (_a = this.draggedFilterId) !== null && _a !== void 0 ? _a : getFilterReorderId(e.dataTransfer);
        this.onFilterDragEnd();
        if (sourceId === undefined) {
            return;
        }
        const items = this.filterItems[prop];
        if (!items) {
            return;
        }
        if (!moveFilterItem(items, sourceId, targetId)) {
            return;
        }
        this.filterId++;
        if (!this.disableDynamicFiltering) {
            this.debouncedApplyFilter();
        }
    }
    onFilterDragEnd() {
        this.draggedFilterId = undefined;
        this.dragOverFilterId = undefined;
    }
    onFilterReorderKeyDown(e, prop, sourceId) {
        let direction = 0;
        if (e.key === 'ArrowUp') {
            direction = -1;
        }
        else if (e.key === 'ArrowDown') {
            direction = 1;
        }
        else {
            return;
        }
        const items = this.filterItems[prop];
        if (!items) {
            return;
        }
        const visibleItems = items.filter(item => !item.hidden);
        const sourceIndex = visibleItems.findIndex(item => item.id === sourceId);
        if (sourceIndex === -1) {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        const target = visibleItems[sourceIndex + direction];
        if (!target || !moveFilterItem(items, sourceId, target.id)) {
            return;
        }
        this.filterId++;
        if (!this.disableDynamicFiltering) {
            this.debouncedApplyFilter();
        }
    }
    toggleFilterAndOr(id) {
        var _a;
        this.assertChanges();
        // this is for reactivity issues for getFilterItemsList()
        this.filterId++;
        const prop = (_a = this.changes) === null || _a === void 0 ? void 0 : _a.prop;
        const items = this.filterItems[prop !== null && prop !== void 0 ? prop : ''];
        if (!items)
            return;
        const index = items.findIndex(d => d.id === id);
        if (index === -1)
            return;
        items[index].relation = items[index].relation === 'and' ? 'or' : 'and';
        if (!this.disableDynamicFiltering) {
            this.debouncedApplyFilter();
        }
    }
    assertChanges() {
        if (!this.changes) {
            throw new Error('Changes required per edit');
        }
    }
    renderSelectOptions(type, isDefaultTypeRemoved = false) {
        if (!this.changes) {
            return;
        }
        const options = [];
        const prop = this.changes.prop;
        const hidden = new Set();
        Object.keys(this.filterItems).forEach((prop) => {
            const values = this.filterItems[prop];
            values.forEach((filter) => {
                if (filter.hidden) {
                    hidden.add(filter.type);
                }
            });
        });
        if (!isDefaultTypeRemoved) {
            const capts = Object.assign(Object.assign({}, this.filterCaptionsInternal), this.filterCaptions);
            options.push(h("option", { selected: this.currentFilterType === defaultType, value: defaultType }, prop && this.filterItems[prop] && this.filterItems[prop].length > 0
                ? capts.add
                : this.filterNames[defaultType]));
        }
        for (let gIndex in this.changes.filterTypes) {
            const group = this.changes.filterTypes[gIndex].filter(k => !hidden.has(k));
            if (group.length) {
                options.push(...group.map(k => (h("option", { value: k, selected: type === k }, this.filterNames[k]))));
                options.push(h("option", { disabled: true }));
            }
        }
        return options;
    }
    renderExtra(prop, index) {
        const currentFilter = this.filterItems[prop];
        if (!currentFilter)
            return '';
        const applyFilter = (value) => {
            this.filterItems[prop][index].value = value;
            if (!this.disableDynamicFiltering) {
                this.debouncedApplyFilter();
            }
        };
        const focusNext = () => {
            const select = this.getAddFilterSelect();
            if (select) {
                select.value = defaultType;
                this.currentFilterType = defaultType;
                this.addNewFilterToProp();
                select.focus();
            }
        };
        const capts = Object.assign(Object.assign({}, this.filterCaptionsInternal), this.filterCaptions);
        const extra = this.filterEntities[currentFilter[index].type].extra;
        if (typeof extra === 'function') {
            return extra(h, {
                value: currentFilter[index].value,
                filter: currentFilter[index],
                prop,
                index,
                placeholder: capts.placeholder,
                onInput: (value) => {
                    applyFilter(value);
                },
                onFocus: () => {
                    focusNext();
                }
            });
        }
        if (extra !== 'input' && extra !== 'datepicker') {
            return '';
        }
        return (h("input", { id: `filter-input-${currentFilter[index].id}`, placeholder: capts.placeholder, type: extra === 'datepicker' ? 'date' : 'text', value: currentFilter[index].value, onInput: (e) => {
                if (e.target instanceof HTMLInputElement) {
                    applyFilter(e.target.value);
                }
            }, onKeyDown: e => {
                if (e.key.toLowerCase() === 'enter') {
                    const select = this.getAddFilterSelect();
                    if (select) {
                        focusNext();
                    }
                    return;
                }
                // keep event local, don't escalate farther to dom
                e.stopPropagation();
            } }));
    }
    getAddFilterSelect() {
        return this.element.querySelector(`#${FILTER_ID}`);
    }
    isOwnFilterButton(target) {
        if (!(target instanceof Element)) {
            return false;
        }
        if (!isFilterBtn(target)) {
            return false;
        }
        const panelGrid = this.getOwningGrid(this.element);
        const targetGrid = this.getOwningGrid(target);
        return !!panelGrid && panelGrid === targetGrid;
    }
    getOwningGrid(element) {
        const grid = element.closest('revo-grid');
        if (grid) {
            return grid;
        }
        const root = element.getRootNode();
        if (root instanceof ShadowRoot && root.host.localName === 'revo-grid') {
            return root.host;
        }
        return undefined;
    }
    render() {
        var _a, _b, _c, _d, _e, _f, _g, _h, _j;
        const style = {
            left: `${(_b = (_a = this.changes) === null || _a === void 0 ? void 0 : _a.x) !== null && _b !== void 0 ? _b : 0}px`,
            top: `${(_d = (_c = this.changes) === null || _c === void 0 ? void 0 : _c.y) !== null && _d !== void 0 ? _d : 0}px`,
        };
        const capts = Object.assign(Object.assign({}, this.filterCaptionsInternal), this.filterCaptions);
        return (h(Host, { key: '2a19b35adb56fb7d23385fffebc768838edee162' }, h("dialog", { key: '94386d7cbc4bd9c631f72928938b1d1550a3de82', class: "filter-panel-dialog", style: style, ref: el => (this.dialog = el), onCancel: e => {
                e.preventDefault();
                this.onCancel();
            } }, this.changes && [
            h("slot", { key: "header-slot", slot: "header" }),
            ((_f = (_e = this.changes).extraContent) === null || _f === void 0 ? void 0 : _f.call(_e, this.changes)) || '',
            ((_g = this.changes) === null || _g === void 0 ? void 0 : _g.hideDefaultFilters) !== true && [
                h("label", { key: "filter-title" }, capts.title),
                h("div", { key: "filter-holder", class: "filter-holder" }, this.getFilterItemsList()),
                h("div", { key: "add-filter", class: "add-filter" }, h("select", { key: '4f7354e39d8e5cf9ae7b735290eff18d105ab87e', id: FILTER_ID, class: "select-css", onChange: e => this.onAddNewFilter(e) }, this.renderSelectOptions(this.currentFilterType))),
            ],
            h("slot", { key: "default-slot" }),
            ((_j = (_h = this.changes).extraBottomContent) === null || _j === void 0 ? void 0 : _j.call(_h, this.changes)) || '',
            h("div", { key: "filter-actions", class: "filter-actions" }, this.disableDynamicFiltering && [
                h("button", { key: "save", id: "revo-button-save", "aria-label": "save", class: "revo-button green", onClick: () => this.onSave() }, capts.save),
                h("button", { key: "cancel", id: "revo-button-ok", "aria-label": "ok", class: "revo-button green", onClick: () => this.onCancel() }, capts.cancel),
            ], !this.disableDynamicFiltering && [
                h("button", { key: "ok", id: "revo-button-ok", "aria-label": "ok", class: "revo-button green", onClick: () => this.onCancel() }, capts.ok),
                h("button", { key: "reset", id: "revo-button-reset", "aria-label": "reset", class: "revo-button outline", onClick: () => this.onReset() }, capts.reset),
            ]),
            h("slot", { key: "footer-slot", slot: "footer" }),
        ])));
    }
    get element() { return getElement(this); }
};
FilterPanel.style = filterStyleCss();

export { FilterPanel as revogr_filter_panel };
