// app/static/js/site-editor/reorder-keys.js
'use strict';

// Pure decision: given a keydown event and the bridge's selection/focus/
// text-editing state, which reorder op (if any) does this keypress mean?
//
// This lives in its own file, separate from bridge.js, purely so it is
// unit-testable. bridge.js is a side-effecting script that installs
// document-level listeners at import time and cannot be imported into a
// test without a full iframe fixture; this module has ZERO side effects —
// no document access at module scope, no listeners, nothing exported
// besides the decision function and its op-kind constants. The caller
// (bridge.js) owns preventDefault() and the DOM; this module only decides.

export const MOVE_SECTION_UP = 'move-section-up';
export const MOVE_SECTION_DOWN = 'move-section-down';
export const MOVE_BLOCK_UP = 'move-block-up';
export const MOVE_BLOCK_DOWN = 'move-block-down';

const FORM_CONTROL_TAGS = ['INPUT', 'TEXTAREA', 'SELECT'];

function isFormControlOrEditable(target) {
  if (!target || typeof target !== 'object') return false;
  if (typeof target.tagName === 'string' && FORM_CONTROL_TAGS.includes(target.tagName.toUpperCase())) {
    return true;
  }
  if (target.isContentEditable) return true;
  return false;
}

/**
 * Decide which reorder op (if any) a keydown means.
 *
 * @param {{key: string, altKey: boolean, target: (Element|null|undefined)}} evt
 * @param {{selectedKind: ('section'|'block'|null), handleFocused: boolean, textEditing: boolean}} ctx
 * @returns {string|null} one of the MOVE_* op-kind constants, or null if this keypress means nothing.
 */
export function reorderIntentFromKey(evt, ctx) {
  if (!evt || (evt.key !== 'ArrowUp' && evt.key !== 'ArrowDown')) return null;
  if (ctx.textEditing) return null;
  if (isFormControlOrEditable(evt.target)) return null;

  const isDown = evt.key === 'ArrowDown';

  // Plain arrow: only fires while the drag handle itself has focus — a bare
  // arrow key must never steal page scrolling from a reader.
  if (ctx.handleFocused && !evt.altKey) {
    if (ctx.selectedKind === 'section') return isDown ? MOVE_SECTION_DOWN : MOVE_SECTION_UP;
    if (ctx.selectedKind === 'block') return isDown ? MOVE_BLOCK_DOWN : MOVE_BLOCK_UP;
    return null;
  }

  // Alt+arrow: the mouse-user shortcut once something is selected, whether
  // or not the handle currently has focus.
  if (evt.altKey) {
    if (ctx.selectedKind === 'section') return isDown ? MOVE_SECTION_DOWN : MOVE_SECTION_UP;
    if (ctx.selectedKind === 'block') return isDown ? MOVE_BLOCK_DOWN : MOVE_BLOCK_UP;
    return null;
  }

  return null;
}
