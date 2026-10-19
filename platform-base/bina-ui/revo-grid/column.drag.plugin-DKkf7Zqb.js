/*!
 * Built by Revolist OU ❤️
 */
import { J as reduce, g as getRange, K as baseEach, C as getColumnType, c as columnTypes, L as toInteger, u as isGrouping, t as getGroupingName, r as rowTypes, B as getCellDataParsed, A as getCellRaw, j as GROUP_COLUMN_PROP, I as getColumnByProp, h as GROUP_EXPANDED, x as getParsedGroup, y as isSameGroup, G as GROUP_DEPTH, e as PSEUDO_GROUP_ITEM_VALUE, d as PSEUDO_GROUP_ITEM_ID, o as GROUPING_ROW_TYPE, p as getSource, f as PSEUDO_GROUP_COLUMN, s as gatherGrouping, m as GROUP_EXPAND_EVENT, v as isGroupingColumn, q as getExpanded, E as isColGrouping } from './column.service-C6hByxPy.js';
import { K as createStore, l as setStore, i as calculateDimensionData, L as identity, N as isArray, b as getSourceItem, g as getPhysical, e as setItems, j as getItemByPosition } from './dimension.helpers-CGKwSvw6.js';
import { j as calculateRowHeaderSize } from './viewport.store-_c579YyM.js';
import { g as getScrollbarSize, t as timeout } from './index-Db3qZoW5.js';
import { h } from './index-Chp_81rd.js';
import { b as FILTER_PROP, i as isFilterBtn } from './filter.button-B-RBiF67.js';
import { d as debounce } from './debounce-PCRWZliA.js';
import { O as ON_COLUMN_CLICK, d as dispatch } from './header-cell-renderer-BMmXRsd_.js';

function calculateRealSize({ count, originItemSize, sizes, }) {
    const safeCount = Math.max(0, count);
    let realSize = safeCount * originItemSize;
    for (let index in sizes) {
        const itemIndex = Number(index);
        if (!Number.isInteger(itemIndex) ||
            itemIndex < 0 ||
            itemIndex >= safeCount ||
            String(itemIndex) !== index) {
            continue;
        }
        realSize += sizes[index] - originItemSize;
    }
    return realSize;
}
/**
 * Plugin which recalculates realSize on changes of sizes, originItemSize and count
 */
const recalculateRealSizePlugin = (storeService) => {
    /**
     * Recalculates realSize if size, origin size or count changes
     */
    return {
        /**
         * Reacts on changes of count, sizes and originItemSize
         */
        set(k) {
            switch (k) {
                case 'count':
                case 'sizes':
                case 'originItemSize': {
                    // recalculate realSize
                    storeService.setStore({
                        realSize: calculateRealSize({
                            count: storeService.store.get('count'),
                            sizes: storeService.store.get('sizes'),
                            originItemSize: storeService.store.get('originItemSize'),
                        }),
                    });
                    break;
                }
            }
        },
    };
};

/**
 * Plugin for trimming
 *
 * 1.a. Retrieves the previous sizes value. Saves the resulting trimmed data as a new sizes value.
 * 1.b. Stores a reference to the trimmed data to prevent further changes.
 * 2. Removes multiple and shifts the data based on the trimmed value.
 */
const trimmedPlugin = (storeService) => {
    let trimmingObject = null;
    let trimmedPreviousSizes = null;
    return {
        set(key, val) {
            switch (key) {
                case 'sizes': {
                    // prevent changes after trimming
                    if (trimmingObject && trimmingObject === val) {
                        trimmingObject = null;
                        return;
                    }
                    trimmedPreviousSizes = null;
                    break;
                }
                case 'trimmed': {
                    const trim = val;
                    if (!trimmedPreviousSizes) {
                        trimmedPreviousSizes = storeService.store.get('sizes');
                    }
                    trimmingObject = removeMultipleAndShift(trimmedPreviousSizes, trim || {});
                    // save a reference to the trimmed object to prevent changes after trimming
                    storeService.setSizes(trimmingObject);
                    break;
                }
            }
        },
    };
};
function removeMultipleAndShift(items, toRemove) {
    const newItems = {};
    const sortedIndexes = Object.keys(items || {})
        .map(Number)
        .sort((a, b) => a - b);
    const lastIndex = sortedIndexes[sortedIndexes.length - 1];
    let shift = 0;
    for (let i = 0; i <= lastIndex; i++) {
        if (toRemove[i] !== undefined) {
            shift++;
            // skip already removed
            if (items[i] !== undefined) {
                continue;
            }
        }
        if (items[i] !== undefined) {
            newItems[i - shift] = items[i];
        }
    }
    return newItems;
}

/**
 * Storing pre-calculated
 * Dimension information and sizes
 */
function initialBase() {
    return {
        indexes: [],
        count: 0,
        // hidden items
        trimmed: null,
        // virtual item index to size
        sizes: {},
        // order in indexes[] to coordinate
        positionIndexToItem: {},
        // initial element to coordinate ^
        indexToItem: {},
        positionIndexes: [],
    };
}
function initialState() {
    return Object.assign(Object.assign({}, initialBase()), {
        // size which all items can take
        realSize: 0,
        // initial item size if it wasn't changed
        originItemSize: 0,
        // logical-to-physical render offset used when scroll space is compressed
        renderOffset: 0
    });
}
class DimensionStore {
    constructor(type) {
        this.type = type;
        this.store = createStore(initialState());
        this.store.use(trimmedPlugin({
            store: this.store,
            setSizes: this.setDimensionSize.bind(this),
        }));
        this.store.use(recalculateRealSizePlugin({
            store: this.store,
            setStore: this.setStore.bind(this),
        }));
    }
    getCurrentState() {
        const state = initialState();
        const keys = Object.keys(state);
        return reduce(keys, (r, k) => {
            const data = this.store.get(k);
            r[k] = data;
            return r;
        }, state);
    }
    dispose() {
        setStore(this.store, initialState());
    }
    setStore(data) {
        setStore(this.store, data);
    }
    drop() {
        setStore(this.store, Object.assign(Object.assign({}, initialBase()), { renderOffset: 0 }));
    }
    /**
     * Set custom dimension sizes and overwrite old
     * Generates new indexes based on sizes
     * @param sizes - sizes to set
     */
    setDimensionSize(sizes = {}) {
        const dimensionData = calculateDimensionData(this.store.get('originItemSize'), sizes);
        setStore(this.store, Object.assign(Object.assign({}, dimensionData), { sizes }));
    }
    updateSizesPositionByIndexes(newItemsOrder, prevItemsOrder = []) {
        // Move custom sizes to new order
        const customSizes = Object.assign({}, this.store.get('sizes'));
        if (!Object.keys(customSizes).length) {
            return;
        }
        // Step 1: Create a map of original indices, but allow duplicates by storing arrays of indices
        const originalIndices = {};
        prevItemsOrder.forEach((physIndex, virtIndex) => {
            if (!originalIndices[physIndex]) {
                originalIndices[physIndex] = [];
            }
            originalIndices[physIndex].push(virtIndex); // Store all indices for each value
        });
        // Step 2: Create new sizes based on new item order
        const newSizes = {};
        newItemsOrder.forEach((physIndex, virtIndex) => {
            const indices = originalIndices[physIndex]; // Get all original indices for this value
            if (indices && indices.length > 0) {
                const originalIndex = indices.shift(); // Get the first available original index
                if (originalIndex !== undefined &&
                    originalIndex !== virtIndex &&
                    typeof customSizes[originalIndex] === 'number') {
                    newSizes[virtIndex] = customSizes[originalIndex];
                    delete customSizes[originalIndex];
                }
            }
        });
        // Step 3: Set new sizes if there are changes
        if (Object.keys(newSizes).length) {
            this.setDimensionSize(Object.assign(Object.assign({}, customSizes), newSizes));
        }
    }
}

/**
 * Selection store
 */
function defaultState() {
    return {
        range: null,
        tempRange: null,
        tempRangeType: null,
        focus: null,
        edit: null,
        lastCell: null,
        nextFocus: null,
    };
}
class SelectionStore {
    constructor() {
        this.unsubscribe = [];
        this.store = createStore(defaultState());
        this.store.on('set', (key, newVal) => {
            if (key === 'tempRange' && !newVal) {
                this.store.set('tempRangeType', null);
            }
        });
    }
    onChange(propName, cb) {
        this.unsubscribe.push(this.store.onChange(propName, cb));
    }
    clearFocus() {
        setStore(this.store, { focus: null, range: null, edit: null, tempRange: null });
    }
    setFocus(focus, end) {
        if (!end) {
            setStore(this.store, { focus });
        }
        else {
            setStore(this.store, {
                focus,
                range: getRange(focus, end),
                edit: null,
                tempRange: null,
            });
        }
    }
    setNextFocus(focus) {
        setStore(this.store, { nextFocus: focus });
    }
    setTempArea(range) {
        setStore(this.store, { tempRange: range === null || range === void 0 ? void 0 : range.area, tempRangeType: range === null || range === void 0 ? void 0 : range.type, edit: null });
    }
    clearTemp() {
        setStore(this.store, { tempRange: null });
    }
    /** Can be applied from selection change or from simple keyboard change clicks */
    setRangeArea(range) {
        setStore(this.store, { range, edit: null, tempRange: null });
    }
    setRange(start, end) {
        const range = getRange(start, end);
        this.setRangeArea(range);
    }
    setLastCell(lastCell) {
        setStore(this.store, { lastCell });
    }
    setEdit(val) {
        const focus = this.store.get('focus');
        if (focus && typeof val === 'string') {
            setStore(this.store, {
                edit: { x: focus.x, y: focus.y, val },
            });
            return;
        }
        setStore(this.store, { edit: null });
    }
    dispose() {
        this.unsubscribe.forEach(f => f());
        this.store.dispose();
    }
}

/**
 * Base layer for plugins
 * Provide minimal starting core for plugins to work
 * Extend this class to create plugin
 */
class BasePlugin {
    constructor(revogrid, providers) {
        this.revogrid = revogrid;
        this.providers = providers;
        this.h = h;
        this.subscriptions = {};
    }
    /**
     *
     * @param eventName - event name to subscribe to in revo-grid component (e.g. 'beforeheaderclick')
     * @param callback - callback function for event
     */
    addEventListener(eventName, callback) {
        this.revogrid.addEventListener(eventName, callback);
        this.subscriptions[eventName] = callback;
    }
    /**
     * Subscribe to property change in revo-grid component
     * You can return false in callback to prevent default value set
     *
     * @param prop - property name
     * @param callback - callback function
     * @param immediate - trigger callback immediately with current value
     */
    watch(prop, callback, { immediate } = { immediate: false }) {
        var _a;
        const nativeValueDesc = Object.getOwnPropertyDescriptor(this.revogrid, prop) ||
            Object.getOwnPropertyDescriptor(this.revogrid.constructor.prototype, prop);
        // Overwrite property descriptor for this instance
        Object.defineProperty(this.revogrid, prop, {
            configurable: true,
            enumerable: (_a = nativeValueDesc === null || nativeValueDesc === void 0 ? void 0 : nativeValueDesc.enumerable) !== null && _a !== void 0 ? _a : true,
            set(val) {
                var _a;
                const keepDefault = callback(val);
                if (keepDefault === false) {
                    return;
                }
                // Continue with native behavior
                return (_a = nativeValueDesc === null || nativeValueDesc === void 0 ? void 0 : nativeValueDesc.set) === null || _a === void 0 ? void 0 : _a.call(this, val);
            },
            get() {
                var _a;
                // Continue with native behavior
                return (_a = nativeValueDesc === null || nativeValueDesc === void 0 ? void 0 : nativeValueDesc.get) === null || _a === void 0 ? void 0 : _a.call(this);
            },
        });
        if (immediate) {
            callback((nativeValueDesc === null || nativeValueDesc === void 0 ? void 0 : nativeValueDesc.get) ? nativeValueDesc.get.call(this.revogrid) : nativeValueDesc === null || nativeValueDesc === void 0 ? void 0 : nativeValueDesc.value);
        }
    }
    /**
     * Remove event listener
     * @param eventName
     */
    removeEventListener(eventName) {
        this.revogrid.removeEventListener(eventName, this.subscriptions[eventName]);
        delete this.subscriptions[eventName];
    }
    /**
     * Emit event from revo-grid component
     * Event can be cancelled by calling event.preventDefault() in callback
     */
    emit(eventName, detail) {
        const event = new CustomEvent(eventName, { detail, cancelable: true });
        this.revogrid.dispatchEvent(event);
        return event;
    }
    /**
     * Clear all subscriptions
     */
    clearSubscriptions() {
        for (let type in this.subscriptions) {
            this.removeEventListener(type);
        }
    }
    /**
     * Destroy plugin and clear all subscriptions
     */
    destroy() {
        this.clearSubscriptions();
    }
}

/**
 * A specialized version of `_.forEach` for arrays without support for
 * iteratee shorthands.
 *
 * @private
 * @param {Array} [array] The array to iterate over.
 * @param {Function} iteratee The function invoked per iteration.
 * @returns {Array} Returns `array`.
 */
function arrayEach(array, iteratee) {
  var index = -1,
      length = array == null ? 0 : array.length;

  while (++index < length) {
    if (iteratee(array[index], index, array) === false) {
      break;
    }
  }
  return array;
}

/**
 * Casts `value` to `identity` if it's not a function.
 *
 * @private
 * @param {*} value The value to inspect.
 * @returns {Function} Returns cast function.
 */
function castFunction(value) {
  return typeof value == 'function' ? value : identity;
}

/**
 * Iterates over elements of `collection` and invokes `iteratee` for each element.
 * The iteratee is invoked with three arguments: (value, index|key, collection).
 * Iteratee functions may exit iteration early by explicitly returning `false`.
 *
 * **Note:** As with other "Collections" methods, objects with a "length"
 * property are iterated like arrays. To avoid this behavior use `_.forIn`
 * or `_.forOwn` for object iteration.
 *
 * @static
 * @memberOf _
 * @since 0.1.0
 * @alias each
 * @category Collection
 * @param {Array|Object} collection The collection to iterate over.
 * @param {Function} [iteratee=_.identity] The function invoked per iteration.
 * @returns {Array|Object} Returns `collection`.
 * @see _.forEachRight
 * @example
 *
 * _.forEach([1, 2], function(value) {
 *   console.log(value);
 * });
 * // => Logs `1` then `2`.
 *
 * _.forEach({ 'a': 1, 'b': 2 }, function(value, key) {
 *   console.log(key);
 * });
 * // => Logs 'a' then 'b' (iteration order is not guaranteed).
 */
function forEach(collection, iteratee) {
  var func = isArray(collection) ? arrayEach : baseEach;
  return func(collection, castFunction(iteratee));
}

/**
 * Plugin module for revo-grid grid system
 * Add support for automatic column resize
 */
const LETTER_BLOCK_SIZE = 7;
var ColumnAutoSizeMode;
(function (ColumnAutoSizeMode) {
    // increases column width on header click according the largest text value
    ColumnAutoSizeMode["headerClickAutosize"] = "headerClickAutoSize";
    // increases column width on data set and text edit, decreases performance
    ColumnAutoSizeMode["autoSizeOnTextOverlap"] = "autoSizeOnTextOverlap";
    // increases and decreases column width based on all items sizes, worst for performance
    ColumnAutoSizeMode["autoSizeAll"] = "autoSizeAll";
})(ColumnAutoSizeMode || (ColumnAutoSizeMode = {}));
class AutoSizeColumnPlugin extends BasePlugin {
    constructor(revogrid, providers, config) {
        super(revogrid, providers);
        this.providers = providers;
        this.config = config;
        this.autoSizeColumns = null;
        /** for edge case when no columns defined before data */
        this.dataResolve = null;
        this.dataReject = null;
        this.letterBlockSize = (config === null || config === void 0 ? void 0 : config.letterBlockSize) || LETTER_BLOCK_SIZE;
        // create test container to check text width
        if (config === null || config === void 0 ? void 0 : config.preciseSize) {
            this.precsizeCalculationArea = this.initiatePresizeElement();
            revogrid.appendChild(this.precsizeCalculationArea);
        }
        const aftersourceset = ({ detail: { source }, }) => {
            this.setSource(source);
        };
        const beforecolumnsset = ({ detail: { columns }, }) => {
            this.columnSet(columns);
        };
        this.addEventListener('beforecolumnsset', beforecolumnsset);
        switch (config === null || config === void 0 ? void 0 : config.mode) {
            case ColumnAutoSizeMode.autoSizeOnTextOverlap:
                this.addEventListener('aftersourceset', aftersourceset);
                this.addEventListener('afteredit', ({ detail }) => {
                    this.afteredit(detail);
                });
                break;
            case ColumnAutoSizeMode.autoSizeAll:
                this.addEventListener('aftersourceset', aftersourceset);
                this.addEventListener('afteredit', ({ detail }) => {
                    this.afterEditAll(detail);
                });
                break;
            default:
                this.addEventListener('headerdblclick', ({ detail }) => {
                    const type = getColumnType(detail.column);
                    const size = this.getColumnSize(detail.index, type);
                    if (size) {
                        this.providers.dimension.setCustomSizes(type, {
                            [detail.index]: size,
                        }, true);
                    }
                });
                break;
        }
    }
    async setSource(source) {
        let autoSize = this.autoSizeColumns;
        if (this.dataReject) {
            this.dataReject();
            this.clearPromise();
        }
        /** If data set first and no column provided await until get one */
        if (!autoSize) {
            const request = new Promise((resolve, reject) => {
                this.dataResolve = resolve;
                this.dataReject = reject;
            });
            try {
                autoSize = await request;
            }
            catch (e) {
                return;
            }
        }
        // calculate sizes
        forEach(autoSize, (_v, type) => {
            const sizes = {};
            forEach(autoSize[type], rgCol => {
                // calculate size
                rgCol.size = sizes[rgCol.index] = source.reduce((prev, rgRow) => Math.max(prev, this.getLength(rgRow[rgCol.prop])), this.getLength(rgCol.name || ''));
            });
            this.providers.dimension.setCustomSizes(type, sizes, true);
        });
    }
    getLength(len) {
        var _a;
        const padding = 15;
        if (!len) {
            return 0;
        }
        try {
            const str = len.toString();
            /**if exact calculation required proxy with html element, slow operation */
            if ((_a = this.config) === null || _a === void 0 ? void 0 : _a.preciseSize) {
                this.precsizeCalculationArea.innerText = str;
                return this.precsizeCalculationArea.scrollWidth + padding * 2;
            }
            return str.length * this.letterBlockSize + padding * 2;
        }
        catch (e) {
            return 0;
        }
    }
    afteredit(e) {
        let data;
        if (this.isRangeEdit(e)) {
            data = e.data;
        }
        else {
            data = { 0: { [e.prop]: e.val } };
        }
        forEach(this.autoSizeColumns, (columns, type) => {
            const sizes = {};
            forEach(columns, rgCol => {
                var _a;
                // calculate size
                const size = reduce(data, (prev, rgRow) => {
                    if (typeof rgRow[rgCol.prop] === 'undefined') {
                        return prev;
                    }
                    return Math.max(prev || 0, this.getLength(rgRow[rgCol.prop]));
                }, undefined);
                if (size && ((_a = rgCol.size) !== null && _a !== void 0 ? _a : 0) < size) {
                    rgCol.size = sizes[rgCol.index] = size;
                }
            });
            this.providers.dimension.setCustomSizes(type, sizes, true);
        });
    }
    afterEditAll(e) {
        const props = {};
        if (this.isRangeEdit(e)) {
            forEach(e.data, r => forEach(r, (_v, p) => (props[p] = true)));
        }
        else {
            props[e.prop] = true;
        }
        forEach(this.autoSizeColumns, (columns, type) => {
            const sizes = {};
            forEach(columns, rgCol => {
                if (props[rgCol.prop]) {
                    const size = this.getColumnSize(rgCol.index, type);
                    if (size) {
                        sizes[rgCol.index] = size;
                    }
                }
            });
            this.providers.dimension.setCustomSizes(type, sizes, true);
        });
    }
    getColumnSize(index, type) {
        var _a, _b;
        const rgCol = (_b = (_a = this.autoSizeColumns) === null || _a === void 0 ? void 0 : _a[type]) === null || _b === void 0 ? void 0 : _b[index];
        if (!rgCol) {
            return 0;
        }
        return reduce(this.providers.data.stores, (r, s) => {
            const perStore = reduce(s.store.get('items'), (prev, _row, i) => {
                const item = getSourceItem(s.store, i);
                return Math.max(prev || 0, this.getLength(item === null || item === void 0 ? void 0 : item[rgCol.prop]));
            }, 0);
            return Math.max(r, perStore);
        }, rgCol.size || 0);
    }
    columnSet(columns) {
        var _a;
        for (let t of columnTypes) {
            const type = t;
            const cols = columns[type];
            for (let i in cols) {
                if (cols[i].autoSize || ((_a = this.config) === null || _a === void 0 ? void 0 : _a.allColumns)) {
                    if (!this.autoSizeColumns) {
                        this.autoSizeColumns = {};
                    }
                    if (!this.autoSizeColumns[type]) {
                        this.autoSizeColumns[type] = {};
                    }
                    this.autoSizeColumns[type][i] = Object.assign(Object.assign({}, cols[i]), { index: parseInt(i, 10) });
                }
            }
        }
        if (this.dataResolve) {
            this.dataResolve(this.autoSizeColumns || {});
            this.clearPromise();
        }
    }
    clearPromise() {
        this.dataResolve = null;
        this.dataReject = null;
    }
    isRangeEdit(e) {
        return !!e.data;
    }
    initiatePresizeElement() {
        var _a;
        const styleForFontTest = {
            position: 'absolute',
            fontSize: '14px',
            height: '0',
            width: '0',
            whiteSpace: 'nowrap',
            top: '0',
            overflowX: 'scroll',
            display: 'block',
        };
        const el = document.createElement('div');
        for (let s in styleForFontTest) {
            el.style[s] = (_a = styleForFontTest[s]) !== null && _a !== void 0 ? _a : '';
        }
        el.classList.add('revo-test-container');
        return el;
    }
    destroy() {
        var _a;
        super.destroy();
        (_a = this.precsizeCalculationArea) === null || _a === void 0 ? void 0 : _a.remove();
    }
}

class StretchColumn extends BasePlugin {
    constructor(revogrid, providers) {
        super(revogrid, providers);
        this.providers = providers;
        this.stretchedColumn = null;
        // calculate scroll bar size for current user session
        this.scrollSize = getScrollbarSize(document);
        // subscribe to column changes
        const beforecolumnapplied = ({ detail: { columns }, }) => this.applyStretch(columns);
        this.addEventListener('beforecolumnapplied', beforecolumnapplied);
    }
    setScroll({ type, hasScroll }) {
        var _a;
        if (type === 'rgRow' &&
            this.stretchedColumn &&
            ((_a = this.stretchedColumn) === null || _a === void 0 ? void 0 : _a.initialSize) === this.stretchedColumn.size) {
            if (hasScroll) {
                this.stretchedColumn.size -= this.scrollSize;
                this.apply();
                this.dropChanges();
            }
        }
    }
    activateChanges() {
        const setScroll = ({ detail }) => this.setScroll(detail);
        this.addEventListener('scrollchange', setScroll);
    }
    dropChanges() {
        this.stretchedColumn = null;
        this.removeEventListener('scrollchange');
    }
    apply() {
        if (!this.stretchedColumn) {
            return;
        }
        const type = 'rgCol';
        const sizes = this.providers.dimension.stores[type].store.get('sizes');
        this.providers.dimension.setCustomSizes(type, Object.assign(Object.assign({}, sizes), { [this.stretchedColumn.index]: this.stretchedColumn.size }), true);
    }
    /**
     * Apply stretch changes
     */
    applyStretch(columns) {
        // unsubscribe from all events
        this.dropChanges();
        // calculate grid size
        let sizeDifference = this.revogrid.clientWidth - 1;
        forEach(columns, (_, type) => {
            const realSize = this.providers.dimension.stores[type].store.get('realSize');
            sizeDifference -= realSize;
        });
        if (this.revogrid.rowHeaders) {
            const itemsLength = this.providers.data.stores.rgRow.store.get('source').length;
            const header = this.revogrid.rowHeaders;
            const rowHeaderSize = calculateRowHeaderSize(itemsLength, typeof header === 'object' ? header : undefined);
            if (rowHeaderSize) {
                sizeDifference -= rowHeaderSize;
            }
        }
        if (sizeDifference > 0) {
            // currently plugin accepts last column only
            const index = columns.rgCol.length - 1;
            const last = columns.rgCol[index];
            /**
             * has column
             * no auto size applied
             * size for column shouldn't be defined
             */
            const colSize = (last === null || last === void 0 ? void 0 : last.size) || this.revogrid.colSize || 0;
            const size = sizeDifference + colSize - 1;
            if (last && !last.autoSize && colSize < size) {
                this.stretchedColumn = {
                    initialSize: size,
                    index,
                    size,
                };
                this.apply();
                this.activateChanges();
            }
        }
    }
}
/**
 * Check plugin type is Stretch
 */
function isStretchPlugin(plugin) {
    return !!plugin.applyStretch;
}

/**
 * The base implementation of `_.clamp` which doesn't coerce arguments.
 *
 * @private
 * @param {number} number The number to clamp.
 * @param {number} [lower] The lower bound.
 * @param {number} upper The upper bound.
 * @returns {number} Returns the clamped number.
 */
function baseClamp(number, lower, upper) {
  if (number === number) {
    {
      number = number <= upper ? number : upper;
    }
    {
      number = number >= lower ? number : lower;
    }
  }
  return number;
}

/** Used as references for the maximum length and index of an array. */
var MAX_ARRAY_LENGTH = 4294967295;

/**
 * Converts `value` to an integer suitable for use as the length of an
 * array-like object.
 *
 * **Note:** This method is based on
 * [`ToLength`](http://ecma-international.org/ecma-262/7.0/#sec-tolength).
 *
 * @static
 * @memberOf _
 * @since 4.0.0
 * @category Lang
 * @param {*} value The value to convert.
 * @returns {number} Returns the converted integer.
 * @example
 *
 * _.toLength(3.2);
 * // => 3
 *
 * _.toLength(Number.MIN_VALUE);
 * // => 0
 *
 * _.toLength(Infinity);
 * // => 4294967295
 *
 * _.toLength('3.2');
 * // => 3
 */
function toLength(value) {
  return value ? baseClamp(toInteger(value), 0, MAX_ARRAY_LENGTH) : 0;
}

/**
 * The base implementation of `_.fill` without an iteratee call guard.
 *
 * @private
 * @param {Array} array The array to fill.
 * @param {*} value The value to fill `array` with.
 * @param {number} [start=0] The start position.
 * @param {number} [end=array.length] The end position.
 * @returns {Array} Returns `array`.
 */
function baseFill(array, value, start, end) {
  var length = array.length;

  start = toInteger(start);
  if (start < 0) {
    start = -start > length ? 0 : (length + start);
  }
  end = (end === undefined || end > length) ? length : toInteger(end);
  if (end < 0) {
    end += length;
  }
  end = start > end ? 0 : toLength(end);
  while (start < end) {
    array[start++] = value;
  }
  return array;
}

/**
 * Fills elements of `array` with `value` from `start` up to, but not
 * including, `end`.
 *
 * **Note:** This method mutates `array`.
 *
 * @static
 * @memberOf _
 * @since 3.2.0
 * @category Array
 * @param {Array} array The array to fill.
 * @param {*} value The value to fill `array` with.
 * @param {number} [start=0] The start position.
 * @param {number} [end=array.length] The end position.
 * @returns {Array} Returns `array`.
 * @example
 *
 * var array = [1, 2, 3];
 *
 * _.fill(array, 'a');
 * console.log(array);
 * // => ['a', 'a', 'a']
 *
 * _.fill(Array(3), 2);
 * // => [2, 2, 2]
 *
 * _.fill([4, 6, 8, 10], '*', 1, 3);
 * // => [4, '*', '*', 10]
 */
function fill(array, value, start, end) {
  var length = array == null ? 0 : array.length;
  if (!length) {
    return [];
  }
  return baseFill(array, value, start, end);
}

const INITIAL = {
    mime: 'text/csv',
    fileKind: 'csv',
    // BOM signature
    bom: true,
    columnDelimiter: ',',
    rowDelimiter: '\r\n',
    encoding: '',
};
// The ASCII character code 13 is called a Carriage Return or CR.
const CARRIAGE_RETURN = String.fromCharCode(13);
// Chr(13) followed by a Chr(10) that compose a proper CRLF.
const LINE_FEED = String.fromCharCode(10);
const DOUBLE_QT = String.fromCharCode(34);
const NO_BREAK_SPACE = String.fromCharCode(0xfeff);
const escapeRegex = new RegExp('"', 'g');
class ExportCsv {
    constructor(options = {}) {
        this.options = Object.assign(Object.assign({}, INITIAL), options);
    }
    doExport({ data, headers, props }) {
        let result = this.options.bom ? NO_BREAK_SPACE : '';
        // any header
        if ((headers === null || headers === void 0 ? void 0 : headers.length) > 0) {
            headers.forEach(header => {
                // ignore empty
                if (!header.length) {
                    return;
                }
                result += this.prepareHeader(header, this.options.columnDelimiter);
                result += this.options.rowDelimiter;
            });
        }
        data.forEach((rgRow, index) => {
            if (index > 0) {
                result += this.options.rowDelimiter;
            }
            // support grouping
            if (isGrouping(rgRow)) {
                result += this.parseCell(getGroupingName(rgRow), this.options.columnDelimiter);
                return;
            }
            result += props.map(p => this.parseCell(rgRow[p], this.options.columnDelimiter)).join(this.options.columnDelimiter);
        });
        return result;
    }
    prepareHeader(columnHeaders, columnDelimiter) {
        let result = '';
        const newColumnHeaders = columnHeaders.map(v => this.parseCell(v, columnDelimiter, true));
        result += newColumnHeaders.join(columnDelimiter);
        return result;
    }
    parseCell(value, columnDelimiter, force = false) {
        let escape = value;
        if (typeof value !== 'string') {
            escape = JSON.stringify(value);
        }
        const toEscape = [CARRIAGE_RETURN, DOUBLE_QT, LINE_FEED, columnDelimiter];
        if (typeof escape === 'undefined') {
            return '';
        }
        if (escape !== '' && (force || toEscape.some(i => escape.indexOf(i) >= 0))) {
            return `"${escape.replace(escapeRegex, '""')}"`;
        }
        return escape;
    }
}

var ExportTypes;
(function (ExportTypes) {
    ExportTypes["csv"] = "csv";
})(ExportTypes || (ExportTypes = {}));
class ExportFilePlugin extends BasePlugin {
    /** Exports string */
    async exportString(options = {}, t = ExportTypes.csv) {
        const data = await this.beforeexport();
        if (!data) {
            return null;
        }
        return this.formatter(t, options).doExport(data);
    }
    /** Exports Blob */
    async exportBlob(options = {}, t = ExportTypes.csv) {
        return await this.getBlob(this.formatter(t, options));
    }
    /** Export file */
    async exportFile(options = {}, t = ExportTypes.csv) {
        const formatter = this.formatter(t, options);
        // url
        const URL = window.URL || window.webkitURL;
        const a = document.createElement('a');
        const { filename, fileKind } = formatter.options;
        const name = `${filename}.${fileKind}`;
        const blob = await this.getBlob(formatter);
        const url = blob ? URL.createObjectURL(blob) : '';
        a.style.display = 'none';
        a.setAttribute('href', url);
        a.setAttribute('download', name);
        this.revogrid.appendChild(a);
        a.dispatchEvent(new MouseEvent('click'));
        this.revogrid.removeChild(a);
        // delay for revoke, correct for some browsers
        await timeout(120);
        URL.revokeObjectURL(url);
    }
    /** Blob object */
    async getBlob(formatter) {
        const type = `${formatter.options.mime};charset=${formatter.options.encoding}`;
        if (typeof Blob !== 'undefined') {
            const data = await this.beforeexport();
            if (!data) {
                return null;
            }
            return new Blob([formatter.doExport(data)], { type });
        }
        return null;
    }
    // before event
    async beforeexport() {
        let data = await this.getData();
        const event = this.emit('beforeexport', { data });
        if (event.defaultPrevented) {
            return null;
        }
        return event.detail.data;
    }
    async getData() {
        const data = await this.getSource();
        const colSource = [];
        const colPromises = [];
        columnTypes.forEach((t, i) => {
            colPromises.push(this.getColPerSource(t).then(s => (colSource[i] = s)));
        });
        await Promise.all(colPromises);
        const columns = {
            headers: [],
            props: [],
        };
        for (let source of colSource) {
            source.headers.forEach((h, i) => {
                if (!columns.headers[i]) {
                    columns.headers[i] = [];
                }
                columns.headers[i].push(...h);
            });
            columns.props.push(...source.props);
        }
        return Object.assign({ data }, columns);
    }
    async getColPerSource(t) {
        const store = await this.revogrid.getColumnStore(t);
        const source = store.get('source');
        const virtualIndexes = store.get('items');
        const depth = store.get('groupingDepth');
        const groups = store.get('groups');
        const colNames = [];
        const colProps = [];
        virtualIndexes.forEach((v) => {
            const prop = source[v].prop;
            colNames.push(source[v].name || '');
            colProps.push(prop);
        });
        const rows = this.getGroupHeaders(depth, groups, virtualIndexes);
        rows.push(colNames);
        return {
            headers: rows,
            props: colProps,
        };
    }
    getGroupHeaders(depth, groups, items) {
        const rows = [];
        const template = fill(new Array(items.length), '');
        for (let d = 0; d < depth; d++) {
            const rgRow = [...template];
            rows.push(rgRow);
            if (!groups[d]) {
                continue;
            }
            const levelGroups = groups[d];
            // add names of groups
            levelGroups.forEach((group) => {
                const minIndex = group.indexes[0];
                if (typeof minIndex === 'number') {
                    rgRow[minIndex] = group.name;
                }
            });
        }
        return rows;
    }
    async getSource() {
        const data = [];
        const promisesData = [];
        rowTypes.forEach(t => {
            const dataPart = [];
            data.push(dataPart);
            const promise = this.revogrid.getVisibleSource(t).then((d) => dataPart.push(...d));
            promisesData.push(promise);
        });
        await Promise.all(promisesData);
        return data.reduce((r, v) => {
            r.push(...v);
            return r;
        }, []);
    }
    // get correct class for future multiple types support
    formatter(type, options = {}) {
        switch (type) {
            case ExportTypes.csv:
                return new ExportCsv(options);
            default:
                throw new Error('Unknown format');
        }
    }
}

const eq = (value, extra) => {
    if (typeof value === 'undefined' || (value === null && !extra)) {
        return true;
    }
    if (typeof value !== 'string') {
        value = JSON.stringify(value);
    }
    const filterVal = extra === null || extra === void 0 ? void 0 : extra.toString().toLocaleLowerCase();
    if ((filterVal === null || filterVal === void 0 ? void 0 : filterVal.length) === 0) {
        return true;
    }
    return value.toLocaleLowerCase() === filterVal;
};
const notEq = (value, extra) => !eq(value, extra);
notEq.extra = 'input';
eq.extra = 'input';

const gtThan = function (value, extra) {
    let conditionValue;
    if (typeof value === 'number' && typeof extra !== 'undefined' && extra !== null) {
        conditionValue = parseFloat(extra === null || extra === void 0 ? void 0 : extra.toString());
        return value > conditionValue;
    }
    return false;
};
gtThan.extra = 'input';

const gtThanEq = function (value, extra) {
    return eq(value, extra) || gtThan(value, extra);
};
gtThanEq.extra = 'input';

const lt = function (value, extra) {
    let conditionValue;
    if (typeof value === 'number' && typeof extra !== 'undefined' && extra !== null) {
        conditionValue = parseFloat(extra.toString());
        return value < conditionValue;
    }
    else {
        return false;
    }
};
lt.extra = 'input';

const lsEq = function (value, extra) {
    return eq(value, extra) || lt(value, extra);
};
lsEq.extra = 'input';

const set = (value) => !(value === '' || value === null || value === void 0);
const notSet = (value) => !set(value);

const beginsWith = (value, extra) => {
    if (!value) {
        return false;
    }
    if (!extra) {
        return true;
    }
    if (typeof value !== 'string') {
        value = JSON.stringify(value);
    }
    if (typeof extra !== 'string') {
        extra = JSON.stringify(extra);
    }
    return value.toLocaleLowerCase().indexOf(extra.toLocaleLowerCase()) === 0;
};
beginsWith.extra = 'input';

const contains = (value, extra) => {
    if (!extra) {
        return true;
    }
    if (!value) {
        return false;
    }
    if (extra) {
        if (typeof value !== 'string') {
            value = JSON.stringify(value);
        }
        return value.toLocaleLowerCase().indexOf(extra.toString().toLowerCase()) > -1;
    }
    return true;
};
const notContains = (value, extra) => {
    return !contains(value, extra);
};
notContains.extra = 'input';
contains.extra = 'input';

// filter.indexed.ts
const filterCoreFunctionsIndexedByType = {
    none: () => true,
    empty: notSet,
    notEmpty: set,
    eq: eq,
    notEq: notEq,
    begins: beginsWith,
    contains: contains,
    notContains: notContains,
    eqN: eq,
    neqN: notEq,
    gt: gtThan,
    gte: gtThanEq,
    lt: lt,
    lte: lsEq,
};
const filterTypes = {
    string: ['notEmpty', 'empty', 'eq', 'notEq', 'begins', 'contains', 'notContains'],
    number: ['notEmpty', 'empty', 'eqN', 'neqN', 'gt', 'gte', 'lt', 'lte'],
};
const filterNames = {
    none: 'None',
    empty: 'Not set',
    notEmpty: 'Set',
    eq: 'Equal',
    notEq: 'Not equal',
    begins: 'Begins with',
    contains: 'Contains',
    notContains: 'Does not contain',
    eqN: '=',
    neqN: '!=',
    gt: '>',
    gte: '>=',
    lt: '<',
    lte: '<=',
};

// filter.plugin.tsx
const FILTER_TRIMMED_TYPE = 'filter';
const FILTER_CONFIG_CHANGED_EVENT = 'filterconfigchanged';
const FILTE_PANEL = 'revogr-filter-panel';
/**
 * @typedef ColumnFilterConfig
 * @type {object}
 *
 * @property {MultiFilterItem|undefined} multiFilterItems - data for multi filtering with relation
 *
 * @property {Record<ColumnProp, FilterCollectionItem>|undefined} collection - preserved filter data, relation for filters will be applied as 'and'
 *
 * @property {string[]|undefined} include - filters to be included, if defined everything else out of scope will be ignored
 *
 * @property {Record<string, CustomFilter>|undefined} customFilters - hash map of {FilterType:CustomFilter}.
 *
 * @property {FilterLocalization|undefined} localization - translation for filter popup captions.
 *
 * @property {boolean|undefined} disableDynamicFiltering - disables dynamic filtering. A way to apply filters on Save only.
 */
/**
 * @internal
 */
class FilterPlugin extends BasePlugin {
    constructor(revogrid, providers, config) {
        var _a;
        super(revogrid, providers);
        this.revogrid = revogrid;
        this.config = config;
        this.filterCollection = {};
        this.multiFilterItems = {};
        /**
         * Filter types
         * @example
         * {
         *    string: ['contains', 'beginswith'],
         *    number: ['eqN', 'neqN', 'gt']
         *  }
         */
        this.filterByType = Object.assign({}, filterTypes);
        this.filterNameIndexByType = Object.assign({}, filterNames);
        this.filterFunctionsIndexedByType = Object.assign({}, filterCoreFunctionsIndexedByType);
        this.filterProp = FILTER_PROP;
        if (config) {
            this.initConfig(config);
        }
        const existingNodes = this.revogrid.registerVNode.filter(n => typeof n === 'object' && n.$tag$ !== FILTE_PANEL);
        this.revogrid.registerVNode = [
            ...existingNodes,
            h("revogr-filter-panel", { filterNames: this.filterNameIndexByType, filterEntities: this.filterFunctionsIndexedByType, filterCaptions: (_a = config === null || config === void 0 ? void 0 : config.localization) === null || _a === void 0 ? void 0 : _a.captions, onFilterChange: e => this.onFilterChange(e.detail), onResetChange: e => this.onFilterReset(e.detail), disableDynamicFiltering: config === null || config === void 0 ? void 0 : config.disableDynamicFiltering, closeOnOutsideClick: config === null || config === void 0 ? void 0 : config.closeFilterPanelOnOutsideClick, ref: e => (this.pop = e) }, ' ', this.extraContent()),
        ];
        const aftersourceset = async () => {
            const filterCollectionProps = Object.keys(this.filterCollection);
            if (filterCollectionProps.length > 0) {
                // handle old way of filtering by reworking FilterCollection to new MultiFilterItem
                filterCollectionProps.forEach((prop, index) => {
                    if (!this.multiFilterItems[prop]) {
                        this.multiFilterItems[prop] = [
                            {
                                id: index,
                                type: this.filterCollection[prop].type,
                                value: this.filterCollection[prop].value,
                                relation: 'and',
                            },
                        ];
                    }
                });
            }
            if (Object.keys(this.multiFilterItems).length === 0) {
                return;
            }
            await timeout();
            await this.runFiltering(this.multiFilterItems);
        };
        this.addEventListener('headerclick', e => this.headerclick(e));
        this.addEventListener(FILTER_CONFIG_CHANGED_EVENT, ({ detail }) => {
            if (!detail ||
                (typeof detail === 'object' &&
                    (!detail.multiFilterItems ||
                        !Object.keys(detail.multiFilterItems).length))) {
                this.clearFiltering();
                return;
            }
            if (typeof detail === 'object') {
                this.initConfig(detail);
            }
            aftersourceset();
        });
        this.addEventListener('aftersourceset', aftersourceset);
        this.addEventListener('filter', ({ detail }) => this.onFilterChange(detail));
    }
    beforeshow(_) {
        // used as hook for filter panel
    }
    extraContent() {
        return null;
    }
    initConfig(config) {
        if (config.multiFilterItems) {
            this.multiFilterItems = Object.assign({}, config.multiFilterItems);
        }
        else {
            this.multiFilterItems = {};
        }
        // Add custom filters
        if (config.customFilters) {
            for (let customFilterType in config.customFilters) {
                const cFilter = config.customFilters[customFilterType];
                if (!this.filterByType[cFilter.columnFilterType]) {
                    this.filterByType[cFilter.columnFilterType] = [];
                }
                // add custom filter type
                this.filterByType[cFilter.columnFilterType].push(customFilterType);
                // add custom filter function
                this.filterFunctionsIndexedByType[customFilterType] = cFilter.func;
                // add custom filter name
                this.filterNameIndexByType[customFilterType] = cFilter.name;
            }
        }
        // Add filterProp if provided in config
        if (config.filterProp) {
            this.filterProp = config.filterProp;
        }
        /**
         * which filters has to be included/excluded
         * convenient way to exclude system filters
         */
        const cfgInlcude = config.include;
        if (cfgInlcude) {
            const filters = {};
            for (let t in this.filterByType) {
                // validate filters, if appropriate function present
                const newTypes = this.filterByType[t].filter(f => cfgInlcude.indexOf(f) > -1);
                if (newTypes.length) {
                    filters[t] = newTypes;
                }
            }
            // if any valid filters provided show them
            if (Object.keys(filters).length > 0) {
                this.filterByType = filters;
            }
        }
        if (config.collection) {
            const filterCollection = {};
            for (const prop of Object.keys(config.collection)) {
                const item = config.collection[prop];
                if (this.filterFunctionsIndexedByType[item.type]) {
                    filterCollection[prop] = item;
                }
            }
            this.filterCollection = filterCollection;
        }
        else {
            this.filterCollection = {};
        }
        if (config.localization) {
            if (config.localization.filterNames) {
                const filterNames = config.localization.filterNames;
                Object.keys(filterNames).forEach((k) => {
                    if (this.filterNameIndexByType[k] != void 0) {
                        this.filterNameIndexByType[k] = filterNames[k];
                    }
                });
            }
        }
    }
    async headerclick(e) {
        var _a, _b;
        const el = (_a = e.detail.originalEvent) === null || _a === void 0 ? void 0 : _a.target;
        const filterButton = isFilterBtn(el);
        if (!filterButton) {
            return;
        }
        e.preventDefault();
        if (!this.pop) {
            return;
        }
        const prop = e.detail.prop;
        const currentPanel = await this.pop.getChanges();
        if ((currentPanel === null || currentPanel === void 0 ? void 0 : currentPanel.prop) === prop) {
            await this.pop.show();
            return;
        }
        // filter button clicked, open filter dialog
        const buttonPos = (filterButton instanceof HTMLElement ? filterButton : el).getBoundingClientRect();
        const data = Object.assign(Object.assign(Object.assign({}, e.detail), this.filterCollection[prop]), { x: buttonPos.x, y: buttonPos.y + buttonPos.height, anchorY: buttonPos.y, autoCorrect: true, filterTypes: this.getColumnFilter(e.detail.filter), filterItems: this.multiFilterItems, extraContent: this.extraHyperContent, extraBottomContent: this.extraBottomHyperContent });
        (_b = this.beforeshow) === null || _b === void 0 ? void 0 : _b.call(this, data);
        this.pop.show(data);
    }
    getColumnFilter(type) {
        let filterType = 'string';
        if (!type) {
            return { [filterType]: this.filterByType[filterType] };
        }
        // if custom column filter
        if (this.isValidType(type)) {
            filterType = type;
            // if multiple filters applied
        }
        else if (typeof type === 'object' && type.length) {
            return type.reduce((r, multiType) => {
                if (this.isValidType(multiType)) {
                    r[multiType] = this.filterByType[multiType];
                }
                return r;
            }, {});
        }
        return { [filterType]: this.filterByType[filterType] };
    }
    isValidType(type) {
        return !!(typeof type === 'string' && this.filterByType[type]);
    }
    /**
     * Called on internal component change
     */
    async onFilterChange(filterItems) {
        // store the filter items
        this.multiFilterItems = filterItems;
        // run the filtering when the items change
        this.runFiltering(this.multiFilterItems);
    }
    onFilterReset(prop) {
        delete this.multiFilterItems[prop !== null && prop !== void 0 ? prop : ''];
        this.onFilterChange(this.multiFilterItems);
    }
    /**
     * Triggers grid filtering
     */
    async doFiltering(collection, source, columns, filterItems) {
        const columnsToUpdate = [];
        /**
         * Loop through the columns and update the columns that need to be updated with the `hasFilter` property.
         */
        const columnByProp = {};
        columns.forEach(rgCol => {
            const column = Object.assign({}, rgCol);
            const hasFilter = filterItems[column.prop];
            columnByProp[column.prop] = column;
            /**
             * If the column has a filter and it's not already marked as filtered, update the column.
             */
            if (column[this.filterProp] && !hasFilter) {
                delete column[this.filterProp];
                columnsToUpdate.push(column);
            }
            /**
             * If the column does not have a filter and it's marked as filtered, update the column.
             */
            if (!column[this.filterProp] && hasFilter) {
                columnsToUpdate.push(column);
                column[this.filterProp] = true;
            }
        });
        const itemsToTrim = this.getRowFilter(source, filterItems, columnByProp);
        // check is filter event prevented
        const { defaultPrevented, detail } = this.emit('beforefiltertrimmed', {
            collection,
            itemsToFilter: itemsToTrim,
            source,
            filterItems,
        });
        if (defaultPrevented) {
            return;
        }
        this.providers.data.setTrimmed({ [FILTER_TRIMMED_TYPE]: detail.itemsToFilter });
        // applies the hasFilter to the columns to show filter icon
        this.providers.column.updateColumns(columnsToUpdate);
        this.emit('afterfilterapply', {
            multiFilterItems: filterItems,
            source,
            collection,
        });
    }
    async clearFiltering() {
        this.multiFilterItems = {};
        await this.runFiltering(this.multiFilterItems);
    }
    async runFiltering(multiFilterItems) {
        const collection = {};
        // handle old filterCollection to return the first filter only (if any) from multiFilterItems
        const filterProps = Object.keys(multiFilterItems);
        for (const prop of filterProps) {
            // check if we have any filter for a column
            if (multiFilterItems[prop].length > 0) {
                const firstFilterItem = multiFilterItems[prop][0];
                collection[prop] = {
                    type: firstFilterItem.type,
                    value: firstFilterItem.value,
                };
            }
        }
        this.filterCollection = collection;
        const columns = this.providers.column.getColumns();
        // run the filtering on the main source only
        const source = this.providers.data.stores['rgRow'].store.get('source');
        const { defaultPrevented, detail } = this.emit('beforefilterapply', {
            collection: this.filterCollection,
            source,
            columns,
            filterItems: this.multiFilterItems,
        });
        if (defaultPrevented) {
            return;
        }
        this.doFiltering(detail.collection, detail.source, detail.columns, detail.filterItems);
    }
    /**
     * Get trimmed rows based on filter
     */
    getRowFilter(rows, filterItems, columnByProp) {
        const propKeys = Object.keys(filterItems);
        const trimmed = {};
        // each rows
        for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
            // check filter by column properties
            for (const prop of propKeys) {
                // add to the list of removed/trimmed rows of filter condition is satisfied
                if (this.shouldTrimRow(filterItems[prop], prop, columnByProp[prop], rows[rowIndex])) {
                    trimmed[rowIndex] = true;
                }
            } // end of for-of propKeys
        }
        return trimmed;
    }
    shouldTrimRow(propFilters, prop, column, model = {}) {
        // reset the count of satisfied filters
        let propFilterSatisfiedCount = 0;
        // reset the array of last filter results
        let lastFilterResults = [];
        // testing each filter for a prop
        for (const [filterIndex, filterData] of propFilters.entries()) {
            // the filter LogicFunction based on the type
            const filterFunc = this.filterFunctionsIndexedByType[filterData.type];
            // THE MAGIC OF FILTERING IS HERE
            // If there is no column but user wants to filter by a property
            const value = column ? getCellDataParsed(model, column) : model[prop];
            // OR relation
            if (filterData.relation === 'or') {
                // reset the array of last filter results
                lastFilterResults = [];
                // if the filter is satisfied, continue to the next filter
                if (filterFunc(value, filterData.value)) {
                    continue;
                }
                // if the filter is not satisfied, count it
                propFilterSatisfiedCount++;
                // AND relation
            }
            else {
                // 'and' relation will need to know the next filter
                // so we save this current filter to include it in the next filter
                lastFilterResults.push(!filterFunc(value, filterData.value));
                if (isFinalAndFilter(filterIndex, propFilters)) {
                    // let's just continue since for sure propFilterSatisfiedCount cannot be satisfied
                    if (allAndConditionsSatisfied(lastFilterResults)) {
                        // reset the array of last filter results
                        lastFilterResults = [];
                        continue;
                    }
                    // we need to add all of the lastFilterResults since we need to satisfy all
                    propFilterSatisfiedCount += lastFilterResults.length;
                    // reset the array of last filter results
                    lastFilterResults = [];
                }
            }
        } // end of propFilters forEach
        return propFilterSatisfiedCount === propFilters.length;
    }
}
/**
 * Checks if the current filter is the final one in an AND sequence.
 * @param index - Current filter index in the list.
 * @param filters - Array of filters for the property.
 * @returns True if this is the last AND condition; false otherwise.
 */
function isFinalAndFilter(index, filters) {
    const nextFilter = filters[index + 1]; // Get the next filter in the list.
    // Return true if there's no next filter or if the next filter defined and is not part of the AND sequence.
    return !nextFilter || (!!nextFilter.relation && nextFilter.relation !== 'and');
}
/**
 * Determines if all conditions in an AND sequence are satisfied.
 * @param pendingResults - An array of results from the AND conditions.
 * @returns True if all conditions are satisfied; false otherwise.
 */
function allAndConditionsSatisfied(pendingResults) {
    // Check if there are any failed conditions in the pending results.
    return !pendingResults.includes(true);
}

/**
 * Checks whether a sorting map contains at least one active order.
 *
 * Empty maps and properties with `undefined` order are treated as inactive.
 */
function hasActiveSorting(sorting) {
    for (const prop of Object.keys(sorting || {})) {
        if (sorting === null || sorting === void 0 ? void 0 : sorting[prop]) {
            return true;
        }
    }
    return false;
}
/**
 * Compares column properties after object-key coercion.
 */
function isSameColumnProp(a, b) {
    return String(a) === String(b);
}
/**
 * Returns active sorting properties in explicit priority order.
 */
function getActiveSortingProps(sorting, sortingOrder) {
    const activeProps = [];
    const add = (prop) => {
        if ((sorting === null || sorting === void 0 ? void 0 : sorting[prop]) && !activeProps.some(active => isSameColumnProp(active, prop))) {
            activeProps.push(prop);
        }
    };
    sortingOrder === null || sortingOrder === void 0 ? void 0 : sortingOrder.forEach(add);
    Object.keys(sorting || {}).forEach(add);
    return activeProps;
}
/**
 * Returns one-based additive sorting rank for a column.
 *
 * A single active sort does not need a visible rank, so it returns undefined.
 */
function getSortingIndex(sorting, prop, sortingOrder) {
    const activeProps = getActiveSortingProps(sorting, sortingOrder);
    if (activeProps.length <= 1) {
        return undefined;
    }
    const index = activeProps.findIndex(active => isSameColumnProp(active, prop));
    return index >= 0 ? index + 1 : undefined;
}
/**
 * Collects only active comparator functions from a sorting function map.
 *
 * This keeps undefined comparator entries from triggering sorting work.
 */
function activeSortingEntries(sortingFunc = {}, sortingOrder) {
    const entries = [];
    const add = (prop) => {
        const cmp = sortingFunc[prop];
        if (typeof cmp === 'function' && !entries.some(([active]) => isSameColumnProp(active, prop))) {
            entries.push([prop, cmp]);
        }
    };
    sortingOrder === null || sortingOrder === void 0 ? void 0 : sortingOrder.forEach(add);
    Object.keys(sortingFunc).forEach(add);
    return entries;
}
/**
 * Reads and normalizes a value for the built-in default comparer.
 */
function getDefaultCompareValue(item, prop, column) {
    const aRaw = column ? getCellRaw(item, column) : item === null || item === void 0 ? void 0 : item[prop];
    return typeof aRaw === 'number' ? aRaw : aRaw === null || aRaw === void 0 ? void 0 : aRaw.toString().toLowerCase();
}
function isEmptyCompareValue(value) {
    return value === '' || value === null || value === undefined;
}
/**
 * Compares two already-normalized default comparer values.
 */
function compareValues(av, bv) {
    if (av === bv) {
        return 0;
    }
    const aEmpty = isEmptyCompareValue(av);
    const bEmpty = isEmptyCompareValue(bv);
    if (aEmpty || bEmpty) {
        if (aEmpty && bEmpty) {
            return 0;
        }
        return aEmpty ? -1 : 1;
    }
    if (av > bv) {
        return 1;
    }
    return -1;
}
/**
 * Sorts indexes by precomputed values for default column comparers.
 *
 * This avoids repeatedly parsing the same cell value during large default
 * sorts while preserving normal multi-column ordering.
 */
function sortIndexByDefaultComparers(indexes, source, entries, sorting, sortingColumns) {
    const prepared = entries.map(([prop]) => {
        const values = [];
        const column = sortingColumns[prop];
        for (const index of indexes) {
            values[index] = getDefaultCompareValue(source[index], prop, column);
        }
        return {
            order: sorting[prop],
            values,
        };
    });
    return indexes.sort((a, b) => {
        for (const { order, values } of prepared) {
            const sorted = compareValues(values[a], values[b]);
            if (sorted) {
                return order === 'desc' ? -sorted : sorted;
            }
        }
        return 0;
    });
}
/**
 * Detects whether the optimized default-comparer path can be used.
 *
 * Grouped rows and custom `cellCompare` functions stay on the legacy
 * comparator path to preserve their exact behavior.
 */
function canUseDefaultCompareFastPath(entries, indexes, source, sorting, sortingColumns) {
    return !indexes.some(index => isGrouping(source[index])) && !!sorting && !!sortingColumns && entries.every(([prop]) => {
        const order = sorting[prop];
        const column = sortingColumns[prop];
        return !!order && !(column === null || column === void 0 ? void 0 : column.cellCompare);
    });
}
/**
 * Group placeholder rows are generated for their grouping column. If sorting is
 * requested for another column, the grouped source must be unwrapped first.
 */
function hasGroupingRowsForOtherSorting(entries, indexes, source) {
    return indexes.some(index => {
        const item = source[index];
        return isGrouping(item) && !entries.some(([prop]) => isSameColumnProp(item[GROUP_COLUMN_PROP], prop));
    });
}
/**
 * Sorts row indexes against a source collection.
 *
 * @param indexes - Current proxy row indexes to sort.
 * @param source - Full source collection addressed by the indexes.
 * @param sortingFunc - Comparator functions by column property.
 * @param sorting - Active sorting order by column property.
 * @param sortingColumns - Column metadata by property for default-comparer optimization.
 * @param sortingOrder - Active sorting priority in click/config insertion order.
 * @returns Sorted proxy indexes. With no sorting function keys, returns source-order indexes.
 */
function sortIndexByItems(indexes, source, sortingFunc = {}, sorting, sortingColumns, sortingOrder) {
    const hasSortingKeys = Object.keys(sortingFunc).length > 0;
    const sortingEntries = activeSortingEntries(sortingFunc, sortingOrder);
    // if no sorting - return unsorted indexes
    if (sortingEntries.length === 0) {
        // Unsorted indexes
        return hasSortingKeys ? indexes : [...new Array(indexes.length).keys()];
    }
    if (hasGroupingRowsForOtherSorting(sortingEntries, indexes, source)) {
        return indexes;
    }
    if (canUseDefaultCompareFastPath(sortingEntries, indexes, source, sorting, sortingColumns)) {
        return sortIndexByDefaultComparers(indexes, source, sortingEntries, sorting, sortingColumns);
    }
    //
    /**
     * go through all indexes and align in new order
     * performs a multi-level sorting by applying multiple comparison functions to determine the order of the items based on different properties.
     */
    return indexes.sort((a, b) => {
        const itemA = source[a];
        const itemB = source[b];
        for (const [prop, cmp] of sortingEntries) {
            if (isGrouping(itemA)) {
                if (!isSameColumnProp(itemA[GROUP_COLUMN_PROP], prop)) {
                    return a - b;
                }
            }
            if (isGrouping(itemB)) {
                if (!isSameColumnProp(itemB[GROUP_COLUMN_PROP], prop)) {
                    return a - b;
                }
            }
            /**
             * If the comparison function returns a non-zero value (sorted), it means that the items should be sorted based on the given property. In such a case, the function immediately returns the sorted value, indicating the order in which the items should be arranged.
             * If none of the comparison functions result in a non-zero value, indicating that the items are equal or should remain in the same order, the function eventually returns 0.
             */
            const sorted = cmp === null || cmp === void 0 ? void 0 : cmp(prop, itemA, itemB);
            if (sorted) {
                return sorted;
            }
        }
        return 0;
    });
}
function defaultCellCompare(prop, a, b) {
    const aRaw = this.column ? getCellRaw(a, this.column) : a === null || a === void 0 ? void 0 : a[prop];
    const bRaw = this.column ? getCellRaw(b, this.column) : b === null || b === void 0 ? void 0 : b[prop];
    const av = typeof aRaw === 'number' ? aRaw : aRaw === null || aRaw === void 0 ? void 0 : aRaw.toString().toLowerCase();
    const bv = typeof bRaw === 'number' ? bRaw : bRaw === null || bRaw === void 0 ? void 0 : bRaw.toString().toLowerCase();
    return compareValues(av, bv);
}
function descCellCompare(cmp) {
    return (prop, a, b) => {
        return -1 * cmp(prop, a, b);
    };
}
function getNextOrder(currentOrder) {
    switch (currentOrder) {
        case undefined:
            return 'asc';
        case 'asc':
            return 'desc';
        case 'desc':
            return undefined;
    }
}
function getComparer(column, order) {
    var _a;
    const cellCmp = ((_a = column === null || column === void 0 ? void 0 : column.cellCompare) === null || _a === void 0 ? void 0 : _a.bind({ order })) || (defaultCellCompare === null || defaultCellCompare === void 0 ? void 0 : defaultCellCompare.bind({ column, order }));
    if (order == 'asc') {
        return cellCmp;
    }
    if (order == 'desc') {
        return descCellCompare(cellCmp);
    }
    return undefined;
}

function getSortableRowIndexes(indexes, source) {
    return indexes.filter(index => !isGrouping(source[index]));
}
function mergeSortedRowsWithGroups(indexes, source, sortedRows) {
    if (sortedRows.length === indexes.length) {
        return sortedRows;
    }
    let rowIndex = 0;
    return indexes.map(index => {
        if (isGrouping(source[index])) {
            return index;
        }
        return sortedRows[rowIndex++];
    });
}
/**
 * Lifecycle
 * 1. @event `beforesorting` - Triggered when sorting just starts. Nothing has happened yet. This can be triggered from a column or from the source. If the type is from rows, the column will be undefined.
 * 2. @event `beforesourcesortingapply` - Triggered before the sorting data is applied to the data source. You can prevent this event, and the data will not be sorted.
 * 3. @event `beforesortingapply` - Triggered before the sorting data is applied to the data source. You can prevent this event, and the data will not be sorted. This event is only called from a column sorting click.
 * 4. @event `aftersortingapply` - Triggered after sorting has been applied and completed. The event detail includes the final sorting state and sorting column metadata when available.
 *
 * Note: If you prevent an event, it will not proceed to the subsequent steps.
 */
class SortingPlugin extends BasePlugin {
    constructor(revogrid, providers, config) {
        super(revogrid, providers);
        this.revogrid = revogrid;
        /**
         * Delayed sorting promise registered in the grid render job queue.
         */
        this.sortingPromise = null;
        /**
         * Debounced sorting entry point.
         *
         * Sorting can be requested by column changes, source changes, and header
         * clicks in quick succession, so the actual sort is delayed and coalesced.
         */
        this.postponeSort = debounce((order, comparison, sortingColumns, sortingOrder, ignoreViewportUpdate) => this.runSorting(order, comparison, sortingColumns, sortingOrder, ignoreViewportUpdate), 50);
        this.applySortingConfig(config);
        this.addEventListener('sortingconfigchanged', ({ detail }) => {
            config = detail;
            this.applySortingConfig(detail);
            this.startSorting(this.sorting, this.sortingFunc, this.sortingColumns, this.sortingOrder);
        });
        this.addEventListener('beforeheaderrender', ({ detail, }) => {
            var _a;
            const { data: column } = detail;
            if (column.sortable) {
                detail.data = Object.assign(Object.assign({}, column), { order: (_a = this.sorting) === null || _a === void 0 ? void 0 : _a[column.prop], sortIndex: getSortingIndex(this.sorting, column.prop, this.sortingOrder) });
            }
        });
        this.addEventListener('beforeanysource', ({ detail: { type }, }) => {
            // if sorting was provided - sort data
            if (hasActiveSorting(this.sorting) && this.sortingFunc) {
                const event = this.emit('beforesourcesortingapply', { type, sorting: this.sorting });
                if (event.defaultPrevented) {
                    return;
                }
                this.startSorting(this.sorting, this.sortingFunc, this.sortingColumns, this.sortingOrder);
            }
        });
        this.addEventListener('aftercolumnsset', ({ detail: { order }, }) => {
            // if config provided - do nothing, read from config
            if (config) {
                return;
            }
            const columns = this.providers.column.getColumns();
            const sortingFunc = {};
            const sortingColumns = {};
            const sortingOrder = [];
            const sorting = {};
            for (let prop in order) {
                if (order[prop]) {
                    const column = getColumnByProp(columns, prop);
                    const cmp = getComparer(column, order[prop]);
                    sorting[prop] = order[prop];
                    sortingFunc[prop] = cmp;
                    sortingColumns[prop] = column;
                    sortingOrder.push(prop);
                }
            }
            // set sorting
            this.sorting = hasActiveSorting(sorting) ? sorting : undefined;
            this.sortingFunc = this.sorting ? sortingFunc : undefined;
            this.sortingColumns = this.sorting ? sortingColumns : undefined;
            this.sortingOrder = this.sorting ? sortingOrder : undefined;
        });
        this.addEventListener('beforeheaderclick', (e) => {
            var _a, _b, _c, _d;
            if (e.defaultPrevented) {
                return;
            }
            if (!((_b = (_a = e.detail) === null || _a === void 0 ? void 0 : _a.column) === null || _b === void 0 ? void 0 : _b.sortable)) {
                return;
            }
            this.headerclick(e.detail.column, (_d = (_c = e.detail) === null || _c === void 0 ? void 0 : _c.originalEvent) === null || _d === void 0 ? void 0 : _d.shiftKey);
        });
    }
    /**
     * Creates mutable sorting maps from current state when additive sorting is requested.
     */
    createSortingState(additive) {
        var _a;
        return {
            sorting: additive ? Object.assign({}, this.sorting) : {},
            sortingFunc: additive ? Object.assign({}, this.sortingFunc) : {},
            sortingColumns: additive ? Object.assign({}, this.sortingColumns) : {},
            sortingOrder: additive ? [...((_a = this.sortingOrder) !== null && _a !== void 0 ? _a : [])] : [],
        };
    }
    /**
     * Stores normalized sorting state, clearing inactive empty maps.
     */
    setSortingState({ sorting, sortingFunc, sortingColumns, sortingOrder, }) {
        this.sorting = hasActiveSorting(sorting) ? sorting : undefined;
        this.sortingFunc = this.sorting ? sortingFunc : undefined;
        this.sortingColumns = this.sorting ? sortingColumns : undefined;
        this.sortingOrder = this.sorting ? sortingOrder : undefined;
    }
    /**
     * Adds or replaces a column in a sorting state.
     */
    setColumnSorting(state, prop, order, cmp, column) {
        state.sorting[prop] = order;
        state.sortingFunc[prop] = cmp;
        state.sortingColumns[prop] = column;
        if (!state.sortingOrder.some(sortingProp => String(sortingProp) === String(prop))) {
            state.sortingOrder.push(prop);
        }
    }
    /**
     * Removes a column from a sorting state.
     */
    clearColumnSorting(state, prop) {
        delete state.sorting[prop];
        delete state.sortingFunc[prop];
        delete state.sortingColumns[prop];
        const index = state.sortingOrder.findIndex(sortingProp => String(sortingProp) === String(prop));
        if (index >= 0) {
            state.sortingOrder.splice(index, 1);
        }
    }
    /**
     * Normalizes external sorting configuration into internal order,
     * comparator, and column metadata maps.
     */
    applySortingConfig(cfg) {
        var _a;
        if (!cfg) {
            return;
        }
        const state = this.createSortingState(cfg.additive);
        (_a = cfg.columns) === null || _a === void 0 ? void 0 : _a.forEach(col => {
            if (col.order) {
                this.setColumnSorting(state, col.prop, col.order, getComparer(col, col.order), col);
                return;
            }
            this.clearColumnSorting(state, col.prop);
        });
        this.setSortingState(state);
    }
    resetSortingForStore(type) {
        const storeService = this.providers.data.stores[type];
        // row data
        const source = storeService.store.get('source');
        // row indexes
        const proxyItems = storeService.store.get('proxyItems');
        // row indexes
        const newItemsOrder = Array.from({ length: source.length }, (_, i) => i); // recover indexes range(0, source.length)
        this.providers.dimension.updateSizesPositionByNewDataIndexes(type, newItemsOrder, proxyItems);
        storeService.setData({ proxyItems: newItemsOrder });
    }
    applySortingForStore(type, sorting, sortingFunc, sortingColumns, sortingOrder, ignoreViewportUpdate) {
        const storeService = this.providers.data.stores[type];
        // row data
        const source = storeService.store.get('source');
        // row indexes
        const proxyItems = storeService.store.get('proxyItems');
        const sortItems = getSortableRowIndexes(proxyItems, source);
        const sortedItems = sortIndexByItems([...sortItems], source, sortingFunc, sorting, sortingColumns, sortingOrder);
        const newItemsOrder = mergeSortedRowsWithGroups(proxyItems, source, sortedItems);
        // take row indexes before trim applied and proxy items
        const prevItems = storeService.store.get('items');
        storeService.setData({
            proxyItems: newItemsOrder,
        });
        // take currently visible row indexes
        const newItems = storeService.store.get('items');
        if (!ignoreViewportUpdate) {
            this.providers.dimension
                .updateSizesPositionByNewDataIndexes(type, newItems, prevItems);
        }
    }
    startSorting(order, sortingFunc, sortingColumns, sortingOrder, ignoreViewportUpdate) {
        if (!this.sortingPromise) {
            // add job before render
            this.revogrid.jobsBeforeRender.push(new Promise(resolve => {
                this.sortingPromise = resolve;
            }));
        }
        if (typeof sortingColumns === 'boolean') {
            this.postponeSort(order, sortingFunc, undefined, undefined, sortingColumns);
            return;
        }
        this.postponeSort(order, sortingFunc, sortingColumns, sortingOrder, ignoreViewportUpdate);
    }
    /**
     * Applies sorting requested by a sortable header click.
     *
     * @param column - Column that initiated sorting.
     * @param additive - If true, add/remove this column from the current multi-sort state.
     */
    headerclick(column, additive) {
        var _a;
        const columnProp = column.prop;
        let order = getNextOrder((_a = this.sorting) === null || _a === void 0 ? void 0 : _a[columnProp]);
        const beforeEvent = this.emit('beforesorting', { column, order, additive });
        if (beforeEvent.defaultPrevented) {
            return;
        }
        order = beforeEvent.detail.order;
        // apply sort data
        const beforeApplyEvent = this.emit('beforesortingapply', {
            column: beforeEvent.detail.column,
            order,
            additive,
        });
        if (beforeApplyEvent.defaultPrevented) {
            return;
        }
        const cmp = getComparer(beforeApplyEvent.detail.column, beforeApplyEvent.detail.order);
        this.applyHeaderSorting(beforeApplyEvent.detail.column, beforeApplyEvent.detail.additive, order, cmp);
        this.startSorting(this.sorting, this.sortingFunc, this.sortingColumns, this.sortingOrder);
    }
    /**
     * Applies sorting state produced by a header click.
     */
    applyHeaderSorting(column, additive, order, cmp) {
        if (!additive) {
            this.setSortingState(order ? {
                sorting: { [column.prop]: order },
                sortingFunc: { [column.prop]: cmp },
                sortingColumns: { [column.prop]: column },
                sortingOrder: [column.prop],
            } : this.createSortingState());
            return;
        }
        const state = this.createSortingState(true);
        if (order) {
            this.setColumnSorting(state, column.prop, order, cmp, column);
        }
        else {
            this.clearColumnSorting(state, column.prop);
        }
        this.setSortingState(state);
    }
    runSorting(order, comparison, sortingColumns, sortingOrder, ignoreViewportUpdate) {
        var _a, _b;
        if (typeof sortingColumns === 'boolean') {
            this.sort(order, comparison, undefined, undefined, undefined, sortingColumns);
            (_a = this.sortingPromise) === null || _a === void 0 ? void 0 : _a.call(this);
            this.sortingPromise = null;
            return;
        }
        this.sort(order, comparison, sortingColumns, sortingOrder, undefined, ignoreViewportUpdate);
        (_b = this.sortingPromise) === null || _b === void 0 ? void 0 : _b.call(this);
        this.sortingPromise = null;
    }
    sort(sorting, sortingFunc, sortingColumns, sortingOrder, types = rowTypes, ignoreViewportUpdate = false) {
        let activeSortingColumns;
        let activeSortingOrder;
        let activeTypes = types;
        let activeIgnoreViewportUpdate = ignoreViewportUpdate;
        if (Array.isArray(sortingColumns)) {
            activeTypes = sortingColumns;
            activeIgnoreViewportUpdate = typeof sortingOrder === 'boolean' ? sortingOrder : false;
        }
        else {
            activeSortingColumns = sortingColumns;
            activeSortingOrder = Array.isArray(sortingOrder) ? sortingOrder : undefined;
        }
        // if no sorting - reset
        if (!Object.keys(sorting || {}).length) {
            for (let type of activeTypes) {
                this.resetSortingForStore(type);
            }
        }
        else {
            for (let type of activeTypes) {
                this.applySortingForStore(type, sorting, sortingFunc, activeSortingColumns, activeSortingOrder, activeIgnoreViewportUpdate);
            }
        }
        // refresh columns to redraw column headers and show correct icon
        columnTypes.forEach((type) => {
            this.providers.column.dataSources[type].refresh();
        });
        const afterSortingDetail = {
            sorting: hasActiveSorting(sorting) ? sorting : undefined,
            sortingColumns: activeSortingColumns,
            sortingOrder: activeSortingOrder,
            types: activeTypes,
        };
        this.emit('aftersortingapply', afterSortingDetail);
    }
}

// provide collapse data
function doCollapse(pIndex, source) {
    const model = source[pIndex];
    const collapseValue = model[PSEUDO_GROUP_ITEM_VALUE];
    const trimmed = {};
    let i = pIndex + 1;
    const total = source.length;
    while (i < total) {
        const currentModel = source[i];
        if (isGrouping(currentModel)) {
            const currentValue = currentModel[PSEUDO_GROUP_ITEM_VALUE];
            if (!currentValue.length || !currentValue.startsWith(collapseValue + ',')) {
                break;
            }
            currentModel[GROUP_EXPANDED] = false;
        }
        trimmed[i++] = true;
    }
    model[GROUP_EXPANDED] = false;
    return { trimmed };
}
/**
 *
 * @param pIndex - physical index
 * @param vIndex - virtual index, need to update item collection
 * @param source - data source
 * @param rowItemsIndexes - rgRow indexes
 */
function doExpand(vIndex, source, rowItemsIndexes) {
    const physicalIndex = rowItemsIndexes[vIndex];
    const model = source[physicalIndex];
    const currentGroup = getParsedGroup(model[PSEUDO_GROUP_ITEM_ID]);
    const trimmed = {};
    // no group found
    if (!currentGroup) {
        return { trimmed };
    }
    const groupItems = [];
    model[GROUP_EXPANDED] = true;
    let i = physicalIndex + 1;
    const total = source.length;
    let groupLevelOnly = 0;
    // go through all rows
    while (i < total) {
        const currentModel = source[i];
        const isGroup = isGrouping(currentModel);
        // group found
        if (isGroup) {
            if (!isSameGroup(currentGroup, model, currentModel)) {
                break;
            }
            else if (!groupLevelOnly) {
                // if get group first it's group only level
                groupLevelOnly = currentModel[GROUP_DEPTH];
            }
        }
        // level 0 or same depth
        if (!groupLevelOnly || (isGroup && groupLevelOnly === currentModel[GROUP_DEPTH])) {
            trimmed[i] = false;
            groupItems.push(i);
        }
        i++;
    }
    const result = {
        trimmed,
    };
    if (groupItems.length) {
        const items = [...rowItemsIndexes];
        items.splice(vIndex + 1, 0, ...groupItems);
        result.items = items;
    }
    return result;
}

const TRIMMED_GROUPING = 'grouping';
/**
 * Converts a trim row index through the index maps produced while regrouping.
 *
 * Group rows are synthetic, so they may not exist in the first map. When a
 * second map is available, fall back to the original index so trims created
 * against the grouped physical source can still be remapped. If neither path
 * resolves to a number, the caller drops the stale trim entry.
 */
function convertTrimmedIndex(initialIndex, firstLevelMap, secondLevelMap) {
    const sourceIndex = Number.parseInt(initialIndex, 10);
    const firstConversionIndex = firstLevelMap[sourceIndex];
    if (!secondLevelMap) {
        return firstConversionIndex;
    }
    const secondConversionKey = typeof firstConversionIndex === 'number' ? firstConversionIndex : sourceIndex;
    return secondLevelMap[secondConversionKey];
}
/**
 * Prepare trimming updated indexes for grouping
 * @param initiallyTrimed
 * @param firstLevelMap
 * @param secondLevelMap
 */
function processDoubleConversionTrimmed(initiallyTrimed, firstLevelMap, secondLevelMap) {
    const trimemedOptionsToUpgrade = {};
    /**
     * go through all groups except grouping
     */
    for (let type in initiallyTrimed) {
        if (type === TRIMMED_GROUPING) {
            continue;
        }
        const items = initiallyTrimed[type];
        const newItems = {};
        for (let initialIndex in items) {
            if (!items[initialIndex]) {
                continue;
            }
            /**
             * if item exists we find it in collection
             * we support 2 level of conversions
             */
            const newConversionIndex = convertTrimmedIndex(initialIndex, firstLevelMap, secondLevelMap);
            // Group rows do not exist in the ungrouped index map and must not leak into new trims.
            if (typeof newConversionIndex !== 'number') {
                continue;
            }
            /**
             * if item was trimmed previously
             * trimming makes sense to apply
             */
            newItems[newConversionIndex] = true;
        }
        trimemedOptionsToUpgrade[type] = newItems;
    }
    return trimemedOptionsToUpgrade;
}
function hasVisibleGroupItems(source, trimmed, groupIndex) {
    var _a;
    const depth = (_a = source[groupIndex]) === null || _a === void 0 ? void 0 : _a[GROUP_DEPTH];
    if (depth == null) {
        return false;
    }
    // A group is visible when at least one descendant data row survives filtering.
    for (let i = groupIndex + 1; i < source.length; i++) {
        const model = source[i];
        if (isGrouping(model)) {
            if (model[GROUP_DEPTH] <= depth) {
                break;
            }
            continue;
        }
        if (!trimmed[i]) {
            return true;
        }
    }
    return false;
}
/**
 * Preserves data-row filter results and recalculates group-row visibility
 * from the filtered state of each group's descendant data rows.
 *
 * @param source - Grouped row source that contains group rows and data rows.
 * @param filterTrimmed - Current filter trim map keyed by physical row index.
 * @returns Filter trim map with empty group rows hidden and matching group rows visible.
 */
function filterOutEmptyGroupRows(source, filterTrimmed) {
    const trimmed = Object.assign({}, filterTrimmed);
    // Recalculate only group rows; data-row filter results are preserved as-is.
    source.forEach((model, index) => {
        if (!isGrouping(model)) {
            return;
        }
        if (hasVisibleGroupItems(source, trimmed, index)) {
            delete trimmed[index];
        }
        else {
            trimmed[index] = true;
        }
    });
    return trimmed;
}

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
class GroupingRowPlugin extends BasePlugin {
    getStore(type = GROUPING_ROW_TYPE) {
        return this.providers.data.stores[type].store;
    }
    constructor(revogrid, providers) {
        super(revogrid, providers);
    }
    // befoce cell focus
    onFocus(e) {
        if (isGrouping(e.detail.model)) {
            e.preventDefault();
        }
    }
    // expand event triggered
    onExpand({ virtualIndex }) {
        const { source } = getSource(this.getStore().get('source'), this.getStore().get('proxyItems'));
        let newTrimmed = this.getStore().get('trimmed')[TRIMMED_GROUPING];
        let i = getPhysical(this.getStore(), virtualIndex);
        const isExpanded = getExpanded(source[i]);
        if (!isExpanded) {
            const { trimmed, items } = doExpand(virtualIndex, source, this.getStore().get('items'));
            newTrimmed = Object.assign(Object.assign({}, newTrimmed), trimmed);
            if (items) {
                setItems(this.getStore(), items);
            }
        }
        else {
            const { trimmed } = doCollapse(i, source);
            newTrimmed = Object.assign(Object.assign({}, newTrimmed), trimmed);
            this.revogrid.clearFocus();
        }
        this.getStore().set('source', source);
        this.revogrid.addTrimmed(newTrimmed, TRIMMED_GROUPING);
    }
    setColumnGrouping(cols) {
        // if 0 column as holder
        if (cols === null || cols === void 0 ? void 0 : cols.length) {
            cols[0][PSEUDO_GROUP_COLUMN] = true;
            return true;
        }
        return false;
    }
    setColumns({ columns }) {
        for (let type of columnTypes) {
            if (this.setColumnGrouping(columns[type])) {
                break;
            }
        }
    }
    // evaluate drag between groups
    onDrag(e) {
        const { from, to } = e.detail;
        const isDown = to - from >= 0;
        const { source } = getSource(this.getStore().get('source'), this.getStore().get('proxyItems'));
        const items = this.getStore().get('items');
        let i = isDown ? from : to;
        const end = isDown ? to : from;
        for (; i < end; i++) {
            const model = source[items[i]];
            const isGroup = isGrouping(model);
            if (isGroup) {
                e.preventDefault();
                return;
            }
        }
    }
    beforeTrimmedApply(trimmed, type) {
        /** Filter trim must keep group headers in sync with their visible children. */
        if (type === FILTER_TRIMMED_TYPE) {
            const source = this.getStore().get('source');
            const updatedTrimmed = filterOutEmptyGroupRows(source, trimmed);
            Object.keys(trimmed).forEach(index => delete trimmed[Number.parseInt(index, 10)]);
            Object.assign(trimmed, updatedTrimmed);
        }
    }
    beforeFilterTrimmed(trimmed) {
        const source = this.getStore().get('source');
        return filterOutEmptyGroupRows(source, trimmed);
    }
    isSortingRunning() {
        const sortingPlugin = this.providers.plugins.getByClass(SortingPlugin);
        return !!(sortingPlugin === null || sortingPlugin === void 0 ? void 0 : sortingPlugin.sortingPromise);
    }
    /**
     * Returns grouping options for regrouping that must preserve current UI state.
     *
     * `expandedAll` and config `prevExpanded` are initial/config instructions.
     * Reusing them after sorting would reopen groups the user collapsed before
     * sorting instead of using the current grouped source state.
     */
    getCurrentExpandedOptions() {
        var _a;
        const _b = (_a = this.options) !== null && _a !== void 0 ? _a : {}, options = __rest(_b, ["expandedAll", "prevExpanded"]);
        return options;
    }
    /**
     * Starts global source update with group clearing and applying new one
     * Initiated when need to reapply grouping
     */
    doSourceUpdate(options) {
        var _a;
        /**
         * Get source without grouping
         * @param newOldIndexMap - provides us mapping with new indexes vs old indexes, we would use it for trimmed mapping
         */
        const store = this.getStore();
        const { source, prevExpanded, oldNewIndexes } = getSource(store.get('source'), store.get('proxyItems'), true);
        const expanded = Object.assign({ prevExpanded }, options);
        /**
         * Group again
         * @param oldNewIndexMap - provides us mapping with new indexes vs old indexes
         */
        const { sourceWithGroups, depth, trimmed, oldNewIndexMap, } = gatherGrouping(source, ((_a = this.options) === null || _a === void 0 ? void 0 : _a.props) || [], expanded);
        const customRenderer = options === null || options === void 0 ? void 0 : options.groupLabelTemplate;
        // setup source
        this.providers.data.setData(sourceWithGroups, GROUPING_ROW_TYPE, this.revogrid.disableVirtualY, { depth, customRenderer }, true);
        this.updateTrimmed(trimmed, oldNewIndexes !== null && oldNewIndexes !== void 0 ? oldNewIndexes : {}, oldNewIndexMap, sourceWithGroups);
    }
    /**
     * Apply grouping on data set
     * Clear grouping from source
     * If source came from other plugin
     */
    onDataSet(data) {
        var _a, _b;
        let preservedExpanded = {};
        if (((_a = this.options) === null || _a === void 0 ? void 0 : _a.preserveGroupingOnUpdate) !== false) {
            let { prevExpanded } = getSource(this.getStore().get('source'), this.getStore().get('proxyItems'), true);
            preservedExpanded = prevExpanded;
        }
        const source = data.source.filter(s => !isGrouping(s));
        const options = Object.assign(Object.assign({}, (this.revogrid.grouping || {})), { prevExpanded: preservedExpanded });
        const { sourceWithGroups, depth, trimmed, oldNewIndexMap, } = gatherGrouping(source, ((_b = this.options) === null || _b === void 0 ? void 0 : _b.props) || [], options);
        data.source = sourceWithGroups;
        this.providers.data.setGrouping({ depth });
        this.updateTrimmed(trimmed, oldNewIndexMap, undefined, sourceWithGroups);
    }
    /**
     * External call to apply grouping. Called by revogrid when prop changed.
     */
    setGrouping(options) {
        var _a, _b;
        // unsubscribe from all events when group applied
        this.clearSubscriptions();
        this.options = options;
        // clear props, no grouping exists
        if (!((_b = (_a = this.options) === null || _a === void 0 ? void 0 : _a.props) === null || _b === void 0 ? void 0 : _b.length)) {
            this.clearGrouping();
            return;
        }
        // props exist and source initd
        const store = this.getStore();
        const { source } = getSource(store.get('source'), store.get('proxyItems'));
        if (source.length) {
            this.doSourceUpdate(Object.assign({}, options));
        }
        // props exist and columns initd
        for (let t of columnTypes) {
            if (this.setColumnGrouping(this.providers.column.getColumns(t))) {
                this.providers.column.refreshByType(t);
                break;
            }
        }
        // if has any grouping subscribe to events again
        /** if grouping present and new data source arrived */
        this.addEventListener('beforesourceset', ({ detail }) => {
            var _a, _b, _c;
            if (!(((_b = (_a = this.options) === null || _a === void 0 ? void 0 : _a.props) === null || _b === void 0 ? void 0 : _b.length) && ((_c = detail === null || detail === void 0 ? void 0 : detail.source) === null || _c === void 0 ? void 0 : _c.length))) {
                return;
            }
            // if sorting is running don't apply grouping, wait for sorting, then it'll apply in @aftersortingapply
            if (this.isSortingRunning()) {
                return;
            }
            this.onDataSet(detail);
        });
        this.addEventListener('beforecolumnsset', ({ detail }) => {
            this.setColumns(detail);
        });
        /**
         * filter applied need to clear grouping and apply again
         * based on new results can be new grouping
         */
        this.addEventListener('beforetrimmed', ({ detail: { trimmed, trimmedType } }) => this.beforeTrimmedApply(trimmed, trimmedType));
        /** Filter plugin owns data-row matching; grouping decides which headers remain visible. */
        this.addEventListener('beforefiltertrimmed', ({ detail }) => {
            detail.itemsToFilter = this.beforeFilterTrimmed(detail.itemsToFilter);
        });
        /**
         * sorting applied need to clear grouping and apply again
         * based on new results whole grouping order will changed
         */
        this.addEventListener('aftersortingapply', () => {
            var _a, _b;
            if (!((_b = (_a = this.options) === null || _a === void 0 ? void 0 : _a.props) === null || _b === void 0 ? void 0 : _b.length)) {
                return;
            }
            this.doSourceUpdate(this.getCurrentExpandedOptions());
        });
        /**
         * Apply logic for focus inside of grouping
         * We can't focus on grouping rows, navigation only inside of groups for now
         */
        this.addEventListener('beforecellfocus', e => this.onFocus(e));
        /**
         * Prevent rgRow drag outside the group
         */
        this.addEventListener('roworderchanged', e => this.onDrag(e));
        /**
         * When grouping expand icon was clicked
         */
        this.addEventListener(GROUP_EXPAND_EVENT, e => this.onExpand(e.detail));
    }
    // clear grouping
    clearGrouping() {
        // clear columns
        columnTypes.forEach(t => {
            const cols = this.providers.column.getColumns(t);
            let deleted = false;
            cols.forEach(c => {
                if (isGroupingColumn(c)) {
                    delete c[PSEUDO_GROUP_COLUMN];
                    deleted = true;
                }
            });
            // if column store had grouping clear and refresh
            if (deleted) {
                this.providers.column.refreshByType(t);
            }
        });
        // clear rows
        const { source, oldNewIndexes } = getSource(this.getStore().get('source'), this.getStore().get('proxyItems'), true);
        this.providers.data.setData(source, GROUPING_ROW_TYPE, this.revogrid.disableVirtualY, undefined, true);
        this.updateTrimmed(undefined, undefined, oldNewIndexes, source);
    }
    updateTrimmed(trimmedGroup = {}, firstLevelMap = {}, secondLevelMap, source = this.getStore().get('source')) {
        // map previously trimmed data
        const trimemedOptionsToUpgrade = processDoubleConversionTrimmed(this.getStore().get('trimmed'), firstLevelMap, secondLevelMap);
        for (let type in trimemedOptionsToUpgrade) {
            if (type === FILTER_TRIMMED_TYPE) {
                /** Regrouping changes physical indexes, so filter trim needs fresh group-header state. */
                trimemedOptionsToUpgrade[type] = filterOutEmptyGroupRows(source, trimemedOptionsToUpgrade[type]);
            }
            this.revogrid.addTrimmed(trimemedOptionsToUpgrade[type], type);
        }
        // const emptyGroups = this.filterOutEmptyGroups(trimemedOptionsToUpgrade, childrenByGroup);
        // setup trimmed data for grouping
        this.revogrid.addTrimmed(Object.assign({}, trimmedGroup), TRIMMED_GROUPING);
    }
}

const COLUMN_DRAG_CLASS = 'column-drag-start';
class ColumnOrderHandler {
    constructor() {
        this.offset = 0;
    }
    renderAutoscroll(_, parent) {
        if (!parent) {
            return;
        }
        this.autoscrollEl = document.createElement('div');
        this.autoscrollEl.classList.add('drag-auto-scroll-y');
        parent.appendChild(this.autoscrollEl);
    }
    autoscroll(pos, dataContainerSize, direction = 'translateX') {
        if (!this.autoscrollEl) {
            return;
        }
        const helperOffset = 10;
        // calculate current y position inside of the grid active holder
        // 3 - size of element + border
        const maxScroll = Math.min(pos + helperOffset, dataContainerSize - 3);
        this.autoscrollEl.style.transform = `${direction}(${maxScroll}px)`;
        this.autoscrollEl.scrollIntoView({
            block: 'nearest',
            inline: 'nearest',
        });
    }
    start(e, { dataEl, gridRect, scrollEl, gridEl }, dir = 'left') {
        gridEl.classList.add(COLUMN_DRAG_CLASS);
        const scrollContainerRect = scrollEl.getBoundingClientRect();
        if (scrollContainerRect) {
            this.offset = scrollContainerRect[dir] - gridRect[dir];
        }
        this.renderAutoscroll(e, dataEl);
    }
    stop(gridEl) {
        var _a;
        gridEl.classList.remove(COLUMN_DRAG_CLASS);
        if (this.element) {
            this.element.hidden = true;
        }
        this.offset = 0;
        (_a = this.autoscrollEl) === null || _a === void 0 ? void 0 : _a.remove();
        this.autoscrollEl = undefined;
    }
    showHandler(pos, size, direction = 'translateX') {
        if (!this.element) {
            return;
        }
        // do not allow overcross top of the scrollable area, header excluded
        if (this.offset) {
            pos = Math.max(pos, this.offset);
        }
        // can not be bigger then grid end
        pos = Math.min(pos, size);
        this.element.style.transform = `${direction}(${pos}px)`;
        this.element.hidden = false;
    }
    render() {
        const el = this.element = document.createElement('div');
        el.classList.add('drag-position-y');
        el.hidden = true;
        return el;
    }
}

/**
 * Plugin for column manual move
 */
const COLUMN_CLICK = ON_COLUMN_CLICK;
const COLUMN_DRAG_MOVE_EVENT = 'columndragmousemove';
const COLUMN_DRAG_END_EVENT = 'columndragend';
const BEFORE_COLUMN_DRAG_END_EVENT = 'beforecolumndragend';
// use this event subscription to drop D&D for particular columns
const COLUMN_DRAG_START_EVENT = 'columndragstart';
class ColumnMovePlugin extends BasePlugin {
    constructor(revogrid, providers) {
        super(revogrid, providers);
        this.moveFunc = debounce((e) => this.doMove(e), 5);
        this.preventHeaderClickAfterDrag = (event) => {
            if (!this.preventNextHeaderClick) {
                return;
            }
            this.preventNextHeaderClick = false;
            event.preventDefault();
        };
        this.staticDragData = null;
        this.dragData = null;
        this.columnDragMoved = false;
        this.preventNextHeaderClick = false;
        this.localSubscriptions = {};
        this.orderUi = new ColumnOrderHandler();
        revogrid.appendChild(this.orderUi.render());
        revogrid.classList.add('column-draggable');
        // Register events
        this.localSubscriptions['mouseleave'] = {
            target: document,
            callback: (e) => this.onMouseOut(e),
        };
        this.localSubscriptions['mouseup'] = {
            target: document,
            callback: (e) => this.onMouseUp(e),
        };
        this.localSubscriptions['mousemove'] = {
            target: document,
            callback: (e) => this.move(e),
        };
        this.addEventListener(COLUMN_CLICK, ({ detail }) => this.dragStart(detail));
        this.revogrid.addEventListener('beforeheaderclick', this.preventHeaderClickAfterDrag, { capture: true });
    }
    dragStart({ event, data }) {
        if (event.defaultPrevented) {
            return;
        }
        this.preventNextHeaderClick = false;
        const { defaultPrevented } = dispatch(this.revogrid, COLUMN_DRAG_START_EVENT, data);
        // check if allowed to drag particulat column
        if (defaultPrevented) {
            return;
        }
        this.clearOrder();
        const { mouseleave, mouseup, mousemove } = this.localSubscriptions;
        mouseleave.target.addEventListener('mouseleave', mouseleave.callback);
        mouseup.target.addEventListener('mouseup', mouseup.callback);
        const dataEl = event.target.closest('revogr-header');
        const scrollEl = event.target.closest('revogr-viewport-scroll');
        if (!dataEl || !scrollEl) {
            return;
        }
        // no grouping drag and no row header column drag
        if (isColGrouping(data) || data.providers.type === 'rowHeaders') {
            return;
        }
        const cols = this.getDimension(data.pin || 'rgCol');
        const gridRect = this.revogrid.getBoundingClientRect();
        const elRect = dataEl.getBoundingClientRect();
        const startItem = getItemByPosition(cols, getLeftRelative(event.x, gridRect.left, elRect.left - gridRect.left) +
            (cols.renderOffset || 0));
        this.staticDragData = {
            startPos: event.x,
            startItem,
            pin: data.pin,
            dataEl,
            scrollEl,
            gridEl: this.revogrid,
            cols,
        };
        this.dragData = this.getData(this.staticDragData, []);
        mousemove.target.addEventListener('mousemove', mousemove.callback);
        this.orderUi.start(event, Object.assign(Object.assign({}, this.dragData), this.staticDragData));
    }
    doMove(e) {
        if (!this.staticDragData) {
            return;
        }
        const dragData = (this.dragData = this.getData(this.staticDragData, []));
        if (!dragData) {
            return;
        }
        const start = this.staticDragData.startPos;
        if (Math.abs(start - e.x) > 10) {
            const x = getLeftRelative(e.x, this.dragData.gridRect.left, this.dragData.scrollOffset);
            const rgCol = getItemByPosition(this.staticDragData.cols, x + (this.staticDragData.cols.renderOffset || 0));
            this.orderUi.autoscroll(x, dragData.elRect.width);
            // prevent position change if out of bounds
            if (rgCol.itemIndex >= this.staticDragData.cols.count) {
                return;
            }
            this.orderUi.showHandler(getColumnDragPosition(rgCol, this.staticDragData.startItem, this.staticDragData.cols.renderOffset || 0, dragData.scrollOffset), dragData.gridRect.width);
        }
    }
    move(e) {
        if (this.staticDragData &&
            Math.abs(this.staticDragData.startPos - e.x) > 10) {
            this.columnDragMoved = true;
        }
        dispatch(this.revogrid, COLUMN_DRAG_MOVE_EVENT, e);
        // then do move
        this.moveFunc(e);
    }
    onMouseOut(_) {
        this.clearOrder();
    }
    onMouseUp(e) {
        const suppressClick = this.columnDragMoved;
        // apply new positions
        if (this.dragData && this.staticDragData) {
            let relativePos = getLeftRelative(e.x, this.dragData.gridRect.left, this.dragData.scrollOffset);
            if (relativePos < 0) {
                relativePos = 0;
            }
            const newPosition = getItemByPosition(this.staticDragData.cols, relativePos + (this.staticDragData.cols.renderOffset || 0));
            const store = this.providers.column.stores[this.dragData.type].store;
            const source = store.get('source');
            const newItems = [...store.get('items')];
            // prevent position change if needed
            const { defaultPrevented: stopDrag } = dispatch(this.revogrid, BEFORE_COLUMN_DRAG_END_EVENT, Object.assign(Object.assign({}, this.staticDragData), { startPosition: this.staticDragData.startItem, newPosition, newItem: source[newItems[this.staticDragData.startItem.itemIndex]] }));
            if (!stopDrag) {
                const prevItems = [...newItems];
                // todo: if move item out of group remove item from group
                const toMove = newItems.splice(this.staticDragData.startItem.itemIndex, 1);
                newItems.splice(newPosition.itemIndex, 0, ...toMove);
                store.set('items', newItems);
                this.providers.dimension.updateSizesPositionByNewDataIndexes(this.dragData.type, newItems, prevItems);
            }
            dispatch(this.revogrid, COLUMN_DRAG_END_EVENT, this.getData(this.staticDragData, newItems, source));
        }
        if (suppressClick) {
            this.preventNextHeaderClick = !!e.target.closest('revogr-header');
        }
        this.clearOrder();
    }
    clearLocalSubscriptions() {
        forEach(this.localSubscriptions, ({ target, callback }, key) => target.removeEventListener(key, callback));
    }
    clearOrder() {
        this.staticDragData = null;
        this.dragData = null;
        this.columnDragMoved = false;
        this.clearLocalSubscriptions();
        this.orderUi.stop(this.revogrid);
    }
    /**
     * Clearing subscription
     */
    clearSubscriptions() {
        super.clearSubscriptions();
        this.clearLocalSubscriptions();
        this.revogrid.removeEventListener('beforeheaderclick', this.preventHeaderClickAfterDrag, { capture: true });
    }
    getData({ gridEl, dataEl, pin }, order, source = []) {
        const gridRect = gridEl.getBoundingClientRect();
        const elRect = dataEl.getBoundingClientRect();
        const scrollOffset = elRect.left - gridRect.left;
        return {
            columns: order.map(index => source[index]).filter(Boolean),
            elRect,
            gridRect,
            order,
            type: pin || 'rgCol',
            scrollOffset,
        };
    }
    getDimension(type) {
        return this.providers.dimension.stores[type].getCurrentState();
    }
}
function getLeftRelative(absoluteX, gridPos, offset) {
    return absoluteX - gridPos - offset;
}
function getColumnDragPosition(targetItem, startItem, renderOffset, scrollOffset) {
    const insertionEdge = startItem.itemIndex > targetItem.itemIndex
        ? targetItem.start
        : targetItem.end;
    return insertionEdge - renderOffset + scrollOffset;
}

export { AutoSizeColumnPlugin as A, BasePlugin as B, ColumnAutoSizeMode as C, DimensionStore as D, ExportFilePlugin as E, FILTER_TRIMMED_TYPE as F, GroupingRowPlugin as G, SelectionStore as S, StretchColumn as a, ExportCsv as b, FILTER_CONFIG_CHANGED_EVENT as c, FILTE_PANEL as d, FilterPlugin as e, filterCoreFunctionsIndexedByType as f, filterTypes as g, filterNames as h, isStretchPlugin as i, doCollapse as j, doExpand as k, COLUMN_DRAG_MOVE_EVENT as l, COLUMN_DRAG_END_EVENT as m, BEFORE_COLUMN_DRAG_END_EVENT as n, COLUMN_DRAG_START_EVENT as o, ColumnMovePlugin as p, getLeftRelative as q, getColumnDragPosition as r, SortingPlugin as s, hasActiveSorting as t, getSortingIndex as u, sortIndexByItems as v, defaultCellCompare as w, descCellCompare as x, getNextOrder as y, getComparer as z };
