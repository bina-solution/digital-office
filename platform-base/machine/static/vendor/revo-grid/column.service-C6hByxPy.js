/*!
 * Built by Revolist OU ❤️
 */
import { Q as toFinite, U as keys, V as isArrayLike, W as baseIteratee, N as isArray, G as GRID_INTERNALS, X as isIterateeCall, a as getVisibleSourceItem, o as DISABLED_CLASS, C as CELL_CLASS, b as getSourceItem } from './dimension.helpers-CGKwSvw6.js';

/**
 * Converts `value` to an integer.
 *
 * **Note:** This method is loosely based on
 * [`ToInteger`](http://www.ecma-international.org/ecma-262/7.0/#sec-tointeger).
 *
 * @static
 * @memberOf _
 * @since 4.0.0
 * @category Lang
 * @param {*} value The value to convert.
 * @returns {number} Returns the converted integer.
 * @example
 *
 * _.toInteger(3.2);
 * // => 3
 *
 * _.toInteger(Number.MIN_VALUE);
 * // => 0
 *
 * _.toInteger(Infinity);
 * // => 1.7976931348623157e+308
 *
 * _.toInteger('3.2');
 * // => 3
 */
function toInteger(value) {
  var result = toFinite(value),
      remainder = result % 1;

  return result === result ? (remainder ? result - remainder : result) : 0;
}

/**
 * A specialized version of `_.reduce` for arrays without support for
 * iteratee shorthands.
 *
 * @private
 * @param {Array} [array] The array to iterate over.
 * @param {Function} iteratee The function invoked per iteration.
 * @param {*} [accumulator] The initial value.
 * @param {boolean} [initAccum] Specify using the first element of `array` as
 *  the initial value.
 * @returns {*} Returns the accumulated value.
 */
function arrayReduce(array, iteratee, accumulator, initAccum) {
  var index = -1,
      length = array == null ? 0 : array.length;

  if (initAccum && length) {
    accumulator = array[++index];
  }
  while (++index < length) {
    accumulator = iteratee(accumulator, array[index], index, array);
  }
  return accumulator;
}

/**
 * Creates a base function for methods like `_.forIn` and `_.forOwn`.
 *
 * @private
 * @param {boolean} [fromRight] Specify iterating from right to left.
 * @returns {Function} Returns the new base function.
 */
function createBaseFor(fromRight) {
  return function(object, iteratee, keysFunc) {
    var index = -1,
        iterable = Object(object),
        props = keysFunc(object),
        length = props.length;

    while (length--) {
      var key = props[++index];
      if (iteratee(iterable[key], key, iterable) === false) {
        break;
      }
    }
    return object;
  };
}

/**
 * The base implementation of `baseForOwn` which iterates over `object`
 * properties returned by `keysFunc` and invokes `iteratee` for each property.
 * Iteratee functions may exit iteration early by explicitly returning `false`.
 *
 * @private
 * @param {Object} object The object to iterate over.
 * @param {Function} iteratee The function invoked per iteration.
 * @param {Function} keysFunc The function to get the keys of `object`.
 * @returns {Object} Returns `object`.
 */
var baseFor = createBaseFor();

/**
 * The base implementation of `_.forOwn` without support for iteratee shorthands.
 *
 * @private
 * @param {Object} object The object to iterate over.
 * @param {Function} iteratee The function invoked per iteration.
 * @returns {Object} Returns `object`.
 */
function baseForOwn(object, iteratee) {
  return object && baseFor(object, iteratee, keys);
}

/**
 * Creates a `baseEach` or `baseEachRight` function.
 *
 * @private
 * @param {Function} eachFunc The function to iterate over a collection.
 * @param {boolean} [fromRight] Specify iterating from right to left.
 * @returns {Function} Returns the new base function.
 */
function createBaseEach(eachFunc, fromRight) {
  return function(collection, iteratee) {
    if (collection == null) {
      return collection;
    }
    if (!isArrayLike(collection)) {
      return eachFunc(collection, iteratee);
    }
    var length = collection.length,
        index = -1,
        iterable = Object(collection);

    while ((++index < length)) {
      if (iteratee(iterable[index], index, iterable) === false) {
        break;
      }
    }
    return collection;
  };
}

/**
 * The base implementation of `_.forEach` without support for iteratee shorthands.
 *
 * @private
 * @param {Array|Object} collection The collection to iterate over.
 * @param {Function} iteratee The function invoked per iteration.
 * @returns {Array|Object} Returns `collection`.
 */
var baseEach = createBaseEach(baseForOwn);

/**
 * The base implementation of `_.reduce` and `_.reduceRight`, without support
 * for iteratee shorthands, which iterates over `collection` using `eachFunc`.
 *
 * @private
 * @param {Array|Object} collection The collection to iterate over.
 * @param {Function} iteratee The function invoked per iteration.
 * @param {*} accumulator The initial value.
 * @param {boolean} initAccum Specify using the first or last element of
 *  `collection` as the initial value.
 * @param {Function} eachFunc The function to iterate over `collection`.
 * @returns {*} Returns the accumulated value.
 */
function baseReduce(collection, iteratee, accumulator, initAccum, eachFunc) {
  eachFunc(collection, function(value, index, collection) {
    accumulator = initAccum
      ? (initAccum = false, value)
      : iteratee(accumulator, value, index, collection);
  });
  return accumulator;
}

/**
 * Reduces `collection` to a value which is the accumulated result of running
 * each element in `collection` thru `iteratee`, where each successive
 * invocation is supplied the return value of the previous. If `accumulator`
 * is not given, the first element of `collection` is used as the initial
 * value. The iteratee is invoked with four arguments:
 * (accumulator, value, index|key, collection).
 *
 * Many lodash methods are guarded to work as iteratees for methods like
 * `_.reduce`, `_.reduceRight`, and `_.transform`.
 *
 * The guarded methods are:
 * `assign`, `defaults`, `defaultsDeep`, `includes`, `merge`, `orderBy`,
 * and `sortBy`
 *
 * @static
 * @memberOf _
 * @since 0.1.0
 * @category Collection
 * @param {Array|Object} collection The collection to iterate over.
 * @param {Function} [iteratee=_.identity] The function invoked per iteration.
 * @param {*} [accumulator] The initial value.
 * @returns {*} Returns the accumulated value.
 * @see _.reduceRight
 * @example
 *
 * _.reduce([1, 2], function(sum, n) {
 *   return sum + n;
 * }, 0);
 * // => 3
 *
 * _.reduce({ 'a': 1, 'b': 2, 'c': 1 }, function(result, value, key) {
 *   (result[value] || (result[value] = [])).push(key);
 *   return result;
 * }, {});
 * // => { '1': ['a', 'c'], '2': ['b'] } (iteration order is not guaranteed)
 */
function reduce(collection, iteratee, accumulator) {
  var func = isArray(collection) ? arrayReduce : baseReduce,
      initAccum = arguments.length < 3;

  return func(collection, baseIteratee(iteratee), accumulator, initAccum, baseEach);
}

function getCellData(val) {
    if (typeof val === 'undefined' || val === null) {
        return '';
    }
    return val;
}
function getCellRaw(model = {}, column) {
    if (!column) {
        return;
    }
    if (column.cellParser) {
        return column.cellParser(model, column);
    }
    return model[column.prop];
}
function getCellDataParsed(model, column) {
    return getCellData(getCellRaw(model, column));
}
/**
 * Get column type from column data
 */
function getColumnType(rgCol) {
    if (rgCol.pin) {
        return rgCol.pin;
    }
    return 'rgCol';
}
function getColumnSizes(cols) {
    const res = {};
    for (const [i, c] of cols.entries()) {
        if (c.size) {
            res[i] = c.size;
        }
    }
    return res;
}
/**
 * Check if column is grouping column
 */
function isColGrouping(colData) {
    return !!colData.children;
}
/**
 * This function is used to create a collection of columns.
 */
function getColumns(columns, level = 0, types, resFromRoot) {
    const collection = {
        // columns as they are in stores per type
        columns: {
            rgCol: [],
            colPinStart: [],
            colPinEnd: [],
        },
        // columns indexed by prop for quick access
        columnByProp: {},
        // column grouping
        columnGrouping: {
            rgCol: [],
            colPinStart: [],
            colPinEnd: [],
        },
        // sorting
        sort: {},
        // max depth level for column grouping
        maxLevel: level,
    };
    return reduce(columns, (res, colData) => {
        var _a;
        // Grouped column
        if (isColGrouping(colData)) {
            res = gatherGroup(res, colData, getColumns(colData.children, level + 1, types, res), resFromRoot === null || resFromRoot === void 0 ? void 0 : resFromRoot.columns, level);
            return res;
        }
        // Column type
        const columnDefinitionFromType = colData.columnType && (types === null || types === void 0 ? void 0 : types[colData.columnType]);
        // Regular column
        const regularColumn = Object.assign(Object.assign({}, columnDefinitionFromType), colData);
        // Regular column, no Pin
        if (!regularColumn.pin) {
            res.columns.rgCol.push(regularColumn);
            // Pin
        }
        else {
            res.columns[regularColumn.pin].push(regularColumn);
        }
        if (regularColumn.order) {
            res.sort[regularColumn.prop] = regularColumn;
        }
        // it's possible that some columns have same prop, but better to avoid it
        if (!res.columnByProp[regularColumn.prop]) {
            res.columnByProp[regularColumn.prop] = [];
        }
        res.columnByProp[regularColumn.prop].push(regularColumn);
        // trigger setup hook if present
        (_a = regularColumn.beforeSetup) === null || _a === void 0 ? void 0 : _a.call(regularColumn, regularColumn);
        return res;
    }, collection);
}
function gatherGroup(res, colData, collection, existingColumnsByType, level = 0) {
    // group template
    const group = Object.assign(Object.assign({}, colData), { level, indexes: [] });
    // check columns for update
    columnTypes.forEach(type => {
        const resultItem = res.columns[type];
        const collectionItem = collection.columns[type];
        // if column data
        if (isArray(resultItem) && isArray(collectionItem)) {
            // fill grouping
            const itemLength = collectionItem.length;
            if (itemLength) {
                const columnLength = [...((existingColumnsByType === null || existingColumnsByType === void 0 ? void 0 : existingColumnsByType[type]) || []), ...resultItem].length;
                // fill columns
                resultItem.push(...collectionItem);
                // fill indexes per each viewport
                res.columnGrouping[type].push(Object.assign(Object.assign({}, group), { indexes: Array(itemLength).fill(columnLength).map((v, i) => v + i) }));
            }
        }
    });
    // merge column groupings
    for (let k in collection.columnGrouping) {
        const key = k;
        const collectionItem = collection.columnGrouping[key];
        const delta = ((existingColumnsByType === null || existingColumnsByType === void 0 ? void 0 : existingColumnsByType[key]) || []).length;
        const rebasedItem = delta > 0
            ? collectionItem.map(group => (Object.assign(Object.assign({}, group), { indexes: group.indexes.map(i => i + delta) })))
            : collectionItem;
        res.columnGrouping[key].push(...rebasedItem);
    }
    res.maxLevel = Math.max(res.maxLevel, collection.maxLevel);
    res.sort = Object.assign(Object.assign({}, res.sort), collection.sort);
    res.columnByProp = Object.assign(Object.assign({}, res.columnByProp), collection.columnByProp);
    return res;
}
function findColumn(columns, prop) {
    for (const c of columns) {
        if (isColGrouping(c)) {
            const found = findColumn(c.children, prop);
            if (found) {
                return found;
            }
        }
        else if (c.prop === prop) {
            return c;
        }
    }
    return undefined;
}
function getColumnByProp(columns, prop) {
    return findColumn(columns, prop);
}

function nextCell(cell, lastCell) {
    const nextItem = {};
    let types = ['x', 'y'];
    // previous item check
    for (let t of types) {
        if (cell[t] < 0) {
            nextItem[t] = cell[t];
            return nextItem;
        }
    }
    // next item check
    for (let t of types) {
        if (cell[t] >= lastCell[t]) {
            nextItem[t] = cell[t] - lastCell[t];
            return nextItem;
        }
    }
    return null;
}
function cropCellToMax(cell, lastCell) {
    const croppedCell = Object.assign({}, cell);
    const cellCoordinates = ['x', 'y'];
    for (const coordinate of cellCoordinates) {
        if (cell[coordinate] < 0) {
            croppedCell[coordinate] = 0;
        }
        else if (cell[coordinate] >= lastCell[coordinate]) {
            croppedCell[coordinate] = lastCell[coordinate] - 1;
        }
    }
    return croppedCell;
}
function getRange(start, end) {
    return start && end
        ? {
            x: Math.min(start.x, end.x),
            y: Math.min(start.y, end.y),
            x1: Math.max(start.x, end.x),
            y1: Math.max(start.y, end.y),
        }
        : null;
}
function isRangeSingleCell(a) {
    return a.x === a.x1 && a.y === a.y1;
}

const rowTypes = ['rowPinStart', 'rgRow', 'rowPinEnd'];
const columnTypes = [
    'colPinStart',
    'rgCol',
    'colPinEnd',
];
function isRowType(type) {
    return rowTypes.indexOf(type) > -1;
}

const GROUP_DEPTH = `${GRID_INTERNALS}-depth`;
const PSEUDO_GROUP_ITEM = `${GRID_INTERNALS}-name`;
const PSEUDO_GROUP_ITEM_ID = `${GRID_INTERNALS}-id`;
const PSEUDO_GROUP_ITEM_VALUE = `${GRID_INTERNALS}-value`;
const PSEUDO_GROUP_COLUMN = `${GRID_INTERNALS}-column`;
const GROUP_EXPANDED = `${GRID_INTERNALS}-expanded`;
const GROUP_COLUMN_PROP = `${GRID_INTERNALS}-prop`;
const GROUP_ORIGINAL_INDEX = `${GRID_INTERNALS}-original-index`;
const GROUP_EXPAND_BTN = `group-expand`;
const GROUP_EXPAND_EVENT = `groupexpandclick`;
const GROUPING_ROW_TYPE = 'rgRow';

function getGroupValueDefault(item, prop) {
    return item[prop] || null;
}
function isDataRow(item) {
    return item != null;
}
// get source based on proxy item collection to preserve rgRow order
function getSource(source, items, withoutGrouping = false) {
    let index = 0;
    const result = {
        source: [],
        prevExpanded: {},
        oldNewIndexes: {},
    };
    // order important here, expected parent is first, then others
    items.forEach(i => {
        const model = source[i];
        if (!withoutGrouping) {
            result.source.push(model);
            return;
        }
        // grouping filter
        if (isGrouping(model)) {
            if (getExpanded(model)) {
                result.prevExpanded[model[PSEUDO_GROUP_ITEM_VALUE]] = true;
            }
        }
        else if (!isDataRow(model)) {
            return;
        }
        else {
            result.source.push(model);
            result.oldNewIndexes[i] = index;
            index++;
        }
    });
    return result;
}
function getExpanded(model = {}) {
    return model[GROUP_EXPANDED];
}
function flattenGroupMaps({ groupedValues, parentIds, isExpanded, itemIndex, expandedAll, prevExpanded, columnProps, }) {
    const depth = parentIds.length;
    const sourceWithGroups = [];
    // collapse all groups in the beginning
    let trimmed = {};
    // index mapping
    let oldNewIndexMap = {};
    groupedValues.forEach((innerGroupedValues, groupId) => {
        const levelIds = [...parentIds, groupId];
        const mergedIds = levelIds.join(',');
        const isGroupExpanded = isExpanded && (!!expandedAll || !!prevExpanded[mergedIds]);
        sourceWithGroups.push({
            [PSEUDO_GROUP_ITEM]: groupId,
            [GROUP_DEPTH]: depth,
            [PSEUDO_GROUP_ITEM_ID]: JSON.stringify(levelIds),
            [PSEUDO_GROUP_ITEM_VALUE]: mergedIds,
            [GROUP_EXPANDED]: isGroupExpanded,
            [GROUP_COLUMN_PROP]: columnProps[depth],
            [columnProps[depth]]: groupId,
        });
        itemIndex += 1;
        // If parent group is collapsed, mark all items as hidden
        if (!isExpanded && depth) {
            trimmed[itemIndex] = true;
        }
        if (Array.isArray(innerGroupedValues)) {
            // This branch handles leaf nodes (actual data items)
            innerGroupedValues.forEach(value => {
                itemIndex += 1;
                if (!isGroupExpanded) {
                    trimmed[itemIndex] = true; // Mark items as hidden if group is collapsed
                }
                oldNewIndexMap[value[GROUP_ORIGINAL_INDEX]] = itemIndex; // Keep track of new positions
            });
            sourceWithGroups.push(...innerGroupedValues);
        }
        else {
            // This branch handles nested groups (further subgroups)
            const children = flattenGroupMaps({
                groupedValues: innerGroupedValues,
                parentIds: levelIds,
                isExpanded: isGroupExpanded,
                itemIndex,
                expandedAll,
                prevExpanded,
                columnProps,
            }); // Recursively process subgroups
            sourceWithGroups.push(...children.source);
            trimmed = Object.assign(Object.assign({}, children.trimmed), trimmed);
            oldNewIndexMap = Object.assign(Object.assign({}, children.oldNewIndexMap), oldNewIndexMap);
            itemIndex = children.itemIndex;
        }
    });
    return {
        source: sourceWithGroups,
        oldNewIndexMap,
        trimmed,
        itemIndex,
    };
}
/**
 * Gather data for grouping
 * @param array - flat data array
 * @param columnProps - ids of groups
 * @param expanded - potentially expanded items if present
 */
function gatherGrouping(array, columnProps, { prevExpanded = {}, expandedAll = false, getGroupValue = getGroupValueDefault, }) {
    const groupedItems = new Map();
    array.forEach((item, originalIndex) => {
        if (!isDataRow(item)) {
            return;
        }
        const groupLevelValues = columnProps.map(groupId => getGroupValue(item, groupId));
        const lastLevelValue = groupLevelValues.pop();
        let currentGroupLevel = groupedItems;
        groupLevelValues.forEach(value => {
            if (!currentGroupLevel.has(value)) {
                currentGroupLevel.set(value, new Map());
            }
            currentGroupLevel = currentGroupLevel.get(value);
        });
        if (!currentGroupLevel.has(lastLevelValue)) {
            const groupItems = [];
            currentGroupLevel.set(lastLevelValue, groupItems);
        }
        const lastLevelItems = currentGroupLevel.get(lastLevelValue);
        lastLevelItems.push(Object.assign(Object.assign({}, item), { [GROUP_ORIGINAL_INDEX]: originalIndex }));
    });
    const groupingDepth = columnProps.length;
    const { source: sourceWithGroups, trimmed, oldNewIndexMap } = flattenGroupMaps({
        groupedValues: groupedItems,
        parentIds: [],
        isExpanded: true,
        itemIndex: -1,
        expandedAll,
        prevExpanded,
        columnProps
    });
    return {
        sourceWithGroups, // updates source mirror
        depth: groupingDepth, // largest depth for grouping
        trimmed, // used for expand/collapse grouping values
        oldNewIndexMap, // used for mapping old values to new
    };
}
function getGroupingName(rgRow) {
    return rgRow === null || rgRow === void 0 ? void 0 : rgRow[PSEUDO_GROUP_ITEM];
}
function isGrouping(rgRow) {
    return typeof (rgRow === null || rgRow === void 0 ? void 0 : rgRow[PSEUDO_GROUP_ITEM]) !== 'undefined';
}
function isGroupingColumn(column) {
    return typeof (column === null || column === void 0 ? void 0 : column[PSEUDO_GROUP_COLUMN]) !== 'undefined';
}
function measureEqualDepth(groupA, groupB) {
    const ln = groupA.length;
    let i = 0;
    for (; i < ln; i++) {
        if (groupA[i] !== groupB[i]) {
            return i;
        }
    }
    return i;
}
function getParsedGroup(id) {
    const parseGroup = JSON.parse(id);
    // extra precaution and type safeguard
    if (!Array.isArray(parseGroup)) {
        return null;
    }
    return parseGroup;
}
// check if items is child of current clicked group
function isSameGroup(currentGroup, currentModel, nextModel) {
    const nextGroup = getParsedGroup(nextModel[PSEUDO_GROUP_ITEM_ID]);
    if (!nextGroup) {
        return false;
    }
    const depth = measureEqualDepth(currentGroup, nextGroup);
    return currentModel[GROUP_DEPTH] < depth;
}

/**
 * The base implementation of `_.slice` without an iteratee call guard.
 *
 * @private
 * @param {Array} array The array to slice.
 * @param {number} [start=0] The start position.
 * @param {number} [end=array.length] The end position.
 * @returns {Array} Returns the slice of `array`.
 */
function baseSlice(array, start, end) {
  var index = -1,
      length = array.length;

  if (start < 0) {
    start = -start > length ? 0 : (length + start);
  }
  end = end > length ? length : end;
  if (end < 0) {
    end += length;
  }
  length = start > end ? 0 : ((end - start) >>> 0);
  start >>>= 0;

  var result = Array(length);
  while (++index < length) {
    result[index] = array[index + start];
  }
  return result;
}

/**
 * Creates a slice of `array` from `start` up to, but not including, `end`.
 *
 * **Note:** This method is used instead of
 * [`Array#slice`](https://mdn.io/Array/slice) to ensure dense arrays are
 * returned.
 *
 * @static
 * @memberOf _
 * @since 3.0.0
 * @category Array
 * @param {Array} array The array to slice.
 * @param {number} [start=0] The start position.
 * @param {number} [end=array.length] The end position.
 * @returns {Array} Returns the slice of `array`.
 */
function slice(array, start, end) {
  var length = array == null ? 0 : array.length;
  if (!length) {
    return [];
  }
  if (end && typeof end != 'number' && isIterateeCall(array, start, end)) {
    start = 0;
    end = length;
  }
  else {
    start = start == null ? 0 : toInteger(start);
    end = end === undefined ? length : toInteger(end);
  }
  return baseSlice(array, start, end);
}

function getCellEditor(column, editors = {}) {
    const editor = column === null || column === void 0 ? void 0 : column.editor;
    if (!editor) {
        return undefined;
    }
    // reference
    if (typeof editor === 'string') {
        return editors[editor];
    }
    return editor;
}
class ColumnService {
    get columns() {
        return getVisibleSourceItem(this.source);
    }
    constructor(dataStore, source) {
        this.dataStore = dataStore;
        this.source = source;
        this.unsubscribe = [];
        this.hasGrouping = false;
        this.unsubscribe.push(source.onChange('source', s => this.checkGrouping(s)));
        this.checkGrouping(source.get('source'));
        this.type = source.get('type');
    }
    checkGrouping(cols) {
        for (let rgCol of cols) {
            if (isGroupingColumn(rgCol)) {
                this.hasGrouping = true;
                return;
            }
            this.hasGrouping = false;
        }
    }
    isReadOnly(r, c) {
        var _a;
        const readOnly = (_a = this.columns[c]) === null || _a === void 0 ? void 0 : _a.readonly;
        if (typeof readOnly === 'function') {
            const data = this.rowDataModel(r, c);
            return readOnly(data);
        }
        return !!readOnly;
    }
    mergeProperties(r, c, defaultProps, schemaModel) {
        var _a, _b;
        const props = Object.assign({}, defaultProps);
        props.class = Object.assign(Object.assign({}, (typeof props.class === 'string'
            ? { [props.class]: true }
            : props.class)), { [CELL_CLASS]: true, [DISABLED_CLASS]: this.isReadOnly(r, c) });
        const extra = (_b = (_a = schemaModel.column) === null || _a === void 0 ? void 0 : _a.cellProperties) === null || _b === void 0 ? void 0 : _b.call(_a, schemaModel);
        if (!extra) {
            return props;
        }
        return doPropMerge(props, extra);
    }
    getRowClass(r, prop) {
        const model = getSourceItem(this.dataStore, r) || {};
        return model[prop] || '';
    }
    getSaveData(rowIndex, colIndex, val) {
        const data = this.rowDataModel(rowIndex, colIndex);
        if (typeof val === 'undefined') {
            val = getCellData(data.value);
        }
        return Object.assign(Object.assign({}, data), { val });
    }
    /**
     * Get cell data model for given rowIndex and colIndex
     * Used to pass data to editor/renderer
     */
    rowDataModel(rowIndex, colIndex) {
        const column = this.columns[colIndex];
        const prop = column === null || column === void 0 ? void 0 : column.prop;
        const model = getSourceItem(this.dataStore, rowIndex) || {};
        const type = this.dataStore.get('type');
        return {
            prop,
            model,
            data: this.dataStore.get('source'),
            column,
            rowIndex,
            colIndex,
            colType: this.type,
            type,
            value: getCellRaw(model, column),
        };
    }
    getRangeData(d, columns) {
        var _a;
        const changed = {};
        // get original length sizes
        const copyColLength = d.oldRange.x1 - d.oldRange.x + 1;
        const copyRowLength = d.oldRange.y1 - d.oldRange.y + 1;
        const mapping = {};
        // rows
        for (let rowIndex = d.newRange.y, i = 0; rowIndex < d.newRange.y1 + 1; rowIndex++, i++) {
            // copy original data link
            const oldRowIndex = d.oldRange.y + (i % copyRowLength);
            const copyRow = getSourceItem(this.dataStore, oldRowIndex) || {};
            // columns
            for (let colIndex = d.newRange.x, j = 0; colIndex < d.newRange.x1 + 1; colIndex++, j++) {
                // check if old range area
                if (rowIndex >= d.oldRange.y &&
                    rowIndex <= d.oldRange.y1 &&
                    colIndex >= d.oldRange.x &&
                    colIndex <= d.oldRange.x1) {
                    continue;
                }
                // requested column beyond range
                if (!this.columns[colIndex]) {
                    continue;
                }
                const prop = (_a = this.columns[colIndex]) === null || _a === void 0 ? void 0 : _a.prop;
                const copyColIndex = d.oldRange.x + (j % copyColLength);
                const copyColumnProp = columns[copyColIndex].prop;
                /** if can write */
                if (!this.isReadOnly(rowIndex, colIndex)) {
                    /** to show before save */
                    if (!changed[rowIndex]) {
                        changed[rowIndex] = {};
                    }
                    changed[rowIndex][prop] = copyRow[copyColumnProp];
                    /** Generate mapping object */
                    if (!mapping[rowIndex]) {
                        mapping[rowIndex] = {};
                    }
                    mapping[rowIndex][prop] = {
                        colIndex: copyColIndex,
                        colProp: copyColumnProp,
                        rowIndex: oldRowIndex,
                    };
                }
            }
        }
        return {
            changed,
            mapping,
        };
    }
    getTransformedDataToApply({ start, data, targetRange, }) {
        const changed = {};
        const copyRowLength = data.length;
        if (!copyRowLength) {
            return {
                changed,
                range: null,
            };
        }
        const colLength = this.columns.length;
        const rowLength = this.dataStore.get('items').length;
        const bounds = this.getDataApplyBounds(start, targetRange, copyRowLength, rowLength, colLength);
        if (!bounds) {
            return {
                changed,
                range: null,
            };
        }
        const { startRow, startCol, endRow } = bounds;
        let maxCol = startCol - 1;
        let lastRow = startRow - 1;
        // rows
        for (let rowIndex = startRow, i = 0; rowIndex <= endRow; rowIndex++, i++) {
            // copy original data link
            const copyRow = data[i % copyRowLength];
            const copyColLength = (copyRow === null || copyRow === void 0 ? void 0 : copyRow.length) || 0;
            if (!copyColLength) {
                continue;
            }
            maxCol = Math.max(maxCol, this.applyClipboardRow(changed, {
                bounds,
                copyColLength,
                copyRow,
                rowIndex,
                start,
                targetRange,
            }));
            lastRow = rowIndex;
        }
        return {
            changed,
            range: this.getAppliedRange(bounds, lastRow, maxCol),
        };
    }
    getDataApplyBounds(start, targetRange, copyRowLength, rowLength, colLength) {
        var _a, _b, _c;
        const startRow = (_a = targetRange === null || targetRange === void 0 ? void 0 : targetRange.y) !== null && _a !== void 0 ? _a : start.y;
        const startCol = (_b = targetRange === null || targetRange === void 0 ? void 0 : targetRange.x) !== null && _b !== void 0 ? _b : start.x;
        const endRow = Math.min(rowLength - 1, (_c = targetRange === null || targetRange === void 0 ? void 0 : targetRange.y1) !== null && _c !== void 0 ? _c : start.y + copyRowLength - 1);
        if (endRow < startRow || startCol >= colLength) {
            return null;
        }
        return { startRow, startCol, endRow, colLength };
    }
    applyClipboardRow(changed, { bounds, copyColLength, copyRow, rowIndex, start, targetRange, }) {
        var _a;
        const endCol = Math.min(bounds.colLength - 1, (_a = targetRange === null || targetRange === void 0 ? void 0 : targetRange.x1) !== null && _a !== void 0 ? _a : start.x + copyColLength - 1);
        for (let colIndex = bounds.startCol, j = 0; colIndex <= endCol; colIndex++, j++) {
            if (this.isReadOnly(rowIndex, colIndex)) {
                continue;
            }
            const prop = this.columns[colIndex].prop;
            changed[rowIndex] = changed[rowIndex] || {};
            changed[rowIndex][prop] = copyRow[j % copyColLength];
        }
        return endCol;
    }
    getAppliedRange({ startRow, startCol }, lastRow, maxCol) {
        if (lastRow < startRow || maxCol < startCol) {
            return null;
        }
        return getRange({ x: startCol, y: startRow }, {
            y: lastRow,
            x: maxCol,
        });
    }
    getRangeStaticData(d, value) {
        const changed = {};
        // rows
        for (let rowIndex = d.y, i = 0; rowIndex < d.y1 + 1; rowIndex++, i++) {
            // columns
            for (let colIndex = d.x, j = 0; colIndex < d.x1 + 1; colIndex++, j++) {
                // requested column beyond range
                if (!this.columns[colIndex]) {
                    continue;
                }
                const p = this.columns[colIndex].prop;
                /** if can write */
                if (!this.isReadOnly(rowIndex, colIndex)) {
                    /** to show before save */
                    if (!changed[rowIndex]) {
                        changed[rowIndex] = {};
                    }
                    changed[rowIndex][p] = value;
                }
            }
        }
        return changed;
    }
    getRangeTransformedToProps(d, store) {
        var _a;
        const area = [];
        const type = this.dataStore.get('type');
        // rows
        for (let rowIndex = d.y, i = 0; rowIndex < d.y1 + 1; rowIndex++, i++) {
            // columns
            for (let colIndex = d.x, j = 0; colIndex < d.x1 + 1; colIndex++, j++) {
                const prop = (_a = this.columns[colIndex]) === null || _a === void 0 ? void 0 : _a.prop;
                area.push({
                    prop,
                    rowIndex,
                    colIndex,
                    model: getSourceItem(store, rowIndex),
                    type,
                    colType: this.type,
                });
            }
        }
        return area;
    }
    copyRangeArray(range, store) {
        const cols = [...this.columns];
        const props = slice(cols, range.x, range.x1 + 1).map(v => v.prop);
        const toCopy = [];
        const mapping = {};
        // rows indexes
        for (let i = range.y; i <= range.y1; i++) {
            const rgRow = [];
            mapping[i] = {};
            // columns indexes
            for (let prop of props) {
                const item = getSourceItem(store, i);
                // if no item - skip
                if (!item) {
                    continue;
                }
                const val = item[prop];
                rgRow.push(val);
                mapping[i][prop] = val;
            }
            toCopy.push(rgRow);
        }
        return {
            data: toCopy,
            mapping,
        };
    }
    destroy() {
        this.unsubscribe.forEach(f => f());
    }
}
/**
 * Checks if the given rowDrag is a service for dragging rows.
 */
function isRowDragService(rowDrag, model) {
    if (typeof rowDrag === 'function') {
        return rowDrag(model);
    }
    return !!rowDrag;
}
function mergeClasses(class1 = {}, class2 = {}) {
    if (typeof class1 === 'string') {
        class1 = { [class1]: true };
    }
    if (typeof class2 === 'string') {
        class2 = { [class2]: true };
    }
    return Object.assign(Object.assign({}, class1), class2);
}
function doPropMerge(existing, extra) {
    // if className is provided - remove it from props it messing with stencil
    if (extra.className) {
        extra.class = mergeClasses(extra.class, extra.className);
        delete extra.className;
    }
    let props = Object.assign(Object.assign({}, extra), existing);
    // extend existing props
    if (extra.class) {
        props.class = mergeClasses(props.class, extra.class);
    }
    if (extra.style) {
        props.style = Object.assign(Object.assign({}, extra.style), props.style);
    }
    return props;
}

export { getCellRaw as A, getCellDataParsed as B, getColumnType as C, getColumnSizes as D, isColGrouping as E, getColumns as F, GROUP_DEPTH as G, gatherGroup as H, getColumnByProp as I, reduce as J, baseEach as K, toInteger as L, ColumnService as M, getCellEditor as N, isRowDragService as O, PSEUDO_GROUP_ITEM as P, doPropMerge as Q, cropCellToMax as a, isRangeSingleCell as b, columnTypes as c, PSEUDO_GROUP_ITEM_ID as d, PSEUDO_GROUP_ITEM_VALUE as e, PSEUDO_GROUP_COLUMN as f, getRange as g, GROUP_EXPANDED as h, isRowType as i, GROUP_COLUMN_PROP as j, GROUP_ORIGINAL_INDEX as k, GROUP_EXPAND_BTN as l, GROUP_EXPAND_EVENT as m, nextCell as n, GROUPING_ROW_TYPE as o, getSource as p, getExpanded as q, rowTypes as r, gatherGrouping as s, getGroupingName as t, isGrouping as u, isGroupingColumn as v, measureEqualDepth as w, getParsedGroup as x, isSameGroup as y, getCellData as z };
