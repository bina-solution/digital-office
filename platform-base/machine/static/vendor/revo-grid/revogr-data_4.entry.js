/*!
 * Built by Revolist OU ❤️
 */
import { r as registerInstance, d as createEvent, h, e as Host, g as getElement } from './index-Chp_81rd.js';
import { M as ColumnService, u as isGrouping } from './column.service-C6hByxPy.js';
import { B as ROW_FOCUSED_CLASS, b as getSourceItem, n as DATA_ROW, m as DATA_COL, M as MIN_COL_SIZE, r as HEADER_SORTABLE_CLASS, H as HEADER_CLASS, F as FOCUS_CLASS, k as getItemByIndex, u as HEADER_ROW_CLASS, v as HEADER_ACTUAL_ROW_CLASS } from './dimension.helpers-CGKwSvw6.js';
import { G as GroupingRowRenderer, C as CellRenderer, R as RowRenderer, P as PADDING_DEPTH, S as SortingSign } from './cell-renderer-CLTRlCa5.js';
import { c as FilterButton } from './filter.button-B-RBiF67.js';
import { H as HeaderCellRenderer } from './header-cell-renderer-BMmXRsd_.js';
import { t as throttle, L as LocalScrollTimer, a as LocalScrollService, g as getContentSize } from './throttle-Cpk1LoGk.js';
import { H as HEADER_SLOT, C as CONTENT_SLOT, F as FOOTER_SLOT } from './viewport.helpers-CoCAvmZs.js';
import './debounce-PCRWZliA.js';

/**
 * Class is responsible for highlighting rows in a table.
 */
class RowHighlightPlugin {
    constructor() {
        this.currentRange = null;
    }
    selectionChange(e, renderedRows) {
        // clear previous range
        if (this.currentRange) {
            renderedRows.forEach((row, y) => {
                var _a;
                // skip current range
                if (e && y >= e.y && y <= e.y1) {
                    return;
                }
                // clear previous range
                if (row &&
                    row.$elm$ instanceof HTMLElement &&
                    row.$elm$.classList.contains(ROW_FOCUSED_CLASS)) {
                    row.$elm$.classList.remove(ROW_FOCUSED_CLASS);
                    if ((_a = row.$attrs$) === null || _a === void 0 ? void 0 : _a.class.includes(ROW_FOCUSED_CLASS)) {
                        row.$attrs$.class = row.$attrs$.class.replace(ROW_FOCUSED_CLASS, '');
                    }
                }
            });
        }
        // apply new range
        if (e) {
            for (let y = e.y; y <= e.y1; y++) {
                const row = renderedRows.get(y);
                if (row &&
                    row.$elm$ instanceof HTMLElement &&
                    !row.$elm$.classList.contains(ROW_FOCUSED_CLASS)) {
                    const attrs = (row.$attrs$ = row.$attrs$ || {});
                    attrs.class = (attrs.class || '') + ' ' + ROW_FOCUSED_CLASS;
                    row.$elm$.classList.add(ROW_FOCUSED_CLASS);
                }
            }
        }
        this.currentRange = e;
    }
    isRowFocused(y) {
        return (this.currentRange && y >= this.currentRange.y && y <= this.currentRange.y1);
    }
}

/**
 * Converts a VNode element into an HTML element and appends it to the specified parentHolder.
 */
function convertVNodeToHTML(parentHolder, redraw) {
    return new Promise(resolve => {
        const vnode = document.createElement('vnode-html');
        parentHolder.appendChild(vnode);
        vnode.redraw = redraw;
        vnode.addEventListener('html', e => {
            vnode.remove();
            resolve(e.detail);
        });
    });
}

const revogrDataStyleCss = () => `.revo-drag-icon{width:11px;opacity:0.8}.revo-drag-icon::before{content:"::";display:inline-block}.revo-alt-icon{-webkit-mask-image:url("data:image/svg+xml,%3C%3Fxml version='1.0' encoding='UTF-8'%3F%3E%3Csvg viewBox='0 0 384 383' xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'%3E%3Cg%3E%3Cpath d='M192.4375,383 C197.424479,383 201.663411,381.254557 205.154297,377.763672 L205.154297,377.763672 L264.25,318.667969 C270.234375,312.683594 271.605794,306.075846 268.364258,298.844727 C265.122721,291.613607 259.51237,287.998047 251.533203,287.998047 L251.533203,287.998047 L213.382812,287.998047 L213.382812,212.445312 L288.935547,212.445312 L288.935547,250.595703 C288.935547,258.57487 292.551107,264.185221 299.782227,267.426758 C307.013346,270.668294 313.621094,269.296875 319.605469,263.3125 L319.605469,263.3125 L378.701172,204.216797 C382.192057,200.725911 383.9375,196.486979 383.9375,191.5 C383.9375,186.513021 382.192057,182.274089 378.701172,178.783203 L378.701172,178.783203 L319.605469,119.6875 C313.621094,114.201823 307.013346,112.955078 299.782227,115.947266 C292.551107,118.939453 288.935547,124.42513 288.935547,132.404297 L288.935547,132.404297 L288.935547,170.554688 L213.382812,170.554688 L213.382812,95.0019531 L251.533203,95.0019531 C259.51237,95.0019531 264.998047,91.3863932 267.990234,84.1552734 C270.982422,76.9241536 269.735677,70.3164062 264.25,64.3320312 L264.25,64.3320312 L205.154297,5.23632812 C201.663411,1.74544271 197.424479,0 192.4375,0 C187.450521,0 183.211589,1.74544271 179.720703,5.23632812 L179.720703,5.23632812 L120.625,64.3320312 C114.640625,70.3164062 113.269206,76.9241536 116.510742,84.1552734 C119.752279,91.3863932 125.36263,95.0019531 133.341797,95.0019531 L133.341797,95.0019531 L171.492188,95.0019531 L171.492188,170.554688 L95.9394531,170.554688 L95.9394531,132.404297 C95.9394531,124.42513 92.3238932,118.814779 85.0927734,115.573242 C77.8616536,112.331706 71.2539062,113.703125 65.2695312,119.6875 L65.2695312,119.6875 L6.17382812,178.783203 C2.68294271,182.274089 0.9375,186.513021 0.9375,191.5 C0.9375,196.486979 2.68294271,200.725911 6.17382812,204.216797 L6.17382812,204.216797 L65.2695312,263.3125 C71.2539062,268.798177 77.8616536,270.044922 85.0927734,267.052734 C92.3238932,264.060547 95.9394531,258.57487 95.9394531,250.595703 L95.9394531,250.595703 L95.9394531,212.445312 L171.492188,212.445312 L171.492188,287.998047 L133.341797,287.998047 C125.36263,287.998047 119.876953,291.613607 116.884766,298.844727 C113.892578,306.075846 115.139323,312.683594 120.625,318.667969 L120.625,318.667969 L179.720703,377.763672 C183.211589,381.254557 187.450521,383 192.4375,383 Z'%3E%3C/path%3E%3C/g%3E%3C/svg%3E");mask-image:url("data:image/svg+xml,%3C%3Fxml version='1.0' encoding='UTF-8'%3F%3E%3Csvg viewBox='0 0 384 383' xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'%3E%3Cg%3E%3Cpath d='M192.4375,383 C197.424479,383 201.663411,381.254557 205.154297,377.763672 L205.154297,377.763672 L264.25,318.667969 C270.234375,312.683594 271.605794,306.075846 268.364258,298.844727 C265.122721,291.613607 259.51237,287.998047 251.533203,287.998047 L251.533203,287.998047 L213.382812,287.998047 L213.382812,212.445312 L288.935547,212.445312 L288.935547,250.595703 C288.935547,258.57487 292.551107,264.185221 299.782227,267.426758 C307.013346,270.668294 313.621094,269.296875 319.605469,263.3125 L319.605469,263.3125 L378.701172,204.216797 C382.192057,200.725911 383.9375,196.486979 383.9375,191.5 C383.9375,186.513021 382.192057,182.274089 378.701172,178.783203 L378.701172,178.783203 L319.605469,119.6875 C313.621094,114.201823 307.013346,112.955078 299.782227,115.947266 C292.551107,118.939453 288.935547,124.42513 288.935547,132.404297 L288.935547,132.404297 L288.935547,170.554688 L213.382812,170.554688 L213.382812,95.0019531 L251.533203,95.0019531 C259.51237,95.0019531 264.998047,91.3863932 267.990234,84.1552734 C270.982422,76.9241536 269.735677,70.3164062 264.25,64.3320312 L264.25,64.3320312 L205.154297,5.23632812 C201.663411,1.74544271 197.424479,0 192.4375,0 C187.450521,0 183.211589,1.74544271 179.720703,5.23632812 L179.720703,5.23632812 L120.625,64.3320312 C114.640625,70.3164062 113.269206,76.9241536 116.510742,84.1552734 C119.752279,91.3863932 125.36263,95.0019531 133.341797,95.0019531 L133.341797,95.0019531 L171.492188,95.0019531 L171.492188,170.554688 L95.9394531,170.554688 L95.9394531,132.404297 C95.9394531,124.42513 92.3238932,118.814779 85.0927734,115.573242 C77.8616536,112.331706 71.2539062,113.703125 65.2695312,119.6875 L65.2695312,119.6875 L6.17382812,178.783203 C2.68294271,182.274089 0.9375,186.513021 0.9375,191.5 C0.9375,196.486979 2.68294271,200.725911 6.17382812,204.216797 L6.17382812,204.216797 L65.2695312,263.3125 C71.2539062,268.798177 77.8616536,270.044922 85.0927734,267.052734 C92.3238932,264.060547 95.9394531,258.57487 95.9394531,250.595703 L95.9394531,250.595703 L95.9394531,212.445312 L171.492188,212.445312 L171.492188,287.998047 L133.341797,287.998047 C125.36263,287.998047 119.876953,291.613607 116.884766,298.844727 C113.892578,306.075846 115.139323,312.683594 120.625,318.667969 L120.625,318.667969 L179.720703,377.763672 C183.211589,381.254557 187.450521,383 192.4375,383 Z'%3E%3C/path%3E%3C/g%3E%3C/svg%3E");width:11px;height:11px;background-size:cover;background-repeat:no-repeat}.arrow-down{position:absolute;right:5px;top:0}.arrow-down svg{width:8px;margin-top:5px;margin-left:5px;opacity:0.4}.cell-value-wrapper{margin-right:10px;overflow:hidden;text-overflow:ellipsis}revogr-data{display:block;width:100%;position:relative}revogr-data .rgRow{position:absolute;width:100%;left:0}revogr-data .rgRow.groupingRow{font-weight:600;text-align:left}revogr-data .rgRow.groupingRow .group-expand{width:25px;height:100%;max-height:25px;margin-right:2px;background-color:transparent;border-color:transparent;vertical-align:middle;padding-left:5px;display:inline-flex}revogr-data .rgRow.groupingRow .group-expand svg{width:7px}revogr-data .revo-draggable{border:none;height:32px;display:inline-flex;outline:0;padding:0;font-size:0.8125rem;box-sizing:border-box;align-items:center;white-space:nowrap;vertical-align:middle;justify-content:center;text-decoration:none;width:24px;height:100%;cursor:pointer;display:inline-flex}revogr-data .revo-draggable:hover>.revo-drag-icon{opacity:1;zoom:1.2;font-weight:600}revogr-data .revo-draggable>.revo-drag-icon{pointer-events:none;transition:opacity 300ms cubic-bezier(0.4, 0, 0.2, 1) 0ms, zoom 300ms cubic-bezier(0.4, 0, 0.2, 1) 0ms}revogr-data .rgCell{top:0;left:0;position:absolute;box-sizing:border-box;height:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;outline:none}revogr-data .rgCell.align-center{text-align:center}revogr-data .rgCell.align-left{text-align:left}revogr-data .rgCell.align-right{text-align:right}`;

const RevogrData = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.beforerowrender = createEvent(this, "beforerowrender", 7);
        this.afterrender = createEvent(this, "afterrender", 7);
        this.beforeCellRender = createEvent(this, "beforecellrender", 7);
        this.beforeDataRender = createEvent(this, "beforedatarender", 7);
        this.dragStartCell = createEvent(this, "dragstartcell", 7);
        /**
         * Prevent rendering until job is done.
         * Can be used for initial rendering performance improvement.
         * When several plugins require initial rendering this will prevent double initial rendering.
         */
        this.jobsBeforeRender = [];
        /**
         * Rendered rows - virtual index vs vnode
         */
        this.renderedRows = new Map();
    }
    /**
     * Pointed cell update.
     */
    async updateCell(e) {
        var _a, _b, _c;
        // Stencil tweak to update cell content
        const cell = (_b = (_a = this.renderedRows.get(e.row)) === null || _a === void 0 ? void 0 : _a.$children$) === null || _b === void 0 ? void 0 : _b[e.col];
        if ((_c = cell === null || cell === void 0 ? void 0 : cell.$attrs$) === null || _c === void 0 ? void 0 : _c.redraw) {
            const children = await convertVNodeToHTML(this.element, cell.$attrs$.redraw);
            cell.$elm$.innerHTML = children.html;
            cell.$key$ = Math.random();
        }
    }
    onDataStoreChange() {
        this.onStoreChange();
    }
    onColDataChange() {
        this.onStoreChange();
    }
    onStoreChange() {
        var _a, _b;
        (_a = this.columnService) === null || _a === void 0 ? void 0 : _a.destroy();
        this.columnService = new ColumnService(this.dataStore, this.colData);
        // make sure we have correct data, before render
        this.providers = {
            type: this.type,
            colType: this.colType,
            readonly: this.readonly,
            data: this.dataStore,
            columns: this.colData,
            viewport: this.viewportCol,
            dimension: this.dimensionRow,
            selection: this.rowSelectionStore,
        };
        (_b = this.rangeUnsubscribe) === null || _b === void 0 ? void 0 : _b.call(this);
        this.rangeUnsubscribe = this.rowSelectionStore.onChange('range', (e) => this.rowHighlightPlugin.selectionChange(e, this.renderedRows));
    }
    connectedCallback() {
        this.rowHighlightPlugin = new RowHighlightPlugin();
        this.onStoreChange();
    }
    disconnectedCallback() {
        var _a, _b;
        (_a = this.columnService) === null || _a === void 0 ? void 0 : _a.destroy();
        (_b = this.rangeUnsubscribe) === null || _b === void 0 ? void 0 : _b.call(this);
    }
    async componentWillRender() {
        this.beforeDataRender.emit({
            rowType: this.type,
            colType: this.colType,
        });
        return Promise.all(this.jobsBeforeRender.map(p => typeof p === 'function' ? p() : p));
    }
    componentDidRender() {
        this.afterrender.emit({ type: this.type });
    }
    render() {
        this.renderedRows = new Map();
        const columnsData = this.columnService.columns;
        if (!columnsData.length) {
            return;
        }
        const rows = this.viewportRow.get('items');
        if (!rows.length) {
            return;
        }
        const cols = this.viewportCol.get('items');
        if (!cols.length) {
            return;
        }
        const rowsEls = [];
        const depth = this.dataStore.get('groupingDepth');
        const groupingCustomRenderer = this.dataStore.get('groupingCustomRenderer');
        const groupDepth = this.columnService.hasGrouping ? depth : 0;
        const rowRenderOffset = this.viewportRow.get('renderOffset') || 0;
        const colRenderOffset = this.viewportCol.get('renderOffset') || 0;
        for (let rgRow of rows) {
            const dataItem = getSourceItem(this.dataStore, rgRow.itemIndex);
            // #region Grouping
            if (isGrouping(dataItem)) {
                const gmodel = Object.assign(Object.assign({}, rgRow), { start: rgRow.start - rowRenderOffset, index: rgRow.itemIndex, model: dataItem, groupingCustomRenderer,
                    // Only show expand button if grouping is enabled and not in row headers
                    hasExpand: this.columnService.hasGrouping && this.colType !== 'rowHeaders', columnItems: cols, providers: this.providers });
                rowsEls.push(h(GroupingRowRenderer, Object.assign({}, gmodel)));
                continue;
            }
            // #endregion
            const cells = [];
            // #region Cells
            for (let rgCol of cols) {
                const smodel = Object.assign(Object.assign({}, this.columnService.rowDataModel(rgRow.itemIndex, rgCol.itemIndex)), { providers: this.providers });
                // call before cell render
                const cellEvent = this.triggerBeforeCellRender(smodel, rgRow, rgCol);
                // if event was prevented
                if (cellEvent.defaultPrevented) {
                    continue;
                }
                const { detail: { column: columnProps, row: rowProps, model: schemaModel }, } = cellEvent;
                const defaultProps = {
                    [DATA_COL]: columnProps.itemIndex,
                    [DATA_ROW]: rowProps.itemIndex,
                    style: {
                        width: `${columnProps.size}px`,
                        transform: `translateX(${columnProps.start - colRenderOffset}px)`,
                        height: rowProps.size ? `${rowProps.size}px` : undefined,
                    },
                };
                /**
                 * For grouping, can be removed in the future and replaced with event
                 */
                if (groupDepth && !columnProps.itemIndex && defaultProps.style) {
                    defaultProps.style.paddingLeft = `${PADDING_DEPTH * groupDepth}px`;
                }
                const props = this.columnService.mergeProperties(rowProps.itemIndex, columnProps.itemIndex, defaultProps, schemaModel);
                // Never use webcomponent for cell render
                // It's very slow because of webcomponent initialization takes time
                const cellNode = h(CellRenderer, { renderProps: {
                        schemaModel,
                        additionalData: this.additionalData,
                        dragStartCell: this.dragStartCell,
                    }, cellProps: props });
                cells.push(cellNode);
            }
            // #endregion
            // #region Rows
            let rowClass = this.rowClass
                ? this.columnService.getRowClass(rgRow.itemIndex, this.rowClass)
                : '';
            if (this.rowHighlightPlugin.isRowFocused(rgRow.itemIndex)) {
                rowClass += ` ${ROW_FOCUSED_CLASS}`;
            }
            const row = (h(RowRenderer, { index: rgRow.itemIndex, rowClass: rowClass, size: rgRow.size, start: rgRow.start - rowRenderOffset, groupingLevel: groupDepth || undefined }, cells));
            this.beforerowrender.emit({
                node: row,
                item: rgRow,
                model: dataItem,
                colType: this.columnService.type,
                rowType: this.type,
            });
            rowsEls.push(row);
            this.renderedRows.set(rgRow.itemIndex, row);
            // #endregion
        }
        return (h(Host, null, h("slot", null), rowsEls));
    }
    triggerBeforeCellRender(model, row, column) {
        const detail = {
            column,
            row,
            model,
            rowType: model.type,
            colType: model.colType,
        };
        return this.beforeCellRender.emit(detail);
    }
    get element() { return getElement(this); }
    static get watchers() { return {
        "dataStore": [{
                "onDataStoreChange": 0
            }],
        "colData": [{
                "onColDataChange": 0
            }]
    }; }
};
RevogrData.style = revogrDataStyleCss();

const HeaderRenderer = (p) => {
    var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k;
    const hasSortingSign = !!(((_a = p.data) === null || _a === void 0 ? void 0 : _a.sortable) ||
        ((_b = p.data) === null || _b === void 0 ? void 0 : _b.order) ||
        ((_c = p.data) === null || _c === void 0 ? void 0 : _c.sortIndex));
    const cellClass = {
        [HEADER_CLASS]: true,
        [HEADER_SORTABLE_CLASS]: !!((_d = p.data) === null || _d === void 0 ? void 0 : _d.sortable),
    };
    if ((_e = p.data) === null || _e === void 0 ? void 0 : _e.order) {
        cellClass[p.data.order] = true;
    }
    const dataProps = {
        key: String((_g = (_f = p.data) === null || _f === void 0 ? void 0 : _f.prop) !== null && _g !== void 0 ? _g : p.column.itemIndex),
        [DATA_COL]: p.column.itemIndex,
        canResize: p.canResize,
        minWidth: ((_h = p.data) === null || _h === void 0 ? void 0 : _h.minSize) || MIN_COL_SIZE,
        maxWidth: (_j = p.data) === null || _j === void 0 ? void 0 : _j.maxSize,
        active: p.active || ['r'],
        class: cellClass,
        style: {
            width: `${p.column.size}px`,
            transform: `translateX(${p.column.start - (p.renderOffset || 0)}px)`,
        },
        onResize: p.onResize,
        onDblClick(originalEvent) {
            var _a;
            (_a = p.onDblClick) === null || _a === void 0 ? void 0 : _a.call(p, {
                column: p.data,
                index: p.column.itemIndex,
                originalEvent,
                providers: p.data.providers,
            });
        },
        onClick(originalEvent) {
            if (originalEvent.defaultPrevented || !p.onClick) {
                return;
            }
            p.onClick({
                column: p.data,
                index: p.column.itemIndex,
                originalEvent,
                providers: p.data.providers,
            });
        },
    };
    if (p.range) {
        if (p.column.itemIndex >= p.range.x && p.column.itemIndex <= p.range.x1) {
            if (typeof dataProps.class === 'object') {
                dataProps.class[FOCUS_CLASS] = true;
            }
        }
    }
    return (h(HeaderCellRenderer, { data: p.data, props: dataProps, additionalData: p.additionalData }, hasSortingSign ? h(SortingSign, { column: p.data }) : null, p.canFilter && ((_k = p.data) === null || _k === void 0 ? void 0 : _k.filter) !== false ? (h(FilterButton, { column: p.data })) : ('')));
};

const HeaderGroupRenderer = (p) => {
    const groupProps = {
        key: `${p.group.name}-${p.group.indexes.join('-')}`,
        canResize: p.canResize,
        minWidth: p.group.indexes.length * MIN_COL_SIZE,
        maxWidth: 0,
        active: p.active || ['r'],
        class: {
            [HEADER_CLASS]: true,
        },
        style: {
            transform: `translateX(${p.start - (p.renderOffset || 0)}px)`,
            width: `${p.end - p.start}px`,
        },
        onResize: p.onResize,
    };
    return (h(HeaderCellRenderer, { data: Object.assign(Object.assign({}, p.group), { prop: '', providers: p.providers, index: p.start }), props: groupProps, additionalData: p.additionalData }));
};

const revogrHeaderStyleCss = () => `@charset "UTF-8";revogr-header{position:relative;z-index:5;display:block}revogr-header .header-rgRow{display:block;position:relative}revogr-header .header-rgRow.group{z-index:0}revogr-header .group-rgRow{position:relative;overflow:hidden}revogr-header .rgHeaderCell{position:absolute;box-sizing:border-box;height:100%;z-index:1;display:flex}revogr-header .rgHeaderCell.align-center{text-align:center}revogr-header .rgHeaderCell.align-left{text-align:left}revogr-header .rgHeaderCell.align-right{text-align:right}revogr-header .rgHeaderCell.sortable{cursor:pointer}revogr-header .rgHeaderCell .sort-indicator{display:inline-flex;align-items:flex-start;gap:1px}revogr-header .rgHeaderCell .sort-indicator i.asc:after,revogr-header .rgHeaderCell .sort-indicator i.desc:after{font-size:13px}revogr-header .rgHeaderCell .sort-indicator i.asc:after{content:"↑"}revogr-header .rgHeaderCell .sort-indicator i.desc:after{content:"↓"}revogr-header .rgHeaderCell .sort-indicator .sort-order-index{font-size:10px;line-height:1;top:0}revogr-header .rgHeaderCell.active{z-index:10}revogr-header .rgHeaderCell.active .resizable{background-color:deepskyblue}revogr-header .rgHeaderCell .header-content{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-grow:1}revogr-header .rgHeaderCell .resizable{display:block;position:absolute;z-index:90;touch-action:none;user-select:none}revogr-header .rgHeaderCell .resizable:hover{background-color:deepskyblue}revogr-header .rgHeaderCell>.resizable-r{cursor:ew-resize;width:6px;right:0;top:0;height:100%}revogr-header .rgHeaderCell>.resizable-rb{cursor:se-resize;width:6px;height:6px;right:0;bottom:0}revogr-header .rgHeaderCell>.resizable-b{cursor:s-resize;height:6px;bottom:0;width:100%;left:0}revogr-header .rgHeaderCell>.resizable-lb{cursor:sw-resize;width:6px;height:6px;left:0;bottom:0}revogr-header .rgHeaderCell>.resizable-l{cursor:w-resize;width:6px;left:0;height:100%;top:0}revogr-header .rgHeaderCell>.resizable-lt{cursor:nw-resize;width:6px;height:6px;left:0;top:0}revogr-header .rgHeaderCell>.resizable-t{cursor:n-resize;height:6px;top:0;width:100%;left:0}revogr-header .rgHeaderCell>.resizable-rt{cursor:ne-resize;width:6px;height:6px;right:0;top:0}revogr-header .rv-filter{visibility:hidden}`;

const RevogrHeaderComponent = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.initialHeaderClick = createEvent(this, "beforeheaderclick", 7);
        this.headerresize = createEvent(this, "headerresize", 7);
        this.beforeResize = createEvent(this, "beforeheaderresize", 7);
        this.headerdblClick = createEvent(this, "headerdblclick", 7);
        this.beforeHeaderRender = createEvent(this, "beforeheaderrender", 7);
        this.beforeGroupHeaderRender = createEvent(this, "beforegroupheaderrender", 7);
        this.afterHeaderRender = createEvent(this, "afterheaderrender", 7);
        /**
         * Grouping depth, how many levels of grouping
         */
        this.groupingDepth = 0;
        /**
         * Extra properties to pass into header renderer, such as vue or react components to handle parent
         */
        this.additionalData = {};
    }
    onResize({ width }, index) {
        const col = this.colData[index];
        const event = this.beforeResize.emit([
            Object.assign(Object.assign({}, col), { size: width || undefined }),
        ]);
        if (event.defaultPrevented) {
            return;
        }
        this.headerresize.emit({ [index]: width || 0 });
    }
    onResizeGroup(changedX, startIndex, endIndex) {
        const sizes = {};
        const change = changedX / (endIndex - startIndex + 1);
        for (let i = startIndex; i <= endIndex; i++) {
            const item = getItemByIndex(this.dimensionCol.state, i);
            sizes[i] = item.end - item.start + change;
        }
        this.headerresize.emit(sizes);
    }
    componentDidRender() {
        this.afterHeaderRender.emit(this.providers);
    }
    render() {
        var _a;
        const cols = this.viewportCol.get('items');
        const range = (_a = this.selectionStore) === null || _a === void 0 ? void 0 : _a.get('range');
        const { cells } = this.renderHeaderColumns(cols, range);
        const groupRow = this.renderGroupingColumns();
        return [
            h("div", { key: '3cc466db6bc4df0cd61c47a22c3a0473318e5dd8', class: "group-rgRow" }, groupRow),
            h("div", { key: '9742a3fa4d4b75073aef5544806f42386ebffdea', class: `${HEADER_ROW_CLASS} ${HEADER_ACTUAL_ROW_CLASS}` }, cells),
        ];
    }
    renderHeaderColumns(cols, range) {
        const columnsToRender = [];
        const renderOffset = this.viewportCol.get('renderOffset') || 0;
        for (let rgCol of cols) {
            const colData = this.colData[rgCol.itemIndex];
            const props = {
                range,
                column: rgCol,
                data: Object.assign(Object.assign({}, colData), { index: rgCol.itemIndex, providers: this.providers }),
                canFilter: !!this.columnFilter,
                canResize: this.canResize,
                renderOffset,
                active: this.resizeHandler,
                additionalData: this.additionalData,
                onResize: e => this.onResize(e, rgCol.itemIndex),
                onDblClick: e => this.headerdblClick.emit(e),
                onClick: e => this.initialHeaderClick.emit(e),
            };
            const event = this.beforeHeaderRender.emit(props);
            if (!event.defaultPrevented) {
                columnsToRender.push(event.detail);
            }
        }
        const duplicateProps = this.getDuplicateHeaderProps(columnsToRender);
        const cells = columnsToRender.map(detail => h(HeaderRenderer, Object.assign({ key: this.getHeaderCellKey(detail.data, this.type, duplicateProps) }, detail)));
        return { cells };
    }
    renderGroupingColumns() {
        const visibleGroupRange = this.getVisibleGroupRange();
        return Array.from({ length: this.groupingDepth }, (_, level) => this.renderGroupRow(level, visibleGroupRange)).flat();
    }
    renderGroupRow(level, visibleGroupRange) {
        const groupCells = (this.groups[level] || [])
            .map(group => this.renderGroupColumn(group, level, visibleGroupRange))
            .filter((cell) => !!cell);
        return [
            ...groupCells,
            h('div', {
                key: `group-row-${level}`,
                class: {
                    [HEADER_ROW_CLASS]: true,
                    group: true,
                },
            }),
        ];
    }
    renderGroupColumn(group, level, visibleGroupRange) {
        const groupRange = this.getGroupIndexRange(group);
        const groupBounds = this.getGroupBounds(groupRange);
        const props = {
            level,
            providers: this.providers,
            start: groupBounds.start,
            end: groupBounds.end,
            group,
            renderOffset: this.viewportCol.get('renderOffset') || 0,
            active: this.resizeHandler,
            canResize: this.canResize,
            additionalData: this.additionalData,
            onResize: e => {
                var _a;
                return groupRange
                    ? this.onResizeGroup((_a = e.changedX) !== null && _a !== void 0 ? _a : 0, groupRange.startIndex, groupRange.endIndex)
                    : undefined;
            },
        };
        const event = this.beforeGroupHeaderRender.emit(props);
        if (event.defaultPrevented) {
            return;
        }
        const renderRange = this.getGroupIndexRange(event.detail.group);
        if (!renderRange ||
            !visibleGroupRange ||
            !isGroupInVisibleRange(renderRange.startIndex, renderRange.endIndex, visibleGroupRange)) {
            return;
        }
        if (event.detail.onResize === props.onResize) {
            event.detail.onResize = e => {
                var _a;
                return this.onResizeGroup((_a = e.changedX) !== null && _a !== void 0 ? _a : 0, renderRange.startIndex, renderRange.endIndex);
            };
        }
        const renderBounds = this.getGroupBounds(renderRange);
        if (event.detail.start === props.start) {
            event.detail.start = renderBounds.start;
        }
        if (event.detail.end === props.end) {
            event.detail.end = renderBounds.end;
        }
        return h(HeaderGroupRenderer, Object.assign({ key: this.getGroupHeaderCellKey(event.detail.group, level) }, event.detail));
    }
    getGroupIndexRange(group) {
        var _a;
        const startIndex = (_a = group.indexes[0]) !== null && _a !== void 0 ? _a : -1;
        if (startIndex < 0) {
            return;
        }
        const endIndex = group.indexes[group.indexes.length - 1];
        return {
            startIndex,
            endIndex,
        };
    }
    getGroupBounds(range) {
        if (!range) {
            return { start: 0, end: 0 };
        }
        return {
            start: getItemByIndex(this.dimensionCol.state, range.startIndex).start,
            end: getItemByIndex(this.dimensionCol.state, range.endIndex).end,
        };
    }
    getVisibleGroupRange() {
        const visibleColumns = this.viewportCol.get('items');
        if (!visibleColumns.length) {
            return;
        }
        return visibleColumns.reduce((range, column) => ({
            start: Math.min(range.start, column.itemIndex),
            end: Math.max(range.end, column.itemIndex),
        }), {
            start: visibleColumns[0].itemIndex,
            end: visibleColumns[0].itemIndex,
        });
    }
    getHeaderCellKey(column, type, duplicateProps) {
        if ((column === null || column === void 0 ? void 0 : column.prop) === undefined) {
            return `${type}-${String(column === null || column === void 0 ? void 0 : column.index)}`;
        }
        const propKey = String(column.prop);
        if (duplicateProps.has(propKey)) {
            return `${type}-${propKey}-${String(column.index)}`;
        }
        return `${type}-${propKey}`;
    }
    getDuplicateHeaderProps(columns) {
        const seenProps = new Set();
        const duplicateProps = new Set();
        columns.forEach(({ data }) => {
            if ((data === null || data === void 0 ? void 0 : data.prop) !== undefined) {
                const propKey = String(data.prop);
                if (seenProps.has(propKey)) {
                    duplicateProps.add(propKey);
                }
                else {
                    seenProps.add(propKey);
                }
            }
        });
        return duplicateProps;
    }
    getGroupHeaderCellKey(group, level) {
        return `group-${level}-${group.name}-${group.indexes.join('-')}`;
    }
    get providers() {
        return {
            type: this.type,
            readonly: this.readonly,
            data: this.colData,
            viewport: this.viewportCol,
            dimension: this.dimensionCol,
            selection: this.selectionStore,
        };
    }
    get element() { return getElement(this); }
};
function isGroupInVisibleRange(groupStartIndex, groupEndIndex, visibleRange) {
    return (groupStartIndex <= visibleRange.end &&
        groupEndIndex >= visibleRange.start);
}
RevogrHeaderComponent.style = revogrHeaderStyleCss();

class GridResizeService {
    constructor(el, resize, elements) {
        this.resize = resize;
        this.resizeObserver = null;
        this.previousSize = {
            width: 0,
            height: 0,
        };
        this.apply = throttle((e) => {
            var _a;
            const entry = {
                width: e.width,
                height: e.height,
            };
            (_a = this.resize) === null || _a === void 0 ? void 0 : _a.call(this, entry, this.previousSize);
            this.previousSize = entry;
        }, 40, {
            leading: false,
            trailing: true,
        });
        const extras = [];
        elements.forEach((element) => {
            if (element) {
                extras.push(element);
            }
        });
        this.init(el, extras);
    }
    init(el, extras = []) {
        const observer = this.resizeObserver = new ResizeObserver((e) => {
            if (e.length) {
                if (e[0].target === el) {
                    this.apply(e[0].contentRect);
                }
                else {
                    this.apply(el.getBoundingClientRect());
                }
            }
        });
        observer.observe(el);
        extras.forEach((extra) => {
            observer.observe(extra);
        });
    }
    destroy() {
        var _a;
        this.apply.cancel();
        (_a = this.resizeObserver) === null || _a === void 0 ? void 0 : _a.disconnect();
        this.resizeObserver = null;
    }
}

const revogrViewportScrollStyleCss = () => `.rowHeaders{z-index:2;font-size:10px;display:flex;height:100%}.rowHeaders revogr-data .rgCell{text-align:center}.rowHeaders .rgCell{padding:0 1em !important;min-width:100%}revogr-viewport-scroll{-ms-overflow-style:none;scrollbar-width:none;overflow-x:auto;overflow-y:hidden;position:relative;z-index:1;height:100%}revogr-viewport-scroll::-webkit-scrollbar{display:none;-webkit-appearance:none}revogr-viewport-scroll.colPinStart,revogr-viewport-scroll.colPinEnd{z-index:2}revogr-viewport-scroll.colPinEnd:has(.active){overflow:visible}revogr-viewport-scroll.rgCol{flex-grow:1}revogr-viewport-scroll .content-wrapper{overflow:hidden}revogr-viewport-scroll .inner-content-table{display:flex;flex-direction:column;max-height:100%;width:100%;min-width:100%;position:relative;z-index:0}revogr-viewport-scroll .vertical-inner{overflow-y:auto;position:relative;width:100%;flex-grow:1;outline:none;-ms-overflow-style:none;scrollbar-width:none;}revogr-viewport-scroll .vertical-inner::-webkit-scrollbar{display:none;-webkit-appearance:none}revogr-viewport-scroll .vertical-inner revogr-data,revogr-viewport-scroll .vertical-inner revogr-overlay-selection{height:100%}`;

const RevogrViewportScroll = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.scrollViewport = createEvent(this, "scrollviewport", 7);
        this.resizeViewport = createEvent(this, "resizeviewport", 7);
        this.scrollchange = createEvent(this, "scrollchange", 7);
        this.silentScroll = createEvent(this, "scrollviewportsilent", 7);
        /**
         * Width of inner content
         */
        this.contentWidth = 0;
        /**
         * Height of inner content
         */
        this.contentHeight = 0;
        this.noHorizontalScrollTransfer = false;
    }
    async setScroll(e) {
        var _a;
        this.localScrollTimer.latestScrollUpdate(e.dimension);
        (_a = this.localScrollService) === null || _a === void 0 ? void 0 : _a.setScroll(e);
    }
    /**
     * update on delta in case we don't know existing position or external change
     * @param e
     */
    async changeScroll(e, silent = false) {
        var _a, _b, _c, _d;
        if (silent) {
            if (e.coordinate && this.verticalScroll) {
                switch (e.dimension) {
                    // for mobile devices to skip negative scroll loop. only on vertical scroll
                    case 'rgRow':
                        this.verticalScroll.style.transform = `translateY(${ -1 * e.coordinate}px)`;
                        break;
                }
            }
            return;
        }
        if (e.delta) {
            let currentPhysicalCoordinate = 0;
            switch (e.dimension) {
                case 'rgCol':
                    currentPhysicalCoordinate = this.horizontalScroll.scrollLeft;
                    break;
                case 'rgRow':
                    currentPhysicalCoordinate = (_b = (_a = this.verticalScroll) === null || _a === void 0 ? void 0 : _a.scrollTop) !== null && _b !== void 0 ? _b : 0;
                    break;
            }
            return (_d = (_c = this.localScrollService) === null || _c === void 0 ? void 0 : _c.setScrollByDelta(e, currentPhysicalCoordinate)) !== null && _d !== void 0 ? _d : e;
        }
        return e;
    }
    /**
     * Dispatch this event to trigger vertical mouse wheel from plugins
     */
    mousewheelVertical({ detail: e, }) {
        this.verticalMouseWheel(e);
    }
    /**
     * Dispatch this event to trigger horizontal mouse wheel from plugins
     */
    mousewheelHorizontal({ detail: e, }) {
        this.horizontalMouseWheel(e);
    }
    /**
     * Allows to use outside listener
     */
    scrollApply({ detail: { type, coordinate }, }) {
        this.applyOnScroll(type, coordinate, true);
    }
    connectedCallback() {
        /**
         * Bind scroll functions for farther usage
         */
        // allow mousewheel for all devices including mobile
        this.verticalMouseWheel = this.onVerticalMouseWheel.bind(this, 'rgRow', 'deltaY');
        this.horizontalMouseWheel = this.onHorizontalMouseWheel.bind(this, 'rgCol', 'deltaX');
        this.localScrollTimer = new LocalScrollTimer('ontouchstart' in document.documentElement ? 0 : 10);
        /**
         * Create local scroll service
         */
        this.localScrollService = new LocalScrollService({
            // to improve safari smoothnes on scroll
            // skipAnimationFrame: isSafariDesktop(),
            runScroll: e => this.scrollViewport.emit(e),
            applyScroll: e => {
                this.localScrollTimer.setCoordinate(e);
                switch (e.dimension) {
                    case 'rgCol':
                        // this will trigger on scroll event
                        this.horizontalScroll.scrollLeft = e.coordinate;
                        break;
                    case 'rgRow':
                        if (this.verticalScroll) {
                            // this will trigger on scroll event
                            this.verticalScroll.scrollTop = e.coordinate;
                            // for mobile devices to skip negative scroll loop. only on vertical scroll
                            if (this.verticalScroll.style.transform) {
                                this.verticalScroll.style.transform = '';
                            }
                        }
                        break;
                }
            },
        });
    }
    componentDidLoad() {
        // track viewport resize
        this.resizeService = new GridResizeService(this.horizontalScroll, (entry) => {
            var _a, _b, _c, _d, _e, _f, _g, _h;
            const els = {};
            let calculatedHeight = entry.height || 0;
            if (calculatedHeight) {
                calculatedHeight -=
                    ((_b = (_a = this.header) === null || _a === void 0 ? void 0 : _a.clientHeight) !== null && _b !== void 0 ? _b : 0) +
                        ((_d = (_c = this.footer) === null || _c === void 0 ? void 0 : _c.clientHeight) !== null && _d !== void 0 ? _d : 0);
            }
            els.rgRow = {
                size: calculatedHeight,
                contentSize: this.contentHeight,
                scroll: (_f = (_e = this.verticalScroll) === null || _e === void 0 ? void 0 : _e.scrollTop) !== null && _f !== void 0 ? _f : 0,
                noScroll: false,
            };
            const calculatedWidth = entry.width || 0;
            els.rgCol = {
                size: calculatedWidth,
                contentSize: this.contentWidth,
                scroll: this.horizontalScroll.scrollLeft,
                noScroll: this.colType !== 'rgCol',
            };
            this.setScrollParams({
                rgRow: calculatedHeight,
                rgCol: calculatedWidth,
            });
            // Process changes in order: width first, then height
            const dimensions = ['rgCol', 'rgRow'];
            for (const dimension of dimensions) {
                const item = els[dimension];
                if (!item)
                    continue;
                this.resizeViewport.emit({
                    dimension,
                    size: item.size,
                    rowHeader: this.rowHeader,
                });
                if (item.noScroll) {
                    continue;
                }
                (_g = this.localScrollService) === null || _g === void 0 ? void 0 : _g.scroll((_h = item.scroll) !== null && _h !== void 0 ? _h : 0, dimension, true);
                // track scroll visibility on outer element change
                this.setScrollVisibility(dimension, item.size, item.contentSize);
            }
        }, [this.footer, this.header]);
    }
    /**
     * Check if scroll present or not per type
     * Trigger this method on inner content size change or on outer element size change
     * If inner content bigger then outer size then scroll is present and mousewheel binding required
     * @param type - dimension type 'rgRow/y' or 'rgCol/x'
     * @param size - outer content size
     * @param innerContentSize - inner content size
     */
    setScrollVisibility(type, size, innerContentSize) {
        // test if scroll present
        const hasScroll = size < innerContentSize;
        let el;
        // event reference for binding
        switch (type) {
            case 'rgCol':
                el = this.horizontalScroll;
                break;
            case 'rgRow':
                el = this.verticalScroll;
                break;
        }
        // based on scroll visibility assign or remove class and event
        if (hasScroll) {
            el === null || el === void 0 ? void 0 : el.classList.add(`scroll-${type}`);
        }
        else {
            el === null || el === void 0 ? void 0 : el.classList.remove(`scroll-${type}`);
        }
        this.scrollchange.emit({ type, hasScroll });
    }
    disconnectedCallback() {
        var _a;
        (_a = this.resizeService) === null || _a === void 0 ? void 0 : _a.destroy();
    }
    async componentDidRender() {
        var _a, _b, _c, _d;
        this.setScrollParams({
            rgRow: (_b = (_a = this.verticalScroll) === null || _a === void 0 ? void 0 : _a.clientHeight) !== null && _b !== void 0 ? _b : 0,
            rgCol: this.horizontalScroll.clientWidth,
        });
        this.setScrollVisibility('rgRow', (_d = (_c = this.verticalScroll) === null || _c === void 0 ? void 0 : _c.clientHeight) !== null && _d !== void 0 ? _d : 0, this.contentHeight);
        this.setScrollVisibility('rgCol', this.horizontalScroll.clientWidth, this.contentWidth);
    }
    setScrollParams(clientSize) {
        this.localScrollService.setParams({
            contentSize: this.contentHeight,
            clientSize: clientSize.rgRow,
            virtualSize: 0,
        }, 'rgRow');
        this.localScrollService.setParams({
            contentSize: this.contentWidth,
            clientSize: clientSize.rgCol,
            virtualSize: 0,
        }, 'rgCol');
    }
    render() {
        var _a, _b;
        const clientHeight = (_b = (_a = this.verticalScroll) === null || _a === void 0 ? void 0 : _a.clientHeight) !== null && _b !== void 0 ? _b : 0;
        // When content fits in the viewport (no scroll needed), don't inflate content-wrapper
        // to clientHeight — that would prevent inner-content-table from shrinking and push
        // rowPinEnd (footer) to the bottom instead of letting it follow the data rows.
        // For large/compressed grids (content > clientHeight), physicalContentHeight handles
        // the browser scroll-size compression correctly.
        const physicalContentHeight = this.contentHeight < clientHeight
            ? Math.max(this.contentHeight, 0)
            : getContentSize(this.contentHeight, clientHeight);
        const physicalContentWidth = getContentSize(this.contentWidth, 0);
        return (h(Host, { key: '3dd9d29cf26743d7aa4995f51180d56008526e54', onWheel: this.horizontalMouseWheel, onScroll: (e) => this.applyScroll('rgCol', e) }, h("div", { key: 'af75428e845044c33eba2fecd1ec04a9177b9b5c', class: "inner-content-table", style: { width: `${physicalContentWidth}px` } }, h("div", { key: 'a0149f597588371e1fafe69efc3bd4411379a017', class: "header-wrapper", ref: e => (this.header = e) }, h("slot", { key: 'e5d2570bf93897cd97ef702141c83bb8c0e13ee2', name: HEADER_SLOT })), h("div", { key: 'd1388ff0d721dd8ce925b934bb2128fddc1ac17b', class: "vertical-inner", ref: el => (this.verticalScroll = el), onWheel: this.verticalMouseWheel, onScroll: (e) => this.applyScroll('rgRow', e) }, h("div", { key: 'a306ff56f62279402e2a881a081e3224341d5bdf', class: "content-wrapper", style: { height: `${physicalContentHeight}px` } }, h("slot", { key: '898bda8e9429da06c9ff2bd41626ac27f3cde3cc', name: CONTENT_SLOT }))), h("div", { key: '5e9eba1edd5fca07a964971054a7900e4dd84099', class: "footer-wrapper", ref: e => (this.footer = e) }, h("slot", { key: 'f233ad1c23b3f692c45e1db235cfef4704a80726', name: FOOTER_SLOT })))));
    }
    /**
     * Extra layer for scroll event monitoring, where MouseWheel event is not passing
     * We need to trigger scroll event in case there is no mousewheel event
     */
    async applyScroll(type, e) {
        if (!(e.target instanceof HTMLElement)) {
            return;
        }
        let scroll = 0;
        switch (type) {
            case 'rgCol':
                scroll = e.target.scrollLeft;
                break;
            case 'rgRow':
                scroll = e.target.scrollTop;
                break;
        }
        // for mobile devices to skip negative scroll loop
        if (scroll < 0) {
            this.silentScroll.emit({ dimension: type, coordinate: scroll });
            return;
        }
        this.applyOnScroll(type, scroll);
    }
    /**
     * Applies change on scroll event only if mousewheel event happened some time ago
     */
    applyOnScroll(type, coordinate, outside = false) {
        const lastScrollUpdate = () => {
            var _a;
            (_a = this.localScrollService) === null || _a === void 0 ? void 0 : _a.scroll(coordinate, type, undefined, undefined, outside);
            this.localScrollTimer.setCoordinateFromScroll({ dimension: type, coordinate });
        };
        // apply after throttling
        if (this.localScrollTimer.isReady(type, coordinate)) {
            lastScrollUpdate();
        }
        else {
            this.localScrollTimer.throttleLastScrollUpdate(type, coordinate, () => lastScrollUpdate());
        }
    }
    /**
     * On vertical mousewheel event
     * @param type
     * @param delta
     * @param e
     */
    onVerticalMouseWheel(type, delta, e) {
        var _a, _b, _c, _d, _e, _f, _g, _h;
        const scrollTop = (_b = (_a = this.verticalScroll) === null || _a === void 0 ? void 0 : _a.scrollTop) !== null && _b !== void 0 ? _b : 0;
        const clientHeight = (_d = (_c = this.verticalScroll) === null || _c === void 0 ? void 0 : _c.clientHeight) !== null && _d !== void 0 ? _d : 0;
        const scrollHeight = (_f = (_e = this.verticalScroll) === null || _e === void 0 ? void 0 : _e.scrollHeight) !== null && _f !== void 0 ? _f : 0;
        // Detect if the user has reached the bottom
        const atBottom = scrollTop + clientHeight >= scrollHeight && e.deltaY > 0;
        const atTop = scrollTop === 0 && e.deltaY < 0;
        if (!atBottom && !atTop) {
            (_g = e.preventDefault) === null || _g === void 0 ? void 0 : _g.call(e);
        }
        const pos = scrollTop + e[delta];
        (_h = this.localScrollService) === null || _h === void 0 ? void 0 : _h.scroll(pos, type, undefined, e[delta]);
        this.localScrollTimer.latestScrollUpdate(type);
    }
    /**
     * On horizontal mousewheel event
     * @param type
     * @param delta
     * @param e
     */
    onHorizontalMouseWheel(type, delta, e) {
        var _a, _b, _c, _d;
        if (!e.deltaX) {
            return;
        }
        const { scrollLeft, scrollWidth, clientWidth } = this.horizontalScroll;
        // Detect if the user has reached the right end
        const atRight = scrollLeft + clientWidth >= scrollWidth && e.deltaX > 0;
        // Detect if the user has reached the left end
        const atLeft = scrollLeft === 0 && e.deltaX < 0;
        if (this.noHorizontalScrollTransfer) {
            if (!atRight && !atLeft) {
                const nextScrollLeft = scrollLeft + e[delta];
                (_a = e.preventDefault) === null || _a === void 0 ? void 0 : _a.call(e);
                this.horizontalScroll.scrollLeft = nextScrollLeft;
                (_b = this.localScrollService) === null || _b === void 0 ? void 0 : _b.scroll(this.horizontalScroll.scrollLeft, type, undefined, e[delta]);
                this.localScrollTimer.latestScrollUpdate(type);
            }
            return;
        }
        if (!atRight && !atLeft) {
            (_c = e.preventDefault) === null || _c === void 0 ? void 0 : _c.call(e);
        }
        const pos = scrollLeft + e[delta];
        (_d = this.localScrollService) === null || _d === void 0 ? void 0 : _d.scroll(pos, type, undefined, e[delta]);
        this.localScrollTimer.latestScrollUpdate(type);
    }
    get horizontalScroll() { return getElement(this); }
};
RevogrViewportScroll.style = revogrViewportScrollStyleCss();

const VNodeToHtml = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.html = createEvent(this, "html", 7);
        this.redraw = null;
        this.vnodes = [];
    }
    componentDidRender() {
        this.html.emit({
            html: this.el.innerHTML,
            vnodes: this.vnodes,
        });
    }
    render() {
        var _a, _b;
        this.vnodes = (_b = (_a = this.redraw) === null || _a === void 0 ? void 0 : _a.call(this)) !== null && _b !== void 0 ? _b : null;
        return (h(Host, { key: '11b76ca8a86ebf279add88bbd86ef9eb5149605a', style: { visibility: 'hidden', position: 'absolute' } }, this.vnodes));
    }
    get el() { return getElement(this); }
};

export { RevogrData as revogr_data, RevogrHeaderComponent as revogr_header, RevogrViewportScroll as revogr_viewport_scroll, VNodeToHtml as vnode_html };
