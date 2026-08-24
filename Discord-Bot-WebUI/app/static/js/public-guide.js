/**
 * Public Guide reader chrome (progressive enhancement).
 *
 * Loaded ONLY on the public /guide page (see public/page_sections.html). The
 * guide is one long sections document (~9 chapters, 40+ subsections) rendered
 * server-side; this module adds navigation on top of whatever headings exist
 * in the DOM, so it keeps working after admins edit the page in the site
 * builder:
 *   - sticky toolbar under the site nav: Contents button, scrollspy label
 *     showing the current chapter, search, and a reading-progress bar
 *   - dropdown panel with a two-level TOC (h2 chapters / h3 subsections)
 *   - client-side full-text search with jump-to-match + flash highlight
 *   - back-to-top button
 *
 * Design contract (design.md): every class string below is a COMPLETE STATIC
 * STRING — tailwind.config.js scans app/static/js/**, but a concatenated class
 * name is purged silently. Colour is var-backed only (`ecs-green-ink` /
 * `ecs-green-300` for ink, flat `ecs-green` for fills and tints, `paper` /
 * `paper-dark` for grounds); every colour utility carries a `dark:` pair (C7);
 * transitions name their properties and carry `motion-reduce:` (§ 8); icon-only
 * controls get an `sr-only` label and `aria-hidden` glyphs (§ 7.9); interactive
 * rows clear the 44px floor with `min-h-11` (C8).
 *
 * No jQuery on purpose — the Vite inject() plugin only adds the import when
 * `$` is referenced, and this must stay a small standalone chunk.
 */

const MIN_CHAPTERS = 3;        // below this the page isn't "long" — do nothing
const SEARCH_MIN_CHARS = 2;
const SEARCH_MAX_RESULTS = 40;

/* design.md § 8: smooth scrolling is opt-in per user. Read the query at call
   time (not once at load) so a mid-session OS change is honoured. */
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
function scrollBehavior() {
  return reduceMotion.matches ? 'auto' : 'smooth';
}

function esc(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function slugify(text) {
  return text.toLowerCase().trim()
    .replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-').slice(0, 80) || 'section';
}

/* Ensure every h2/h3 has a unique id so the TOC and search can link to it.
   Seeded chapters ship h2 ids from the converter; h3s (and any headings admins
   add later in the builder) get generated ones. */
function ensureIds(headings) {
  const seen = new Set(headings.map((h) => h.id).filter(Boolean));
  headings.forEach((h) => {
    if (!h.id) {
      let base = slugify(h.textContent); let id = base; let n = 2;
      while (seen.has(id)) id = `${base}-${n++}`;
      seen.add(id); h.id = id;
    }
  });
}

/* Outline = ordered chapters (h2) each owning the h3s that follow it. */
function buildOutline(main) {
  const headings = Array.from(main.querySelectorAll('h2, h3'));
  ensureIds(headings);
  const chapters = [];
  headings.forEach((h) => {
    if (h.tagName === 'H2') {
      chapters.push({ el: h, title: h.textContent.trim(), subs: [] });
    } else if (chapters.length) {
      chapters[chapters.length - 1].subs.push({ el: h, title: h.textContent.trim() });
    }
  });
  return { chapters, headings };
}

/* Flat text index for search: every prose-ish element tagged with its chapter.
   Content ABOVE the first h2 (the hero blurb, the intro/download paragraphs)
   is real on-page text and must be findable too — it gets a pseudo-chapter. */
function buildSearchIndex(main, chapters) {
  const index = [];
  let chapter = { title: 'Introduction' };
  const walk = main.querySelectorAll('h2, h3, h4, p, li, dt, dd');
  walk.forEach((el) => {
    if (el.tagName === 'H2') {
      const c = chapters.find((ch) => ch.el === el);
      if (c) chapter = c;
      return; // chapter titles are already in the TOC
    }
    // Skip nav content (the server-rendered "What's inside" card): its links
    // duplicate chapter titles and the card is hidden once we mount, so a
    // search hit there would jump to an invisible element.
    if (el.closest('nav')) return;
    const text = el.textContent.replace(/\s+/g, ' ').trim();
    if (text) index.push({ el, text, chapter, isHeading: el.tagName === 'H3' });
  });
  return index;
}

/* Flat `ecs-green` is a FILL, never an ink — as a 20/30% wash behind inherited
   body ink it stays a tint, which is the one job it has (design.md § 3.1). */
function snippet(text, q) {
  const at = text.toLowerCase().indexOf(q.toLowerCase());
  const start = Math.max(0, at - 40);
  const end = Math.min(text.length, at + q.length + 60);
  const pre = (start > 0 ? '…' : '') + esc(text.slice(start, at));
  const hit = esc(text.slice(at, at + q.length));
  const post = esc(text.slice(at + q.length, end)) + (end < text.length ? '…' : '');
  return `${pre}<mark class="bg-ecs-green/20 px-0.5 text-inherit dark:bg-ecs-green/30">${hit}</mark>${post}`;
}

function flashTarget(el) {
  const box = el.closest('li, dd, dt, p, h2, h3, h4') || el;
  box.classList.add('transition-colors', 'duration-700', 'ease-out',
    'motion-reduce:transition-none', 'rounded-lg',
    'bg-ecs-green/15', 'dark:bg-ecs-green/25');
  setTimeout(() => box.classList.remove('bg-ecs-green/15', 'dark:bg-ecs-green/25'), 1600);
}

function init() {
  const main = document.querySelector('main');
  if (!main) return;
  const { chapters } = buildOutline(main);
  if (chapters.length < MIN_CHAPTERS) return;
  const searchIndex = buildSearchIndex(main, chapters);

  // NOTE the inline "What's inside" card is NOT hidden here any more. It is
  // gated server-side by the section's `hide_at: 'xl'`, so it is the contents
  // below xl (where there is no gutter for the rail) and the rail takes over
  // above it. Hiding a whole section from JS was a second post-paint shift.

  // ---- Toolbar ----------------------------------------------------------
  // The shell is SERVER-RENDERED (public/_guide_chrome.html) and this module
  // only enhances it. It used to be built here and main.prepend()ed, which
  // pushed the whole document down by the bar's own 48px after first paint —
  // a guaranteed layout shift on the site's longest page, every single load.
  // If the markup is absent there is nothing to enhance: bail rather than
  // resurrect the old injection path, so the two can never drift.
  const bar = document.querySelector('[data-guide-bar]');
  if (!bar) return;

  // NOTE anchor clearance is NOT set here any more. base_public.html declares
  // it for the guide in @layer base, because the inline contents card is a set
  // of anchors that has to work before this module runs — and did not.
  // Per-heading scroll-margin would STACK on top of the shell's padding and
  // overshoot every jump, so it stays a single declaration (design.md § 5.5).

  const panel = bar.querySelector('[data-guide-panel]');
  const list = bar.querySelector('[data-guide-list]');
  const searchInput = bar.querySelector('[data-guide-search]');
  const toggleBtn = bar.querySelector('[data-guide-toggle]');
  const chevron = bar.querySelector('[data-guide-chevron]');
  const currentLabel = bar.querySelector('[data-guide-current]');
  const progress = bar.querySelector('[data-guide-progress]');

  // The xl gutter rail, also server-rendered. Absent below xl only in the sense
  // that CSS hides it — the nodes exist, so the scrollspy can drive it without
  // a resize listener and it is already correct the moment it becomes visible.
  const railLinks = new Map();
  document.querySelectorAll('[data-guide-rail-link]').forEach((a) => {
    railLinks.set(a.getAttribute('data-guide-rail-link'), a);
  });
  /* Complete static strings on both sides of the toggle — tailwind.config.js
     scans app/static/js/**, but it cannot see a class name built by
     concatenation. */
  const RAIL_ON = ['border-ecs-green-ink', 'text-gray-900', 'font-semibold',
    'dark:border-ecs-green-300', 'dark:text-white'];
  const RAIL_OFF = ['border-transparent', 'text-gray-600', 'dark:text-gray-400'];
  function markRail(id) {
    railLinks.forEach((a, key) => {
      const on = key === id;
      a.classList.toggle('border-transparent', !on);
      RAIL_ON.forEach((c) => a.classList.toggle(c, on));
      RAIL_OFF.filter((c) => c !== 'border-transparent')
        .forEach((c) => a.classList.toggle(c, !on));
      if (on) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
  }

  // ---- TOC / search result rendering ------------------------------------
  // Shared row classes live OUTSIDE the active/inactive ternary so an active
  // row can never lose its focus ring (design.md § 7.3).
  const rowBase = 'flex w-full min-h-11 items-center rounded-lg py-2 text-sm transition-colors duration-150 ease-out hover:bg-ecs-green/[0.08] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ecs-green-ink focus-visible:ring-offset-2 focus-visible:ring-offset-white motion-reduce:transition-none dark:hover:bg-white/[0.06] dark:focus-visible:ring-ecs-green-300 dark:focus-visible:ring-offset-paper-dark';
  const chapterLink = `${rowBase} px-3 font-semibold`;
  const subLink = `${rowBase} pl-10 pr-3`;

  function renderToc(activeId) {
    list.innerHTML = chapters.map((c, i) => {
      const on = c.el.id === activeId;
      const subs = c.subs.map((s) => {
        const sOn = s.el.id === activeId;
        return `<a href="#${s.el.id}"${sOn ? ' aria-current="location"' : ''} class="${subLink} ${sOn
          ? 'font-medium text-ecs-green-ink dark:text-ecs-green-300'
          : 'text-gray-600 dark:text-gray-300'}"><span class="min-w-0">${esc(s.title)}</span></a>`;
      }).join('');
      return `<a href="#${c.el.id}"${on ? ' aria-current="location"' : ''} class="${chapterLink} ${on
        ? 'text-ecs-green-ink dark:text-ecs-green-300'
        : 'text-gray-900 dark:text-white'}">
          <span class="mr-2 w-5 shrink-0 text-right text-xs font-normal tabular-nums text-gray-500 dark:text-gray-400" aria-hidden="true">${i + 1}</span><span class="min-w-0">${esc(c.title)}</span>
        </a>${subs}`;
    }).join('');
  }

  function renderResults(q) {
    const needle = q.toLowerCase();
    // Collect ALL matches, THEN rank and cap — capping the document-order walk
    // first would let 40 early body hits crowd out a matching heading in a
    // late chapter, defeating the headings-first ranking where it matters.
    let hits = searchIndex.filter((item) => item.text.toLowerCase().includes(needle));
    // Heading hits first — they're better jump targets than body text.
    hits.sort((a, b) => Number(b.isHeading) - Number(a.isHeading));
    hits = hits.slice(0, SEARCH_MAX_RESULTS);
    if (!hits.length) {
      list.innerHTML = `<p class="px-3 py-6 text-center text-sm text-gray-600 dark:text-gray-300">
        No matches for “${esc(q)}”.</p>`;
      return;
    }
    list.innerHTML = hits.map((h, i) => `
      <button type="button" data-guide-hit="${i}"
              class="flex w-full min-h-11 flex-col justify-center gap-0.5 rounded-lg px-3 py-2 text-left transition-colors duration-150 ease-out hover:bg-ecs-green/[0.08] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ecs-green-ink focus-visible:ring-offset-2 focus-visible:ring-offset-white motion-reduce:transition-none dark:hover:bg-white/[0.06] dark:focus-visible:ring-ecs-green-300 dark:focus-visible:ring-offset-paper-dark">
        <span class="block text-xs font-bold uppercase tracking-[0.14em] text-ecs-green-ink dark:text-ecs-green-300">
          ${esc(h.chapter.title)}</span>
        <span class="block text-sm text-gray-700 dark:text-gray-200">${snippet(h.text, q)}</span>
      </button>`).join('');
    list.querySelectorAll('[data-guide-hit]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const hit = hits[Number(btn.dataset.guideHit)];
        closePanel();
        // scroll-padding-top on <html> clears the sticky stack for us, so the
        // hit element needs no scroll-margin of its own.
        hit.el.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
        flashTarget(hit.el);
      });
    });
  }

  // ---- Panel open/close --------------------------------------------------
  let open = false;
  function openPanel(focusSearch) {
    open = true;
    panel.classList.remove('hidden');
    toggleBtn.setAttribute('aria-expanded', 'true');
    chevron.classList.add('rotate-180');
    if (!searchInput.value.trim()) renderToc(currentId);
    if (focusSearch) searchInput.focus();
  }
  function closePanel() {
    open = false;
    panel.classList.add('hidden');
    toggleBtn.setAttribute('aria-expanded', 'false');
    chevron.classList.remove('rotate-180');
  }
  toggleBtn.addEventListener('click', () => (open ? closePanel() : openPanel(false)));
  bar.querySelector('[data-guide-search-open]').addEventListener('click', () => openPanel(true));
  document.addEventListener('click', (e) => {
    if (open && !bar.contains(e.target)) closePanel();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && open) { closePanel(); return; }
    // "/" jumps to guide search unless the user is already typing somewhere.
    if (e.key === '/' && !open && !/^(input|textarea|select)$/i.test(e.target.tagName)) {
      e.preventDefault(); openPanel(true);
    }
  });
  list.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    // Smooth-scroll TOC jumps ourselves (matches search-result jumps) but keep
    // the hash in the URL so the position is shareable/bookmarkable.
    const target = document.getElementById(a.getAttribute('href').slice(1));
    if (target) {
      e.preventDefault();
      closePanel();
      target.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
      history.pushState(null, '', a.getAttribute('href'));
    } else {
      closePanel();
    }
  });
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim();
    if (q.length >= SEARCH_MIN_CHARS) renderResults(q);
    else renderToc(currentId);
  });

  // ---- Scrollspy + progress + back-to-top -------------------------------
  const topBtn = document.createElement('button');
  topBtn.type = 'button';
  topBtn.className = 'fixed bottom-5 right-5 z-30 hidden h-11 w-11 items-center justify-center '
    + 'rounded-full bg-ecs-green-ink text-white shadow-md dark:bg-ecs-green-ink dark:text-white dark:shadow-none '
    + 'transition-[background-color,transform,color] duration-150 ease-out hover:bg-ecs-green-ink/90 '
    + 'active:translate-y-px active:shadow-none active:brightness-95 '
    + 'focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ecs-green-ink '
    + 'focus-visible:ring-offset-2 focus-visible:ring-offset-paper '
    + 'motion-reduce:transition-none motion-reduce:transform-none '
    + 'dark:focus-visible:ring-ecs-green-300 dark:focus-visible:ring-offset-paper-dark';
  topBtn.innerHTML = '<i class="ti ti-arrow-up text-lg" aria-hidden="true"></i><span class="sr-only">Back to top</span>';
  topBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: scrollBehavior() }));
  document.body.appendChild(topBtn);

  const spyTargets = [];
  chapters.forEach((c) => {
    spyTargets.push({ el: c.el, chapter: c, label: c.title });
    c.subs.forEach((s) => spyTargets.push({ el: s.el, chapter: c, label: `${c.title} › ${s.title}` }));
  });

  let currentId = null;
  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const line = bar.getBoundingClientRect().bottom + 16;
      let active = null;
      for (const t of spyTargets) {
        if (t.el.getBoundingClientRect().top <= line) active = t;
        else break;
      }
      currentLabel.textContent = active ? active.label : '';
      const newId = active ? active.el.id : null;
      if (newId !== currentId) {
        currentId = newId;
        if (open && searchInput.value.trim().length < SEARCH_MIN_CHARS) renderToc(currentId);
        // The rail lists CHAPTERS (h2) only, so walk up from a subsection to
        // the chapter that owns it — otherwise scrolling through h3s clears the
        // marker instead of holding it on the chapter you are reading.
        markRail(active && active.chapter ? active.chapter.el.id : null);
      }
      const doc = document.documentElement;
      const max = doc.scrollHeight - window.innerHeight;
      progress.style.width = max > 0 ? `${Math.min(100, (window.scrollY / max) * 100)}%` : '0%';
      topBtn.classList.toggle('hidden', window.scrollY < 600);
      topBtn.classList.toggle('flex', window.scrollY >= 600);
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
