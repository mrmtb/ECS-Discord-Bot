/**
 * reorder-keys decision table tests
 * @module site-editor/__tests__/reorder-keys
 *
 * Why this exists: `bridge.js` is a side-effecting script that installs
 * document listeners at import time and cannot be imported into a test
 * without a full iframe fixture. `reorder-keys.js` is the pure decision
 * pulled out of it so every branch — including the must-not-fire cases —
 * is unit-testable in isolation.
 */

import { describe, it, expect } from 'vitest';
import {
  reorderIntentFromKey,
  MOVE_SECTION_UP,
  MOVE_SECTION_DOWN,
  MOVE_BLOCK_UP,
  MOVE_BLOCK_DOWN,
} from '../reorder-keys.js';

describe('reorderIntentFromKey', () => {
  it('ArrowDown with handleFocused true and selectedKind section returns move-section-down', () => {
    const evt = { key: 'ArrowDown', altKey: false, target: null };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBe(MOVE_SECTION_DOWN);
  });

  it('ArrowUp under the same conditions returns move-section-up', () => {
    const evt = { key: 'ArrowUp', altKey: false, target: null };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBe(MOVE_SECTION_UP);
  });

  it('ArrowDown with handleFocused false and no Alt returns null (must never steal scrolling)', () => {
    const evt = { key: 'ArrowDown', altKey: false, target: null };
    const ctx = { selectedKind: 'section', handleFocused: false, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
  });

  it('ArrowDown with Alt held and selectedKind section returns move-section-down even without focus', () => {
    const evt = { key: 'ArrowDown', altKey: true, target: null };
    const ctx = { selectedKind: 'section', handleFocused: false, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBe(MOVE_SECTION_DOWN);
  });

  it('ArrowDown with Alt held and selectedKind block returns move-block-down', () => {
    const evt = { key: 'ArrowDown', altKey: true, target: null };
    const ctx = { selectedKind: 'block', handleFocused: false, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBe(MOVE_BLOCK_DOWN);
  });

  it('ArrowUp with Alt held and selectedKind block returns move-block-up', () => {
    const evt = { key: 'ArrowUp', altKey: true, target: null };
    const ctx = { selectedKind: 'block', handleFocused: false, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBe(MOVE_BLOCK_UP);
  });

  it('any arrow with textEditing true returns null, even with handle focused and Alt held', () => {
    const evt = { key: 'ArrowDown', altKey: true, target: null };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: true };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
  });

  it('any arrow whose target is an input returns null', () => {
    const input = document.createElement('input');
    const evt = { key: 'ArrowDown', altKey: true, target: input };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
  });

  it('any arrow whose target is a textarea returns null', () => {
    const textarea = document.createElement('textarea');
    const evt = { key: 'ArrowDown', altKey: true, target: textarea };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
  });

  it('any arrow whose target is a select returns null', () => {
    const select = document.createElement('select');
    const evt = { key: 'ArrowDown', altKey: true, target: select };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
  });

  it('any arrow whose target is contenteditable returns null', () => {
    const div = document.createElement('div');
    div.contentEditable = 'true';
    document.body.appendChild(div);
    const evt = { key: 'ArrowDown', altKey: true, target: div };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
    div.remove();
  });

  it('a non-arrow key returns null', () => {
    const evt = { key: 'Enter', altKey: false, target: null };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
  });

  it('selectedKind null with no focused handle returns null', () => {
    const evt = { key: 'ArrowDown', altKey: false, target: null };
    const ctx = { selectedKind: null, handleFocused: false, textEditing: false };
    expect(reorderIntentFromKey(evt, ctx)).toBeNull();
  });

  it('a synthetic event with no target does not throw', () => {
    const evt = { key: 'ArrowDown', altKey: false };
    const ctx = { selectedKind: 'section', handleFocused: true, textEditing: false };
    expect(() => reorderIntentFromKey(evt, ctx)).not.toThrow();
  });
});
