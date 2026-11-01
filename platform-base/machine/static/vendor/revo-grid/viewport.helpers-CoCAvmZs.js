/*!
 * Built by Revolist OU ❤️
 */
const FALLBACK_MAX_SCROLL_SIZE = 16000000;
const SCROLL_SIZE_GUARD = 1000000;
let detectedMaxScrollSize;
function getMaxScrollSize(doc = typeof document === 'undefined' ? undefined : document) {
    if (typeof detectedMaxScrollSize === 'number') {
        return detectedMaxScrollSize;
    }
    const body = doc === null || doc === void 0 ? void 0 : doc.body;
    if (body) {
        const ownerDocument = body.ownerDocument;
        const element = ownerDocument.createElement('div');
        element.style.cssText = [
            'height:1px',
            'left:-10000px',
            'overflow:scroll',
            'position:absolute',
            'top:-10000px',
            'visibility:hidden',
            'width:1px',
        ].join(';');
        const content = ownerDocument.createElement('div');
        content.style.height = `${FALLBACK_MAX_SCROLL_SIZE * 4}px`;
        element.appendChild(content);
        body.appendChild(element);
        detectedMaxScrollSize = Math.max(0, Math.min(element.scrollHeight, FALLBACK_MAX_SCROLL_SIZE * 4) - SCROLL_SIZE_GUARD);
        element.remove();
        if (detectedMaxScrollSize > SCROLL_SIZE_GUARD) {
            return detectedMaxScrollSize;
        }
        detectedMaxScrollSize = FALLBACK_MAX_SCROLL_SIZE;
        return detectedMaxScrollSize;
    }
    return FALLBACK_MAX_SCROLL_SIZE;
}
function getScrollDimension({ contentSize, clientSize, virtualSize = 0, maxScrollSize = getMaxScrollSize(), }) {
    const safeContentSize = Math.max(0, maxScrollSize - SCROLL_SIZE_GUARD);
    const size = Math.max(0, contentSize);
    const client = Math.max(0, clientSize);
    const viewport = Math.max(0, virtualSize || client);
    const logicalScrollSize = Math.max(0, size - viewport);
    const maxPhysicalScrollSize = Math.max(0, safeContentSize - client);
    const physicalScrollSize = Math.min(logicalScrollSize, maxPhysicalScrollSize);
    const physicalContentSize = client + physicalScrollSize;
    const isCompressed = logicalScrollSize > physicalScrollSize && physicalScrollSize > 0;
    const clampLogical = (coordinate) => Math.min(Math.max(0, coordinate || 0), logicalScrollSize);
    const clampPhysical = (coordinate) => Math.min(Math.max(0, coordinate || 0), physicalScrollSize);
    const toLogicalCoordinate = (coordinate) => {
        if (!logicalScrollSize || !physicalScrollSize) {
            return 0;
        }
        if (!isCompressed) {
            return clampLogical(coordinate);
        }
        return clampLogical((clampPhysical(coordinate) / physicalScrollSize) * logicalScrollSize);
    };
    const toPhysicalCoordinate = (coordinate) => {
        if (!logicalScrollSize || !physicalScrollSize) {
            return 0;
        }
        if (!isCompressed) {
            return clampPhysical(coordinate);
        }
        return clampPhysical((clampLogical(coordinate) / logicalScrollSize) * physicalScrollSize);
    };
    return {
        contentSize: size,
        clientSize: client,
        viewportSize: viewport,
        physicalContentSize,
        logicalScrollSize,
        physicalScrollSize,
        isCompressed,
        toLogicalCoordinate,
        toPhysicalCoordinate,
        getRenderOffset(coordinate) {
            const logical = clampLogical(coordinate);
            return logical - toPhysicalCoordinate(logical);
        },
    };
}

/**
 * Collects data for pinned columns in the required @ViewportProps format.
 */
/**
 * Represents the slot names for the viewport slots.
 */
const HEADER_SLOT = 'header'; // Slot name for the header slot
const FOOTER_SLOT = 'footer'; // Slot name for the footer slot
const CONTENT_SLOT = 'content'; // Slot name for the content slot
const DATA_SLOT = 'data'; // Slot name for the data slot
/**
 * Returns the last visible cell in the viewport for a given row type.
 * Coordinates are not zero-based and are relative to the viewport.
 * If needed to be zero-based they can be adjusted by subtracting 1.
 */
function getLastCell(data, rowType) {
    // Get the last visible column count from the viewport column data.
    const lastVisibleColumnCount = data.viewports[data.colType].store.get('realCount');
    // Get the last visible row count for the given row type from the viewport column data.
    const lastVisibleRowCount = data.viewports[rowType].store.get('realCount');
    // Return the last visible cell with the last visible column count and row count.
    return {
        x: lastVisibleColumnCount,
        y: lastVisibleRowCount,
    };
}
function viewportDataPartition(data, type, slot, fixed) {
    return {
        colData: data.colStore,
        viewportCol: data.viewports[data.colType].store,
        viewportRow: data.viewports[type].store,
        /**
         * lastCell is the last real coordinate + 1, saved to selection store
         */
        lastCell: getLastCell(data, type),
        slot,
        type,
        canDrag: !fixed,
        position: data.position,
        dataStore: data.rowStores[type].store,
        dimensionCol: data.dimensions[data.colType].store,
        dimensionRow: data.dimensions[type].store,
        style: fixed
            ? { height: `${data.dimensions[type].store.get('realSize')}px` }
            : undefined,
    };
}

export { CONTENT_SLOT as C, DATA_SLOT as D, FOOTER_SLOT as F, HEADER_SLOT as H, getScrollDimension as g, viewportDataPartition as v };
