/*!
 * Built by Revolist OU ❤️
 */
function isTouch(e) {
    return !!e.touches;
}
function verifyTouchTarget(touchEvent, focusClass) {
    if (focusClass && touchEvent) {
        if (!(touchEvent.target instanceof Element && touchEvent.target.classList.contains(focusClass))) {
            return false;
        }
    }
    return true;
}
/**
 * Function to get the value of a specific property from a MouseEvent or TouchEvent object.
 */
function getPropertyFromEvent(e, prop, focusClass // for touch events
) {
    // Check if the event is a touch event
    if (isTouch(e)) {
        // If the event has touches, get the first touch
        if (e.touches.length > 0) {
            const touchEvent = e.touches[0];
            // Check if the target of the touch event is the specified element
            if (!verifyTouchTarget(touchEvent, focusClass)) {
                // If not, return null
                return null;
            }
            // Get the value of the specified property from the touch event and return it
            return touchEvent[prop] || 0;
        }
        // If there are no touches, return null
        return null;
    }
    // If the event is not a touch event, get the value of the specified property from the event and return it
    return e[prop] || 0;
}

export { getPropertyFromEvent as g, verifyTouchTarget as v };
