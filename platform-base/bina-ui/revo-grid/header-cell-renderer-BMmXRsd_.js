/*!
 * Built by Revolist OU ❤️
 */
import { h } from './index-Chp_81rd.js';
import { Q as doPropMerge } from './column.service-C6hByxPy.js';

/**
 * Dispatches a custom event to a specified target element.
 *
 * @param target - The target element to dispatch the event to.
 * @param eventName - The name of the custom event.
 * @param detail - Optional. The detail of the custom event.
 * @returns The custom event that was dispatched.
 */
function dispatch(target, eventName, detail) {
    // Create a new CustomEvent with the specified event name and detail.
    const event = new CustomEvent(eventName, {
        detail,
        cancelable: true, // Indicates whether the event can be canceled.
        bubbles: true, // Indicates whether the event bubbles up through the DOM.
    });
    // Dispatch the event on the target element.
    target === null || target === void 0 ? void 0 : target.dispatchEvent(event);
    // Return the custom event that was dispatched.
    return event;
}
/**
 * Dispatches a custom event based on an existing event object and prevents the default behavior of the original event.
 *
 * @param e - The original event object containing the target and preventDefault method.
 * @param eventName - The name of the custom event.
 * @param detail - Optional. The detail of the custom event.
 * @returns The custom event that was dispatched.
 */
function dispatchByEvent(e, // The original event object containing the target and preventDefault method.
eventName, // The name of the custom event.
detail) {
    // Prevent the default behavior of the original event.
    e.preventDefault();
    // Dispatch the custom event to the target element specified in the original event object.
    return dispatch(e.target, eventName, detail);
}

var ResizeEvents;
(function (ResizeEvents) {
    ResizeEvents["start"] = "resize:start";
    ResizeEvents["move"] = "resize:move";
    ResizeEvents["end"] = "resize:end";
})(ResizeEvents || (ResizeEvents = {}));
const RESIZE_MASK = {
    'resizable-r': { bit: 0b0001, cursor: 'ew-resize' },
    'resizable-rb': { bit: 0b0011, cursor: 'se-resize' },
    'resizable-b': { bit: 0b0010, cursor: 's-resize' },
    'resizable-lb': { bit: 0b0110, cursor: 'sw-resize' },
    'resizable-l': { bit: 0b0100, cursor: 'w-resize' },
    'resizable-lt': { bit: 0b1100, cursor: 'nw-resize' },
    'resizable-t': { bit: 0b1000, cursor: 'n-resize' },
    'resizable-rt': { bit: 0b1001, cursor: 'ne-resize' },
};
const DISABLE_MASK = {
    w: 0b0100,
    h: 0b1000,
};
const defaultProps = (props) => {
    return Object.assign(Object.assign({}, props), { fitParent: props.fitParent || false, active: props.active || [], disableAttributes: props.disableAttributes || [], minWidth: props.minWidth || 0, minHeight: props.minHeight || 0 });
};
class ResizeDirective {
    constructor(initialProps, $event) {
        var _a, _b;
        this.initialProps = initialProps;
        this.$event = $event;
        this.mouseX = 0;
        this.mouseY = 0;
        this.width = 0;
        this.height = 0;
        this.changeX = 0;
        this.changeY = 0;
        this.disableCalcMap = 0b1111;
        this.props = defaultProps(initialProps);
        this.mouseMoveFunc = this.handleMove.bind(this);
        this.mouseUpFunc = this.handleUp.bind(this);
        this.minW = this.props.minWidth;
        this.minH = this.props.minHeight;
        this.maxW = (_a = this.props.maxWidth) !== null && _a !== void 0 ? _a : 0;
        this.maxH = (_b = this.props.maxHeight) !== null && _b !== void 0 ? _b : 0;
        this.parent = { width: 0, height: 0 };
        this.resizeState = 0;
    }
    set($el) {
        this.$el = $el;
        this.props.disableAttributes.forEach(attr => {
            switch (attr) {
                case 'l':
                    this.disableCalcMap &= -2;
                    break;
                case 't':
                    this.disableCalcMap &= -3;
                    break;
                case 'w':
                    this.disableCalcMap &= -5;
                    break;
                case 'h':
                    this.disableCalcMap &= -9;
            }
        });
    }
    emitEvent(eventName, additionalOptions) {
        var _a;
        if (!this.$event) {
            return;
        }
        const isLeft = (_a = this.activeResizer) === null || _a === void 0 ? void 0 : _a.classList.contains('resizable-l');
        this.$event(Object.assign({ eventName, width: this.width + this.changeX * (isLeft ? -1 : 1), height: this.height + this.changeY, changedX: this.changeX, changedY: this.changeY }, additionalOptions));
    }
    static isTouchEvent(e) {
        var _a;
        const event = e;
        return ((_a = event.touches) === null || _a === void 0 ? void 0 : _a.length) >= 0;
    }
    handleMove(event) {
        var _a;
        if (!this.resizeState) {
            return;
        }
        let eventY, eventX;
        if (ResizeDirective.isTouchEvent(event)) {
            eventY = event.touches[0].clientY;
            eventX = event.touches[0].clientX;
        }
        else {
            eventY = event.clientY;
            eventX = event.clientX;
        }
        let isX = this.resizeState & RESIZE_MASK['resizable-r'].bit ||
            this.resizeState & RESIZE_MASK['resizable-l'].bit;
        let isY = this.resizeState & RESIZE_MASK['resizable-t'].bit ||
            this.resizeState & RESIZE_MASK['resizable-b'].bit;
        if (isY && this.disableCalcMap & DISABLE_MASK.h) {
            let diffY = eventY - this.mouseY;
            let changedY = this.changeY + diffY;
            const newHeight = this.height + changedY;
            // if overcrossed min height
            if (newHeight < this.minH) {
                changedY = -(this.height - this.minH);
            }
            // if overcrossed max heiht
            if (this.maxH && newHeight > this.maxH) {
                changedY = this.maxH - this.height;
            }
            this.changeY = changedY;
            this.mouseY = eventY;
            if (this.activeResizer) {
                this.activeResizer.style.bottom = `${-this.changeY}px`;
            }
        }
        if (isX && this.disableCalcMap & DISABLE_MASK.w) {
            const isLeft = (_a = this.activeResizer) === null || _a === void 0 ? void 0 : _a.classList.contains('resizable-l');
            let diffX = eventX - this.mouseX;
            let changedX = this.changeX + diffX;
            const newWidth = this.width + changedX * (isLeft ? -1 : 1);
            // if overcrossed min width
            if (newWidth < this.minW) {
                changedX = -(this.width - this.minW);
            }
            // if overcrossed max width
            if (this.maxW && newWidth > this.maxW) {
                changedX = this.maxW - this.width;
            }
            this.changeX = changedX;
            this.mouseX = eventX;
            if (this.activeResizer) {
                if (!isLeft) {
                    this.activeResizer.style.right = `${-this.changeX}px`;
                }
                else {
                    this.activeResizer.style.left = `${this.changeX}px`;
                }
            }
        }
        this.emitEvent(ResizeEvents.move);
    }
    handleDown(event) {
        if (event.defaultPrevented) {
            return;
        }
        // stop other events if resize in progress
        event.preventDefault();
        this.dropInitial();
        for (let elClass in RESIZE_MASK) {
            const target = event.target;
            if (this.$el.contains(target) && (target === null || target === void 0 ? void 0 : target.classList.contains(elClass))) {
                document.body.style.cursor = RESIZE_MASK[elClass].cursor;
                if (ResizeDirective.isTouchEvent(event)) {
                    this.setInitials(event.touches[0], target);
                }
                else {
                    event.preventDefault && event.preventDefault();
                    this.setInitials(event, target);
                }
                this.resizeState = RESIZE_MASK[elClass].bit;
                const eventName = ResizeEvents.start;
                this.emitEvent(eventName);
                break;
            }
        }
        this.bindMove();
    }
    handleUp(e) {
        e.preventDefault();
        if (this.resizeState !== 0) {
            this.resizeState = 0;
            document.body.style.cursor = '';
            const eventName = ResizeEvents.end;
            this.emitEvent(eventName);
        }
        this.dropInitial();
        this.unbindMove();
    }
    setInitials({ clientX, clientY }, target) {
        var _a, _b, _c, _d;
        const computedStyle = getComputedStyle(this.$el);
        this.$el.classList.add('active');
        this.activeResizer = target;
        if (this.disableCalcMap & DISABLE_MASK.w) {
            this.mouseX = clientX;
            this.width = this.$el.clientWidth;
            this.parent.width = (_b = (_a = this.$el.parentElement) === null || _a === void 0 ? void 0 : _a.clientWidth) !== null && _b !== void 0 ? _b : 0;
            // min width
            const minPaddingX = parseFloat(computedStyle.paddingLeft) +
                parseFloat(computedStyle.paddingRight);
            this.minW = Math.max(minPaddingX, this.initialProps.minWidth || 0);
            // max width
            if (this.initialProps.maxWidth) {
                this.maxW = Math.max(this.width, this.initialProps.maxWidth);
            }
        }
        if (this.disableCalcMap & DISABLE_MASK.h) {
            this.mouseY = clientY;
            this.height = this.$el.clientHeight;
            this.parent.height = (_d = (_c = this.$el.parentElement) === null || _c === void 0 ? void 0 : _c.clientHeight) !== null && _d !== void 0 ? _d : 0;
            // min height
            const minPaddingY = parseFloat(computedStyle.paddingTop) +
                parseFloat(computedStyle.paddingBottom);
            this.minH = Math.max(minPaddingY, this.initialProps.minHeight || 0);
            // max height
            if (this.initialProps.maxHeight) {
                this.maxH = Math.max(this.height, this.initialProps.maxHeight);
            }
        }
    }
    dropInitial() {
        this.changeX = this.changeY = this.minW = this.minH;
        this.width = this.height = 0;
        if (this.activeResizer) {
            this.activeResizer.removeAttribute('style');
        }
        this.$el.classList.remove('active');
        this.activeResizer = undefined;
    }
    bindMove() {
        document.documentElement.addEventListener('mouseup', this.mouseUpFunc, true);
        document.documentElement.addEventListener('touchend', this.mouseUpFunc, true);
        document.documentElement.addEventListener('mousemove', this.mouseMoveFunc, true);
        document.documentElement.addEventListener('touchmove', this.mouseMoveFunc, true);
        document.documentElement.addEventListener('mouseleave', this.mouseUpFunc);
    }
    unbindMove() {
        document.documentElement.removeEventListener('mouseup', this.mouseUpFunc, true);
        document.documentElement.removeEventListener('touchend', this.mouseUpFunc, true);
        document.documentElement.removeEventListener('mousemove', this.mouseMoveFunc, true);
        document.documentElement.removeEventListener('touchmove', this.mouseMoveFunc, true);
        document.documentElement.removeEventListener('mouseleave', this.mouseUpFunc);
    }
}

const ResizableElement = (props, children) => {
    const resizeEls = [];
    const directive = (props.canResize &&
        new ResizeDirective(props, e => {
            var _a;
            if (e.eventName === ResizeEvents.end) {
                (_a = props.onResize) === null || _a === void 0 ? void 0 : _a.call(props, e);
            }
        })) ||
        null;
    if (props.active && props.canResize) {
        for (let p in props.active) {
            resizeEls.push(h("div", { onClick: e => e.preventDefault(), onDblClick: e => {
                    var _a;
                    e.preventDefault();
                    (_a = props.onDblClick) === null || _a === void 0 ? void 0 : _a.call(props, e);
                }, onMouseDown: (e) => directive === null || directive === void 0 ? void 0 : directive.handleDown(e), onTouchStart: (e) => directive === null || directive === void 0 ? void 0 : directive.handleDown(e), class: `resizable resizable-${props.active[p]}` }));
        }
    }
    return (h("div", Object.assign({}, props, { ref: e => e && (directive === null || directive === void 0 ? void 0 : directive.set(e)) }), children, resizeEls));
};

const ON_COLUMN_CLICK = 'columnclick';
const HeaderCellRenderer = ({ data, props, additionalData }, children) => {
    let colTemplate = (data === null || data === void 0 ? void 0 : data.name) || '';
    let cellProps = props;
    if (data === null || data === void 0 ? void 0 : data.columnTemplate) {
        colTemplate = data.columnTemplate(h, data, additionalData);
    }
    if (data === null || data === void 0 ? void 0 : data.columnProperties) {
        const extra = data.columnProperties(data);
        if (extra) {
            cellProps = doPropMerge(props, extra);
        }
    }
    const resizeProps = Object.assign(Object.assign({}, cellProps), { onMouseDown(e) {
            dispatch(e.currentTarget, ON_COLUMN_CLICK, {
                data,
                event: e,
            });
        } });
    return (h(ResizableElement, Object.assign({}, resizeProps), h("div", { class: "header-content" }, colTemplate), children));
};

export { HeaderCellRenderer as H, ON_COLUMN_CLICK as O, dispatchByEvent as a, dispatch as d };
