// app/static/js/site-editor/media-picker.js
'use strict';

// The ONE Media Library picker in this codebase — browse, search, upload,
// alt-text edit, confirm. It is mounted in exactly two places: the site
// editor's slide-over panel (shell.js's pickImage(), a thin wrapper around
// this module) and the Posts featured-image control
// (news_edit_flowbite.html, reached via window.ECSMediaPicker below).
// Duplicating this logic anywhere else is the exact drift RESEARCH.md's
// first named anti-pattern calls out — "building a second Media Library
// picker for the Posts featured-image field" — and is the same kind of
// unsynchronized-copy that caused Phase 2's footer bug. If a third mount
// point is ever needed, mount THIS module into it; do not write a new one.
//
// Every node here is built with document.createElement and populated with
// textContent/setAttribute — assigning a pre-built markup string to an
// element's contents happens nowhere in this file. The asset id is an
// integer and the filename/alt text are author-supplied; building nodes
// removes the escaping question entirely rather than answering it.

/**
 * Open the Media Library picker into `opts.mount`.
 *
 * @param {{mount: Element, csrf?: string, onClose?: () => void}} opts
 * @returns {Promise<Object|null>} resolves with the chosen asset (the same
 *   shape MediaAsset.to_dict() returns: id/url/alt/title/filename/...), or
 *   null if the picker was cancelled.
 */
export function openMediaPicker(opts) {
  const mount = opts && opts.mount;
  const csrf = (opts && opts.csrf) || '';
  const onClose = (opts && typeof opts.onClose === 'function') ? opts.onClose : () => {};

  return new Promise((resolve) => {
    if (!mount) { resolve(null); return; }
    mount.textContent = '';

    let assets = [];
    let selected = null;
    let altDirty = false;
    let settled = false;

    // ---- search ----
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.setAttribute('data-role', 'picker-search');
    searchInput.setAttribute('placeholder', 'Search by filename or alt text…');
    searchInput.className = 'mb-3 w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm';
    mount.appendChild(searchInput);

    // ---- upload ----
    const upLabel = document.createElement('label');
    upLabel.className = 'block mb-3 cursor-pointer rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 p-4 text-center text-sm text-gray-500 hover:border-ecs-green';
    const upText = document.createElement('span');
    upText.textContent = 'Upload a new image';
    upLabel.appendChild(upText);
    const upInput = document.createElement('input');
    upInput.type = 'file';
    upInput.accept = 'image/*';
    upInput.className = 'hidden';
    upLabel.appendChild(upInput);
    mount.appendChild(upLabel);

    // ---- error banner (shown when the list load or an upload fails) ----
    const errorEl = document.createElement('p');
    errorEl.className = 'mb-3 hidden text-sm text-red-600 dark:text-red-400';
    errorEl.setAttribute('data-role', 'picker-error');
    mount.appendChild(errorEl);

    // ---- grid ----
    const grid = document.createElement('div');
    grid.className = 'grid grid-cols-3 gap-2';
    grid.setAttribute('data-role', 'picker-grid');
    mount.appendChild(grid);

    // ---- persistent alt-text field (the fix over the old one-time prompt) ----
    const altWrap = document.createElement('div');
    altWrap.className = 'mt-3 hidden';
    const altLabel = document.createElement('label');
    altLabel.className = 'block text-sm font-medium mb-1.5';
    altLabel.textContent = 'Alt text (for screen readers)';
    const altInput = document.createElement('input');
    altInput.type = 'text';
    altInput.setAttribute('data-role', 'picker-alt-input');
    altInput.className = 'w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm';
    altInput.addEventListener('input', () => { altDirty = true; });
    altWrap.appendChild(altLabel);
    altWrap.appendChild(altInput);
    mount.appendChild(altWrap);

    // ---- confirm / cancel ----
    const btnRow = document.createElement('div');
    btnRow.className = 'mt-3 flex gap-2';
    const useBtn = document.createElement('button');
    useBtn.type = 'button';
    useBtn.setAttribute('data-role', 'picker-use');
    useBtn.textContent = 'Use';
    useBtn.disabled = true;
    useBtn.className = 'flex-1 rounded-lg bg-ecs-green px-4 py-2.5 text-sm font-semibold text-white hover:bg-ecs-green-dark disabled:opacity-50 disabled:cursor-not-allowed';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.setAttribute('data-role', 'picker-cancel');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.className = 'flex-1 rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-2.5 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50';
    btnRow.appendChild(useBtn);
    btnRow.appendChild(cancelBtn);
    mount.appendChild(btnRow);

    function settle(value) {
      if (settled) return;
      settled = true;
      onClose();
      resolve(value);
    }

    cancelBtn.addEventListener('click', () => settle(null));

    useBtn.addEventListener('click', async () => {
      if (!selected) return;
      if (altDirty) {
        const fd = new FormData();
        fd.append('alt_text', altInput.value);
        try {
          await fetch(`/admin-panel/public-site/media/${selected.id}/save`,
            { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd });
        } catch (e) {
          // Best-effort — the picker still resolves with the chosen asset
          // even if the alt-text save itself failed to reach the server.
        }
        selected = { ...selected, alt: altInput.value };
      }
      settle(selected);
    });

    function markSelected(btn) {
      grid.querySelectorAll('[data-selected]').forEach((b) => {
        b.removeAttribute('data-selected');
        b.classList.remove('ring-2', 'ring-ecs-green');
      });
      btn.setAttribute('data-selected', '1');
      btn.classList.add('ring-2', 'ring-ecs-green');
    }

    function selectAsset(asset, btn) {
      selected = asset;
      altDirty = false;
      altInput.value = asset.alt || '';
      altWrap.classList.remove('hidden');
      useBtn.disabled = false;
      markSelected(btn);
    }

    function renderGrid(list) {
      grid.textContent = '';
      list.forEach((a) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.setAttribute('data-asset-id', String(a.id));
        btn.className = 'aspect-square overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700 hover:ring-2 hover:ring-ecs-green';
        const img = document.createElement('img');
        img.src = a.url;
        img.alt = a.alt || '';
        img.className = 'h-full w-full object-cover';
        btn.appendChild(img);
        btn.addEventListener('click', () => selectAsset(a, btn));
        grid.appendChild(btn);
      });
    }

    searchInput.addEventListener('input', () => {
      const q = searchInput.value.trim().toLowerCase();
      if (!q) { renderGrid(assets); return; }
      renderGrid(assets.filter((a) =>
        (a.filename || '').toLowerCase().includes(q) ||
        (a.alt || '').toLowerCase().includes(q)));
    });

    upInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      let data = {};
      try {
        const r = await fetch('/admin-panel/public-site/upload-image',
          { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd });
        data = await r.json();
      } catch (err) {
        errorEl.textContent = 'Upload failed — the file may be too large.';
        errorEl.classList.remove('hidden');
        return;
      }
      if (data.url) {
        errorEl.classList.add('hidden');
        await loadAssets();
      } else {
        errorEl.textContent = data.error || 'Upload failed';
        errorEl.classList.remove('hidden');
      }
    });

    async function loadAssets() {
      try {
        const r = await fetch('/admin-panel/public-site/media/list');
        const data = await r.json();
        assets = data.assets || [];
        errorEl.classList.add('hidden');
        renderGrid(assets);
      } catch (e) {
        assets = [];
        grid.textContent = '';
        errorEl.textContent = 'Could not load the Media Library — try again.';
        errorEl.classList.remove('hidden');
      }
    }

    loadAssets();
  });
}

// Reachable as a plain global too, so a template's bare <script> (the Posts
// featured-image control) can call it without any import machinery.
if (typeof window !== 'undefined') {
  window.ECSMediaPicker = { open: openMediaPicker };
}
