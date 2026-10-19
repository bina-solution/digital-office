/*!
 * Built by Revolist OU ❤️
 */
export { o as GROUPING_ROW_TYPE, j as GROUP_COLUMN_PROP, G as GROUP_DEPTH, h as GROUP_EXPANDED, l as GROUP_EXPAND_BTN, m as GROUP_EXPAND_EVENT, k as GROUP_ORIGINAL_INDEX, f as PSEUDO_GROUP_COLUMN, P as PSEUDO_GROUP_ITEM, d as PSEUDO_GROUP_ITEM_ID, e as PSEUDO_GROUP_ITEM_VALUE, c as columnTypes, a as cropCellToMax, H as gatherGroup, s as gatherGrouping, z as getCellData, B as getCellDataParsed, A as getCellRaw, I as getColumnByProp, D as getColumnSizes, C as getColumnType, F as getColumns, q as getExpanded, t as getGroupingName, x as getParsedGroup, g as getRange, p as getSource, E as isColGrouping, u as isGrouping, v as isGroupingColumn, b as isRangeSingleCell, i as isRowType, y as isSameGroup, w as measureEqualDepth, n as nextCell, r as rowTypes } from './column.service-C6hByxPy.js';
import { B as BasePlugin } from './column.drag.plugin-DKkf7Zqb.js';
export { A as AutoSizeColumnPlugin, n as BEFORE_COLUMN_DRAG_END_EVENT, m as COLUMN_DRAG_END_EVENT, l as COLUMN_DRAG_MOVE_EVENT, o as COLUMN_DRAG_START_EVENT, C as ColumnAutoSizeMode, p as ColumnMovePlugin, D as DimensionStore, b as ExportCsv, E as ExportFilePlugin, c as FILTER_CONFIG_CHANGED_EVENT, F as FILTER_TRIMMED_TYPE, d as FILTE_PANEL, e as FilterPlugin, G as GroupingRowPlugin, S as SelectionStore, s as SortingPlugin, a as StretchColumn, w as defaultCellCompare, x as descCellCompare, j as doCollapse, k as doExpand, f as filterCoreFunctionsIndexedByType, h as filterNames, g as filterTypes, r as getColumnDragPosition, z as getComparer, q as getLeftRelative, y as getNextOrder, u as getSortingIndex, t as hasActiveSorting, i as isStretchPlugin, v as sortIndexByItems } from './column.drag.plugin-DKkf7Zqb.js';
export { d as dispatch, a as dispatchByEvent } from './header-cell-renderer-BMmXRsd_.js';
export { C as CellRenderer, G as GroupingRowRenderer, S as SortingSign, e as expandEvent, a as expandSvgIconVNode } from './cell-renderer-CLTRlCa5.js';
export { a as applyMixins, f as findPositionInArray, g as getScrollbarSize, m as mergeSortedArray, p as pushSorted, r as range, s as scaleValue, t as timeout } from './index-Db3qZoW5.js';
export { T as TextEditor } from './text-editor-C3RUSwH5.js';
export { k as isAll, c as isClear, h as isCopy, a as isCtrlKey, b as isCtrlMetaKey, g as isCut, m as isEditInput, n as isEditorCtrConstructible, f as isEnterKeyValue, i as isMetaKey, j as isPaste, l as isShortcutModifier, d as isTab, e as isTabKeyValue } from './edit.utils-Dnnbd0xG.js';
export { h } from './index-Chp_81rd.js';
export { C as CELL_CLASS, z as CELL_HANDLER_CLASS, m as DATA_COL, n as DATA_ROW, o as DISABLED_CLASS, x as DRAGGABLE_CLASS, A as DRAGG_TEXT, w as DRAG_ICON_CLASS, D as DataStore, E as EDIT_INPUT_WR, F as FOCUS_CLASS, G as GRID_INTERNALS, v as HEADER_ACTUAL_ROW_CLASS, H as HEADER_CLASS, u as HEADER_ROW_CLASS, r as HEADER_SORTABLE_CLASS, M as MIN_COL_SIZE, y as MOBILE_CLASS, R as RESIZE_INTERVAL, B as ROW_FOCUSED_CLASS, q as ROW_HEADER_TYPE, S as SELECTION_BORDER_CLASS, T as TMP_SELECTION_BG_CLASS, i as calculateDimensionData, I as codesLetter, h as gatherTrimmedItems, k as getItemByIndex, j as getItemByPosition, g as getPhysical, b as getSourceItem, f as getSourceItemVirtualIndexByProp, c as getSourcePhysicalIndex, a as getVisibleSourceItem, J as keyValues, p as proxyPlugin, e as setItems, d as setSourceByPhysicalIndex, s as setSourceByVirtualIndex, l as setStore, t as trimmedPlugin } from './dimension.helpers-CGKwSvw6.js';
export { V as ViewportStore, b as addMissingItems, j as calculateRowHeaderSize, c as clampViewportCoordinate, f as getFirstItem, d as getItems, h as getLastItem, a as getUpdatedItemsByPosition, g as getViewportMaxCoordinate, i as isActiveRange, e as isActiveRangeOutsideLastItem, r as recombineByOffset, s as setItemSizes, u as updateMissingAndRange } from './viewport.store-_c579YyM.js';
export { A as AND_OR_BUTTON, e as AndOrButton, a as FILTER_BUTTON_ACTIVE, F as FILTER_BUTTON_CLASS, b as FILTER_PROP, c as FilterButton, R as REORDER_BUTTON, f as ReorderButton, T as TRASH_BUTTON, d as TrashButton, i as isFilterBtn } from './filter.button-B-RBiF67.js';
import './debounce-PCRWZliA.js';

const REVOGRID_EVENTS = new Map([
    ['contentsizechanged', 'contentsizechanged'],
    ['beforeedit', 'beforeedit'],
    ['beforerangeedit', 'beforerangeedit'],
    ['afteredit', 'afteredit'],
    ['beforeautofill', 'beforeautofill'],
    ['beforerange', 'beforerange'],
    ['afterfocus', 'afterfocus'],
    ['roworderchanged', 'roworderchanged'],
    ['beforesorting', 'beforesorting'],
    ['beforesourcesortingapply', 'beforesourcesortingapply'],
    ['beforesortingapply', 'beforesortingapply'],
    ['aftersortingapply', 'aftersortingapply'],
    ['rowdragstart', 'rowdragstart'],
    ['headerclick', 'headerclick'],
    ['beforecellfocus', 'beforecellfocus'],
    ['beforefocuslost', 'beforefocuslost'],
    ['beforesourceset', 'beforesourceset'],
    ['beforeanysource', 'beforeanysource'],
    ['aftersourceset', 'aftersourceset'],
    ['afteranysource', 'afteranysource'],
    ['beforecolumnsgather', 'beforecolumnsgather'],
    ['beforecolumnsset', 'beforecolumnsset'],
    ['beforecolumnapplied', 'beforecolumnapplied'],
    ['aftercolumnsset', 'aftercolumnsset'],
    ['beforefilterapply', 'beforefilterapply'],
    ['beforefiltertrimmed', 'beforefiltertrimmed'],
    ['beforetrimmed', 'beforetrimmed'],
    ['aftertrimmed', 'aftertrimmed'],
    ['viewportscroll', 'viewportscroll'],
    ['beforeexport', 'beforeexport'],
    ['beforeeditstart', 'beforeeditstart'],
    ['aftercolumnresize', 'aftercolumnresize'],
    ['beforerowdefinition', 'beforerowdefinition'],
    ['filterconfigchanged', 'filterconfigchanged'],
    ['sortingconfigchanged', 'sortingconfigchanged'],
    ['rowheaderschanged', 'rowheaderschanged'],
    ['beforegridrender', 'beforegridrender'],
    ['aftergridrender', 'aftergridrender'],
    ['aftergridinit', 'aftergridinit'],
    ['additionaldatachanged', 'additionaldatachanged'],
    ['afterthemechanged', 'afterthemechanged'],
    ['created', 'created'],
    ['beforepaste', 'beforepaste'],
    ['beforepasteapply', 'beforepasteapply'],
    ['pasteregion', 'pasteregion'],
    ['afterpasteapply', 'afterpasteapply'],
    ['beforecut', 'beforecut'],
    ['clearregion', 'clearregion'],
    ['beforecopy', 'beforecopy'],
    ['beforecopyapply', 'beforecopyapply'],
    ['copyregion', 'copyregion'],
    ['beforerowrender', 'beforerowrender'],
    ['afterrender', 'afterrender'],
    ['beforecellrender', 'beforecellrender'],
    ['beforedatarender', 'beforedatarender'],
    ['dragstartcell', 'dragstartcell'],
    ['celleditinit', 'celleditinit'],
    ['closeedit', 'closeedit'],
    ['filterChange', 'filterChange'],
    ['resetChange', 'resetChange'],
    ['beforefocusrender', 'beforefocusrender'],
    ['beforescrollintoview', 'beforescrollintoview'],
    ['afterfocus', 'afterfocus'],
    ['beforeheaderclick', 'beforeheaderclick'],
    ['headerresize', 'headerresize'],
    ['beforeheaderresize', 'beforeheaderresize'],
    ['headerdblclick', 'headerdblclick'],
    ['beforeheaderrender', 'beforeheaderrender'],
    ['beforegroupheaderrender', 'beforegroupheaderrender'],
    ['afterheaderrender', 'afterheaderrender'],
    ['columndragstart', 'columndragstart'],
    ['columndragmousemove', 'columndragmousemove'],
    ['beforecolumndragend', 'beforecolumndragend'],
    ['columndragend', 'columndragend'],
    ['rowdragstartinit', 'rowdragstartinit'],
    ['rowdragendinit', 'rowdragendinit'],
    ['rowdragmoveinit', 'rowdragmoveinit'],
    ['rowdragmousemove', 'rowdragmousemove'],
    ['rowdropinit', 'rowdropinit'],
    ['roworderchange', 'roworderchange'],
    ['beforecopyregion', 'beforecopyregion'],
    ['beforepasteregion', 'beforepasteregion'],
    ['celleditapply', 'celleditapply'],
    ['beforecellfocusinit', 'beforecellfocusinit'],
    ['beforenextvpfocus', 'beforenextvpfocus'],
    ['setedit', 'setedit'],
    ['beforeapplyrange', 'beforeapplyrange'],
    ['beforesetrange', 'beforesetrange'],
    ['setrange', 'setrange'],
    ['beforeeditrender', 'beforeeditrender'],
    ['selectall', 'selectall'],
    ['canceledit', 'canceledit'],
    ['settemprange', 'settemprange'],
    ['beforesettemprange', 'beforesettemprange'],
    ['applyfocus', 'applyfocus'],
    ['focuscell', 'focuscell'],
    ['beforerangedataapply', 'beforerangedataapply'],
    ['selectionchangeinit', 'selectionchangeinit'],
    ['beforerangecopyapply', 'beforerangecopyapply'],
    ['rangeeditapply', 'rangeeditapply'],
    ['clipboardrangecopy', 'clipboardrangecopy'],
    ['clipboardrangepaste', 'clipboardrangepaste'],
    ['beforekeydown', 'beforekeydown'],
    ['beforekeyup', 'beforekeyup'],
    ['beforecellsave', 'beforecellsave'],
    ['celledit', 'celledit'],
    ['scrollview', 'scrollview'],
    ['ref', 'ref'],
    ['scrollvirtual', 'scrollvirtual'],
    ['scrollviewport', 'scrollviewport'],
    ['resizeviewport', 'resizeviewport'],
    ['scrollchange', 'scrollchange'],
    ['scrollviewportsilent', 'scrollviewportsilent'],
    ['html', 'html']
]);

/**
 * Automatically adds new rows when pasted data is larger than current rows
 * @event newRows - is triggered when new rows are added. Data of new rows can be filled with default values. If the event is prevented, no rows will be added
 */
class AutoAddRowsPlugin extends BasePlugin {
    constructor(revogrid, providers) {
        super(revogrid, providers);
        this.addEventListener('beforepasteapply', evt => this.handleBeforePasteApply(evt));
    }
    handleBeforePasteApply(event) {
        const start = this.providers.selection.focused;
        const isEditing = this.providers.selection.edit != null;
        if (!start || isEditing) {
            return;
        }
        const rowLength = this.providers.data.stores.rgRow.store.get('items').length;
        const endRow = start.y + event.detail.parsed.length;
        if (rowLength < endRow) {
            const count = endRow - rowLength;
            const newRows = Array.from({ length: count }, (_, i) => ({
                index: rowLength + i,
                data: {},
            }));
            const event = this.emit('newRows', { newRows: newRows });
            if (event.defaultPrevented) {
                return;
            }
            const items = [
                ...this.providers.data.stores.rgRow.store.get('source'),
                ...event.detail.newRows.map(j => j.data),
            ];
            this.providers.data.setData(items);
        }
    }
}

export { AutoAddRowsPlugin, BasePlugin, REVOGRID_EVENTS };
