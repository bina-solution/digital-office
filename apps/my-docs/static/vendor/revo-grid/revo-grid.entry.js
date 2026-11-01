/*!
 * Built by Revolist OU ❤️
 */
import { h, r as registerInstance, d as createEvent, e as Host, g as getElement } from './index-Chp_81rd.js';
import { c as columnTypes, J as reduce, C as getColumnType, r as rowTypes, i as isRowType, D as getColumnSizes, a as cropCellToMax, n as nextCell, I as getColumnByProp, F as getColumns } from './column.service-C6hByxPy.js';
import { D as DataStore, b as getSourceItem, f as getSourceItemVirtualIndexByProp, d as setSourceByPhysicalIndex, s as setSourceByVirtualIndex, a as getVisibleSourceItem, h as gatherTrimmedItems, k as getItemByIndex, R as RESIZE_INTERVAL } from './dimension.helpers-CGKwSvw6.js';
import { d as debounce } from './debounce-PCRWZliA.js';
import { g as getScrollDimension, v as viewportDataPartition, F as FOOTER_SLOT, C as CONTENT_SLOT, H as HEADER_SLOT, D as DATA_SLOT } from './viewport.helpers-CoCAvmZs.js';
import { D as DimensionStore, S as SelectionStore, B as BasePlugin, G as GroupingRowPlugin, a as StretchColumn, i as isStretchPlugin, A as AutoSizeColumnPlugin, e as FilterPlugin, E as ExportFilePlugin, s as SortingPlugin, p as ColumnMovePlugin } from './column.drag.plugin-DKkf7Zqb.js';
import { V as ViewportStore } from './viewport.store-_c579YyM.js';
import { T as ThemeService } from './theme.service-BmnDvr6P.js';
import { t as timeout } from './index-Db3qZoW5.js';
import { g as getPropertyFromEvent } from './events-BvSmBueA.js';
import './filter.button-B-RBiF67.js';
import './header-cell-renderer-BMmXRsd_.js';

class ColumnDataProvider {
    get stores() {
        return this.dataSources;
    }
    constructor() {
        this.collection = null;
        this.dataSources = columnTypes.reduce((sources, k) => {
            sources[k] = new DataStore(k);
            return sources;
        }, {});
    }
    column(c, type = 'rgCol') {
        return this.getColumn(c, type);
    }
    getColumn(virtualIndex, type) {
        return getSourceItem(this.dataSources[type].store, virtualIndex);
    }
    getRawColumns() {
        return reduce(this.dataSources, (result, item, type) => {
            result[type] = item.store.get('source');
            return result;
        }, {
            rgCol: [],
            colPinStart: [],
            colPinEnd: [],
        });
    }
    getColumns(type = 'all') {
        const columnsByType = this.getRawColumns();
        if (type !== 'all') {
            return columnsByType[type];
        }
        return columnTypes.reduce((r, t) => [...r, ...columnsByType[t]], []);
    }
    getColumnIndexByProp(prop, type) {
        return getSourceItemVirtualIndexByProp(this.dataSources[type].store, prop);
    }
    getColumnByProp(prop) {
        var _a;
        return (_a = this.collection) === null || _a === void 0 ? void 0 : _a.columnByProp[prop];
    }
    refreshByType(type) {
        this.dataSources[type].refresh();
    }
    /**
     * Main method to set columns
     */
    setColumns(data) {
        columnTypes.forEach(k => {
            // set columns data
            this.dataSources[k].updateData(data.columns[k], {
                // max depth level
                depth: data.maxLevel,
                // groups
                groups: data.columnGrouping[k].reduce((res, g) => {
                    if (!res[g.level]) {
                        res[g.level] = [];
                    }
                    res[g.level].push(g);
                    return res;
                }, {}),
            });
        });
        this.collection = data;
        return data;
    }
    /**
     * Used in plugins
     * Modify columns in store
     */
    updateColumns(updatedColumns) {
        // collect column by type and propert
        const columnByKey = updatedColumns.reduce((res, c) => {
            const type = getColumnType(c);
            if (!res[type]) {
                res[type] = {};
            }
            res[type][c.prop] = c;
            return res;
        }, {});
        // find indexes in source
        const colByIndex = {};
        for (const t in columnByKey) {
            if (!columnByKey.hasOwnProperty(t)) {
                continue;
            }
            const type = t;
            const colsToUpdate = columnByKey[type];
            const sourceItems = this.dataSources[type].store.get('source');
            colByIndex[type] = {};
            for (let i = 0; i < sourceItems.length; i++) {
                const column = sourceItems[i];
                const colToUpdateIfExists = colsToUpdate === null || colsToUpdate === void 0 ? void 0 : colsToUpdate[column.prop];
                // update column if exists in source
                if (colToUpdateIfExists) {
                    colByIndex[type][i] = colToUpdateIfExists;
                }
            }
        }
        for (const t in colByIndex) {
            if (!colByIndex.hasOwnProperty(t)) {
                continue;
            }
            const type = t;
            setSourceByPhysicalIndex(this.dataSources[type].store, colByIndex[type] || {});
        }
    }
    updateColumn(column, index) {
        const type = getColumnType(column);
        setSourceByVirtualIndex(this.dataSources[type].store, { [index]: column });
    }
}

/**
 * Data source provider
 *
 * @dependsOn DimensionProvider
 */
class DataProvider {
    constructor(dimensionProvider) {
        this.dimensionProvider = dimensionProvider;
        this.stores = reduce(rowTypes, (sources, k) => {
            sources[k] = new DataStore(k);
            return sources;
        }, {});
    }
    /**
     * Replaces the data source for a row type and synchronizes the related dimension metadata.
     *
     * `rgRow` updates also refresh the virtual row model unless `disableVirtualRows` is set.
     * Pinned row types skip virtual row recalculation because they are rendered directly.
     *
     * @param data Full source data assigned to the target row store.
     * @param type Row collection to update. Defaults to the main body rows.
     * @param disableVirtualRows Prevents recalculating virtual rows for the main row store.
     * @param grouping Optional grouping metadata applied together with the new data set.
     * @param silent Preserves the current trimmed state instead of resetting it during the update.
     * @param preserveTrimmed Re-applies current trimmed indexes after a silent update.
     * @returns The same `data` array that was provided to the method.
     */
    setData(data, type = 'rgRow', disableVirtualRows = false, grouping, 
    // if true, store will be updated without resetting trimmed state
    silent = false, preserveTrimmed = false) {
        // set rgRow data
        this.stores[type].updateData([...data], grouping, silent, preserveTrimmed);
        // for pinned row no need virtual data
        const noVirtual = type !== 'rgRow' || disableVirtualRows;
        this.dimensionProvider.setData(data.length, type, noVirtual);
        return data;
    }
    getModel(virtualIndex, type = 'rgRow') {
        const store = this.stores[type].store;
        return getSourceItem(store, virtualIndex);
    }
    changeOrder({ rowType = 'rgRow', from, to }) {
        const storeService = this.stores[rowType];
        // take currently visible row indexes
        const newItemsOrder = [...storeService.store.get('proxyItems')];
        const prevItems = storeService.store.get('items');
        // take out
        const toMove = newItemsOrder.splice(newItemsOrder.indexOf(prevItems[from]), // get index in proxy
        1);
        const targetItem = prevItems[from < to ? to + 1 : to];
        const targetIndex = targetItem === undefined
            ? newItemsOrder.length
            : newItemsOrder.indexOf(targetItem);
        // insert before
        newItemsOrder.splice(targetIndex, 0, ...toMove);
        storeService.setData({
            proxyItems: newItemsOrder,
        });
        // take currently visible row indexes
        const newItems = storeService.store.get('items');
        this.dimensionProvider.updateSizesPositionByNewDataIndexes(rowType, newItems, prevItems);
    }
    setCellData({ type, rowIndex, prop, val }, mutate = true) {
        const model = this.getModel(rowIndex, type);
        model[prop] = val;
        this.stores[type].setSourceData({ [rowIndex]: model }, mutate);
    }
    setRangeData(data, type) {
        const items = {};
        for (let rowIndex in data) {
            const oldModel = (items[rowIndex] = getSourceItem(this.stores[type].store, parseInt(rowIndex, 10)));
            if (!oldModel) {
                continue;
            }
            for (let prop in data[rowIndex]) {
                oldModel[prop] = data[rowIndex][prop];
            }
        }
        this.stores[type].setSourceData(items);
    }
    refresh(type = 'all') {
        if (isRowType(type)) {
            this.refreshItems(type);
        }
        rowTypes.forEach((t) => this.refreshItems(t));
    }
    refreshItems(type = 'rgRow') {
        const items = this.stores[type].store.get('items');
        this.stores[type].setData({ items: [...items] });
    }
    setGrouping({ depth }, type = 'rgRow') {
        this.stores[type].setData({ groupingDepth: depth });
    }
    setTrimmed(trimmed, type = 'rgRow') {
        const store = this.stores[type];
        store.addTrimmed(trimmed);
        this.dimensionProvider.setTrimmed(trimmed, type);
        if (type === 'rgRow') {
            this.dimensionProvider.setData(getVisibleSourceItem(store.store).length, type);
        }
    }
}

const DEFAULT_VIRTUAL_X = ['rgCol'];
function isVirtualXDimension(type, disableVirtualX = false, virtualX = DEFAULT_VIRTUAL_X) {
    return !disableVirtualX && virtualX.includes(type);
}
/**
 * Dimension provider
 * Stores dimension information and custom sizes
 *
 * @dependsOn ViewportProvider
 */
class DimensionProvider {
    constructor(viewports, config) {
        this.viewports = viewports;
        const sizeChanged = debounce((k) => config.realSizeChanged(k), RESIZE_INTERVAL);
        this.stores = [...rowTypes, ...columnTypes].reduce((sources, t) => {
            sources[t] = new DimensionStore(t);
            sources[t].store.onChange('realSize', () => sizeChanged(t));
            return sources;
        }, {});
    }
    /**
     * Clear old sizes from dimension and viewports
     * @param type - dimension type
     * @param count - count of items
     */
    clearSize(t, count) {
        this.stores[t].drop();
        // after we done with drop trigger viewport recalculaction
        this.viewports.stores[t].setOriginalSizes(this.stores[t].store.get('originItemSize'));
        this.setItemCount(count, t);
    }
    /**
     * Apply new custom sizes to dimension and view port
     * @param type - dimension type
     * @param sizes - new custom sizes
     * @param keepOld - keep old sizes merge new with old
     */
    setCustomSizes(type, sizes, keepOld = false) {
        let newSizes = sizes;
        if (keepOld) {
            const oldSizes = this.stores[type].store.get('sizes');
            newSizes = Object.assign(Object.assign({}, oldSizes), sizes);
        }
        this.stores[type].setDimensionSize(newSizes);
        this.setViewPortCoordinate({
            type,
            force: true,
        });
    }
    setItemCount(realCount, type) {
        this.viewports.stores[type].setViewport({ realCount });
        this.stores[type].setStore({ count: realCount });
    }
    /**
     * Apply trimmed items
     * @param trimmed - trimmed items
     * @param type
     */
    setTrimmed(trimmed, type) {
        const allTrimmed = gatherTrimmedItems(trimmed);
        const dimStoreType = this.stores[type];
        dimStoreType.setStore({ trimmed: allTrimmed });
        this.setViewPortCoordinate({
            type,
            force: true,
        });
    }
    /**
     * Sets dimension data and viewport coordinate
     * @param itemCount
     * @param type - dimension type
     * @param noVirtual - disable virtual data
     */
    setData(itemCount, type, noVirtual = false) {
        this.setItemCount(itemCount, type);
        // Virtualization will get disabled
        if (noVirtual) {
            const dimension = this.stores[type].getCurrentState();
            this.viewports.stores[type].setViewport({
                virtualSize: dimension.realSize,
            });
        }
        this.setViewPortCoordinate({
            type,
        });
    }
    /**
     * Applies new columns to the dimension provider
     * @param columns - new columns data
     * @param disableVirtualX - disable virtual data for X axis
     * @param virtualX - column dimensions that should use virtual data
     */
    applyNewColumns(columns, disableVirtualX, keepOld = false, virtualX = DEFAULT_VIRTUAL_X) {
        // Apply new columns to dimension provider
        for (let type of columnTypes) {
            if (!keepOld) {
                // Clear existing data in the dimension provider
                this.stores[type].drop();
            }
            // Get the new columns for the current type
            const items = columns[type];
            // Determine if virtual data should be disabled for the current type
            const noVirtual = !isVirtualXDimension(type, disableVirtualX, virtualX);
            // Set the items count in the dimension provider
            this.stores[type].setStore({ count: items.length });
            // Set the custom sizes for the columns
            const newSizes = getColumnSizes(items);
            this.stores[type].setDimensionSize(newSizes);
            // Update the viewport with new data
            const vpUpdate = {
                // This triggers drop on realCount change
                realCount: items.length,
            };
            // If virtual data is disabled, set the virtual size to the real size
            if (noVirtual) {
                vpUpdate.virtualSize = this.stores[type].getCurrentState().realSize;
            }
            // Update the viewport
            this.viewports.stores[type].setViewport(vpUpdate);
            this.setViewPortCoordinate({
                type,
            });
        }
    }
    /**
     * Gets the full size of the grid by summing up the sizes of all dimensions
     * Goes through all dimensions columnTypes (x) and rowTypes (y) and sums up their sizes
     */
    getFullSize() {
        var _a, _b;
        let x = 0;
        let y = 0;
        for (let type of columnTypes) {
            x += ((_a = this.stores[type]) === null || _a === void 0 ? void 0 : _a.store.get('realSize')) || 0;
        }
        for (let type of rowTypes) {
            y += ((_b = this.stores[type]) === null || _b === void 0 ? void 0 : _b.store.get('realSize')) || 0;
        }
        return { y, x };
    }
    setViewPortCoordinate({ type, coordinate = this.viewports.stores[type].lastCoordinate, force = false, }) {
        const dimension = this.stores[type].getCurrentState();
        const viewport = this.viewports.stores[type].store;
        const clientSize = viewport.get('clientSize');
        const viewportSize = viewport.get('virtualSize');
        const scrollDimension = getScrollDimension({
            contentSize: dimension.realSize,
            clientSize,
            virtualSize: viewportSize,
        });
        // Render offset must use the true logical scroll coordinate
        // It is the logical scroll position that should be used for compressed-scroll offset math.
        const renderCoordinate = Math.min(Math.max(0, coordinate), // prevents negative scroll positions
        scrollDimension.logicalScrollSize); // prevents positions past the logical end
        /**
         * If viewport sizing is initialized (clientSize and viewportSize are truthy), calculate the offset needed for compressed scroll.
         * Otherwise keep renderOffset at 0, because there is not enough measurement data yet.
         *
         * In normal scrolling, logical and physical coordinates are the same, so offset is 0.
         */
        const renderOffset = clientSize && viewportSize
            ? scrollDimension.getRenderOffset(renderCoordinate)
            : 0;
        this.stores[type].setStore({ renderOffset });
        this.viewports.stores[type].setViewport({ renderOffset });
        this.viewports.stores[type].setViewPortCoordinate(coordinate, dimension, force);
    }
    getViewPortPos(e) {
        const dimension = this.stores[e.dimension].getCurrentState();
        const item = getItemByIndex(dimension, e.coordinate);
        return item.start;
    }
    setSettings(data, dimensionType) {
        let stores = [];
        switch (dimensionType) {
            case 'rgCol':
                stores = columnTypes;
                break;
            case 'rgRow':
                stores = rowTypes;
                break;
        }
        for (let s of stores) {
            this.stores[s].setStore(data);
        }
    }
    updateSizesPositionByNewDataIndexes(type, newItemsOrder, prevItemsOrder = []) {
        // Move custom sizes to new order
        this.stores[type].updateSizesPositionByIndexes(newItemsOrder, prevItemsOrder);
        this.setViewPortCoordinate({
            type,
            force: true,
        });
    }
}

class ViewportProvider {
    constructor() {
        this.stores = reduce([...rowTypes, ...columnTypes], (sources, k) => {
            sources[k] = new ViewportStore(k);
            return sources;
        }, {});
    }
    setViewport(type, data) {
        this.stores[type].setViewport(data);
    }
}

function getViewportResizeDimension(colType, dimension) {
    return dimension === 'rgCol' ? colType : dimension;
}
/** Collect Column data */
function gatherColumnData(data) {
    const colDimension = data.dimensions[data.colType].store;
    const realWidth = colDimension.get('realSize');
    const prop = {
        contentWidth: realWidth,
        class: data.colType,
        contentHeight: data.contentHeight,
        key: data.colType,
        colType: data.colType,
        noHorizontalScrollTransfer: data.noHorizontalScrollTransfer,
        onResizeviewport: data.onResizeviewport,
        // set viewport size to real size
        style: data.fixWidth ? { minWidth: `${realWidth}px` } : undefined,
    };
    const headerProp = {
        colData: getVisibleSourceItem(data.colStore),
        dimensionCol: colDimension,
        type: data.colType,
        groups: data.colStore.get('groups'),
        groupingDepth: data.colStore.get('groupingDepth'),
        resizeHandler: data.colType === 'colPinEnd' ? ['l'] : undefined,
        onHeaderresize: data.onHeaderresize,
    };
    return {
        prop,
        type: data.colType,
        position: data.position,
        headerProp,
        viewportCol: data.viewports[data.colType].store,
    };
}
class ViewportService {
    constructor(config, contentHeight) {
        // ----------- Handle columns ----------- //
        var _a;
        this.config = config;
        // Transform data from stores and apply it to different components
        const columns = [];
        let x = 0; // we increase x only if column present
        columnTypes.forEach(val => {
            const colStore = config.columnProvider.stores[val].store;
            // only columns that have data show
            if (!colStore.get('items').length) {
                return;
            }
            const column = {
                colType: val,
                position: { x, y: 1 },
                contentHeight,
                // only central column has dynamic width
                fixWidth: val !== 'rgCol',
                viewports: config.viewportProvider.stores,
                dimensions: config.dimensionProvider.stores,
                rowStores: config.dataProvider.stores,
                noHorizontalScrollTransfer: config.noHorizontalScrollTransfer,
                colStore,
                onHeaderresize: e => this.onColumnResize(val, e, colStore),
            };
            column.onResizeviewport = (e) => {
                var _a;
                const vpState = {
                    clientSize: e.detail.size,
                };
                const dimension = getViewportResizeDimension(val, e.detail.dimension);
                const isVirtualColumn = columnTypes.includes(dimension)
                    && isVirtualXDimension(dimension, config.disableVirtualX, config.virtualX);
                // Keep virtual dimensions in sync with their viewport size.
                if ((dimension === 'rgRow' && !config.disableVirtualY) || isVirtualColumn) {
                    vpState.virtualSize = e.detail.size;
                }
                (_a = config.viewportProvider) === null || _a === void 0 ? void 0 : _a.setViewport(dimension, vpState);
            };
            const colData = gatherColumnData(column);
            const columnSelectionStore = this.registerCol(colData.position.x, val);
            // render per each column data collections vertically
            const dataPorts = this.dataViewPort(column).reduce((r, rgRow) => {
                // register selection store for Segment
                const segmentSelection = this.registerSegment(rgRow.position, rgRow.lastCell);
                // register selection store for Row
                const rowSelectionStore = this.registerRow(rgRow.position.y, rgRow.type);
                const rowDef = Object.assign(Object.assign({ colType: val }, rgRow), { rowSelectionStore, selectionStore: segmentSelection.store, onSetrange: e => {
                        segmentSelection.setRangeArea(e.detail);
                    }, onSettemprange: e => segmentSelection.setTempArea(e.detail), onFocuscell: e => {
                        // todo: multi focus
                        segmentSelection.clearFocus();
                        config.selectionStoreConnector.focus(segmentSelection, e.detail);
                    } });
                r.push(rowDef);
                return r;
            }, []);
            columns.push(Object.assign(Object.assign({}, colData), { columnSelectionStore,
                dataPorts }));
            x++;
        });
        this.columns = columns;
        // ----------- Handle columns end ----------- //
        (_a = this.config.scrollingService) === null || _a === void 0 ? void 0 : _a.unregister();
    }
    onColumnResize(type, { detail }, store) {
        var _a;
        // apply to dimension provider
        (_a = this.config.dimensionProvider) === null || _a === void 0 ? void 0 : _a.setCustomSizes(type, detail, true);
        // set resize event
        const changedItems = {};
        for (const i of Object.keys(detail || {})) {
            const size = detail[i];
            const virtualIndex = parseInt(i, 10);
            const item = getSourceItem(store, virtualIndex);
            if (item) {
                changedItems[virtualIndex] = Object.assign(Object.assign({}, item), { size });
            }
        }
        this.config.resize(changedItems);
    }
    /** register selection store for Segment */
    registerSegment(position, lastCell) {
        const store = this.config.selectionStoreConnector.register(position);
        store.setLastCell(lastCell);
        return store;
    }
    /** register selection store for Row */
    registerRow(y, type) {
        return this.config.selectionStoreConnector.registerRow(y, type).store;
    }
    /** register selection store for Column */
    registerCol(x, type) {
        return this.config.selectionStoreConnector.registerColumn(x, type).store;
    }
    /** Collect Row data */
    dataViewPort(data) {
        const slots = {
            rowPinStart: HEADER_SLOT,
            rgRow: CONTENT_SLOT,
            rowPinEnd: FOOTER_SLOT,
        };
        // y position for selection
        let y = 0;
        return rowTypes.reduce((result, type) => {
            const rgCol = Object.assign(Object.assign({}, data), { position: Object.assign(Object.assign({}, data.position), { y }) });
            const partition = viewportDataPartition(rgCol, type, slots[type], type !== 'rgRow');
            result.push(partition);
            y++;
            return result;
        }, []);
    }
    scrollToCell(cell) {
        for (let key in cell) {
            const coordinate = cell[key];
            if (typeof coordinate === 'number') {
                this.config.scrollingService.proxyScroll({
                    dimension: key === 'x' ? 'rgCol' : 'rgRow',
                    coordinate,
                });
            }
        }
    }
    /**
     * Clear current grid focus
     */
    clearFocused() {
        this.config.selectionStoreConnector.clearAll();
    }
    clearEdit() {
        this.config.selectionStoreConnector.setEdit(false);
    }
    /**
     * Collect focused element data
     */
    getFocused() {
        const focused = this.config.selectionStoreConnector.focusedStore;
        if (!focused) {
            return null;
        }
        // get column data
        const colType = this.config.selectionStoreConnector.storesXToType[focused.position.x];
        const column = this.config.columnProvider.getColumn(focused.cell.x, colType);
        // get row data
        const rowType = this.config.selectionStoreConnector.storesYToType[focused.position.y];
        const model = this.config.dataProvider.getModel(focused.cell.y, rowType);
        return {
            column,
            model,
            cell: focused.cell,
            colType,
            rowType,
        };
    }
    getStoreCoordinateByType(colType, rowType) {
        const stores = this.config.selectionStoreConnector.storesByType;
        if (typeof stores[colType] === 'undefined' || typeof stores[rowType] === 'undefined') {
            return;
        }
        return {
            x: stores[colType],
            y: stores[rowType],
        };
    }
    setFocus(colType, rowType, start, end) {
        var _a;
        const coordinate = this.getStoreCoordinateByType(colType, rowType);
        if (coordinate) {
            (_a = this.config.selectionStoreConnector) === null || _a === void 0 ? void 0 : _a.focusByCell(coordinate, start, end);
        }
    }
    getSelectedRange() {
        const focused = this.config.selectionStoreConnector.focusedStore;
        if (!focused) {
            return null;
        }
        // get column data
        const colType = this.config.selectionStoreConnector.storesXToType[focused.position.x];
        // get row data
        const rowType = this.config.selectionStoreConnector.storesYToType[focused.position.y];
        const range = focused.entity.store.get('range');
        if (!range) {
            return null;
        }
        return Object.assign(Object.assign({}, range), { colType,
            rowType });
    }
    setEdit(rowIndex, colIndex, colType, rowType) {
        var _a;
        const coordinate = this.getStoreCoordinateByType(colType, rowType);
        if (coordinate) {
            (_a = this.config.selectionStoreConnector) === null || _a === void 0 ? void 0 : _a.setEditByCell(coordinate, { x: colIndex, y: rowIndex });
        }
    }
}

class GridScrollingService {
    constructor(setViewport) {
        this.setViewport = setViewport;
        this.elements = {};
    }
    async proxyScroll(e, key, skipEvent) {
        var _a;
        let newEventPromise;
        let event = e;
        for (let elKey in (skipEvent ? {} : this.elements)) {
            // skip
            if (e.dimension === 'rgCol' && elKey === 'headerRow') {
                continue;
                // pinned column only
            }
            else if (this.isPinnedColumn(key) && e.dimension === 'rgCol') {
                if (elKey === key || !e.delta) {
                    continue;
                }
                for (let el of this.elements[elKey]) {
                    if (el.changeScroll) {
                        newEventPromise = el.changeScroll(e);
                    }
                }
            }
            else {
                for (let el of this.elements[elKey]) {
                    await ((_a = el.setScroll) === null || _a === void 0 ? void 0 : _a.call(el, e));
                }
            }
        }
        const newEvent = await newEventPromise;
        if (newEvent) {
            event = newEvent;
        }
        this.setViewport(skipEvent && this.isPinnedColumn(key)
            ? Object.assign(Object.assign({}, event), { dimension: key }) : event);
    }
    /**
     * Silent scroll update for mobile devices when we have negative scroll top
     */
    async scrollSilentService(e, key) {
        var _a;
        for (let elKey in this.elements) {
            // skip same element update
            if (elKey === key) {
                continue;
            }
            if (columnTypes.includes(key) &&
                (elKey === 'headerRow' ||
                    columnTypes.includes(elKey))) {
                for (let el of this.elements[elKey]) {
                    await ((_a = el.changeScroll) === null || _a === void 0 ? void 0 : _a.call(el, e, true));
                }
                continue;
            }
        }
    }
    isPinnedColumn(key) {
        return !!key && ['colPinStart', 'colPinEnd'].indexOf(key) > -1;
    }
    registerElements(els) {
        this.elements = els;
    }
    /**
     * Register new element for farther scroll support
     * @param el - can be null if holder removed
     * @param key - element key
     */
    registerElement(el, key) {
        if (!this.elements[key]) {
            this.elements[key] = [];
        }
        // new element added
        if (el) {
            this.elements[key].push(el);
        }
        else if (this.elements[key]) {
            // element removed
            delete this.elements[key];
        }
    }
    unregister() {
        this.elements = {};
    }
}

class SelectionStoreConnector {
    constructor() {
        this.stores = {};
        this.columnStores = {};
        this.rowStores = {};
        /**
         * Helpers for data conversion
         */
        this.storesByType = {};
        this.storesXToType = {};
        this.storesYToType = {};
    }
    get focusedStore() {
        var _a;
        for (let y in this.stores) {
            for (let x in this.stores[y]) {
                const focused = (_a = this.stores[y][x]) === null || _a === void 0 ? void 0 : _a.store.get('focus');
                if (focused) {
                    return {
                        entity: this.stores[y][x],
                        cell: focused,
                        position: {
                            x: parseInt(x, 10),
                            y: parseInt(y, 10),
                        },
                    };
                }
            }
        }
        return null;
    }
    get edit() {
        var _a;
        return (_a = this.focusedStore) === null || _a === void 0 ? void 0 : _a.entity.store.get('edit');
    }
    get focused() {
        var _a;
        return (_a = this.focusedStore) === null || _a === void 0 ? void 0 : _a.entity.store.get('focus');
    }
    get selectedRange() {
        var _a;
        return (_a = this.focusedStore) === null || _a === void 0 ? void 0 : _a.entity.store.get('range');
    }
    registerColumn(x, type) {
        this.updateColumnTypeMapping(x, type);
        if (this.columnStores[x]) {
            return this.columnStores[x];
        }
        this.columnStores[x] = new SelectionStore();
        return this.columnStores[x];
    }
    registerRow(y, type) {
        if (this.rowStores[y]) {
            return this.rowStores[y];
        }
        this.rowStores[y] = new SelectionStore();
        // build cross linking type to position
        this.storesByType[type] = y;
        this.storesYToType[y] = type;
        return this.rowStores[y];
    }
    /**
     * Cross store proxy, based on multiple dimensions
     */
    register({ x, y }) {
        if (!this.stores[y]) {
            this.stores[y] = {};
        }
        let store = this.stores[y][x];
        if (store) {
            // Store already registered. Do not register twice
            return store;
        }
        this.stores[y][x] = store = new SelectionStore();
        // proxy update, column store trigger only range area
        store.onChange('range', c => {
            this.columnStores[x].setRangeArea(c);
            this.rowStores[y].setRangeArea(c);
        });
        // clean up on remove
        store.store.on('dispose', () => this.destroy(x, y));
        return store;
    }
    destroy(x, y) {
        var _a, _b;
        (_a = this.columnStores[x]) === null || _a === void 0 ? void 0 : _a.dispose();
        (_b = this.rowStores[y]) === null || _b === void 0 ? void 0 : _b.dispose();
        delete this.rowStores[y];
        delete this.columnStores[x];
        // clear x cross-link
        if (this.storesXToType[x]) {
            const type = this.storesXToType[x];
            delete this.storesXToType[x];
            delete this.storesByType[type];
        }
        // clear y cross-link
        if (this.storesYToType[y]) {
            const type = this.storesYToType[y];
            delete this.storesYToType[y];
            delete this.storesByType[type];
        }
        if (this.stores[y]) {
            delete this.stores[y][x];
        }
        // clear empty rows
        if (!Object.keys(this.stores[y] || {}).length) {
            delete this.stores[y];
        }
    }
    setEditByCell(storePos, editCell) {
        this.focusByCell(storePos, editCell, editCell);
        this.setEdit('');
    }
    /**
     * Sets the next focus cell before the current one.
     *
     * @param focus - The cell to set as the next focus.
     */
    beforeNextFocusCell(focus) {
        var _a;
        // If there is no focused store, return early.
        if (!this.focusedStore) {
            return;
        }
        // Get the next store based on the current focus and the last cell.
        const lastCell = this.focusedStore.entity.store.get('lastCell');
        const next = lastCell && this.getNextStore(focus, this.focusedStore.position, lastCell);
        // Set the next focus cell in the store.
        (_a = next === null || next === void 0 ? void 0 : next.store) === null || _a === void 0 ? void 0 : _a.setNextFocus(Object.assign(Object.assign({}, focus), next.item));
    }
    focusByCell(storePos, start, end) {
        const store = this.stores[storePos.y][storePos.x];
        this.focus(store, { focus: start, end });
    }
    focus(store, { focus, end }) {
        const currentStorePointer = this.getCurrentStorePointer(store);
        if (!currentStorePointer) {
            return null;
        }
        // check for the focus in nearby store/viewport
        const lastCell = store.store.get('lastCell');
        const next = lastCell && this.getNextStore(focus, currentStorePointer, lastCell);
        // if next store present - update
        if (next === null || next === void 0 ? void 0 : next.store) {
            const item = Object.assign(Object.assign({}, focus), next.item);
            this.focus(next.store, { focus: item, end: item });
            return null;
        }
        if (lastCell) {
            focus = cropCellToMax(focus, lastCell);
            end = cropCellToMax(end, lastCell);
        }
        store.setFocus(focus, end);
        return focus;
    }
    /**
     * Retrieves the current store pointer based on the active store.
     * Clears focus from all stores except the active one.
     */
    getCurrentStorePointer(store) {
        let currentStorePointer;
        // Iterate through all stores
        for (let y in this.stores) {
            for (let x in this.stores[y]) {
                const s = this.stores[y][x];
                // Clear focus from stores other than the active one
                if (s !== store) {
                    s.clearFocus();
                }
                else {
                    // Update the current store pointer with the active store coordinates
                    currentStorePointer = {
                        x: parseInt(x, 10),
                        y: parseInt(y, 10)
                    };
                }
            }
        }
        return currentStorePointer;
    }
    /**
     * Retrieves the next store based on the focus cell and current store pointer.
     * If the next store exists, returns an object with the next store and the item in the new store.
     * If the next store does not exist, returns null.
     */
    getNextStore(focus, currentStorePointer, lastCell) {
        // item in new store
        const nextItem = nextCell(focus, lastCell);
        let nextStore;
        if (nextItem) {
            Object.keys(nextItem).forEach((t) => {
                var _a;
                const type = t;
                const nextItemCoord = (_a = nextItem[type]) !== null && _a !== void 0 ? _a : 0;
                let stores;
                switch (type) {
                    case 'x':
                        // Get the X stores for the current Y coordinate of the current store pointer
                        stores = this.getXStores(currentStorePointer.y);
                        break;
                    case 'y':
                        // Get the Y stores for the current X coordinate of the current store pointer
                        stores = this.getYStores(currentStorePointer.x);
                        break;
                }
                // Get the next store based on the item in the new store
                if (nextItemCoord >= 0) {
                    nextStore = stores[++currentStorePointer[type]];
                }
                else {
                    nextStore = stores[--currentStorePointer[type]];
                    const nextLastCell = nextStore === null || nextStore === void 0 ? void 0 : nextStore.store.get('lastCell');
                    if (nextLastCell) {
                        nextItem[type] = nextLastCell[type] + nextItemCoord;
                    }
                }
            });
        }
        // if last cell is empty store is empty, no next store
        const lastCellNext = nextStore === null || nextStore === void 0 ? void 0 : nextStore.store.get('lastCell');
        if (!(lastCellNext === null || lastCellNext === void 0 ? void 0 : lastCellNext.x) || !(lastCellNext === null || lastCellNext === void 0 ? void 0 : lastCellNext.y)) {
            nextStore = undefined;
        }
        return {
            store: nextStore,
            item: nextItem,
        };
    }
    clearAll() {
        var _a;
        for (let y in this.stores) {
            for (let x in this.stores[y]) {
                (_a = this.stores[y][x]) === null || _a === void 0 ? void 0 : _a.clearFocus();
            }
        }
    }
    setEdit(val) {
        if (!this.focusedStore) {
            return;
        }
        this.focusedStore.entity.setEdit(val);
    }
    /**
     * Select all cells across all stores
     */
    selectAll() {
        for (let y in this.stores) {
            for (let x in this.stores[y]) {
                const store = this.stores[y][x];
                if (!store) {
                    continue;
                }
                const lastCell = store.store.get('lastCell');
                if (lastCell) {
                    store.setRange({ x: 0, y: 0 }, { x: lastCell.x - 1, y: lastCell.y - 1 });
                }
            }
        }
    }
    getXStores(y) {
        return this.stores[y];
    }
    getYStores(x) {
        const stores = {};
        for (let i in this.stores) {
            stores[i] = this.stores[i][x];
        }
        return stores;
    }
    /**
     * Keep column viewport positions and types in sync across pin/unpin rerenders.
     * Regression case: when a selected rgCol cell was pinned left, colPinStart
     * could take over x=0 and render the stale rgCol focus store in the pinned area.
     */
    updateColumnTypeMapping(x, type) {
        const previousType = this.storesXToType[x];
        const previousX = this.storesByType[type];
        let shouldClearFocus = false;
        this.storesByType[type] = x;
        this.storesXToType[x] = type;
        if (previousType && previousType !== type) {
            shouldClearFocus = true;
            if (this.storesByType[previousType] === x) {
                delete this.storesByType[previousType];
            }
        }
        if (typeof previousX === 'number' && previousX !== x && this.storesXToType[previousX] === type) {
            delete this.storesXToType[previousX];
            shouldClearFocus = true;
        }
        if (shouldClearFocus) {
            this.clearAll();
        }
    }
}

/**
 * Draw drag
 */
class OrdererService {
    constructor() {
        this.parentY = 0;
    }
    start(parent, { pos, text, event }) {
        var _a;
        const { top } = parent.getBoundingClientRect();
        this.parentY = top;
        if (this.text) {
            this.text.innerText = text;
        }
        this.move(pos);
        this.moveTip({ x: event.x, y: event.y });
        (_a = this.el) === null || _a === void 0 ? void 0 : _a.classList.remove('hidden');
    }
    end() {
        var _a;
        (_a = this.el) === null || _a === void 0 ? void 0 : _a.classList.add('hidden');
    }
    move(pos) {
        this.moveElement(pos.end - this.parentY);
    }
    moveTip({ x, y }) {
        if (!this.draggable) {
            return;
        }
        this.draggable.style.left = `${x}px`;
        this.draggable.style.top = `${y}px`;
    }
    moveElement(y) {
        if (!this.rgRow) {
            return;
        }
        this.rgRow.style.transform = `translateY(${y}px)`;
    }
}
const OrderRenderer = ({ ref }) => {
    const service = new OrdererService();
    ref(service);
    return (h("div", { class: "draggable-wrapper hidden", ref: e => (service.el = e) }, h("div", { class: "draggable", ref: el => (service.draggable = el) }, h("span", { class: "revo-alt-icon" }), h("span", { ref: e => (service.text = e) })), h("div", { class: "drag-position", ref: e => (service.rgRow = e) })));
};

const rowDefinitionByType = (newVal = []) => {
    const result = {};
    for (const v of newVal) {
        let rowDefs = result[v.type];
        if (!rowDefs) {
            rowDefs = result[v.type] = {};
        }
        if (typeof v.size === 'number') {
            if (!rowDefs.sizes) {
                rowDefs.sizes = {};
            }
            rowDefs.sizes[v.index] = v.size;
        }
    }
    return result;
};
const rowDefinitionRemoveByType = (oldVal = []) => {
    const result = {};
    for (const v of oldVal) {
        let rowDefs = result[v.type];
        if (!rowDefs) {
            rowDefs = result[v.type] = [];
        }
        if (typeof v.size === 'number') {
            rowDefs.push(v.index);
        }
    }
    return result;
};

function isMobileDevice() {
    return /Mobi/i.test(navigator.userAgent) || /Android/i.test(navigator.userAgent) || navigator.maxTouchPoints > 0;
}

/**
 * WCAG Plugin is responsible for enhancing the accessibility features of the RevoGrid component.
 * It ensures that the grid is fully compliant with Web Content Accessibility Guidelines (WCAG) 2.1.
 * This plugin should be the last plugin you add, as it modifies the grid's default behavior.
 *
 * The WCAG Plugin performs the following tasks:
 * - Sets the 'dir' attribute to 'ltr' for left-to-right text direction.
 * - Sets the 'role' attribute to 'treegrid' for treelike hierarchical structure.
 * - Sets the 'aria-keyshortcuts' attribute to 'Enter' and 'Esc' for keyboard shortcuts.
 * - Adds event listeners for keyboard navigation and editing.
 *
 * By default, the plugin adds ARIA roles and properties to the grid elements, providing semantic information
 * for assistive technologies. These roles include 'grid', 'row', and 'gridcell'. The plugin also sets
 * ARIA attributes such as 'aria-rowindex', 'aria-colindex', and 'aria-selected'.
 *
 * The WCAG Plugin ensures that the grid is fully functional and usable for users with various disabilities,
 * including visual impairments, deaf-blindness, and cognitive disabilities.
 *
 * Note: The WCAG Plugin should be added as the last plugin in the list of plugins, as it modifies the grid's
 * default behavior and may conflict with other plugins if added earlier.
 */
class WCAGPlugin extends BasePlugin {
    constructor(revogrid, providers) {
        super(revogrid, providers);
        revogrid.setAttribute('role', 'treegrid');
        revogrid.setAttribute('aria-keyshortcuts', 'Enter');
        revogrid.setAttribute('aria-multiselectable', 'true');
        revogrid.setAttribute('tabindex', '0');
        /**
         * Before Columns Set Event
         */
        this.addEventListener('beforecolumnsset', ({ detail }) => {
            const columns = [
                ...detail.columns.colPinStart,
                ...detail.columns.rgCol,
                ...detail.columns.colPinEnd,
            ];
            revogrid.setAttribute('aria-colcount', `${columns.length}`);
            columns.forEach((column, index) => {
                const { columnProperties, cellProperties } = column;
                column.columnProperties = (...args) => {
                    const result = (columnProperties === null || columnProperties === void 0 ? void 0 : columnProperties(...args)) || {};
                    result.role = 'columnheader';
                    result['aria-colindex'] = `${index}`;
                    return result;
                };
                column.cellProperties = (...args) => {
                    const wcagProps = {
                        ['role']: 'gridcell',
                        ['aria-colindex']: `${index}`,
                        ['aria-rowindex']: `${args[0].rowIndex}`,
                        ['tabindex']: -1,
                    };
                    const columnProps = (cellProperties === null || cellProperties === void 0 ? void 0 : cellProperties(...args)) || {};
                    return Object.assign(Object.assign({}, wcagProps), columnProps);
                };
            });
        });
        /**
         * Before Row Set Event
         */
        this.addEventListener('beforesourceset', ({ detail, }) => {
            revogrid.setAttribute('aria-rowcount', `${detail.source.length}`);
        });
        this.addEventListener('beforerowrender', ({ detail, }) => {
            detail.node.$attrs$ = Object.assign(Object.assign({}, detail.node.$attrs$), { role: 'row', ['aria-rowindex']: detail.item.itemIndex });
        });
        // focuscell
        this.addEventListener('afterfocus', async (e) => {
            if (e.defaultPrevented) {
                return;
            }
            const el = this.revogrid.querySelector(`revogr-data[type="${e.detail.rowType}"][col-type="${e.detail.colType}"] [data-rgrow="${e.detail.rowIndex}"][data-rgcol="${e.detail.colIndex}"]`);
            if (el instanceof HTMLElement) {
                el.focus();
            }
        });
    }
}

/**
 * Plugin service
 * Manages plugins
 */
class PluginService {
    constructor() {
        /**
         * Plugins
         * Define plugins collection
         */
        this.internalPlugins = [];
    }
    /**
     * Get all plugins
     */
    get() {
        return [...this.internalPlugins];
    }
    /**
     * Add plugin to collection
     */
    add(plugin) {
        this.internalPlugins.push(plugin);
    }
    /**
     * Add user plugins and create
     */
    addUserPluginsAndCreate(element, plugins = [], prevPlugins, pluginData) {
        if (!pluginData) {
            return;
        }
        // Step 1: Identify plugins to remove, compare new and old plugins
        const pluginsToRemove = (prevPlugins === null || prevPlugins === void 0 ? void 0 : prevPlugins.filter(prevPlugin => !plugins.some(userPlugin => userPlugin === prevPlugin))) || [];
        // Step 2: Remove old plugins
        pluginsToRemove.forEach(plugin => {
            var _a, _b;
            const index = this.internalPlugins.findIndex(createdPlugin => createdPlugin instanceof plugin);
            if (index !== -1) {
                (_b = (_a = this.internalPlugins[index]).destroy) === null || _b === void 0 ? void 0 : _b.call(_a);
                this.internalPlugins.splice(index, 1); // Remove the plugin
            }
        });
        // Step 3: Register user plugins
        plugins === null || plugins === void 0 ? void 0 : plugins.forEach(userPlugin => {
            // check if plugin already exists, if so, skip
            const existingPlugin = this.internalPlugins.find(createdPlugin => createdPlugin instanceof userPlugin);
            if (existingPlugin) {
                return;
            }
            this.add(new userPlugin(element, pluginData));
        });
    }
    /**
     * Get plugin by class
     */
    getByClass(pluginClass) {
        return this.internalPlugins.find(p => p instanceof pluginClass);
    }
    /**
     * Remove plugin
     */
    remove(plugin) {
        var _a, _b;
        const index = this.internalPlugins.indexOf(plugin);
        if (index > -1) {
            (_b = (_a = this.internalPlugins[index]).destroy) === null || _b === void 0 ? void 0 : _b.call(_a);
            this.internalPlugins.splice(index, 1);
        }
    }
    /**
     * Remove all plugins
     */
    destroy() {
        this.internalPlugins.forEach(p => { var _a; return (_a = p.destroy) === null || _a === void 0 ? void 0 : _a.call(p); });
        this.internalPlugins = [];
    }
}

/**
 * RTL (Right-to-Left) Plugin for RevoGrid
 *
 * This plugin handles RTL transformation by subscribing to the beforecolumnsset event
 * and applying column order reversal when RTL mode is enabled.
 */
class RTLPlugin extends BasePlugin {
    constructor(revogrid, providers) {
        super(revogrid, providers);
        this.isRTLEnabled = false;
        this.init();
    }
    init() {
        // Subscribe to beforecolumnsset event to apply RTL transformation
        this.addEventListener('beforecolumnsset', (event) => {
            this.handleBeforeColumnsSet(event);
        });
        // Listen for RTL property changes
        this.addEventListener('aftergridinit', () => {
            this.updateRTLState();
        });
        // Watch for RTL property changes
        this.watch('rtl', (value) => {
            this.isRTLEnabled = value;
            this.emit('rtlstatechanged', { rtl: this.isRTLEnabled });
        }, { immediate: true });
    }
    /**
     * Handle the beforecolumnsset event to apply RTL transformation
     */
    handleBeforeColumnsSet(event) {
        if (!this.isRTLEnabled) {
            return; // No transformation needed if RTL is disabled
        }
        const columnCollection = event.detail;
        // Apply RTL transformation to all column types
        const transformedColumns = this.applyRTLTransformationToCollection(columnCollection);
        // Update the event detail with transformed columns
        event.detail.columns = transformedColumns.columns;
        event.detail.columnByProp = transformedColumns.columnByProp;
        event.detail.columnGrouping = transformedColumns.columnGrouping;
    }
    /**
     * Apply RTL transformation to the entire column collection
     */
    applyRTLTransformationToCollection(collection) {
        const transformedCollection = {
            columns: {
                rgCol: [],
                colPinStart: [],
                colPinEnd: [],
            },
            columnByProp: Object.assign({}, collection.columnByProp),
            columnGrouping: {
                rgCol: [],
                colPinStart: [],
                colPinEnd: [],
            },
            maxLevel: collection.maxLevel,
            sort: Object.assign({}, collection.sort),
        };
        // Transform each column type
        Object.keys(collection.columns).forEach((type) => {
            const columnType = type;
            const columns = collection.columns[columnType];
            // Apply RTL transformation to columns - create new reversed array
            const reversedColumns = [...columns].reverse();
            transformedCollection.columns[columnType] = reversedColumns;
            // Transform column grouping for this type
            transformedCollection.columnGrouping[columnType] = this.applyRTLTransformationToGroups(collection.columnGrouping[columnType], columns.length);
        });
        return transformedCollection;
    }
    /**
     * Apply RTL transformation to column groups
     */
    applyRTLTransformationToGroups(groups, totalColumns) {
        return groups.map(group => {
            // Reverse the indexes for RTL
            const reversedIndexes = group.indexes.map((index) => totalColumns - 1 - index).reverse();
            return Object.assign(Object.assign({}, group), { indexes: reversedIndexes });
        }).reverse(); // Reverse the group order
    }
    /**
     * Update RTL state based on the grid's rtl property
     */
    updateRTLState() {
        const grid = this.revogrid;
        if (grid && typeof grid.rtl === 'boolean') {
            this.isRTLEnabled = grid.rtl;
        }
    }
    /**
     * Get current RTL state
     */
    getRTLState() {
        return this.isRTLEnabled;
    }
    /**
     * Clean up the plugin
     */
    destroy() {
        super.destroy();
    }
}

const revoGridStyleCss = () => `revo-grid[theme=default],revo-grid:not([theme]){border:1px solid var(--revo-grid-header-border);font-size:12px}revo-grid[theme=default] .rowHeaders revogr-header,revo-grid:not([theme]) .rowHeaders revogr-header{box-shadow:-1px 0 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] revogr-header,revo-grid:not([theme]) revogr-header{text-align:center;line-height:30px;background-color:var(--revo-grid-header-bg)}revo-grid[theme=default] revogr-header .group-rgRow,revo-grid:not([theme]) revogr-header .group-rgRow{box-shadow:none}revo-grid[theme=default] revogr-header .group-rgRow .rgHeaderCell,revo-grid:not([theme]) revogr-header .group-rgRow .rgHeaderCell{box-shadow:-1px 0 0 0 var(--revo-grid-header-border), -1px 0 0 0 var(--revo-grid-header-border) inset, 0 -1px 0 0 var(--revo-grid-header-border), 0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] revogr-header .header-rgRow,revo-grid[theme=default] revogr-header .group-rgRow,revo-grid:not([theme]) revogr-header .header-rgRow,revo-grid:not([theme]) revogr-header .group-rgRow{text-transform:uppercase;font-size:12px;color:var(--revo-grid-header-color)}revo-grid[theme=default] revogr-header .header-rgRow,revo-grid:not([theme]) revogr-header .header-rgRow{height:30px;box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] revogr-header .rgHeaderCell,revo-grid:not([theme]) revogr-header .rgHeaderCell{box-shadow:-1px 0 0 0 var(--revo-grid-header-border) inset, 0 -1px 0 0 var(--revo-grid-header-border), 0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] .rowHeaders,revo-grid:not([theme]) .rowHeaders{background-color:var(--revo-grid-header-bg)}revo-grid[theme=default] .rowHeaders revogr-data .rgCell,revo-grid:not([theme]) .rowHeaders revogr-data .rgCell{color:var(--revo-grid-header-color)}revo-grid[theme=default] .rowHeaders revogr-data .rgCell:first-child,revo-grid:not([theme]) .rowHeaders revogr-data .rgCell:first-child{box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] .rowHeaders revogr-data .rgCell:not(:first-child),revo-grid:not([theme]) .rowHeaders revogr-data .rgCell:not(:first-child){box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset, 1px 0 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] .rowHeaders revogr-data .rgCell:last-child,revo-grid:not([theme]) .rowHeaders revogr-data .rgCell:last-child{border-right:1px solid var(--revo-grid-header-border)}revo-grid[theme=default] .rowHeaders revogr-data revogr-header,revo-grid:not([theme]) .rowHeaders revogr-data revogr-header{box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] revogr-viewport-scroll.colPinStart revogr-data .rgRow .rgCell:last-child,revo-grid:not([theme]) revogr-viewport-scroll.colPinStart revogr-data .rgRow .rgCell:last-child{box-shadow:0 -1px 0 0 var(--revo-grid-cell-border) inset, -1px 0 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] revogr-viewport-scroll.colPinStart .footer-wrapper revogr-data .rgRow:first-child .rgCell,revo-grid:not([theme]) revogr-viewport-scroll.colPinStart .footer-wrapper revogr-data .rgRow:first-child .rgCell{box-shadow:0 1px 0 0 var(--revo-grid-header-border) inset, -1px 0 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] revogr-viewport-scroll.colPinEnd,revo-grid[theme=default] revogr-viewport-scroll.colPinEnd revogr-header,revo-grid:not([theme]) revogr-viewport-scroll.colPinEnd,revo-grid:not([theme]) revogr-viewport-scroll.colPinEnd revogr-header{box-shadow:1px 0 0 var(--revo-grid-header-border) inset}revo-grid[theme=default] .footer-wrapper revogr-data .rgRow:first-child .rgCell,revo-grid:not([theme]) .footer-wrapper revogr-data .rgRow:first-child .rgCell{box-shadow:0 1px 0 0 var(--revo-grid-cell-border) inset, -1px 0 0 0 var(--revo-grid-cell-border) inset, 0 -1px 0 0 var(--revo-grid-cell-border) inset}revo-grid[theme=default] revogr-data,revo-grid:not([theme]) revogr-data{text-align:center}revo-grid[theme=default] revogr-data .revo-draggable,revo-grid:not([theme]) revogr-data .revo-draggable{float:left}revo-grid[theme=default] revogr-data .rgRow,revo-grid:not([theme]) revogr-data .rgRow{line-height:27px}revo-grid[theme=default] revogr-data .rgCell,revo-grid:not([theme]) revogr-data .rgCell{box-shadow:0 -1px 0 0 var(--revo-grid-cell-border) inset, -1px 0 0 0 var(--revo-grid-cell-border) inset}revo-grid[theme=material]{font-family:Nunito, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"}revo-grid[theme=material] revogr-header{line-height:50px;font-weight:600;text-align:left}revo-grid[theme=material] revogr-header .rgHeaderCell{padding:0 15px;text-overflow:ellipsis}revo-grid[theme=material] revogr-header .header-rgRow{height:50px}revo-grid[theme=material] revogr-data{text-align:left}revo-grid[theme=material] revogr-data .rgRow{line-height:42px}revo-grid[theme=material] revogr-data .rgCell{padding:0 15px}revo-grid[theme=darkMaterial]{font-family:Nunito, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"}revo-grid[theme=darkMaterial] revogr-header{line-height:50px;font-weight:600;text-align:left}revo-grid[theme=darkMaterial] revogr-header .rgHeaderCell{padding:0 15px;text-overflow:ellipsis}revo-grid[theme=darkMaterial] revogr-header .header-rgRow{height:50px}revo-grid[theme=darkMaterial] revogr-data{text-align:left}revo-grid[theme=darkMaterial] revogr-data .rgRow{line-height:42px}revo-grid[theme=darkMaterial] revogr-data .rgCell{padding:0 15px}revo-grid[theme=darkCompact]{font-family:Nunito, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"}revo-grid[theme=darkCompact] revogr-header{line-height:45px;font-weight:600;text-align:left}revo-grid[theme=darkCompact] revogr-header .rgHeaderCell{padding:0 15px;text-overflow:ellipsis}revo-grid[theme=darkCompact] revogr-header .header-rgRow{height:45px}revo-grid[theme=darkCompact] revogr-data{text-align:left}revo-grid[theme=darkCompact] revogr-data .rgRow{line-height:32px}revo-grid[theme=darkCompact] revogr-data .rgCell{padding:0 15px}revo-grid[theme=compact]{font-family:Nunito, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"}revo-grid[theme=compact] revogr-header{line-height:45px;font-weight:600;text-align:left}revo-grid[theme=compact] revogr-header .rgHeaderCell{padding:0 15px;text-overflow:ellipsis}revo-grid[theme=compact] revogr-header .header-rgRow{height:45px}revo-grid[theme=compact] revogr-data{text-align:left}revo-grid[theme=compact] revogr-data .rgRow{line-height:32px}revo-grid[theme=compact] revogr-data .rgCell{padding:0 15px}revo-grid[theme=compact] revo-dropdown .rv-dr-root{padding:0px 9px}revo-grid[dir=rtl] .viewports{flex-direction:row-reverse}revo-grid[dir=rtl] revogr-header .rgHeaderCell{text-align:right}revo-grid[dir=rtl] revogr-data .rgCell{text-align:right}revo-grid[dir=rtl] .rowHeaders revogr-data .rgCell{text-align:right}revo-grid[dir=rtl] revogr-filter-panel{direction:rtl}revo-grid[dir=rtl] revo-dropdown .rv-dr-root{text-align:right}revo-grid[dir=rtl] .drag-position{right:0;left:auto}revo-grid[dir=rtl] .drag-auto-scroll-y{right:0;left:auto}revo-grid[dir=rtl] .clipboard{right:0;left:auto}revo-grid[dir=rtl] .draggable{margin-left:-20px;margin-right:0;padding-right:20px;padding-left:5px}revo-grid[dir=rtl] .draggable .revo-alt-icon{right:5px;left:auto}revo-grid[dir=rtl] .focused-cell{border-right:2px solid var(--revo-grid-primary);border-left:none}revo-grid[dir=rtl] .selection-range{border-right:2px solid var(--revo-grid-primary);border-left:none}revo-grid[dir=rtl] .resize-handle{right:0;left:auto}revo-grid[dir=rtl] .sort-indicator{margin-left:0;margin-right:5px}revo-grid[dir=rtl] .filter-button{margin-left:0;margin-right:5px}revo-grid[dir=rtl] .group-expand{margin-right:0;margin-left:2px;padding-right:5px;padding-left:0}revo-grid[dir=rtl] .rgCell,revo-grid[dir=rtl] .rgHeaderCell{padding-left:5px;padding-right:5px}revo-grid[dir=rtl] revogr-edit{direction:rtl}revo-grid[dir=rtl] .rgHeaderCell{direction:rtl}revo-grid[dir=rtl][theme=material] revogr-header,revo-grid[dir=rtl][theme=darkMaterial] revogr-header{text-align:right}revo-grid[dir=rtl][theme=material] revogr-data,revo-grid[dir=rtl][theme=darkMaterial] revogr-data{text-align:right}revo-grid[dir=rtl][theme=default] .rowHeaders,revo-grid[dir=rtl]:not([theme]) .rowHeaders{background-color:var(--revo-grid-header-bg)}revo-grid[dir=rtl][theme=default] .rowHeaders revogr-data .rgCell,revo-grid[dir=rtl]:not([theme]) .rowHeaders revogr-data .rgCell{color:var(--revo-grid-header-color)}revo-grid[dir=rtl][theme=default] .rowHeaders revogr-data .rgCell:first-child,revo-grid[dir=rtl]:not([theme]) .rowHeaders revogr-data .rgCell:first-child{box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid[dir=rtl][theme=default] .rowHeaders revogr-data .rgCell:not(:first-child),revo-grid[dir=rtl]:not([theme]) .rowHeaders revogr-data .rgCell:not(:first-child){box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset, 1px 0 0 0 var(--revo-grid-header-border) inset}revo-grid[dir=rtl][theme=default] .rowHeaders revogr-data .rgCell:last-child,revo-grid[dir=rtl]:not([theme]) .rowHeaders revogr-data .rgCell:last-child{border-left:1px solid var(--revo-grid-header-border);border-right:none}revo-grid[dir=rtl][theme=default] .rowHeaders revogr-data revogr-header,revo-grid[dir=rtl]:not([theme]) .rowHeaders revogr-data revogr-header{box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid[dir=rtl][theme=default] revogr-header,revo-grid[dir=rtl]:not([theme]) revogr-header{text-align:right}revo-grid[dir=rtl][theme=default] revogr-data,revo-grid[dir=rtl]:not([theme]) revogr-data{text-align:right}revo-grid[dir=rtl][theme=compact] revogr-header,revo-grid[dir=rtl][theme=darkCompact] revogr-header{text-align:right}revo-grid[dir=rtl][theme=compact] revogr-data,revo-grid[dir=rtl][theme=darkCompact] revogr-data{text-align:right}.revo-drag-icon{width:11px;opacity:0.8}.revo-drag-icon::before{content:"::";display:inline-block}.revo-alt-icon{-webkit-mask-image:url("data:image/svg+xml,%3C%3Fxml version='1.0' encoding='UTF-8'%3F%3E%3Csvg viewBox='0 0 384 383' xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'%3E%3Cg%3E%3Cpath d='M192.4375,383 C197.424479,383 201.663411,381.254557 205.154297,377.763672 L205.154297,377.763672 L264.25,318.667969 C270.234375,312.683594 271.605794,306.075846 268.364258,298.844727 C265.122721,291.613607 259.51237,287.998047 251.533203,287.998047 L251.533203,287.998047 L213.382812,287.998047 L213.382812,212.445312 L288.935547,212.445312 L288.935547,250.595703 C288.935547,258.57487 292.551107,264.185221 299.782227,267.426758 C307.013346,270.668294 313.621094,269.296875 319.605469,263.3125 L319.605469,263.3125 L378.701172,204.216797 C382.192057,200.725911 383.9375,196.486979 383.9375,191.5 C383.9375,186.513021 382.192057,182.274089 378.701172,178.783203 L378.701172,178.783203 L319.605469,119.6875 C313.621094,114.201823 307.013346,112.955078 299.782227,115.947266 C292.551107,118.939453 288.935547,124.42513 288.935547,132.404297 L288.935547,132.404297 L288.935547,170.554688 L213.382812,170.554688 L213.382812,95.0019531 L251.533203,95.0019531 C259.51237,95.0019531 264.998047,91.3863932 267.990234,84.1552734 C270.982422,76.9241536 269.735677,70.3164062 264.25,64.3320312 L264.25,64.3320312 L205.154297,5.23632812 C201.663411,1.74544271 197.424479,0 192.4375,0 C187.450521,0 183.211589,1.74544271 179.720703,5.23632812 L179.720703,5.23632812 L120.625,64.3320312 C114.640625,70.3164062 113.269206,76.9241536 116.510742,84.1552734 C119.752279,91.3863932 125.36263,95.0019531 133.341797,95.0019531 L133.341797,95.0019531 L171.492188,95.0019531 L171.492188,170.554688 L95.9394531,170.554688 L95.9394531,132.404297 C95.9394531,124.42513 92.3238932,118.814779 85.0927734,115.573242 C77.8616536,112.331706 71.2539062,113.703125 65.2695312,119.6875 L65.2695312,119.6875 L6.17382812,178.783203 C2.68294271,182.274089 0.9375,186.513021 0.9375,191.5 C0.9375,196.486979 2.68294271,200.725911 6.17382812,204.216797 L6.17382812,204.216797 L65.2695312,263.3125 C71.2539062,268.798177 77.8616536,270.044922 85.0927734,267.052734 C92.3238932,264.060547 95.9394531,258.57487 95.9394531,250.595703 L95.9394531,250.595703 L95.9394531,212.445312 L171.492188,212.445312 L171.492188,287.998047 L133.341797,287.998047 C125.36263,287.998047 119.876953,291.613607 116.884766,298.844727 C113.892578,306.075846 115.139323,312.683594 120.625,318.667969 L120.625,318.667969 L179.720703,377.763672 C183.211589,381.254557 187.450521,383 192.4375,383 Z'%3E%3C/path%3E%3C/g%3E%3C/svg%3E");mask-image:url("data:image/svg+xml,%3C%3Fxml version='1.0' encoding='UTF-8'%3F%3E%3Csvg viewBox='0 0 384 383' xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'%3E%3Cg%3E%3Cpath d='M192.4375,383 C197.424479,383 201.663411,381.254557 205.154297,377.763672 L205.154297,377.763672 L264.25,318.667969 C270.234375,312.683594 271.605794,306.075846 268.364258,298.844727 C265.122721,291.613607 259.51237,287.998047 251.533203,287.998047 L251.533203,287.998047 L213.382812,287.998047 L213.382812,212.445312 L288.935547,212.445312 L288.935547,250.595703 C288.935547,258.57487 292.551107,264.185221 299.782227,267.426758 C307.013346,270.668294 313.621094,269.296875 319.605469,263.3125 L319.605469,263.3125 L378.701172,204.216797 C382.192057,200.725911 383.9375,196.486979 383.9375,191.5 C383.9375,186.513021 382.192057,182.274089 378.701172,178.783203 L378.701172,178.783203 L319.605469,119.6875 C313.621094,114.201823 307.013346,112.955078 299.782227,115.947266 C292.551107,118.939453 288.935547,124.42513 288.935547,132.404297 L288.935547,132.404297 L288.935547,170.554688 L213.382812,170.554688 L213.382812,95.0019531 L251.533203,95.0019531 C259.51237,95.0019531 264.998047,91.3863932 267.990234,84.1552734 C270.982422,76.9241536 269.735677,70.3164062 264.25,64.3320312 L264.25,64.3320312 L205.154297,5.23632812 C201.663411,1.74544271 197.424479,0 192.4375,0 C187.450521,0 183.211589,1.74544271 179.720703,5.23632812 L179.720703,5.23632812 L120.625,64.3320312 C114.640625,70.3164062 113.269206,76.9241536 116.510742,84.1552734 C119.752279,91.3863932 125.36263,95.0019531 133.341797,95.0019531 L133.341797,95.0019531 L171.492188,95.0019531 L171.492188,170.554688 L95.9394531,170.554688 L95.9394531,132.404297 C95.9394531,124.42513 92.3238932,118.814779 85.0927734,115.573242 C77.8616536,112.331706 71.2539062,113.703125 65.2695312,119.6875 L65.2695312,119.6875 L6.17382812,178.783203 C2.68294271,182.274089 0.9375,186.513021 0.9375,191.5 C0.9375,196.486979 2.68294271,200.725911 6.17382812,204.216797 L6.17382812,204.216797 L65.2695312,263.3125 C71.2539062,268.798177 77.8616536,270.044922 85.0927734,267.052734 C92.3238932,264.060547 95.9394531,258.57487 95.9394531,250.595703 L95.9394531,250.595703 L95.9394531,212.445312 L171.492188,212.445312 L171.492188,287.998047 L133.341797,287.998047 C125.36263,287.998047 119.876953,291.613607 116.884766,298.844727 C113.892578,306.075846 115.139323,312.683594 120.625,318.667969 L120.625,318.667969 L179.720703,377.763672 C183.211589,381.254557 187.450521,383 192.4375,383 Z'%3E%3C/path%3E%3C/g%3E%3C/svg%3E");width:11px;height:11px;background-size:cover;background-repeat:no-repeat}.arrow-down{position:absolute;right:5px;top:0}.arrow-down svg{width:8px;margin-top:5px;margin-left:5px;opacity:0.4}.cell-value-wrapper{margin-right:10px;overflow:hidden;text-overflow:ellipsis}revo-grid{--revo-grid-primary:#266ae8;--revo-grid-primary-transparent:rgba(38, 106, 232, 0.9);--revo-grid-background:#fff;--revo-grid-foreground:black;--revo-grid-divider:gray;--revo-grid-shadow:rgba(0, 0, 0, 0.15);--revo-grid-text:black;--revo-grid-border:rgba(0, 0, 0, 0.2);--revo-grid-filter-panel-bg:#fff;--revo-grid-filter-panel-border:#d9d9d9;--revo-grid-filter-panel-shadow:rgba(0, 0, 0, 0.15);--revo-grid-filter-panel-input-bg:#eaeaeb;--revo-grid-filter-panel-divider:#d9d9d9;--revo-grid-filter-panel-select-border:transparent;--revo-grid-filter-panel-select-border-hover:transparent;--revo-grid-header-bg:#f8f9fa;--revo-grid-header-color:#000;--revo-grid-header-border:#cecece;--revo-grid-cell-border:#e2e3e3;--revo-grid-focused-bg:rgba(233, 234, 237, 0.5);--revo-grid-row-hover:#f1f1f1;--revo-grid-row-headers-bg:#f7faff;--revo-grid-row-headers-color:#757a82;--revo-grid-cell-disabled-bg:rgba(0, 0, 0, 0.07);direction:ltr !important;display:flex !important;height:100%;min-height:300px;font-family:Helvetica, Arial, Sans-Serif, serif;font-size:14px;position:relative;color:var(--revo-grid-text);-webkit-touch-callout:none;-webkit-user-select:none;-khtml-user-select:none;-moz-user-select:none;-ms-user-select:none;user-select:none;display:flex;flex-direction:column;width:100%;height:100%}revo-grid[theme*=dark]{--revo-grid-background:#212529;--revo-grid-foreground:#fff;--revo-grid-text:rgba(255, 255, 255, 0.9);--revo-grid-divider:#505050;--revo-grid-border:rgba(255, 255, 255, 0.2);--revo-grid-filter-panel-bg:#212529;--revo-grid-filter-panel-border:#505050;--revo-grid-filter-panel-input-bg:#343a40;--revo-grid-filter-panel-divider:#505050;--revo-grid-header-bg:#343a40;--revo-grid-header-color:#fff;--revo-grid-header-border:#505050;--revo-grid-cell-border:#424242;--revo-grid-focused-bg:rgba(52, 58, 64, 0.5);--revo-grid-row-hover:rgba(80, 80, 80, 0.5);--revo-grid-row-headers-bg:rgba(52, 58, 64, 0.8);--revo-grid-row-headers-color:rgba(255, 255, 255, 0.8);--revo-grid-cell-disabled-bg:rgba(255, 255, 255, 0.07)}revo-grid revogr-header .header-rgRow.group{box-shadow:0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid revogr-header .header-rgRow:not(.group){box-shadow:0 -1px 0 0 var(--revo-grid-header-border), 0 -1px 0 0 var(--revo-grid-header-border) inset}revo-grid revogr-header .rgHeaderCell.sortable:hover{background-color:var(--revo-grid-row-hover)}revo-grid revogr-header .rgHeaderCell.focused-cell{background:var(--revo-grid-focused-bg)}revo-grid .footer-wrapper revogr-data{box-shadow:0 -1px 0 var(--revo-grid-cell-border)}revo-grid revogr-viewport-scroll.colPinStart{box-shadow:-1px 0 0 var(--revo-grid-cell-border) inset}revo-grid revogr-viewport-scroll.colPinEnd{box-shadow:-1px 0 0 var(--revo-grid-cell-border)}revo-grid revogr-data .rgRow{box-shadow:0 -1px 0 0 var(--revo-grid-cell-border) inset}revo-grid revogr-data .rgRow.focused-rgRow{background-color:var(--revo-grid-focused-bg)}revo-grid revogr-data .rgCell{color:var(--revo-grid-text)}revo-grid revogr-data .rgCell.disabled{background-color:var(--revo-grid-cell-disabled-bg)}revo-grid .attribution{position:absolute;bottom:0;left:0;right:0;z-index:1000;width:0;height:0;border-left:4px solid var(--revo-grid-primary-transparent);border-bottom:4px solid var(--revo-grid-primary-transparent);border-top:4px solid transparent;border-right:4px solid transparent;cursor:pointer}revo-grid .attribution .value{position:absolute;bottom:0;left:0;background-color:var(--revo-grid-background);padding:4px;border-radius:4px;box-shadow:0 1px 10px var(--revo-grid-border);white-space:nowrap;text-decoration:none;color:var(--revo-grid-text);letter-spacing:0.3px;font-size:11px;opacity:0;width:4px;overflow:hidden;transition:opacity 0.5s ease-in-out, width 0.3s ease-in-out}revo-grid .attribution:hover .value{width:63px;opacity:1}revo-grid.column-draggable.column-drag-start:hover,revo-grid.column-draggable.column-drag-start *:hover{cursor:grabbing}revo-grid .footer-wrapper,revo-grid .header-wrapper{width:100%}revo-grid .footer-wrapper revogr-data,revo-grid .header-wrapper revogr-data{z-index:3}revo-grid revo-dropdown{width:100%}revo-grid revo-dropdown .rv-dr-root{max-height:100%}revo-grid revo-dropdown.shrink label{opacity:0}revo-grid .viewports{max-width:100%;display:flex;flex-direction:row;align-items:flex-start;flex-grow:1}revo-grid .main-viewport{flex-grow:1;height:0;display:flex;justify-content:space-between;flex-direction:row}revo-grid .draggable{position:fixed;height:30px;line-height:30px;background:var(--revo-grid-background);border-radius:3px;display:block;z-index:100;margin-top:5px;margin-right:-20px;box-shadow:0 4px 20px 0 var(--revo-grid-shadow);padding-left:20px;padding-right:5px}revo-grid .draggable.hidden{display:none}revo-grid .draggable .revo-alt-icon{background-color:var(--revo-grid-foreground);position:absolute;left:5px;top:10px}revo-grid .draggable-wrapper.hidden{display:none}revo-grid .drag-position{position:absolute;left:0;right:0;height:1px;z-index:2;background:var(--revo-grid-divider);pointer-events:none}revo-grid .drag-position-y{position:absolute;top:0;left:0;bottom:0;width:1px;z-index:2;background:var(--revo-grid-divider);pointer-events:none}revo-grid .drag-auto-scroll-y{pointer-events:none;position:absolute;left:0;top:0;height:50px;width:1px}revo-grid .clipboard{position:absolute;left:0;top:0}revo-grid revogr-scroll-virtual{position:relative}revo-grid revogr-scroll-virtual.vertical,revo-grid revogr-scroll-virtual.horizontal{z-index:3}`;

const RevoGridComponent = class {
    constructor(hostRef) {
        registerInstance(this, hostRef);
        this.contentsizechanged = createEvent(this, "contentsizechanged", 7);
        this.beforeedit = createEvent(this, "beforeedit", 7);
        this.beforerangeedit = createEvent(this, "beforerangeedit", 7);
        this.afteredit = createEvent(this, "afteredit", 7);
        this.beforeautofill = createEvent(this, "beforeautofill", 7);
        this.beforerange = createEvent(this, "beforerange", 7);
        this.afterfocus = createEvent(this, "afterfocus", 7);
        this.roworderchanged = createEvent(this, "roworderchanged", 7);
        this.beforesorting = createEvent(this, "beforesorting", 7);
        this.beforesourcesortingapply = createEvent(this, "beforesourcesortingapply", 7);
        this.beforesortingapply = createEvent(this, "beforesortingapply", 7);
        this.aftersortingapply = createEvent(this, "aftersortingapply", 7);
        this.rowdragstart = createEvent(this, "rowdragstart", 7);
        this.headerclick = createEvent(this, "headerclick", 7);
        this.beforecellfocus = createEvent(this, "beforecellfocus", 7);
        this.beforefocuslost = createEvent(this, "beforefocuslost", 7);
        this.beforesourceset = createEvent(this, "beforesourceset", 7);
        this.beforeanysource = createEvent(this, "beforeanysource", 7);
        this.aftersourceset = createEvent(this, "aftersourceset", 7);
        this.afteranysource = createEvent(this, "afteranysource", 7);
        this.beforecolumnsgather = createEvent(this, "beforecolumnsgather", 7);
        this.beforecolumnsset = createEvent(this, "beforecolumnsset", 7);
        this.beforecolumnapplied = createEvent(this, "beforecolumnapplied", 7);
        this.aftercolumnsset = createEvent(this, "aftercolumnsset", 7);
        this.beforefilterapply = createEvent(this, "beforefilterapply", 7);
        this.beforefiltertrimmed = createEvent(this, "beforefiltertrimmed", 7);
        this.beforetrimmed = createEvent(this, "beforetrimmed", 7);
        this.aftertrimmed = createEvent(this, "aftertrimmed", 7);
        this.viewportscroll = createEvent(this, "viewportscroll", 7);
        this.beforeexport = createEvent(this, "beforeexport", 7);
        this.beforeeditstart = createEvent(this, "beforeeditstart", 7);
        this.aftercolumnresize = createEvent(this, "aftercolumnresize", 7);
        this.beforerowdefinition = createEvent(this, "beforerowdefinition", 7);
        this.filterconfigchanged = createEvent(this, "filterconfigchanged", 7);
        this.sortingconfigchanged = createEvent(this, "sortingconfigchanged", 7);
        this.rowheaderschanged = createEvent(this, "rowheaderschanged", 7);
        this.beforegridrender = createEvent(this, "beforegridrender", 7);
        this.aftergridrender = createEvent(this, "aftergridrender", 7);
        this.aftergridinit = createEvent(this, "aftergridinit", 7);
        this.additionaldatachanged = createEvent(this, "additionaldatachanged", 7);
        this.afterthemechanged = createEvent(this, "afterthemechanged", 7);
        this.created = createEvent(this, "created", 7);
        /**
         * Defines how many rows/columns should be rendered outside visible area.
         */
        this.frameSize = 1;
        /**
         * Indicates default rgRow size.
         * By default 0, means theme package size will be applied
         *
         * Alternatively you can use `rowSize` to reset viewport
         */
        this.rowSize = 0;
        /** Indicates default column size. */
        this.colSize = 100;
        /** When true, user can select a cell range. Required for range-based clipboard fill. */
        this.range = false;
        /** When true, grid in read only mode. */
        this.readonly = false;
        /** When true, columns are resizable. */
        this.resize = false;
        /**
         * Prevents horizontal scroll state from being mirrored across viewport sections.
         */
        this.noHorizontalScrollTransfer = false;
        /** When true cell focus appear. */
        this.canFocus = true;
        /** When true enable clipboard. Can be boolean or clipboard config. */
        this.useClipboard = true;
        /**
         * Columns - defines an array of grid columns.
         * Can be column or grouped column.
         */
        this.columns = [];
        /**
         * Source - defines main data source.
         * Can be an Object or 2 dimensional array([][]);
         * Keys/indexes referenced from columns Prop.
         */
        this.source = [];
        /** Pinned top Source: {[T in ColumnProp]: any} - defines pinned top rows data source. */
        this.pinnedTopSource = [];
        /** Pinned bottom Source: {[T in ColumnProp]: any} - defines pinned bottom rows data source. */
        this.pinnedBottomSource = [];
        /** Custom row properies to be applied. See `RowDefinition` for more info. */
        this.rowDefinitions = [];
        /** Custom editors register. */
        this.editors = {};
        /**
         * Apply changes in editor when closed except 'Escape' cases.
         * If custom editor in use method getValue required.
         * Check interfaces.d.ts `EditorBase` for more info.
         */
        this.applyOnClose = false;
        /**
         * Custom grid plugins. Can be added or removed at runtime.
         * Every plugin should be inherited from BasePlugin class.
         *
         * For more details check [Plugin guide](https://rv-grid.com/guide/plugin/)
         */
        this.plugins = [];
        /**
         * Column Types Format.
         * Every type represent multiple column properties.
         * Types will be merged but can be replaced with column properties.
         * Types were made as separate objects to be reusable per multiple columns.
         */
        this.columnTypes = {};
        /** Theme name. */
        this.theme = 'default';
        /**
         * Row class property mapping.
         * Map custom classes to rows from row object data.
         * Define this property in rgRow object and this will be mapped as rgRow class.
         */
        this.rowClass = '';
        /**
         * Autosize config.
         * Enables columns autoSize.
         * For more details check `autoSizeColumn` plugin.
         * By default disabled, hence operation is not performance efficient.
         * `true` to enable with default params (double header separator click for autosize).
         * Or define config. See `AutoSizeColumnConfig` for more details.
         */
        this.autoSizeColumn = false;
        /**
         * Enables filter plugin.
         * Can be boolean.
         * Or can be filter collection See `FilterCollection` for more info.
         */
        this.filter = false;
        /**
         * Enable column move plugin.
         */
        this.canMoveColumns = false;
        /**
         * Trimmed rows.
         * Functionality which allows to hide rows from main data set.
         * `trimmedRows` are physical `rgRow` indexes to hide.
         */
        this.trimmedRows = {};
        /**
         * Enable export plugin.
         */
        this.exporting = false;
        /**
         * Stretch strategy for columns by `StretchColumn` plugin.
         * For example if there are more space on the right last column size would be increased.
         */
        this.stretch = false;
        /**
         * Additional data to be passed to plugins, renders or editors.
         * For example if you need to pass Vue component instance.
         */
        this.additionalData = {};
        /**
         * Disable lazy rendering mode for the `X axis`.
         * Use when not many columns present and you don't need rerenader cells during scroll.
         * Can be used for initial rendering performance improvement.
         */
        this.disableVirtualX = false;
        /**
         * Column dimensions that use X axis virtual rendering.
         * Defaults to regular columns only to preserve pinned column behavior.
         * Set to `['rgCol', 'colPinStart', 'colPinEnd']` to virtualize all column areas.
         */
        this.virtualX = ['rgCol'];
        /**
         * Disable lazy rendering mode for the `Y axis`.
         * Use when not many rows present and you don't need rerenader cells during scroll.
         * Can be used for initial rendering performance improvement.
         */
        this.disableVirtualY = false;
        /**
         * Please only hide the attribution if you are subscribed to Pro version
         */
        this.hideAttribution = false;
        /**
         * Prevent rendering until job is done.
         * Can be used for initial rendering performance improvement.
         * When several plugins require initial rendering this will prevent double initial rendering.
         */
        this.jobsBeforeRender = [];
        /**
         * Register new virtual node inside of grid.
         * Used for additional items creation such as plugin elements.
         * Should be set before grid render inside of plugins.
         * Can return VNode result of h() function or a function that returns VNode.
         * Function can be used for performance improvement and additional renders.
         */
        this.registerVNode = [];
        /**
         * Enable accessibility. If disabled, the grid will not be accessible.
         * @default true
         */
        this.accessible = true;
        /**
         * Enable right-to-left (RTL) mode. When enabled, columns will be displayed from right to left.
         * @default false
         */
        this.rtl = false;
        /**
         * Disable native drag&drop plugin.
         */
        this.canDrag = true;
        this.extraElements = [];
        this.pluginService = new PluginService();
        this.viewport = null;
        this.isInited = false;
    }
    // #endregion
    // #region Methods
    /**
     * Refreshes data viewport.
     * Can be specific part as rgRow or pinned rgRow or 'all' by default.
     */
    async refresh(type = 'all') {
        if (!this.dataProvider) {
            throw new Error('Not connected');
        }
        this.dataProvider.refresh(type);
    }
    /**
     * Refreshes data at specified cell.
     * Useful for performance optimization.
     * No viewport update will be triggered.
     *
     * @example
     * const grid = document.querySelector('revo-grid');
     * grid.setDataAt({ row: 0, col: 0, val: 'test' }); // refresh
     */
    async setDataAt({ row, col, colType = 'rgCol', rowType = 'rgRow', val, skipDataUpdate = false }) {
        var _a;
        if (this.dataProvider && this.columnProvider && !skipDataUpdate) {
            const columnProp = (_a = this.columnProvider.getColumn(col, colType)) === null || _a === void 0 ? void 0 : _a.prop;
            if (typeof columnProp !== 'undefined') {
                this.dataProvider.setCellData({
                    type: rowType,
                    rowIndex: row,
                    prop: columnProp,
                    val,
                }, false);
            }
        }
        const dataElement = this.element.querySelector(`revogr-data[type="${rowType}"][col-type="${colType}"]`);
        return dataElement === null || dataElement === void 0 ? void 0 : dataElement.updateCell({
            row,
            col,
        });
    }
    /**
     * Scrolls viewport to specified row by index.
     */
    async scrollToRow(coordinate = 0) {
        if (!this.dimensionProvider) {
            throw new Error('Not connected');
        }
        const y = this.dimensionProvider.getViewPortPos({
            coordinate,
            dimension: 'rgRow',
        });
        await this.scrollToCoordinate({ y });
    }
    /**
     * Scrolls viewport to specified column by index.
     */
    async scrollToColumnIndex(coordinate = 0) {
        if (!this.dimensionProvider) {
            throw new Error('Not connected');
        }
        const x = this.dimensionProvider.getViewPortPos({
            coordinate,
            dimension: 'rgCol',
        });
        await this.scrollToCoordinate({ x });
    }
    /**
     * Scrolls viewport to specified column by prop
     */
    async scrollToColumnProp(prop, dimension = 'rgCol') {
        if (!this.dimensionProvider || !this.columnProvider) {
            throw new Error('Not connected');
        }
        const coordinate = this.columnProvider.getColumnIndexByProp(prop, dimension);
        if (coordinate < 0) {
            // already on the screen
            return;
        }
        const x = this.dimensionProvider.getViewPortPos({
            coordinate,
            dimension,
        });
        await this.scrollToCoordinate({ x });
    }
    /** Update columns */
    async updateColumns(cols) {
        var _a;
        (_a = this.columnProvider) === null || _a === void 0 ? void 0 : _a.updateColumns(cols);
    }
    /** Add trimmed by type */
    async addTrimmed(trimmed, trimmedType = 'external', type = 'rgRow') {
        if (!this.dataProvider) {
            throw new Error('Not connected');
        }
        const event = this.beforetrimmed.emit({
            trimmed,
            trimmedType,
            type,
        });
        if (event.defaultPrevented) {
            return event;
        }
        this.dataProvider.setTrimmed({ [trimmedType]: event.detail.trimmed }, type);
        this.aftertrimmed.emit();
        return event;
    }
    /**  Scrolls view port to coordinate */
    async scrollToCoordinate(cell) {
        var _a;
        (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.scrollToCell(cell);
    }
    /**  Open editor for cell. */
    async setCellEdit(rgRow, prop, rowSource = 'rgRow') {
        var _a;
        const rgCol = getColumnByProp(this.columns, prop);
        if (!rgCol) {
            return;
        }
        await timeout();
        const colGroup = rgCol.pin || 'rgCol';
        if (!this.columnProvider) {
            throw new Error('Not connected');
        }
        (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.setEdit(rgRow, this.columnProvider.getColumnIndexByProp(prop, colGroup), colGroup, rowSource);
    }
    /**  Set focus range. */
    async setCellsFocus(cellStart = { x: 0, y: 0 }, cellEnd = { x: 0, y: 0 }, colType = 'rgCol', rowType = 'rgRow') {
        var _a;
        (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.setFocus(colType, rowType, cellStart, cellEnd);
    }
    /**  Get data from source */
    async getSource(type = 'rgRow') {
        if (!this.dataProvider) {
            throw new Error('Not connected');
        }
        return this.dataProvider.stores[type].store.get('source');
    }
    /**
     * Get data from visible part of source
     * Trimmed/filtered rows will be excluded
     * @param type - type of source
     */
    async getVisibleSource(type = 'rgRow') {
        if (!this.dataProvider) {
            throw new Error('Not connected');
        }
        return getVisibleSourceItem(this.dataProvider.stores[type].store);
    }
    /**
     * Provides access to rows internal store observer
     * Can be used for plugin support
     * @param type - type of source
     */
    async getSourceStore(type = 'rgRow') {
        if (!this.dataProvider) {
            throw new Error('Not connected');
        }
        return this.dataProvider.stores[type].store;
    }
    /**
     * Provides access to column internal store observer
     * Can be used for plugin support
     * @param type - type of column
     */
    async getColumnStore(type = 'rgCol') {
        if (!this.columnProvider) {
            throw new Error('Not connected');
        }
        return this.columnProvider.stores[type].store;
    }
    /**
     * Update column sorting
     * @param column - column prop and cellCompare
     * @param order - order to apply
     * @param additive - if false will replace current order
     *
     * later passed to SortingPlugin
     */
    async updateColumnSorting(column, order, additive) {
        this.sortingconfigchanged.emit({
            columns: [{
                    prop: column.prop,
                    order,
                    cellCompare: column.cellCompare,
                }],
            additive,
        });
    }
    /**
     * Clears column sorting
     */
    async clearSorting() {
        this.sortingconfigchanged.emit({
            columns: [],
        });
    }
    /**
     * Receive all columns in data source
     */
    async getColumns() {
        if (!this.columnProvider) {
            throw new Error('Not connected');
        }
        return this.columnProvider.getColumns();
    }
    /**
     * Clear current grid focus. Grid has no longer focus on it.
     */
    async clearFocus() {
        var _a, _b;
        const focused = (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.getFocused();
        const event = this.beforefocuslost.emit(focused);
        if (event.defaultPrevented) {
            return;
        }
        (_b = this.selectionStoreConnector) === null || _b === void 0 ? void 0 : _b.clearAll();
    }
    /**
     * Get all active plugins instances
     */
    async getPlugins() {
        return this.pluginService.get();
    }
    /**
     * Get the currently focused cell.
     */
    async getFocused() {
        var _a, _b;
        return (_b = (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.getFocused()) !== null && _b !== void 0 ? _b : null;
    }
    /**
     * Get size of content
     * Including all pinned data
     */
    async getContentSize() {
        var _a;
        if (!this.dimensionProvider) {
            throw new Error('Not connected');
        }
        return (_a = this.dimensionProvider) === null || _a === void 0 ? void 0 : _a.getFullSize();
    }
    /**
     * Get the currently selected Range.
     */
    async getSelectedRange() {
        var _a, _b;
        return (_b = (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.getSelectedRange()) !== null && _b !== void 0 ? _b : null;
    }
    /**
     * Refresh extra elements. Triggers re-rendering of extra elements and functions.
     * Part of extraElements and registerVNode methods.
     * Useful for plugins.
     */
    async refreshExtraElements() {
        var _a;
        (_a = this.extraService) === null || _a === void 0 ? void 0 : _a.refresh();
    }
    /**
     * Get all providers for grid
     * Useful for external grid integration
     */
    async getProviders() {
        return this.getPluginData();
    }
    mousedownHandle(event) {
        const screenX = getPropertyFromEvent(event, 'screenX');
        const screenY = getPropertyFromEvent(event, 'screenY');
        if (screenX === null || screenY === null) {
            return;
        }
        this.clickTrackForFocusClear = screenX + screenY;
    }
    /**
     * To keep your elements from losing focus use mouseup/touchend e.preventDefault();
     */
    async mouseupHandle(event) {
        var _a;
        const screenX = getPropertyFromEvent(event, 'screenX');
        const screenY = getPropertyFromEvent(event, 'screenY');
        if (screenX === null || screenY === null) {
            return;
        }
        if (event.defaultPrevented) {
            return;
        }
        const pos = screenX + screenY;
        // detect if mousemove then do nothing
        if (Math.abs(((_a = this.clickTrackForFocusClear) !== null && _a !== void 0 ? _a : 0) - pos) > 10) {
            return;
        }
        // Check if action finished inside the document
        // if event prevented, or it is current table don't clear focus
        const path = event.composedPath();
        if (!path.includes(this.element) &&
            !(this.element.shadowRoot && path.includes(this.element.shadowRoot))) {
            // Perform actions if the click is outside the component
            await this.clearFocus();
        }
    }
    // #endregion
    // #region Listeners
    /** Drag events */
    onRowDragStarted(e) {
        var _a;
        const dragStart = this.rowdragstart.emit(e.detail);
        if (dragStart.defaultPrevented) {
            e.preventDefault();
            return;
        }
        (_a = this.orderService) === null || _a === void 0 ? void 0 : _a.start(this.element, Object.assign(Object.assign({}, e.detail), dragStart.detail));
    }
    onRowDragEnd() {
        var _a;
        (_a = this.orderService) === null || _a === void 0 ? void 0 : _a.end();
    }
    onRowOrderChange(e) {
        var _a;
        (_a = this.dataProvider) === null || _a === void 0 ? void 0 : _a.changeOrder(e.detail);
    }
    onRowDrag({ detail }) {
        var _a;
        (_a = this.orderService) === null || _a === void 0 ? void 0 : _a.move(detail);
    }
    onRowMouseMove(e) {
        var _a;
        (_a = this.orderService) === null || _a === void 0 ? void 0 : _a.moveTip(e.detail);
    }
    async onCellEdit(e) {
        var _a;
        const { defaultPrevented, detail } = this.beforeedit.emit(e.detail);
        await timeout();
        // apply data
        if (!defaultPrevented) {
            (_a = this.dataProvider) === null || _a === void 0 ? void 0 : _a.setCellData(detail);
            // @feature: incrimental update for cells
            // this.dataProvider.setCellData(detail, false);
            // await this.setDataAt({
            //   row: detail.rowIndex,
            //   col: detail.colIndex,
            //   rowType: detail.type,
            //   colType: detail.colType,
            // });
            this.afteredit.emit(detail);
        }
    }
    onRangeEdit(e) {
        if (!this.dataProvider) {
            throw new Error('Not connected');
        }
        const { defaultPrevented, detail } = this.beforerangeedit.emit(e.detail);
        if (defaultPrevented) {
            e.preventDefault();
            return;
        }
        this.dataProvider.setRangeData(detail.data, detail.type);
        this.afteredit.emit(detail);
    }
    onRangeChanged(e) {
        const beforeange = this.beforerange.emit(e.detail);
        if (beforeange.defaultPrevented) {
            e.preventDefault();
        }
        const beforeFill = this.beforeautofill.emit(beforeange.detail);
        if (beforeFill.defaultPrevented) {
            e.preventDefault();
        }
    }
    onRowDropped(e) {
        // e.cancelBubble = true;
        const { defaultPrevented } = this.roworderchanged.emit(e.detail);
        if (defaultPrevented) {
            e.preventDefault();
        }
    }
    onHeaderClick(e) {
        const { defaultPrevented } = this.headerclick.emit(Object.assign(Object.assign({}, e.detail.column), { originalEvent: e.detail.originalEvent }));
        if (defaultPrevented) {
            e.preventDefault();
        }
    }
    onCellFocus(e) {
        const { defaultPrevented } = this.beforecellfocus.emit(e.detail);
        if (!this.canFocus || defaultPrevented) {
            e.preventDefault();
        }
    }
    // #endregion
    // #region Watchers
    columnTypesChanged() {
        // Column format change will trigger column structure update
        this.columnChanged(this.columns);
    }
    columnChanged(newVal = [], _prevVal = undefined, __watchName = 'columns', init = false) {
        if (!this.dimensionProvider || !this.columnProvider) {
            return;
        }
        const focusToRestore = init ? undefined : this.getColumnFocusRestore();
        const beforeGatherEvent = this.beforecolumnsgather.emit({
            columns: [...newVal],
        });
        if (beforeGatherEvent.defaultPrevented) {
            return;
        }
        const columnGather = getColumns(beforeGatherEvent.detail.columns, 0, this.columnTypes);
        const beforeSetEvent = this.beforecolumnsset.emit(columnGather);
        if (beforeSetEvent.defaultPrevented) {
            return;
        }
        this.dimensionProvider.applyNewColumns(beforeSetEvent.detail.columns, this.disableVirtualX, init, this.virtualX);
        const beforeApplyEvent = this.beforecolumnapplied.emit(columnGather);
        if (beforeApplyEvent.defaultPrevented) {
            return;
        }
        const columns = this.columnProvider.setColumns(beforeApplyEvent.detail);
        if (focusToRestore) {
            this.pendingColumnFocusRestore = focusToRestore;
        }
        const order = {};
        for (const prop of Object.keys(beforeApplyEvent.detail.sort)) {
            order[prop] = beforeApplyEvent.detail.sort[prop].order;
        }
        this.aftercolumnsset.emit({
            columns,
            order,
        });
    }
    /**
     * Capture logical focus before columns are repartitioned by pin state.
     * Regression case: selecting a regular cell, then pinning that column left,
     * used to let the new pinned viewport reuse the old rgCol selection store.
     */
    getColumnFocusRestore() {
        var _a, _b, _c, _d;
        const focused = (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.getFocused();
        const prevStoreX = (_c = (_b = this.selectionStoreConnector) === null || _b === void 0 ? void 0 : _b.focusedStore) === null || _c === void 0 ? void 0 : _c.position.x;
        const prop = (_d = focused === null || focused === void 0 ? void 0 : focused.column) === null || _d === void 0 ? void 0 : _d.prop;
        if (!focused || prop === undefined || prevStoreX === undefined) {
            return;
        }
        return {
            prop,
            colType: focused.colType,
            colIndex: focused.cell.x,
            prevStoreX,
            rowType: focused.rowType,
            rowIndex: focused.cell.y,
        };
    }
    /**
     * Reapply focus by column prop after render, once pinning has moved the
     * column to its new viewport and virtual index.
     */
    restoreColumnFocusAfterRender() {
        var _a, _b, _c, _d;
        const pending = this.pendingColumnFocusRestore;
        if (!pending) {
            return;
        }
        this.pendingColumnFocusRestore = undefined;
        if (!this.viewport || !this.columnProvider) {
            return;
        }
        const column = (_b = (_a = this.columnProvider.getColumnByProp(pending.prop)) === null || _a === void 0 ? void 0 : _a[0]) !== null && _b !== void 0 ? _b : getColumnByProp(this.columns, pending.prop);
        if (!column) {
            return;
        }
        const colType = column.pin || 'rgCol';
        const columnIndex = this.columnProvider.getColumnIndexByProp(pending.prop, colType);
        if (columnIndex < 0) {
            return;
        }
        // Header-only column refreshes should not collapse an existing range.
        // Replay focus only when pin/unpin or repartitioning moved the logical column.
        if (colType === pending.colType &&
            columnIndex === pending.colIndex &&
            pending.prevStoreX === ((_d = (_c = this.selectionStoreConnector) === null || _c === void 0 ? void 0 : _c.focusedStore) === null || _d === void 0 ? void 0 : _d.position.x)) {
            return;
        }
        const cell = {
            x: columnIndex,
            y: pending.rowIndex,
        };
        this.viewport.setFocus(colType, pending.rowType, cell, cell);
    }
    refreshColumnsOnConfigChange(newVal, prevVal) {
        if (newVal === prevVal) {
            return;
        }
        this.columnChanged(this.columns);
    }
    disableVirtualXChanged(newVal = false, prevVal = false) {
        this.refreshColumnsOnConfigChange(newVal, prevVal);
    }
    virtualXChanged(newVal = ['rgCol'], prevVal = ['rgCol']) {
        this.refreshColumnsOnConfigChange(newVal, prevVal);
    }
    rowSizeChanged(s) {
        if (!this.dimensionProvider) {
            return;
        }
        // clear existing data
        this.dimensionProvider.setSettings({ originItemSize: s }, 'rgRow');
        this.rowDefChanged(this.rowDefinitions, this.rowDefinitions, 'rowSize', true);
    }
    themeChanged(t, _, __ = 'theme', init = false) {
        if (!this.dimensionProvider) {
            return;
        }
        this.themeService.register(t);
        this.dimensionProvider.setSettings({ originItemSize: this.themeService.rowSize }, 'rgRow');
        this.dimensionProvider.setSettings({ originItemSize: this.colSize }, 'rgCol');
        // if theme change we need to reapply row size and reset viewport
        if (!init) {
            // clear existing data
            this.dimensionProvider.setSettings({ originItemSize: this.themeService.rowSize }, 'rgRow');
            this.rowDefChanged(
            // for cases when some custom size present and not
            this.rowDefinitions, this.rowDefinitions, 'theme', true);
        }
        this.afterthemechanged.emit(t);
    }
    dataSourceChanged(newVal = [], _, watchName) {
        if (!this.dataProvider) {
            return;
        }
        let type = 'rgRow';
        switch (watchName) {
            case 'pinnedBottomSource':
                type = 'rowPinEnd';
                break;
            case 'pinnedTopSource':
                type = 'rowPinStart';
                break;
            case 'source':
                type = 'rgRow';
                /**
                 * Applied for source only for cross compatability between plugins
                 */
                const beforesourceset = this.beforesourceset.emit({
                    type,
                    source: newVal,
                });
                newVal = beforesourceset.detail.source;
                break;
        }
        const beforesourceset = this.beforeanysource.emit({
            type,
            source: newVal,
        });
        const newSource = [...beforesourceset.detail.source];
        this.dataProvider.setData(newSource, type, this.disableVirtualY);
        /**
         * Applied for source only for cross compatability between plugins
         */
        if (watchName === 'source') {
            this.aftersourceset.emit({
                type,
                source: newVal,
            });
        }
        this.afteranysource.emit({
            type,
            source: newVal,
        });
    }
    disableVirtualYChanged(newVal = false, prevVal = false) {
        if (newVal === prevVal) {
            return;
        }
        this.dataSourceChanged(this.source, this.source, 'source');
    }
    rowDefChanged(after, before, _watchName, forceUpdate = true) {
        // in firefox it's triggered before init
        if (!this.dimensionProvider || !this.dataProvider) {
            return;
        }
        const { detail: { vals: newVal, oldVals: oldVal }, } = this.beforerowdefinition.emit({
            vals: after,
            oldVals: before,
        });
        // apply new values
        const newRows = rowDefinitionByType(newVal);
        // clear current defs
        if (oldVal) {
            const remove = rowDefinitionRemoveByType(oldVal);
            // clear all old data and drop sizes
            for (const t in remove) {
                if (remove.hasOwnProperty(t)) {
                    const type = t;
                    const store = this.dataProvider.stores[type];
                    const sourceLength = store.store.get('source').length;
                    this.dimensionProvider.clearSize(type, sourceLength);
                }
            }
        }
        // set new sizes
        rowTypes.forEach((t) => {
            var _a;
            const newSizes = newRows[t];
            // apply new sizes or force update
            if (newSizes || forceUpdate) {
                (_a = this.dimensionProvider) === null || _a === void 0 ? void 0 : _a.setCustomSizes(t, (newSizes === null || newSizes === void 0 ? void 0 : newSizes.sizes) || {});
            }
        });
    }
    trimmedRowsChanged(newVal = {}) {
        this.addTrimmed(newVal);
    }
    /**
     * Grouping
     */
    groupingChanged(newVal = {}) {
        var _a;
        (_a = this.pluginService.getByClass(GroupingRowPlugin)) === null || _a === void 0 ? void 0 : _a.setGrouping(newVal || {});
    }
    /**
     * Stretch Plugin Apply
     */
    applyStretch(isStretch) {
        if (!this.dimensionProvider || !this.dataProvider || !this.columnProvider || !this.viewportProvider) {
            return;
        }
        if (isStretch === 'false') {
            isStretch = false;
        }
        const pluginData = this.getPluginData();
        if (!pluginData) {
            return;
        }
        const stretch = this.pluginService.getByClass(StretchColumn);
        if ((typeof isStretch === 'boolean' && isStretch) || isStretch === 'true') {
            if (!stretch) {
                this.pluginService.add(new StretchColumn(this.element, pluginData));
            }
            else if (isStretchPlugin(stretch)) {
                stretch.applyStretch(this.columnProvider.getRawColumns());
            }
        }
        else if (stretch) {
            this.pluginService.remove(stretch);
        }
    }
    applyFilter(cfg) {
        this.filterconfigchanged.emit(cfg);
    }
    applySorting(cfg) {
        this.sortingconfigchanged.emit(cfg);
    }
    rowHeadersChange(rowHeaders) {
        this.rowheaderschanged.emit(rowHeaders);
    }
    /**
     * Register external VNodes
     */
    registerOutsideVNodes(elements = []) {
        this.extraElements = elements;
    }
    additionalDataChanged(data) {
        this.additionaldatachanged.emit(data);
    }
    /**
     * Watch for RTL changes and reapply column ordering
     */
    rtlChanged() {
        // The RTL plugin will handle the transformation automatically
        // Just trigger a column refresh to ensure the plugin processes the change
        this.columnChanged(this.columns);
    }
    /**
     * User can add plugins via plugins property
     */
    pluginsChanged(plugins = [], prevPlugins) {
        this.pluginService.addUserPluginsAndCreate(this.element, plugins, prevPlugins, this.getPluginData());
    }
    // #endregion
    // #region Plugins
    setPlugins() {
        // remove old plugins if any
        this.removePlugins();
        // pass data provider to plugins
        const pluginData = this.getPluginData();
        if (!pluginData) {
            return;
        }
        // register system plugins
        this.setCorePlugins(pluginData);
        // register user plugins
        this.pluginsChanged(this.plugins);
    }
    setCorePlugins(pluginData) {
        if (this.accessible) {
            this.pluginService.add(new WCAGPlugin(this.element, pluginData));
        }
        // register RTL plugin
        this.pluginService.add(new RTLPlugin(this.element, pluginData));
        // register auto size plugin
        if (this.autoSizeColumn) {
            this.pluginService.add(new AutoSizeColumnPlugin(this.element, pluginData, typeof this.autoSizeColumn === 'object'
                ? this.autoSizeColumn
                : undefined));
        }
        // register filter plugin
        if (this.filter) {
            this.pluginService.add(new FilterPlugin(this.element, pluginData, typeof this.filter === 'object' ? this.filter : undefined));
        }
        // register export plugin
        if (this.exporting) {
            this.pluginService.add(new ExportFilePlugin(this.element, pluginData));
        }
        // register sorting plugin
        this.pluginService.add(new SortingPlugin(this.element, pluginData));
        // register grouping plugin
        this.pluginService.add(new GroupingRowPlugin(this.element, pluginData));
        if (this.canMoveColumns) {
            this.pluginService.add(new ColumnMovePlugin(this.element, pluginData));
        }
    }
    getPluginData() {
        if (!this.dimensionProvider || !this.dataProvider || !this.columnProvider || !this.viewportProvider || !this.selectionStoreConnector) {
            return;
        }
        // pass data provider to plugins
        const pluginData = {
            data: this.dataProvider,
            column: this.columnProvider,
            dimension: this.dimensionProvider,
            viewport: this.viewportProvider,
            selection: this.selectionStoreConnector,
            plugins: this.pluginService,
        };
        return pluginData;
    }
    removePlugins() {
        this.pluginService.destroy();
    }
    // #endregion
    // if reconnect to dom we need to set up plugins
    connectedCallback() {
        if (this.isInited) {
            this.setPlugins();
        }
        this.created.emit();
    }
    /**
     * Called once just after the component is first connected to the DOM.
     * Since this method is only called once, it's a good place to load data asynchronously and to setup the state
     * without triggering extra re-renders.
     * A promise can be returned, that can be used to wait for the first render().
     */
    componentWillLoad() {
        var _a;
        // #region Setup Providers
        this.viewportProvider = new ViewportProvider();
        this.themeService = new ThemeService({
            rowSize: this.rowSize,
        });
        this.dimensionProvider = new DimensionProvider(this.viewportProvider, {
            realSizeChanged: (k) => this.contentsizechanged.emit(k),
        });
        this.columnProvider = new ColumnDataProvider();
        this.selectionStoreConnector = new SelectionStoreConnector();
        this.dataProvider = new DataProvider(this.dimensionProvider);
        // #endregion
        this.registerOutsideVNodes(this.registerVNode);
        // init plugins
        this.setPlugins();
        // set data
        this.applyStretch(this.stretch);
        this.themeChanged(this.theme, undefined, undefined, true);
        this.columnChanged(this.columns, undefined, undefined, true);
        this.dataSourceChanged(this.source, undefined, 'source');
        this.dataSourceChanged(this.pinnedTopSource, undefined, 'pinnedTopSource');
        this.dataSourceChanged(this.pinnedBottomSource, undefined, 'pinnedBottomSource');
        if (Object.keys((_a = this.trimmedRows) !== null && _a !== void 0 ? _a : {}).length > 0) {
            this.trimmedRowsChanged(this.trimmedRows);
        }
        this.rowDefChanged(this.rowDefinitions, undefined, undefined, false);
        // init grouping
        if (this.grouping && Object.keys(this.grouping).length > 0) {
            this.groupingChanged(this.grouping);
        }
        // init scrolling service
        this.scrollingService = new GridScrollingService((e) => {
            var _a;
            (_a = this.dimensionProvider) === null || _a === void 0 ? void 0 : _a.setViewPortCoordinate({
                coordinate: e.coordinate,
                type: e.dimension,
            });
            this.viewportscroll.emit(e);
        });
        this.aftergridinit.emit();
        // set inited flag for connectedCallback
        this.isInited = true;
    }
    componentWillRender() {
        const event = this.beforegridrender.emit();
        if (event.defaultPrevented) {
            return false;
        }
        return Promise.all(this.jobsBeforeRender);
    }
    componentDidRender() {
        this.restoreColumnFocusAfterRender();
        this.aftergridrender.emit();
    }
    render() {
        if (!this.dimensionProvider || !this.dataProvider || !this.columnProvider || !this.viewportProvider || !this.selectionStoreConnector) {
            return;
        }
        const contentHeight = this.dimensionProvider.stores['rgRow'].store.get('realSize');
        // init viewport service helpers
        this.viewport = new ViewportService({
            columnProvider: this.columnProvider,
            dataProvider: this.dataProvider,
            dimensionProvider: this.dimensionProvider,
            viewportProvider: this.viewportProvider,
            scrollingService: this.scrollingService,
            orderService: this.orderService,
            selectionStoreConnector: this.selectionStoreConnector,
            noHorizontalScrollTransfer: this.noHorizontalScrollTransfer,
            disableVirtualX: this.disableVirtualX,
            virtualX: this.virtualX,
            disableVirtualY: this.disableVirtualY,
            resize: c => this.aftercolumnresize.emit(c),
        }, contentHeight);
        // #region ViewportSections
        /**
         * The code renders a viewport divided into sections.
         * It starts by rendering the pinned start, data, and pinned end sections.
         * Within each section, it renders columns along with their headers, pinned top, center data, and pinned bottom.
         * The code iterates over the columns and their data to generate the view port's HTML structure.
         */
        const viewportSections = [];
        // Row headers setting
        if (this.rowHeaders && this.viewport.columns.length) {
            const anyView = this.viewport.columns[0];
            viewportSections.push(h("revogr-row-headers", { additionalData: this.additionalData, height: contentHeight, rowClass: this.rowClass, resize: this.resize, dataPorts: anyView.dataPorts, headerProp: anyView.headerProp, jobsBeforeRender: this.jobsBeforeRender, rowHeaderColumn: typeof this.rowHeaders === 'object' ? this.rowHeaders : undefined, onScrollview: ({ detail: e }) => this.scrollingService.proxyScroll(e, 'headerRow'), onRef: ({ detail: e }) => this.scrollingService.registerElement(e, 'headerRow') }));
        }
        // Viewport section render
        const isMobile = isMobileDevice();
        const viewPortHtml = [];
        // Render viewports column(horizontal sections)
        for (let view of this.viewport.columns) {
            const headerProperties = Object.assign(Object.assign({}, view.headerProp), { type: view.type, additionalData: this.additionalData, viewportCol: view.viewportCol, selectionStore: view.columnSelectionStore, canResize: this.resize, readonly: this.readonly, columnFilter: !!this.filter });
            // Column headers
            const dataViews = [
                h("revogr-header", Object.assign({}, headerProperties, { slot: HEADER_SLOT })),
            ];
            // Render viewport data (vertical sections)
            view.dataPorts.forEach(data => {
                const key = `${data.type}_${view.type}`;
                const dataView = (h("revogr-overlay-selection", Object.assign({}, data, { canDrag: this.canDrag && data.canDrag, isMobileDevice: isMobile, onSelectall: () => { var _a; return (_a = this.selectionStoreConnector) === null || _a === void 0 ? void 0 : _a.selectAll(); }, editors: this.editors, readonly: this.readonly, range: this.range, useClipboard: this.useClipboard, applyChangesOnClose: this.applyOnClose, additionalData: this.additionalData, slot: data.slot, onBeforenextvpfocus: (e) => { var _a; return (_a = this.selectionStoreConnector) === null || _a === void 0 ? void 0 : _a.beforeNextFocusCell(e.detail); }, onCanceledit: () => { var _a; return (_a = this.selectionStoreConnector) === null || _a === void 0 ? void 0 : _a.setEdit(false); }, onSetedit: ({ detail }) => {
                        var _a;
                        const event = this.beforeeditstart.emit(detail);
                        if (!event.defaultPrevented) {
                            (_a = this.selectionStoreConnector) === null || _a === void 0 ? void 0 : _a.setEdit(detail.val);
                        }
                    } }), h("revogr-data", Object.assign({}, data, { colType: view.type, key: key, readonly: this.readonly, range: this.range, rowClass: this.rowClass, rowSelectionStore: data.rowSelectionStore, additionalData: this.additionalData, jobsBeforeRender: this.jobsBeforeRender, slot: DATA_SLOT }), h("slot", { name: `data-${view.type}-${data.type}` })), h("revogr-temp-range", { selectionStore: data.selectionStore, dimensionRow: data.dimensionRow, dimensionCol: data.dimensionCol }), h("revogr-focus", { colData: data.colData, dataStore: data.dataStore, focusTemplate: this.focusTemplate, rowType: data.type, colType: view.type, selectionStore: data.selectionStore, dimensionRow: data.dimensionRow, dimensionCol: data.dimensionCol }, h("slot", { name: `focus-${view.type}-${data.type}` }))));
                dataViews.push(dataView);
            });
            // Add viewport scroll in the end
            viewPortHtml.push(h("revogr-viewport-scroll", Object.assign({}, view.prop, { ref: el => this.scrollingService.registerElement(el, `${view.prop.key}`), onScrollviewport: e => {
                    this.scrollingService.proxyScroll(e.detail, `${view.prop.key}`, this.noHorizontalScrollTransfer && e.detail.dimension === 'rgCol');
                }, onScrollviewportsilent: e => this.scrollingService.scrollSilentService(e.detail, `${view.prop.key}`) }), dataViews));
        }
        viewportSections.push(viewPortHtml);
        // #endregion
        const typeRow = 'rgRow';
        const typeCol = 'rgCol';
        const viewports = this.viewportProvider.stores;
        const dimensions = this.dimensionProvider.stores;
        const verticalScroll = (h("revogr-scroll-virtual", { class: "vertical", dimension: typeRow, clientSize: viewports[typeRow].store.get('clientSize'), virtualSize: viewports[typeRow].store.get('virtualSize'), realSize: dimensions[typeRow].store.get('realSize'), ref: el => this.scrollingService.registerElement(el, 'rowScroll'), onScrollvirtual: e => this.scrollingService.proxyScroll(e.detail) }));
        const horizontalScroll = (h("revogr-scroll-virtual", { class: "horizontal", dimension: typeCol, clientSize: viewports[typeCol].store.get('clientSize'), virtualSize: viewports[typeCol].store.get('virtualSize'), realSize: dimensions[typeCol].store.get('realSize'), ref: el => this.scrollingService.registerElement(el, 'colScroll'), onScrollvirtual: e => this.scrollingService.proxyScroll(e.detail) }));
        return (h(Host, { dir: this.rtl ? 'rtl' : 'ltr' }, this.hideAttribution ? null : (h("revogr-attribution", { class: "attribution" })), h("slot", { name: "header" }), h("div", { class: "main-viewport", onClick: (e) => {
                var _a;
                if (e.currentTarget === e.target) {
                    (_a = this.viewport) === null || _a === void 0 ? void 0 : _a.clearEdit();
                }
            } }, h("div", { class: "viewports" }, h("slot", { name: "viewport" }), viewportSections, verticalScroll, h(OrderRenderer, { ref: e => (this.orderService = e) }))), horizontalScroll, h("revogr-extra", { ref: el => (this.extraService = el), nodes: this.extraElements }), h("slot", { name: "footer" })));
    }
    disconnectedCallback() {
        // Remove all plugins, to avoid memory leaks
        // and unexpected behaviour when the component is removed
        this.removePlugins();
    }
    get element() { return getElement(this); }
    static get watchers() { return {
        "columnTypes": [{
                "columnTypesChanged": 0
            }],
        "columns": [{
                "columnChanged": 0
            }],
        "disableVirtualX": [{
                "disableVirtualXChanged": 0
            }],
        "virtualX": [{
                "virtualXChanged": 0
            }],
        "rowSize": [{
                "rowSizeChanged": 0
            }],
        "theme": [{
                "themeChanged": 0
            }],
        "source": [{
                "dataSourceChanged": 0
            }],
        "pinnedBottomSource": [{
                "dataSourceChanged": 0
            }],
        "pinnedTopSource": [{
                "dataSourceChanged": 0
            }],
        "disableVirtualY": [{
                "disableVirtualYChanged": 0
            }],
        "rowDefinitions": [{
                "rowDefChanged": 0
            }],
        "trimmedRows": [{
                "trimmedRowsChanged": 0
            }],
        "grouping": [{
                "groupingChanged": 0
            }],
        "stretch": [{
                "applyStretch": 0
            }],
        "filter": [{
                "applyFilter": 0
            }],
        "sorting": [{
                "applySorting": 0
            }],
        "rowHeaders": [{
                "rowHeadersChange": 0
            }],
        "registerVNode": [{
                "registerOutsideVNodes": 0
            }],
        "additionalData": [{
                "additionalDataChanged": 0
            }],
        "rtl": [{
                "rtlChanged": 0
            }],
        "plugins": [{
                "pluginsChanged": 0
            }]
    }; }
};
RevoGridComponent.style = revoGridStyleCss();

export { RevoGridComponent as revo_grid };
