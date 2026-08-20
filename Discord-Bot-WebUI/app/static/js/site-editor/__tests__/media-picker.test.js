/**
 * Media Library picker tests
 * @module site-editor/__tests__/media-picker
 *
 * media-picker.js is the ONE Media Library picker in this codebase — mounted
 * by the site editor's slide-over panel (shell.js's pickImage()) and by the
 * Posts featured-image control (news_edit_flowbite.html). These tests
 * exercise it directly against a stubbed fetch so both mount points share
 * one proven implementation rather than drifting apart, per RESEARCH.md's
 * first named anti-pattern ("building a second Media Library picker for the
 * Posts featured-image field").
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openMediaPicker } from '../media-picker.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const ASSETS = [
  { id: 1, url: '/static/img/publeague/one.jpg', alt: 'Sounders crest', filename: 'one.jpg', title: 'one.jpg' },
  { id: 2, url: '/static/img/publeague/two.jpg', alt: '', filename: 'two.jpg', title: 'two.jpg' },
];

function stubFetch(assets = ASSETS) {
  return vi.fn((url) => {
    const u = String(url);
    if (u.includes('/media/list')) {
      return Promise.resolve({ json: () => Promise.resolve({ assets }) });
    }
    if (u.includes('/save')) {
      return Promise.resolve({ json: () => Promise.resolve({}) });
    }
    return Promise.reject(new Error(`unexpected fetch in test: ${u}`));
  });
}

function stubFailingListFetch() {
  return vi.fn(() => Promise.reject(new Error('network down')));
}

// Let queued microtasks (the fetch().then/await chains inside the module)
// resolve before assertions run.
async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function thumbButtons(mount) {
  return Array.from(mount.querySelectorAll('[data-asset-id]'));
}

describe('openMediaPicker', () => {
  let mount;

  beforeEach(() => {
    mount = document.createElement('div');
    document.body.appendChild(mount);
  });

  afterEach(() => {
    mount.remove();
    vi.restoreAllMocks();
    delete global.fetch;
  });

  it('renders one thumbnail per asset returned by the list endpoint, reading it exactly once per open', async () => {
    global.fetch = stubFetch();
    openMediaPicker({ mount, csrf: 'tok' });
    await flush();

    expect(thumbButtons(mount).length).toBe(ASSETS.length);
    const listCalls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/media/list'));
    expect(listCalls.length).toBe(1);
  });

  it('builds the grid from DOM nodes only — the module source never assigns a pre-built markup string', () => {
    const src = fs.readFileSync(path.join(__dirname, '..', 'media-picker.js'), 'utf8');
    // A behavioural assertion can't prove a negative about construction
    // technique; a source assertion can. Spelled via concatenation so this
    // very assertion doesn't self-trip the property it's checking for.
    const forbiddenProperty = 'inner' + 'HTML';
    expect(src).not.toContain(forbiddenProperty);
  });

  it('clicking a thumbnail highlights it and populates alt text; clicking a different one swaps both', async () => {
    global.fetch = stubFetch();
    openMediaPicker({ mount, csrf: 'tok' });
    await flush();

    const [first, second] = thumbButtons(mount);
    const altInput = mount.querySelector('[data-role="picker-alt-input"]');

    first.click();
    expect(first.getAttribute('data-selected')).toBe('1');
    expect(altInput.value).toBe('Sounders crest');

    second.click();
    expect(second.getAttribute('data-selected')).toBe('1');
    expect(first.getAttribute('data-selected')).toBeNull();
    expect(altInput.value).toBe('');
  });

  it('confirming after changing alt text POSTs form-encoded data to the alt-text save endpoint with X-CSRFToken, then resolves with the asset', async () => {
    global.fetch = stubFetch();
    const resultPromise = openMediaPicker({ mount, csrf: 'the-csrf-token' });
    await flush();

    const [first] = thumbButtons(mount);
    first.click();
    const altInput = mount.querySelector('[data-role="picker-alt-input"]');
    altInput.value = 'A better description';
    altInput.dispatchEvent(new Event('input'));

    mount.querySelector('[data-role="picker-use"]').click();
    await flush();

    const result = await resultPromise;
    expect(result.id).toBe(1);

    const saveCall = global.fetch.mock.calls.find(([url]) => String(url).includes('/media/1/save'));
    expect(saveCall).toBeTruthy();
    const [, saveOpts] = saveCall;
    expect(saveOpts.method).toBe('POST');
    expect(saveOpts.headers['X-CSRFToken']).toBe('the-csrf-token');
    expect(saveOpts.body).toBeInstanceOf(FormData);
    expect(saveOpts.body.get('alt_text')).toBe('A better description');
  });

  it('confirming WITHOUT changing the alt text does not call the save endpoint', async () => {
    global.fetch = stubFetch();
    const resultPromise = openMediaPicker({ mount, csrf: 'tok' });
    await flush();

    thumbButtons(mount)[0].click();
    mount.querySelector('[data-role="picker-use"]').click();
    await flush();

    const result = await resultPromise;
    expect(result.id).toBe(1);
    const saveCalls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/save'));
    expect(saveCalls.length).toBe(0);
  });

  it('cancelling resolves with a null-ish value and calls no save endpoint', async () => {
    global.fetch = stubFetch();
    const resultPromise = openMediaPicker({ mount, csrf: 'tok' });
    await flush();

    thumbButtons(mount)[0].click();  // select something, then cancel anyway
    mount.querySelector('[data-role="picker-cancel"]').click();
    await flush();

    const result = await resultPromise;
    expect(result == null).toBe(true);
    const saveCalls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/save'));
    expect(saveCalls.length).toBe(0);
  });

  it('a list endpoint that rejects leaves the mount showing an error message rather than throwing', async () => {
    global.fetch = stubFailingListFetch();
    expect(() => openMediaPicker({ mount, csrf: 'tok' })).not.toThrow();
    await flush();

    const error = mount.querySelector('[data-role="picker-error"]');
    expect(error).toBeTruthy();
    expect(error.classList.contains('hidden')).toBe(false);
    expect(error.textContent.length).toBeGreaterThan(0);
    expect(thumbButtons(mount).length).toBe(0);
  });

  it('calls the optional onClose callback when the picker settles, both on confirm and on cancel', async () => {
    global.fetch = stubFetch();
    const onCloseConfirm = vi.fn();
    openMediaPicker({ mount, csrf: 'tok', onClose: onCloseConfirm });
    await flush();
    thumbButtons(mount)[0].click();
    mount.querySelector('[data-role="picker-use"]').click();
    await flush();
    expect(onCloseConfirm).toHaveBeenCalledTimes(1);

    const mount2 = document.createElement('div');
    document.body.appendChild(mount2);
    const onCloseCancel = vi.fn();
    openMediaPicker({ mount: mount2, csrf: 'tok', onClose: onCloseCancel });
    await flush();
    mount2.querySelector('[data-role="picker-cancel"]').click();
    await flush();
    expect(onCloseCancel).toHaveBeenCalledTimes(1);
    mount2.remove();
  });

  it('exposes itself as window.ECSMediaPicker.open for template inline scripts', () => {
    expect(typeof window.ECSMediaPicker).toBe('object');
    expect(typeof window.ECSMediaPicker.open).toBe('function');
  });
});
