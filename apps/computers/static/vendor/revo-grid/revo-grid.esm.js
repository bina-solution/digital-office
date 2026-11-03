/*!
 * Built by Revolist OU ❤️
 */
import { p as promiseResolve, B as BUILD, c as consoleDevInfo, w as win, N as NAMESPACE, H, b as bootstrapLazy } from './index-Chp_81rd.js';
export { s as setNonce } from './index-Chp_81rd.js';
import { g as globalScripts } from './app-globals-B_B_OtEa.js';
import './theme.service-BmnDvr6P.js';

/*
 Stencil Client Patch Browser v4.43.2 | MIT Licensed | https://stenciljs.com
 */

var patchBrowser = () => {
  if (BUILD.isDev && !BUILD.isTesting) {
    consoleDevInfo("Running in development mode.");
  }
  if (BUILD.cloneNodeFix) {
    patchCloneNodeFix(H.prototype);
  }
  const scriptElm = BUILD.scriptDataOpts ? win.document && Array.from(win.document.querySelectorAll("script")).find(
    (s) => new RegExp(`/${NAMESPACE}(\\.esm)?\\.js($|\\?|#)`).test(s.src) || s.getAttribute("data-stencil-namespace") === NAMESPACE
  ) : null;
  const importMeta = import.meta.url;
  const opts = BUILD.scriptDataOpts ? (scriptElm || {})["data-opts"] || {} : {};
  if (importMeta !== "") {
    opts.resourcesUrl = new URL(".", importMeta).href;
  }
  return promiseResolve(opts);
};
var patchCloneNodeFix = (HTMLElementPrototype) => {
  const nativeCloneNodeFn = HTMLElementPrototype.cloneNode;
  HTMLElementPrototype.cloneNode = function(deep) {
    if (this.nodeName === "TEMPLATE") {
      return nativeCloneNodeFn.call(this, deep);
    }
    const clonedNode = nativeCloneNodeFn.call(this, false);
    const srcChildNodes = this.childNodes;
    if (deep) {
      for (let i = 0; i < srcChildNodes.length; i++) {
        if (srcChildNodes[i].nodeType !== 2) {
          clonedNode.appendChild(srcChildNodes[i].cloneNode(true));
        }
      }
    }
    return clonedNode;
  };
};

patchBrowser().then(async (options) => {
  await globalScripts();
  return bootstrapLazy([["revo-grid",[[260,"revo-grid",{"rowHeaders":[4,"row-headers"],"frameSize":[2,"frame-size"],"rowSize":[2,"row-size"],"colSize":[2,"col-size"],"range":[4],"readonly":[4],"resize":[4],"noHorizontalScrollTransfer":[4,"no-horizontal-scroll-transfer"],"canFocus":[4,"can-focus"],"useClipboard":[4,"use-clipboard"],"columns":[16],"source":[16],"pinnedTopSource":[16],"pinnedBottomSource":[16],"rowDefinitions":[16],"editors":[16],"applyOnClose":[4,"apply-on-close"],"plugins":[16],"columnTypes":[16],"theme":[1537],"rowClass":[513,"row-class"],"autoSizeColumn":[4,"auto-size-column"],"filter":[4],"sorting":[16],"focusTemplate":[16],"canMoveColumns":[4,"can-move-columns"],"trimmedRows":[16],"exporting":[4],"grouping":[16],"stretch":[8],"additionalData":[16],"disableVirtualX":[4,"disable-virtual-x"],"virtualX":[16],"disableVirtualY":[4,"disable-virtual-y"],"hideAttribution":[4,"hide-attribution"],"jobsBeforeRender":[16],"registerVNode":[16],"accessible":[4],"rtl":[4],"canDrag":[4,"can-drag"],"refresh":[64],"setDataAt":[64],"scrollToRow":[64],"scrollToColumnIndex":[64],"scrollToColumnProp":[64],"updateColumns":[64],"addTrimmed":[64],"scrollToCoordinate":[64],"setCellEdit":[64],"setCellsFocus":[64],"getSource":[64],"getVisibleSource":[64],"getSourceStore":[64],"getColumnStore":[64],"updateColumnSorting":[64],"clearSorting":[64],"getColumns":[64],"clearFocus":[64],"getPlugins":[64],"getFocused":[64],"getContentSize":[64],"getSelectedRange":[64],"refreshExtraElements":[64],"getProviders":[64]},[[5,"touchstart","mousedownHandle"],[5,"mousedown","mousedownHandle"],[5,"touchend","mouseupHandle"],[5,"mouseup","mouseupHandle"],[0,"rowdragstartinit","onRowDragStarted"],[0,"rowdragendinit","onRowDragEnd"],[0,"roworderchange","onRowOrderChange"],[0,"rowdragmoveinit","onRowDrag"],[0,"rowdragmousemove","onRowMouseMove"],[0,"celleditapply","onCellEdit"],[0,"rangeeditapply","onRangeEdit"],[0,"selectionchangeinit","onRangeChanged"],[0,"rowdropinit","onRowDropped"],[0,"beforeheaderclick","onHeaderClick"],[0,"beforecellfocusinit","onCellFocus"]],{"columnTypes":[{"columnTypesChanged":0}],"columns":[{"columnChanged":0}],"disableVirtualX":[{"disableVirtualXChanged":0}],"virtualX":[{"virtualXChanged":0}],"rowSize":[{"rowSizeChanged":0}],"theme":[{"themeChanged":0}],"source":[{"dataSourceChanged":0}],"pinnedBottomSource":[{"dataSourceChanged":0}],"pinnedTopSource":[{"dataSourceChanged":0}],"disableVirtualY":[{"disableVirtualYChanged":0}],"rowDefinitions":[{"rowDefChanged":0}],"trimmedRows":[{"trimmedRowsChanged":0}],"grouping":[{"groupingChanged":0}],"stretch":[{"applyStretch":0}],"filter":[{"applyFilter":0}],"sorting":[{"applySorting":0}],"rowHeaders":[{"rowHeadersChange":0}],"registerVNode":[{"registerOutsideVNodes":0}],"additionalData":[{"additionalDataChanged":0}],"rtl":[{"rtlChanged":0}],"plugins":[{"pluginsChanged":0}]}]]],["revogr-filter-panel",[[260,"revogr-filter-panel",{"filterNames":[16],"filterEntities":[16],"filterCaptions":[16],"disableDynamicFiltering":[4,"disable-dynamic-filtering"],"closeOnOutsideClick":[4,"close-on-outside-click"],"isFilterIdSet":[32],"filterId":[32],"currentFilterId":[32],"currentFilterType":[32],"changes":[32],"filterItems":[32],"draggedFilterId":[32],"dragOverFilterId":[32],"show":[64],"getChanges":[64]},[[5,"mousedown","onMouseDown"]]]]],["revogr-clipboard_3",[[0,"revogr-clipboard",{"readonly":[4],"doCopy":[64]},[[4,"paste","onPaste"],[4,"copy","copyStarted"],[4,"cut","cutStarted"]]],[0,"revogr-edit",{"editCell":[16],"column":[16],"editor":[16],"saveOnClose":[4,"save-on-close"],"additionalData":[8,"additional-data"],"cancelChanges":[64],"beforeDisconnect":[64]}],[0,"revogr-order-editor",{"parent":[16],"dimensionRow":[16],"dimensionCol":[16],"dataStore":[16],"rowType":[1,"row-type"],"dragStart":[64],"endOrder":[64],"clearOrder":[64]}]]],["revogr-data_4",[[260,"revogr-data",{"readonly":[4],"range":[4],"rowClass":[1,"row-class"],"additionalData":[8,"additional-data"],"rowSelectionStore":[16],"viewportRow":[16],"viewportCol":[16],"dimensionRow":[16],"colData":[16],"dataStore":[16],"type":[513],"colType":[513,"col-type"],"jobsBeforeRender":[16],"providers":[32],"updateCell":[64]},null,{"dataStore":[{"onDataStoreChange":0}],"colData":[{"onColDataChange":0}]}],[0,"revogr-header",{"viewportCol":[16],"dimensionCol":[16],"selectionStore":[16],"groups":[16],"groupingDepth":[2,"grouping-depth"],"readonly":[4],"canResize":[4,"can-resize"],"resizeHandler":[16],"colData":[16],"columnFilter":[4,"column-filter"],"type":[1],"additionalData":[8,"additional-data"]}],[260,"revogr-viewport-scroll",{"rowHeader":[4,"row-header"],"contentWidth":[2,"content-width"],"contentHeight":[2,"content-height"],"colType":[1,"col-type"],"noHorizontalScrollTransfer":[4,"no-horizontal-scroll-transfer"],"setScroll":[64],"changeScroll":[64],"applyScroll":[64]},[[0,"mousewheel-vertical","mousewheelVertical"],[0,"mousewheel-horizontal","mousewheelHorizontal"],[0,"scroll-coordinate","scrollApply"]]],[0,"vnode-html",{"redraw":[16]}]]],["revogr-attribution_7",[[0,"revogr-row-headers",{"height":[2],"dataPorts":[16],"headerProp":[16],"rowClass":[1,"row-class"],"resize":[4],"rowHeaderColumn":[16],"additionalData":[8,"additional-data"],"jobsBeforeRender":[16]}],[260,"revogr-overlay-selection",{"readonly":[4],"range":[4],"canDrag":[4,"can-drag"],"useClipboard":[4,"use-clipboard"],"selectionStore":[16],"dimensionRow":[16],"dimensionCol":[16],"dataStore":[16],"colData":[16],"lastCell":[16],"editors":[16],"applyChangesOnClose":[4,"apply-changes-on-close"],"additionalData":[8,"additional-data"],"isMobileDevice":[4,"is-mobile-device"]},[[5,"touchmove","onMouseMove"],[5,"mousemove","onMouseMove"],[5,"touchend","onMouseUp"],[5,"mouseup","onMouseUp"],[5,"mouseleave","onMouseUp"],[0,"dragstartcell","onCellDrag"],[4,"keyup","onKeyUp"],[4,"keydown","onKeyDown"]],{"selectionStore":[{"selectionServiceSet":0}],"dimensionRow":[{"createAutoFillService":0}],"dimensionCol":[{"createAutoFillService":0}],"dataStore":[{"columnServiceSet":0}],"colData":[{"columnServiceSet":0}]}],[0,"revogr-attribution"],[260,"revogr-focus",{"colType":[1,"col-type"],"rowType":[1,"row-type"],"selectionStore":[16],"dimensionRow":[16],"dimensionCol":[16],"dataStore":[16],"colData":[16],"focusTemplate":[16]}],[0,"revogr-scroll-virtual",{"dimension":[1],"realSize":[2,"real-size"],"virtualSize":[2,"virtual-size"],"clientSize":[2,"client-size"],"setScroll":[64],"changeScroll":[64]}],[0,"revogr-temp-range",{"selectionStore":[16],"dimensionRow":[16],"dimensionCol":[16]}],[0,"revogr-extra",{"nodes":[16],"update":[32],"refresh":[64]}]]]], options);
});
