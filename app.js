// Queer London — Calendar MVP
// Vanilla JS, no build step.

// ---------- Constants ----------
const CATEGORIES = [
  { id: 'fitness',  label: 'Fitness' },
  { id: 'outdoors', label: 'Outdoors' },
  { id: 'social',   label: 'Social' },
  { id: 'arts',     label: 'Arts' },
  { id: 'games',    label: 'Games' },
  { id: 'food',     label: 'Food' },
  { id: 'pride',    label: 'Pride' },
  { id: 'festival', label: 'Festival' },
];

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const MONTHS_AHEAD = 3;  // months rendered at once in month view

// ---------- State ----------
const STATE = {
  view: 'auto',
  month: startOfMonth(new Date()),
  filters: { sources: new Set(), categories: new Set(), favoritesOnly: false, sharedOnly: false },
  filtersOpen: false,  // mobile-only — desktop ignores this and always shows chips
  showPastEvents: false,  // list view: hide events whose start day is before today
  events: [],
  sources: {},
  openEvent: null,
  favorites: new Set(),        // local: Set<shortCode> persisted in localStorage
  sharedFavorites: new Set(),  // recipient mode: Set<shortCode> read from URL hash
  sharedNotFound: 0,           // count of f= codes in hash that didn't resolve
  modal: null,                 // null | 'clear-favorites' | 'contact'
  monthsLoaded: 1,             // list view: how many months from STATE.month are rendered
  displayedMonth: null,        // list view: tracks the topmost visible month for the header label
};

// Share URL category encoding: each category → single letter
const CAT_LETTER = {
  fitness: 'f', outdoors: 'o', social: 's', arts: 'a',
  games: 'g', food: 'd', pride: 'p', festival: 'e',
};
const LETTER_CAT = Object.fromEntries(Object.entries(CAT_LETTER).map(([k, v]) => [v, k]));

const FAVORITES_KEY = 'glc.favorites.v1';
function loadFavorites() {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}
function saveFavorites() {
  try { localStorage.setItem(FAVORITES_KEY, JSON.stringify([...STATE.favorites])); }
  catch { /* localStorage may be disabled (private mode) */ }
}

function parseShareHash() {
  const h = location.hash.slice(1);
  if (!h) return null;
  const p = new URLSearchParams(h);
  // No version flag in v1 URLs. If a future format adds `v=2+`, this guard
  // rejects it so the v1 parser doesn't mis-decode the new payload.
  const v = p.get('v');
  if (v && v !== '1') return null;
  const cats = new Set();
  for (const l of (p.get('c') || '')) if (LETTER_CAT[l]) cats.add(LETTER_CAT[l]);
  const favs = new Set();
  const f = p.get('f') || '';
  for (let i = 0; i + 2 <= f.length; i += 2) favs.add(f.slice(i, i + 2));
  if (cats.size === 0 && favs.size === 0) return null;
  return { categories: cats, favorites: favs };
}
function buildShareHash() {
  const parts = [];
  const cats = [...STATE.filters.categories].map(c => CAT_LETTER[c]).filter(Boolean).join('');
  if (cats) parts.push(`c=${cats}`);
  const favs = [...STATE.favorites].join('');
  if (favs) parts.push(`f=${favs}`);
  return parts.join('&');
}

// ---------- Date helpers ----------
function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function endOfMonth(d)   { return new Date(d.getFullYear(), d.getMonth()+1, 0); }
function startOfDay(d)   { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
function addMonths(d, n) { return new Date(d.getFullYear(), d.getMonth() + n, 1); }
function addYears(d, n)  { return new Date(d.getFullYear() + n, 0, 1); }
function isSameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
function isSameMonth(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth(); }
function dateKey(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function fmtTime(d) {
  const h = d.getHours();
  const m = d.getMinutes();
  const period = h >= 12 ? 'pm' : 'am';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12} ${period}` : `${h12}:${String(m).padStart(2,'0')} ${period}`;
}
function fmtDayHeader(d) {
  const today = startOfDay(new Date());
  const tomorrow = new Date(today); tomorrow.setDate(tomorrow.getDate() + 1);
  if (isSameDay(d, today))    return `Today · ${DAY_LABELS[(d.getDay()+6)%7]} ${d.getDate()} ${MONTHS[d.getMonth()].slice(0,3)}`;
  if (isSameDay(d, tomorrow)) return `Tomorrow · ${DAY_LABELS[(d.getDay()+6)%7]} ${d.getDate()} ${MONTHS[d.getMonth()].slice(0,3)}`;
  return `${DAY_LABELS[(d.getDay()+6)%7]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

// ---------- Event helpers ----------
function effectiveCategories(ev) {
  return ev.categoriesOverride && ev.categoriesOverride.length ? ev.categoriesOverride : ev.categories || [];
}
function primaryCategory(ev) {
  const cats = effectiveCategories(ev);
  return cats[0] || 'default';
}
function passesFilters(ev) {
  const f = STATE.filters;
  // Favorites + Shared are independent toggles with OR semantics: if any
  // are on, the event must be in at least one of the enabled sets.
  if (f.favoritesOnly || f.sharedOnly) {
    const code = ev.shortCode;
    const inFav = f.favoritesOnly && code && STATE.favorites.has(code);
    const inShared = f.sharedOnly && code && STATE.sharedFavorites.has(code);
    if (!inFav && !inShared) return false;
  }
  if (f.sources.size > 0 && !f.sources.has(ev.source)) return false;
  if (f.categories.size > 0) {
    const cats = effectiveCategories(ev);
    if (!cats.some(c => f.categories.has(c))) return false;
  }
  return true;
}
function eventsForDay(d) {
  return STATE.events.filter(ev => isSameDay(new Date(ev.start), d) && passesFilters(ev))
    .sort((a, b) => new Date(a.start) - new Date(b.start));
}
function eventsForMonth(monthStart) {
  return STATE.events.filter(ev => isSameMonth(new Date(ev.start), monthStart) && passesFilters(ev))
    .sort((a, b) => new Date(a.start) - new Date(b.start));
}

// List view (multi-month): events from [start, start + monthCount).
function eventsForMonthRange(startMonth, monthCount) {
  const endMonth = addMonths(startMonth, monthCount);
  return STATE.events.filter(ev => {
    if (!passesFilters(ev)) return false;
    const d = new Date(ev.start);
    return d >= startMonth && d < endMonth;
  }).sort((a, b) => new Date(a.start) - new Date(b.start));
}

// Is there at least one event past the currently-loaded range?
function hasEventsAfter(month) {
  return STATE.events.some(ev => passesFilters(ev) && new Date(ev.start) >= month);
}

// Reset list-view anchor to a specific month. Drops the lazy-loaded window
// back to a single month and re-syncs the displayed-month tracker.
function jumpListToMonth(newMonth) {
  STATE.month = startOfMonth(newMonth);
  STATE.displayedMonth = STATE.month;
  STATE.monthsLoaded = 1;
}

// ---------- Init ----------
async function init() {
  try {
    const sources = await fetch('./data/sources.json').then(r => r.json());
    STATE.sources = sources;
    const perSource = await Promise.all(
      Object.keys(sources).map(id =>
        fetch(`./data/${id}.json`).then(r => r.ok ? r.json() : []).catch(() => [])
      )
    );
    STATE.events = perSource.flat();
  } catch (e) {
    console.error('Failed to load data', e);
    document.getElementById('app').innerHTML = `<div class="p-8 text-center text-red-600">Failed to load event data. Are you running this through a local server?</div>`;
    return;
  }
  applyUrlState();
  // Load local favorites and any incoming share hash
  STATE.favorites = loadFavorites();
  const share = parseShareHash();
  if (share) {
    if (share.categories.size) STATE.filters.categories = share.categories;
    STATE.sharedFavorites = share.favorites;
    const codeSet = new Set(STATE.events.map(e => e.shortCode).filter(Boolean));
    STATE.sharedNotFound = [...share.favorites].filter(c => !codeSet.has(c)).length;
    // Auto-enable the Shared filter so the recipient lands on the shared
    // selection only. They can toggle it off to browse everything.
    if (share.favorites.size > 0) STATE.filters.sharedOnly = true;
  }
  render();
  // Once web fonts load, header/filter heights may shift slightly. Re-measure.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => updateLayoutVars());
  }
  window.addEventListener('resize', debounce(render, 150));
  window.addEventListener('popstate', () => { applyUrlState(); render(); });
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (STATE.modal) { STATE.modal = null; render(); return; }
    if (STATE.openEvent) {
      STATE.openEvent = null;
      document.querySelector('[data-drawer-card]')?.closest('.fixed')?.remove();
      syncBodyScrollLock();
    }
  });
  // Global scroll listener: updates the sticky month indicator on month view
  window.addEventListener('scroll', () => {
    updateStickyMonthLabel();
    updateListVisibleMonth();
  }, { passive: true });
}

function debounce(fn, ms) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ---------- URL state ----------
function applyUrlState() {
  const p = new URLSearchParams(location.search);
  if (p.get('cat')) STATE.filters.categories = new Set(p.get('cat').split(',').filter(Boolean));
  if (p.get('src')) STATE.filters.sources = new Set(p.get('src').split(',').filter(Boolean));
  if (p.get('view')) STATE.view = p.get('view');
  if (p.get('month')) {
    const [y, m] = p.get('month').split('-').map(Number);
    if (y && m) STATE.month = new Date(y, m-1, 1);
  }
}
function pushUrlState() {
  const p = new URLSearchParams();
  if (STATE.filters.categories.size) p.set('cat', [...STATE.filters.categories].join(','));
  if (STATE.filters.sources.size) p.set('src', [...STATE.filters.sources].join(','));
  if (STATE.view !== 'auto') p.set('view', STATE.view);
  p.set('month', `${STATE.month.getFullYear()}-${String(STATE.month.getMonth()+1).padStart(2,'0')}`);
  history.replaceState(null, '', `?${p}`);
}

// ---------- Rendering ----------
function effectiveView() {
  if (STATE.view !== 'auto') return STATE.view;
  return window.innerWidth >= 1024 ? 'month' : 'list';
}

function render() {
  pushUrlState();
  const isDesktop = window.innerWidth >= 1024;
  const effView = effectiveView();

  const app = document.getElementById('app');

  // Preserve <img> nodes across the innerHTML wipe so cached images don't
  // re-paint on every state change. Key gotcha: replaceWith() *moves* a
  // node — duplicate-src nodes (e.g. the same source logo on every card)
  // need a pool, not a single map entry, so each new slot gets its own
  // preserved node and we only clone when the new DOM has more slots than
  // we preserved.
  const preservedPools = new Map();
  for (const img of app.querySelectorAll('img')) {
    if (!img.src) continue;
    if (!preservedPools.has(img.src)) preservedPools.set(img.src, []);
    preservedPools.get(img.src).push(img);
  }

  app.innerHTML = `
    ${renderHeader(effView, isDesktop)}
    ${renderFilterBar()}
    <main class="max-w-6xl mx-auto px-4 sm:px-6 pt-4 pb-24">
      ${renderShareBanner()}
      ${effView === 'month' ? renderMonthsView()
        : effView === 'year' ? renderYearGrid()
        : renderList()}
    </main>
    ${STATE.openEvent ? renderEventDrawer(STATE.openEvent) : ''}
    ${renderModal()}
  `;

  const consumed = new Map();
  for (const img of app.querySelectorAll('img')) {
    if (!img.src) continue;
    const pool = preservedPools.get(img.src);
    if (!pool || pool.length === 0) continue;
    const idx = consumed.get(img.src) || 0;
    const replacement = idx < pool.length
      ? pool[idx]
      : pool[0].cloneNode(true);
    consumed.set(img.src, idx + 1);
    // Inherit the freshly-rendered classes/style so the preserved node
    // adopts the new container's layout context.
    replacement.className = img.className;
    replacement.style.cssText = img.style.cssText;
    img.replaceWith(replacement);
  }

  attachHandlers();
  attachDrawerSwipeHandlers();
  syncBodyScrollLock();
  updateLayoutVars();
  if (effView === 'month') updateStickyMonthLabel();
  if (effView === 'list') {
    attachListSentinelObserver();
    updateListVisibleMonth();
  }
  processInstagramEmbeds();
  if (STATE.modal === 'contact') attachContactFormHandler();
}

// Instagram embed loader — script is fetched lazily the first time a
// `.instagram-media` blockquote appears in the DOM. After load, the script
// auto-processes existing blockquotes. On subsequent renders we manually
// call `instgrm.Embeds.process()` to convert any new blockquotes.
let _instagramScriptLoaded = false;
function processInstagramEmbeds() {
  if (!document.querySelector('.instagram-media')) return;
  if (!_instagramScriptLoaded) {
    _instagramScriptLoaded = true;
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.instagram.com/embed.js';
    document.body.appendChild(s);
    return;
  }
  window.instgrm?.Embeds?.process();
}

// Freeze background scroll when a drawer or modal is open. Standard pattern:
// fix the body in place at the current scrollY, restore on close. Combined
// with `overscroll-contain` on the drawer, this eliminates touch scroll
// chaining to the page underneath.
function syncBodyScrollLock() {
  const shouldLock = STATE.openEvent !== null || STATE.modal !== null;
  const body = document.body;
  const isLocked = body.dataset.scrollLock === '1';
  if (shouldLock && !isLocked) {
    const y = window.scrollY;
    body.dataset.scrollLock = '1';
    body.dataset.lockY = String(y);
    body.style.position = 'fixed';
    body.style.top = `-${y}px`;
    body.style.left = '0';
    body.style.right = '0';
    body.style.width = '100%';
  } else if (!shouldLock && isLocked) {
    const y = parseInt(body.dataset.lockY || '0', 10);
    body.style.position = '';
    body.style.top = '';
    body.style.left = '';
    body.style.right = '';
    body.style.width = '';
    delete body.dataset.scrollLock;
    delete body.dataset.lockY;
    window.scrollTo(0, y);
  }
}

// Swipe-down-to-dismiss on the drawer card. Gesture only activates when the
// drawer is already scrolled to the top — otherwise native scroll wins, so
// long content can be read by scrolling up first. Past a release threshold
// (25% of card height, capped at 120px) the drawer animates out and closes.
function attachDrawerSwipeHandlers() {
  const card = document.querySelector('[data-drawer-card]');
  if (!card) return;
  const backdrop = document.querySelector('[data-drawer-backdrop]');
  let startY = null;
  let startScrollTop = 0;
  let deltaY = 0;
  let dragging = false;

  const resetVisuals = () => {
    card.style.transition = 'transform 0.2s ease-out';
    card.style.transform = 'translateY(0)';
    if (backdrop) {
      backdrop.style.transition = 'opacity 0.2s ease-out';
      backdrop.style.opacity = '';
    }
  };

  card.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return;
    startY = e.touches[0].clientY;
    startScrollTop = card.scrollTop;
    deltaY = 0;
    dragging = false;
  }, { passive: true });

  card.addEventListener('touchmove', (e) => {
    if (startY === null) return;
    const dy = e.touches[0].clientY - startY;
    if (dy > 0 && startScrollTop <= 0) {
      if (!dragging) {
        dragging = true;
        card.style.transition = 'none';
        if (backdrop) backdrop.style.transition = 'none';
      }
      deltaY = dy;
      card.style.transform = `translateY(${deltaY}px)`;
      if (backdrop) backdrop.style.opacity = String(Math.max(0, 1 - deltaY / 400));
      e.preventDefault();
    } else if (dragging) {
      deltaY = Math.max(0, dy);
      card.style.transform = `translateY(${deltaY}px)`;
      if (backdrop) backdrop.style.opacity = String(Math.max(0, 1 - deltaY / 400));
      e.preventDefault();
    }
  }, { passive: false });

  const onEnd = () => {
    if (startY === null) return;
    if (dragging) {
      const threshold = Math.min(120, card.offsetHeight * 0.25);
      if (deltaY > threshold) {
        card.style.transition = 'transform 0.2s ease-out';
        card.style.transform = 'translateY(100%)';
        if (backdrop) {
          backdrop.style.transition = 'opacity 0.2s ease-out';
          backdrop.style.opacity = '0';
        }
        setTimeout(() => {
          STATE.openEvent = null;
          // Surgical close: remove the drawer DOM and sync body scroll
          // without a full re-render. A full render would rebuild the
          // header, filter bar, and list — visibly flashing them.
          card.closest('.fixed')?.remove();
          syncBodyScrollLock();
        }, 200);
      } else {
        resetVisuals();
      }
    }
    startY = null;
    dragging = false;
  };

  card.addEventListener('touchend', onEnd, { passive: true });
  card.addEventListener('touchcancel', onEnd, { passive: true });
}

// Auto-load the next month when the bottom sentinel scrolls into view.
// Re-attached on every render — the old observer's target is gone after the
// innerHTML wipe, but we disconnect explicitly to release references.
let _listSentinelObserver = null;
function attachListSentinelObserver() {
  if (_listSentinelObserver) {
    _listSentinelObserver.disconnect();
    _listSentinelObserver = null;
  }
  const sentinel = document.querySelector('[data-month-sentinel]');
  if (!sentinel) return;
  _listSentinelObserver = new IntersectionObserver((entries) => {
    if (entries.some(e => e.isIntersecting)) {
      STATE.monthsLoaded += 1;
      render();
    }
  }, { rootMargin: '600px 0px' });
  _listSentinelObserver.observe(sentinel);
}

// Update the header month label to whatever month is currently topmost in
// the viewport (just below the sticky header band). Direct DOM update — no
// re-render — so we can run this on every scroll without thrash.
function updateListVisibleMonth() {
  if (effectiveView() !== 'list') return;
  const anchors = document.querySelectorAll('[data-month-anchor]');
  if (anchors.length === 0) return;
  // The "active" anchor is the bottommost one whose top has crossed the
  // sticky-header band. If none has crossed yet (we're above the first),
  // use the first anchor.
  const bandBottom =
    (document.getElementById('app-header')?.offsetHeight || 0) +
    (document.getElementById('filter-bar')?.offsetHeight || 0) +
    20;
  let active = anchors[0];
  for (const a of anchors) {
    const top = a.getBoundingClientRect().top;
    if (top <= bandBottom) active = a;
    else break;
  }
  const ym = active.dataset.monthAnchor;
  if (!ym) return;
  const [y, m] = ym.split('-').map(Number);
  const newMonth = new Date(y, m, 1);
  if (!STATE.displayedMonth || newMonth.getTime() !== STATE.displayedMonth.getTime()) {
    STATE.displayedMonth = newMonth;
    const label = `${MONTHS[m]} ${y}`;
    document.querySelectorAll('[data-list-title]').forEach(el => { el.textContent = label; });
    // Mirror the Today-button visibility against the now-displayed month.
    const now = new Date();
    const onToday = newMonth.getMonth() === now.getMonth() && newMonth.getFullYear() === now.getFullYear();
    document.querySelectorAll('[data-today-wrapper]').forEach(el => {
      el.classList.toggle('hidden', onToday);
    });
  }
}

// Measure the live header + filter bar heights and publish them as CSS
// variables, so sticky offsets adapt automatically when the mobile header
// becomes two rows or the mobile filter bar expands. A ResizeObserver
// re-measures whenever fonts load, viewport rotates, or content shifts —
// otherwise first-paint values use fallback-font metrics and stick at the
// wrong offsets until the next re-render.
let _layoutObserver = null;
function updateLayoutVars() {
  const header = document.getElementById('app-header');
  const filterBar = document.getElementById('filter-bar');
  const root = document.documentElement;
  const apply = () => {
    if (header)    root.style.setProperty('--header-h', header.offsetHeight + 'px');
    if (filterBar) root.style.setProperty('--filter-h', filterBar.offsetHeight + 'px');
  };
  apply();
  if (window.ResizeObserver) {
    if (_layoutObserver) _layoutObserver.disconnect();
    _layoutObserver = new ResizeObserver(apply);
    if (header) _layoutObserver.observe(header);
    if (filterBar) _layoutObserver.observe(filterBar);
  }
}

function renderHeader(effView, isDesktop) {
  // In list view, the title tracks whatever month is currently topmost in
  // view (displayedMonth) — not the anchor. Falls back to STATE.month
  // before the observer has reported anything.
  const listLabelMonth = STATE.displayedMonth || STATE.month;
  const titleText = effView === 'year'
    ? `${STATE.month.getFullYear()}`
    : effView === 'month'
      ? `${MONTHS[STATE.month.getMonth()].slice(0,3)}–${MONTHS[addMonths(STATE.month, MONTHS_AHEAD-1).getMonth()].slice(0,3)} ${STATE.month.getFullYear()}`
      : `${MONTHS[listLabelMonth.getMonth()]} ${listLabelMonth.getFullYear()}`;
  const prevLabel = effView === 'year' ? 'Previous year' : 'Previous month';
  const nextLabel = effView === 'year' ? 'Next year' : 'Next month';

  // "Today" button only appears when not already on today's view. In list
  // view this is based on displayedMonth (what's actually visible) so the
  // button appears as soon as you scroll into a non-current month — even
  // though STATE.month (the anchor) is unchanged.
  const now = new Date();
  const monthForTodayCheck = effView === 'list' ? (STATE.displayedMonth || STATE.month) : STATE.month;
  const onTodayPeriod = effView === 'year'
    ? STATE.month.getFullYear() === now.getFullYear()
    : (monthForTodayCheck.getMonth() === now.getMonth() && monthForTodayCheck.getFullYear() === now.getFullYear());
  const showTodayBtn = !onTodayPeriod;

  // Share button visible when there's a selection worth sharing.
  const hasShareable = STATE.favorites.size > 0
    || STATE.filters.categories.size > 0
    || STATE.filters.sources.size > 0;
  const shareBtn = hasShareable ? `
    <button data-action="share" class="p-2 rounded-lg hover:bg-slate-100 text-slate-700" title="Share your selection" aria-label="Share">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
    </button>` : '';

  const contactBtn = `
    <button data-action="open-contact" class="p-2 rounded-lg hover:bg-slate-100 text-slate-700" title="Submit an event / get in touch" aria-label="Contact">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
    </button>`;

  const todayBtn = `
    <button data-action="today" class="px-3 py-1.5 rounded-lg text-sm font-medium border border-slate-300 hover:bg-slate-50 text-slate-700 whitespace-nowrap">
      Today
    </button>`;
  const prevBtn = `
    <button data-action="prev-period" class="p-2 rounded-lg hover:bg-slate-100 text-slate-600" title="${prevLabel}" aria-label="${prevLabel}">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
    </button>`;
  const nextBtn = `
    <button data-action="next-period" class="p-2 rounded-lg hover:bg-slate-100 text-slate-600" title="${nextLabel}" aria-label="${nextLabel}">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
    </button>`;
  const monthLabelBtnDesktop = `
    <button data-action="today" class="px-3 py-1.5 rounded-lg text-sm font-medium border border-slate-200 hover:bg-slate-50 whitespace-nowrap">
      <span data-list-title>${titleText}</span>
    </button>`;
  const monthLabelBtnMobile = `
    <button data-action="today" class="flex-1 px-3 py-1.5 rounded-lg text-sm font-semibold text-center border border-slate-200 hover:bg-slate-50">
      <span data-list-title>${titleText}</span>
    </button>`;
  const viewToggle = isDesktop ? `
    <div class="flex rounded-lg border border-slate-200 p-0.5 bg-white">
      <button data-action="view-list"  class="px-3 py-1 text-sm rounded-md ${effView==='list'  ? 'bg-slate-900 text-white' : 'text-slate-600 hover:text-slate-900'}">List</button>
      <button data-action="view-month" class="px-3 py-1 text-sm rounded-md ${effView==='month' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:text-slate-900'}">Month</button>
      <button data-action="view-year"  class="px-3 py-1 text-sm rounded-md ${effView==='year'  ? 'bg-slate-900 text-white' : 'text-slate-600 hover:text-slate-900'}">Year</button>
    </div>
  ` : `
    <div class="flex rounded-lg border border-slate-200 p-0.5 bg-white">
      <button data-action="view-list" class="px-2 py-1 text-xs rounded-md ${effView==='list' ? 'bg-slate-900 text-white' : 'text-slate-600'}">List</button>
      <button data-action="view-year" class="px-2 py-1 text-xs rounded-md ${effView==='year' ? 'bg-slate-900 text-white' : 'text-slate-600'}">Year</button>
    </div>
  `;

  return `
    <header id="app-header" class="sticky top-0 z-40 bg-white/90 day-header border-b border-slate-200">
      <div class="max-w-6xl mx-auto px-4 sm:px-6 py-2.5 sm:py-3">
        <!-- Row 1: title + (desktop nav inline) + view toggle -->
        <div class="flex items-center gap-2 sm:gap-3">
          <div class="flex-1 min-w-0">
            <h1 class="text-base sm:text-xl font-semibold tracking-tight truncate">Gay London Calendar</h1>
            <p class="hidden sm:block text-xs text-slate-500 -mt-0.5">Events from your favourite communities</p>
          </div>
          <!-- Desktop only: full nav inline with title -->
          <div class="hidden sm:flex items-center gap-2">
            <span data-today-wrapper class="${showTodayBtn ? '' : 'hidden'}">${todayBtn}</span>
            ${prevBtn}
            ${monthLabelBtnDesktop}
            ${nextBtn}
          </div>
          ${shareBtn}
          ${contactBtn}
          ${viewToggle}
        </div>
        <!-- Row 2 (mobile only): prev / month label / next  (+ Today if not on today) -->
        <div class="sm:hidden mt-2 flex items-center gap-1.5">
          ${prevBtn}
          ${monthLabelBtnMobile}
          ${nextBtn}
          <span data-today-wrapper class="${showTodayBtn ? '' : 'hidden'}">${todayBtn}</span>
        </div>
      </div>
    </header>
  `;
}

function renderFilterBar() {
  const f = STATE.filters;
  const sourceIds = Object.keys(STATE.sources);
  const anySource = sourceIds.length > 1;
  const sharedCount = STATE.sharedFavorites.size;
  const hasShared = sharedCount > 0;
  const activeCount = f.categories.size + f.sources.size + (f.favoritesOnly ? 1 : 0) + (f.sharedOnly ? 1 : 0);
  const isOpen = STATE.filtersOpen;
  const favCount = STATE.favorites.size;

  const favChip = `
    <button data-action="toggle-fav-filter"
      class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition
        ${f.favoritesOnly
          ? 'bg-yellow-100 text-yellow-900 ring-2 ring-offset-1 ring-yellow-400'
          : 'bg-white text-slate-700 border border-slate-200 hover:border-slate-300'}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="${f.favoritesOnly ? '#facc15' : 'none'}" stroke="${f.favoritesOnly ? '#ca8a04' : '#94a3b8'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
      Favorites${favCount > 0 ? ` <span class="ml-0.5 text-xs text-slate-500">(${favCount})</span>` : ''}
    </button>
  `;

  const sharedChip = hasShared ? `
    <button data-action="toggle-shared-filter"
      class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition
        ${f.sharedOnly
          ? 'bg-yellow-50 text-yellow-900 ring-2 ring-offset-1 ring-yellow-300'
          : 'bg-white text-slate-700 border border-slate-200 hover:border-slate-300'}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${f.sharedOnly ? '#ca8a04' : '#94a3b8'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
      Shared <span class="ml-0.5 text-xs text-slate-500">(${sharedCount})</span>
    </button>
  ` : '';

  const chips = `
    ${favChip}
    ${sharedChip}
    ${CATEGORIES.map(c => {
      const active = f.categories.has(c.id);
      return `
        <button data-action="toggle-cat" data-cat="${c.id}"
          class="cat-${c.id} flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition
            ${active
              ? 'cat-chip ring-2 ring-offset-1 ring-[color:var(--c)]'
              : 'bg-white text-slate-700 border border-slate-200 hover:border-slate-300'}">
          <span class="w-2 h-2 rounded-full cat-stripe"></span>
          ${c.label}
        </button>
      `;
    }).join('')}
    ${anySource ? sourceIds.map(sid => {
      const src = STATE.sources[sid];
      const active = f.sources.has(sid);
      return `
        <button data-action="toggle-src" data-src="${sid}"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap border transition
            ${active ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-700 border-slate-200 hover:border-slate-300'}">
          ${renderSourceAvatar(sid, 14)}
          ${escapeHtml(src.shortName || src.name)}
        </button>
      `;
    }).join('') : ''}
    ${activeCount > 0 ? `
      <button data-action="clear-filters" class="hidden sm:inline-flex items-center px-3 py-1.5 rounded-full text-sm text-slate-500 hover:text-slate-900 whitespace-nowrap">
        Clear filters
      </button>
    ` : ''}
    ${favCount > 0 ? `
      <button data-action="prompt-clear-favorites" class="inline-flex items-center px-3 py-1.5 rounded-full text-sm text-slate-500 hover:text-rose-700 whitespace-nowrap">
        Clear favorites
      </button>
    ` : ''}
  `;

  return `
    <div id="filter-bar" class="sticky z-30 bg-slate-50/90 day-header border-b border-slate-100" style="top: var(--header-h)">
      <div class="max-w-6xl mx-auto px-4 sm:px-6 py-2.5">
        <!-- Mobile: toggle button row -->
        <div class="sm:hidden flex items-center justify-between gap-2">
          <button data-action="toggle-filters" class="flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium border border-slate-200 bg-white hover:bg-slate-50">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="4" y1="6"  x2="20" y2="6"/>
              <line x1="7" y1="12" x2="17" y2="12"/>
              <line x1="10" y1="18" x2="14" y2="18"/>
            </svg>
            <span>Filters${activeCount > 0 ? ` <span class="ml-0.5 inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 text-[11px] font-semibold rounded-full bg-slate-900 text-white">${activeCount}</span>` : ''}</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="transition-transform ${isOpen ? 'rotate-180' : ''}"><polyline points="6 9 12 15 18 9"></polyline></svg>
          </button>
          ${activeCount > 0 ? `
            <button data-action="clear-filters" class="px-3 py-1.5 rounded-full text-sm text-slate-500 hover:text-slate-900 whitespace-nowrap">
              Clear
            </button>
          ` : ''}
        </div>
        <!-- Chips: always visible on desktop, only when open on mobile -->
        <div class="filter-row flex flex-wrap gap-2 ${isOpen ? 'mt-3 sm:mt-0 flex' : 'hidden sm:flex'}">
          ${chips}
        </div>
      </div>
    </div>
  `;
}

// ---------- List view ----------
function renderList() {
  const today = startOfDay(new Date());
  // When a share is active, the list spans every month/year the shared
  // events touch — STATE.month is ignored. The user came here from a link
  // pointing at a specific set of events, not a specific month.
  const sharedMode = STATE.filters.sharedOnly && STATE.sharedFavorites.size > 0;
  const multiMonth = sharedMode || STATE.monthsLoaded > 1;
  const baseEvents = sharedMode
    ? STATE.events.filter(passesFilters).sort((a, b) => new Date(a.start) - new Date(b.start))
    : eventsForMonthRange(STATE.month, STATE.monthsLoaded);
  const visibleEvents = STATE.showPastEvents
    ? baseEvents
    : baseEvents.filter(ev => startOfDay(new Date(ev.start)) >= today);
  const hiddenPastCount = baseEvents.length - visibleEvents.length;
  // Sentinel only relevant outside shared mode and when more months exist.
  const canLoadMore = !sharedMode && hasEventsAfter(addMonths(STATE.month, STATE.monthsLoaded));

  const eyeIcon = STATE.showPastEvents
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" y1="2" x2="22" y2="22"/></svg>`
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>`;

  const toggleBtn = (STATE.showPastEvents || hiddenPastCount > 0)
    ? `<div class="mb-3 flex justify-end">
        <button data-action="toggle-past-events"
          class="text-xs text-slate-500 hover:text-slate-900 flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-slate-100 transition">
          ${eyeIcon}
          ${STATE.showPastEvents ? 'Hide past events' : `Show past events${hiddenPastCount > 0 ? ` (${hiddenPastCount})` : ''}`}
        </button>
      </div>`
    : '';

  if (!visibleEvents.length) {
    const scopeLabel = sharedMode ? 'in this shared selection' : 'this month';
    const emptyBody = baseEvents.length > 0
      ? `<p class="text-base">No upcoming events ${scopeLabel}.</p>
         <button data-action="toggle-past-events" class="mt-3 text-sm text-slate-900 underline">Show ${baseEvents.length} past event${baseEvents.length === 1 ? '' : 's'}</button>`
      : `<p class="text-base">No events match your filters ${scopeLabel}.</p>
         <button data-action="clear-filters" class="mt-3 text-sm text-slate-900 underline">Clear filters</button>`;
    return `
      ${toggleBtn}
      <div class="text-center py-16 text-slate-500">
        ${emptyBody}
      </div>
      ${canLoadMore ? '<div data-month-sentinel class="h-1"></div>' : ''}
    `;
  }
  const byDay = new Map();
  for (const ev of visibleEvents) {
    const k = dateKey(new Date(ev.start));
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k).push(ev);
  }
  const days = [...byDay.keys()].sort();
  let prevYear = null;
  let prevMonth = null;
  return `
    ${toggleBtn}
    <div class="space-y-6">
      ${days.map(k => {
        const [y, m, d] = k.split('-').map(Number);
        const date = new Date(y, m-1, d);
        const isToday = isSameDay(date, today);
        const isPast = startOfDay(date) < startOfDay(today);

        const isFirst = prevYear === null;
        const monthChanged = isFirst || m !== prevMonth || y !== prevYear;
        const yearChanged = !isFirst && y !== prevYear;
        // Anchor marker for the visible-month tracker observer — present at
        // the start of every month, even when there's no visible divider.
        const anchor = monthChanged
          ? `<div data-month-anchor="${y}-${m-1}" aria-hidden="true"></div>`
          : '';
        let divider = anchor;
        if (multiMonth && monthChanged && !isFirst) {
          divider += yearChanged
            ? `<div class="pt-8 pb-2 mt-4 border-t-2 border-slate-300 flex items-baseline gap-3">
                <div class="text-3xl font-bold text-slate-900 tracking-tight">${y}</div>
                <div class="text-sm font-medium text-slate-500">${MONTHS[m-1]}</div>
              </div>`
            : `<div class="pt-5 pb-1 mt-2 border-t border-slate-200">
                <div class="text-base font-semibold text-slate-700">${MONTHS[m-1]} ${y}</div>
              </div>`;
        }
        prevYear = y;
        prevMonth = m;

        return divider + `
          <section>
            <h2 class="sticky z-20 -mx-4 sm:-mx-6 px-4 sm:px-6 py-1.5 bg-slate-50/95 day-header text-xs font-semibold uppercase tracking-wider flex items-center gap-2
              ${isToday ? 'text-slate-900' : (isPast ? 'text-slate-400' : 'text-slate-500')}"
              style="top: calc(var(--header-h) + var(--filter-h))">
              ${isToday ? '<span class="w-1.5 h-1.5 rounded-full bg-slate-900"></span>' : ''}
              ${fmtDayHeader(date)}
            </h2>
            <div class="mt-2 space-y-1 ${isPast && !isToday ? 'opacity-50 saturate-50' : ''}">
              ${byDay.get(k).map(renderListCard).join('')}
            </div>
          </section>
        `;
      }).join('')}
    </div>
    ${canLoadMore ? '<div data-month-sentinel class="h-1 mt-8"></div>' : ''}
  `;
}

function renderShareBanner() {
  if (STATE.sharedFavorites.size === 0) return '';
  const n = STATE.sharedFavorites.size;
  const missing = STATE.sharedNotFound;
  const newCount = [...STATE.sharedFavorites].filter(c => !STATE.favorites.has(c)).length;
  return `
    <div class="mb-4 bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-3">
      <div class="text-sm text-yellow-900 leading-tight">
        <span class="font-semibold">Shared selection:</span> ${n} event${n === 1 ? '' : 's'} highlighted
        ${missing > 0 ? `<span class="block text-xs text-yellow-700 mt-0.5">${missing} event${missing === 1 ? '' : 's'} in this share no longer available</span>` : ''}
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <button data-action="save-shared" ${newCount === 0 ? 'disabled' : ''}
          class="text-sm font-medium px-3 py-1.5 rounded-md transition whitespace-nowrap
            ${newCount === 0
              ? 'bg-yellow-100 text-yellow-500 cursor-not-allowed'
              : 'bg-yellow-900 text-yellow-50 hover:bg-yellow-800'}">
          ${newCount === 0 ? 'All saved' : `Save ${newCount > 1 ? `${newCount} ` : ''}to favorites`}
        </button>
        <button data-action="clear-share" class="text-sm text-yellow-800 hover:text-yellow-900 font-medium px-2 py-1 whitespace-nowrap">Clear</button>
      </div>
    </div>
  `;
}

function renderModal() {
  if (STATE.modal === 'clear-favorites') return renderClearFavoritesModal();
  if (STATE.modal === 'contact') return renderContactModal();
  return '';
}

function renderClearFavoritesModal() {
  const n = STATE.favorites.size;
  return `
    <div data-action="close-modal" class="fixed inset-0 z-50 bg-slate-900/50"></div>
    <div class="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
      <div role="dialog" aria-labelledby="modal-title" class="bg-white rounded-2xl shadow-xl max-w-sm w-full pointer-events-auto overflow-hidden">
        <div class="px-5 py-4">
          <h3 id="modal-title" class="text-base font-semibold text-slate-900 mb-1">Remove all favorites?</h3>
          <p class="text-sm text-slate-600">This will remove ${n} event${n === 1 ? '' : 's'} from your favorites. You can re-favorite them anytime, but the current selection will be lost.</p>
        </div>
        <div class="px-5 py-3 bg-slate-50 border-t border-slate-100 flex items-center justify-end gap-2">
          <button data-action="close-modal" class="px-4 py-2 rounded-md text-sm font-medium text-slate-700 hover:bg-slate-100 transition">Cancel</button>
          <button data-action="do-clear-favorites" class="px-4 py-2 rounded-md text-sm font-medium bg-rose-600 text-white hover:bg-rose-700 transition">Remove all</button>
        </div>
      </div>
    </div>
  `;
}

const FORMSPREE_ENDPOINT = 'https://formspree.io/f/mykawakg';

function renderContactModal() {
  return `
    <div data-action="close-modal" class="fixed inset-0 z-50 bg-slate-900/50"></div>
    <div class="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 pointer-events-none">
      <div role="dialog" aria-labelledby="modal-title"
        class="bg-white rounded-t-2xl sm:rounded-2xl shadow-xl w-full sm:max-w-md max-h-[92vh] sm:max-h-[88vh] pointer-events-auto overflow-y-auto overscroll-contain">
        <div class="sticky top-0 bg-white border-b border-slate-200 px-5 py-3.5 flex items-center justify-between gap-3">
          <h3 id="modal-title" class="text-base font-semibold text-slate-900">Get in touch</h3>
          <button data-action="close-modal" class="text-slate-400 hover:text-slate-900 p-1" aria-label="Close">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
        <form data-contact-form class="px-5 py-5 flex flex-col gap-4" method="POST" action="${FORMSPREE_ENDPOINT}">
          <p class="text-sm text-slate-600 -mt-1">Submit an event, flag one that shouldn't be listed, ask about an existing event, or just send feedback.</p>

          <input type="text" name="_gotcha" tabindex="-1" autocomplete="off" aria-hidden="true"
            class="absolute left-[-9999px] w-px h-px opacity-0 pointer-events-none" />

          <label class="flex flex-col gap-1.5">
            <span class="text-sm font-medium text-slate-700">What's this about? <span class="text-rose-500">*</span></span>
            <select name="topic" required
              class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400">
              <option value="">Pick one…</option>
              <option value="Submit an event">Submit an event</option>
              <option value="Talk about an existing event">Talk about an existing event</option>
              <option value="Remove an event">Remove an event from the calendar</option>
              <option value="General feedback">General feedback</option>
              <option value="Other">Other</option>
            </select>
          </label>

          <label class="flex flex-col gap-1.5">
            <span class="text-sm font-medium text-slate-700">Your name <span class="text-rose-500">*</span></span>
            <input type="text" name="name" required autocomplete="name" placeholder="Jamie"
              class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400" />
          </label>

          <label class="flex flex-col gap-1.5">
            <span class="text-sm font-medium text-slate-700">Your email <span class="text-rose-500">*</span></span>
            <input type="email" name="email" required autocomplete="email" placeholder="jamie@example.com"
              class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400" />
          </label>

          <label class="flex flex-col gap-1.5">
            <span class="text-sm font-medium text-slate-700">Event link <span class="text-slate-400 font-normal">(if applicable)</span></span>
            <input type="url" name="event_link" autocomplete="off" placeholder="https://www.instagram.com/p/…"
              class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400" />
          </label>

          <label class="flex flex-col gap-1.5">
            <span class="text-sm font-medium text-slate-700">Message <span class="text-rose-500">*</span></span>
            <textarea name="message" rows="5" required placeholder="Tell me what's up…"
              class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400 resize-y min-h-[120px]"></textarea>
          </label>

          <input type="hidden" name="_subject" value="Gay London Calendar — contact" />

          <p data-contact-error hidden class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">Something went wrong. Please try again or email me directly.</p>

          <button type="submit"
            class="bg-slate-900 hover:bg-slate-800 text-white text-sm font-medium px-4 py-2.5 rounded-lg transition disabled:opacity-60 disabled:cursor-not-allowed">
            Send message
          </button>
        </form>
        <div data-contact-success hidden class="px-5 py-12 text-center">
          <div class="mx-auto w-12 h-12 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center mb-3">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
          </div>
          <h4 class="text-base font-semibold text-slate-900 mb-1">Message sent</h4>
          <p class="text-sm text-slate-600 mb-5">Thanks — I'll get back to you as soon as I can.</p>
          <button data-action="close-modal" class="px-4 py-2 rounded-md text-sm font-medium bg-slate-900 text-white hover:bg-slate-800 transition">Close</button>
        </div>
      </div>
    </div>
  `;
}

function attachContactFormHandler() {
  const form = document.querySelector('[data-contact-form]');
  if (!form) return;
  const errorEl = document.querySelector('[data-contact-error]');
  const successEl = document.querySelector('[data-contact-success]');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector('button[type="submit"]');
    const originalText = btn?.textContent || 'Send message';
    if (btn) { btn.textContent = 'Sending…'; btn.disabled = true; }
    errorEl?.setAttribute('hidden', '');
    try {
      const res = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'Accept': 'application/json' },
      });
      if (res.ok) {
        form.reset();
        form.setAttribute('hidden', '');
        successEl?.removeAttribute('hidden');
      } else {
        errorEl?.removeAttribute('hidden');
        if (btn) { btn.textContent = originalText; btn.disabled = false; }
      }
    } catch {
      errorEl?.removeAttribute('hidden');
      if (btn) { btn.textContent = originalText; btn.disabled = false; }
    }
  });
}

function showToast(msg) {
  const el = document.createElement('div');
  el.className = 'fixed left-1/2 -translate-x-1/2 bottom-6 z-[60] bg-slate-900 text-white text-sm px-4 py-2 rounded-full shadow-lg transition-opacity duration-300';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; }, 1500);
  setTimeout(() => el.remove(), 1900);
}

async function doShare() {
  const hash = buildShareHash();
  const url = `${location.origin}${location.pathname}#${hash}`;
  const favCount = STATE.favorites.size;
  const text = favCount > 0
    ? `${favCount} event${favCount === 1 ? '' : 's'} on my Gay London Calendar`
    : 'Gay London Calendar';
  if (navigator.share) {
    try { await navigator.share({ title: 'Gay London Calendar', text, url }); return; }
    catch (e) { if (e.name === 'AbortError') return; /* fall through to clipboard */ }
  }
  try {
    await navigator.clipboard.writeText(url);
    showToast('Link copied');
  } catch {
    // Last-resort: write to the URL bar so the user can copy from there.
    history.replaceState(null, '', `#${hash}`);
    showToast('Link in address bar');
  }
}

function starSvg(filled) {
  return filled
    ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="#facc15" stroke="#ca8a04" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`
    : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
}
function renderFavBtn(ev, padding = 'p-1.5') {
  if (!ev.shortCode) return '';
  const isFav = STATE.favorites.has(ev.shortCode);
  const label = isFav ? 'Remove from favorites' : 'Add to favorites';
  return `
    <button data-action="toggle-fav" data-code="${ev.shortCode}"
      class="${padding} rounded-full hover:bg-slate-100 transition"
      aria-label="${label}" title="${label}">
      ${starSvg(isFav)}
    </button>
  `;
}

function renderListCard(ev) {
  const start = new Date(ev.start);
  const cats = effectiveCategories(ev);
  const src = STATE.sources[ev.source];
  const loc = displayLocation(ev.location);
  const free = isFreeEvent(ev);
  const projected = isProjected(ev);
  const soldOut = isSoldOut(ev);
  const isShared = ev.shortCode && STATE.sharedFavorites.has(ev.shortCode);
  const sharedRing = isShared ? ' ring-2 ring-yellow-300 shadow-sm' : '';
  const wrapClass = projected
    ? `w-full text-left bg-white rounded-xl hover:bg-slate-50 transition p-3.5 sm:p-4 border border-dashed border-slate-300${sharedRing}`
    : `w-full text-left bg-white rounded-xl hover:bg-slate-50 transition p-3.5 sm:p-4${sharedRing}`;
  const priceChunk = projected
    ? '<span class="text-slate-300">·</span><span class="text-slate-500 font-bold tracking-wide">TBC</span>'
    : soldOut
    ? '<span class="text-slate-300">·</span><span class="ml-1 text-rose-600 font-bold tracking-wide">SOLD OUT</span>'
    : (ev.price ? (free
        ? '<span class="ml-1 text-emerald-600 font-bold tracking-wide">FREE</span>'
        : `<span class="text-slate-300">·</span><span class="text-slate-500 font-medium">${escapeHtml(ev.price)}</span>`) : '');
  const titleClass = projected ? 'italic text-slate-600' : (soldOut ? 'font-light text-slate-400' : 'font-light text-slate-900');
  return `
    <div class="relative">
      <button data-action="open-event" data-id="${ev.id}"
        class="${wrapClass}">
        <div class="flex items-center gap-2 text-xs pr-9">
          ${renderSourceAvatar(ev.source, 18)}
          <span class="font-semibold" style="color:${src?.color || '#475569'}">${escapeHtml(src?.shortName || ev.source)}</span>
          <span class="text-slate-300">·</span>
          <span class="font-semibold ${projected ? 'text-slate-500' : 'text-slate-900'}">${fmtTime(start)}</span>
          ${priceChunk}
        </div>
        <div class="mt-1.5 ${titleClass} leading-snug line-clamp-2 pr-9">${escapeHtml(ev.title)}</div>
        ${loc ? `
          <div class="mt-1 flex items-center gap-1 text-sm text-slate-500">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="flex-shrink-0"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
            <span class="truncate">${escapeHtml(loc)}</span>
          </div>
        ` : ''}
        ${cats.length ? `
          <div class="mt-2 flex flex-wrap gap-1">
            ${cats.map(c => `<span class="cat-${c} cat-chip text-[10.5px] px-2 py-0.5 rounded-full font-medium capitalize">${c}</span>`).join('')}
          </div>
        ` : ''}
      </button>
      ${ev.shortCode ? `
        <div class="absolute top-2 right-2">${renderFavBtn(ev)}</div>
      ` : ''}
    </div>
  `;
}

// ---------- Month view: ONE continuous grid spanning N months ----------
function renderMonthsView() {
  const startMonth = STATE.month;
  const endMonth = addMonths(startMonth, MONTHS_AHEAD - 1);
  const lastDay = endOfMonth(endMonth);

  // Extend backwards to the Monday of startMonth's first week
  // and forwards to the Sunday of endMonth's last week
  const leadingPad = (startMonth.getDay() + 6) % 7;
  const trailingPad = 6 - ((lastDay.getDay() + 6) % 7);
  const gridStart = new Date(startMonth); gridStart.setDate(gridStart.getDate() - leadingPad);
  const gridEnd = new Date(lastDay); gridEnd.setDate(gridEnd.getDate() + trailingPad);

  const cells = [];
  let d = new Date(gridStart);
  while (d <= gridEnd) {
    cells.push(new Date(d));
    d.setDate(d.getDate() + 1);
  }

  const today = new Date();
  const earliestMonth = startMonth;
  return `
    <div class="bg-white rounded-2xl border border-slate-200">
      <div class="month-sticky sticky z-20 bg-white border-b border-slate-200 rounded-t-2xl" style="top: calc(var(--header-h) + var(--filter-h))">
        <div class="px-4 sm:px-5 py-2.5">
          <span id="cur-month" class="text-xl font-bold tracking-tight text-slate-900" data-default="${MONTHS[earliestMonth.getMonth()]} ${earliestMonth.getFullYear()}">${MONTHS[earliestMonth.getMonth()]} ${earliestMonth.getFullYear()}</span>
        </div>
        <div class="grid grid-cols-7 border-t border-slate-100 bg-slate-50">
          ${DAY_LABELS.map(l => `<div class="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500 text-center">${l}</div>`).join('')}
        </div>
      </div>
      <div class="grid grid-cols-7 rounded-b-2xl overflow-hidden" id="cells-grid">
        ${cells.map((d, i) => renderCalCell(d, today, startMonth, endMonth, i)).join('')}
      </div>
    </div>
  `;
}

function renderCalCell(d, today, startMonth, endMonth, i) {
  const monthEndDay = endOfMonth(endMonth);
  const beforeRange = d < startMonth;
  const afterRange = d > monthEndDay;
  const isOutsideRange = beforeRange || afterRange;
  const isToday = isSameDay(d, today);
  const isPast = startOfDay(d) < startOfDay(today);
  const isFirstOfMonth = d.getDate() === 1;
  const events = eventsForDay(d);
  const visible = events.slice(0, 6);
  const overflow = events.length - visible.length;
  const isLastCol = (i % 7) === 6;

  // Subtle month separator: darken the 1px border on edges that touch a
  // different-month neighbor. Combined across cells, this naturally produces
  // an L-shaped step between months without any cell having a thick border.
  const dRight = new Date(d); dRight.setDate(d.getDate() + 1);
  const dBelow = new Date(d); dBelow.setDate(d.getDate() + 7);
  const rightDifferentMonth = !isLastCol && (dRight.getMonth() !== d.getMonth() || dRight.getFullYear() !== d.getFullYear());
  const belowDifferentMonth = (dBelow.getMonth() !== d.getMonth() || dBelow.getFullYear() !== d.getFullYear());
  const SEP_COLOR = '#334155'; // slate-700 — close to black but not harsh
  let sepStyle = '';
  if (rightDifferentMonth) sepStyle += `border-right-color: ${SEP_COLOR};`;
  if (belowDifferentMonth) sepStyle += `border-bottom-color: ${SEP_COLOR};`;

  const cellBg = isToday ? 'bg-slate-50'
    : isOutsideRange ? 'bg-slate-50/40'
    : (isPast) ? 'bg-slate-100/60'
    : '';
  const cellRing = isToday ? 'ring-2 ring-inset ring-slate-900 relative z-10' : '';

  const dayNumStyle = isToday
    ? 'bg-slate-900 text-white px-2.5 py-0.5 rounded-lg text-[26px] font-extrabold leading-none tracking-tight'
    : isOutsideRange ? 'text-slate-300 text-[26px] font-extrabold leading-none tracking-tight'
    : isPast ? 'text-slate-400 text-[26px] font-extrabold leading-none tracking-tight'
    : 'text-slate-900 text-[26px] font-extrabold leading-none tracking-tight';

  const eventsDimmed = (isPast && !isToday) ? 'opacity-50 saturate-50' : '';
  const monthLabel = isFirstOfMonth
    ? `<span class="text-[20px] font-bold uppercase tracking-wider ${isOutsideRange ? 'text-slate-300' : 'text-slate-900'} mr-1">${MONTHS[d.getMonth()].slice(0,3)}</span>`
    : '';

  return `
    <div data-day="${dateKey(d)}" data-month-key="${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}"
      class="min-h-[150px] border-r border-b border-slate-100 p-2 flex flex-col gap-1.5 ${cellBg} ${cellRing} ${isLastCol ? 'border-r-0' : ''}"
      style="${sepStyle}">
      <div class="flex items-start justify-between gap-1 min-h-[28px]">
        <div class="flex items-baseline gap-1">
          ${monthLabel}
          <span class="${dayNumStyle}">${d.getDate()}</span>
        </div>
        ${events.length > 0 && !isOutsideRange ? `<span class="text-[10px] font-semibold ${isToday ? 'text-slate-700' : 'text-slate-400'} mt-2">${events.length} event${events.length === 1 ? '' : 's'}</span>` : ''}
      </div>
      ${!isOutsideRange ? `
        <div class="flex flex-col gap-0.5 ${eventsDimmed}">
          ${visible.map(renderMonthCellEvent).join('')}
          ${overflow > 0 ? `
            <button data-action="open-day" data-date="${dateKey(d)}" class="text-[11px] text-slate-500 hover:text-slate-900 text-left px-1.5 font-medium mt-0.5">
              + ${overflow} more
            </button>
          ` : ''}
        </div>
      ` : ''}
    </div>
  `;
}

function renderMonthCellEvent(ev) {
  const start = new Date(ev.start);
  const loc = displayLocation(ev.location);
  const free = isFreeEvent(ev);
  const projected = isProjected(ev);
  const soldOut = isSoldOut(ev);
  const isFav = ev.shortCode && STATE.favorites.has(ev.shortCode);
  const isShared = ev.shortCode && STATE.sharedFavorites.has(ev.shortCode);
  const sharedBg = isShared ? ' bg-yellow-50 ring-1 ring-yellow-300' : '';
  const wrapClass = projected
    ? `group w-full text-left rounded-md hover:bg-slate-100 transition px-1.5 py-1 border border-dashed border-slate-300${sharedBg}`
    : `group w-full text-left rounded-md hover:bg-slate-100 transition px-1.5 py-1${sharedBg}`;
  const timeClass = projected ? 'text-slate-400' : 'text-slate-600';
  const titleClass = projected ? 'italic text-slate-500' : (soldOut ? 'font-light text-slate-400' : 'font-light text-slate-900');
  // Right-side tag priority: favorited star > TBC > SOLD OUT > FREE
  const favStarTag = isFav
    ? '<svg width="11" height="11" viewBox="0 0 24 24" fill="#facc15" stroke="#ca8a04" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="ml-auto flex-shrink-0"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
    : '';
  const rightTag = projected
    ? '<span class="text-[9.5px] font-bold text-slate-400 tracking-wide ml-auto">TBC</span>'
    : soldOut
    ? '<span class="text-[9.5px] font-bold text-rose-600 tracking-wide ml-auto">SOLD OUT</span>'
    : (free ? '<span class="text-[9.5px] font-bold text-emerald-600 tracking-wide ml-auto">FREE</span>' : '');
  return `
    <button data-action="open-event" data-id="${ev.id}"
      class="${wrapClass}">
      <div class="flex items-center gap-1.5 leading-none">
        ${renderSourceAvatar(ev.source, 13)}
        <span class="text-[10.5px] font-semibold ${timeClass} tracking-tight whitespace-nowrap">${fmtTime(start)}</span>
        ${favStarTag || rightTag}
      </div>
      <div class="mt-1 text-[11.5px] ${titleClass} leading-tight line-clamp-2 group-hover:underline">${escapeHtml(ev.title)}</div>
      ${loc ? `
        <div class="mt-0.5 flex items-center gap-0.5 text-[10px] text-slate-500 leading-none">
          <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="flex-shrink-0"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
          <span class="truncate">${escapeHtml(loc)}</span>
        </div>
      ` : ''}
    </button>
  `;
}

// Update the sticky month indicator based on which cell is at the top of the viewport
function updateStickyMonthLabel() {
  const indicator = document.getElementById('cur-month');
  if (!indicator) return;
  const grid = document.getElementById('cells-grid');
  if (!grid) return;
  const sticky = document.querySelector('.month-sticky');
  const stickyBottom = sticky ? sticky.getBoundingClientRect().bottom : 100;
  const cells = grid.querySelectorAll('[data-month-key]');
  let topCell = null;
  for (const c of cells) {
    const rect = c.getBoundingClientRect();
    if (rect.bottom > stickyBottom + 4) { topCell = c; break; }
  }
  if (!topCell) return;
  const key = topCell.dataset.monthKey;
  const [y, m] = key.split('-').map(Number);
  const label = `${MONTHS[m-1]} ${y}`;
  if (indicator.textContent !== label) indicator.textContent = label;
}

// ---------- Year view ----------
function renderYearGrid() {
  const year = STATE.month.getFullYear();
  const months = [];
  for (let m = 0; m < 12; m++) months.push(new Date(year, m, 1));
  return `
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      ${months.map(renderMiniMonth).join('')}
    </div>
  `;
}

function renderMiniMonth(monthStart) {
  const monthEnd = endOfMonth(monthStart);
  const firstWeekday = (monthStart.getDay() + 6) % 7;
  const gridStart = new Date(monthStart); gridStart.setDate(monthStart.getDate() - firstWeekday);
  const totalDays = firstWeekday + monthEnd.getDate();
  const rows = Math.ceil(totalDays / 7);
  const cells = [];
  for (let i = 0; i < rows * 7; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    cells.push(d);
  }
  const today = new Date();
  const monthEvents = eventsForMonth(monthStart);
  const isCurrentMonth = isSameMonth(monthStart, today);
  return `
    <div class="bg-white rounded-2xl border ${isCurrentMonth ? 'border-slate-900 ring-2 ring-slate-200' : 'border-slate-200'} overflow-hidden">
      <button data-action="open-month" data-year="${monthStart.getFullYear()}" data-month="${monthStart.getMonth()}"
        class="w-full text-left px-3.5 py-2.5 border-b border-slate-100 hover:bg-slate-50 transition flex items-center justify-between">
        <span class="font-bold text-base text-slate-900">
          ${MONTHS[monthStart.getMonth()]}
        </span>
        <span class="text-xs text-slate-400 font-medium">
          ${monthEvents.length} event${monthEvents.length === 1 ? '' : 's'}
        </span>
      </button>
      <div class="grid grid-cols-7 text-[9px] text-slate-400 font-bold uppercase border-b border-slate-100 py-1">
        ${DAY_LABELS.map(l => `<div class="text-center">${l[0]}</div>`).join('')}
      </div>
      <div class="grid grid-cols-7 p-2 gap-0.5">
        ${cells.map(d => renderMiniMonthCell(d, monthStart, today)).join('')}
      </div>
    </div>
  `;
}

function renderMiniMonthCell(d, monthStart, today) {
  const isOtherMonth = !isSameMonth(d, monthStart);
  if (isOtherMonth) return `<div class="aspect-square"></div>`;
  const isToday = isSameDay(d, today);
  const isPast = startOfDay(d) < startOfDay(today);
  const events = eventsForDay(d);
  const hasEvents = events.length > 0;
  const cat = hasEvents ? primaryCategory(events[0]) : null;
  const dayText = isToday
    ? 'text-white font-bold'
    : isPast ? 'text-slate-300 font-medium'
    : hasEvents ? 'text-slate-900 font-semibold'
    : 'text-slate-500';
  const bg = isToday ? 'bg-slate-900' : '';
  return `
    <button data-action="open-day" data-date="${dateKey(d)}"
      class="aspect-square rounded-md flex flex-col items-center justify-center text-[11px] hover:bg-slate-100 relative transition ${dayText} ${bg}">
      <span class="leading-none">${d.getDate()}</span>
      ${hasEvents && !isToday ? `<span class="cat-${cat} cat-stripe absolute bottom-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full"></span>` : ''}
    </button>
  `;
}

// ---------- Event drawer ----------
function renderEventDrawer(id) {
  const ev = STATE.events.find(e => e.id === id);
  if (!ev) return '';
  const start = new Date(ev.start);
  const end = ev.end ? new Date(ev.end) : null;
  const cats = effectiveCategories(ev);
  const src = STATE.sources[ev.source];
  const loc = displayLocation(ev.location);
  const projected = isProjected(ev);
  const soldOut = isSoldOut(ev);
  const links = getLinks(ev);
  // Dedupe by URL — when a source has no separate website (website === IG),
  // the Instagram label wins and the duplicate "Website" button is dropped.
  const seenHrefs = new Set();
  const secondaryLinks = [
    links.instagram ? { label: 'Instagram', href: links.instagram } : null,
    links.website   ? { label: 'Website',   href: links.website   } : null,
  ].filter(l => {
    if (!l) return false;
    if (seenHrefs.has(l.href)) return false;
    seenHrefs.add(l.href);
    return true;
  });
  return `
    <div class="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-end">
      <div data-action="close-event" data-drawer-backdrop class="absolute inset-0 bg-slate-900/40"></div>
      <div data-drawer-card class="relative bg-white w-full sm:max-w-md sm:h-full sm:rounded-none rounded-t-2xl max-h-[88vh] sm:max-h-full overflow-y-auto overscroll-contain shadow-xl will-change-transform">
        ${ev.image ? `
          <img src="${escapeHtml(ev.image)}" alt="" loading="lazy" decoding="async"
            class="w-full h-48 sm:h-56 object-cover bg-slate-100"
            onerror="this.remove()" />
        ` : ''}
        <div class="sticky top-0 bg-white border-b border-slate-200 px-5 py-3.5 flex items-center gap-3">
          ${renderSourceAvatar(ev.source, 36)}
          <span class="text-base font-semibold" style="color:${src?.color || '#475569'}">${src?.shortName || ev.source}</span>
          <div class="flex-1"></div>
          ${renderFavBtn(ev, 'p-1.5')}
          <button data-action="close-event" class="text-slate-400 hover:text-slate-900 p-1" aria-label="Close">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
        <div class="px-5 py-5">
          <div class="flex items-start gap-2">
            <h2 class="text-xl font-semibold leading-tight flex-1 ${projected ? 'italic text-slate-700' : (soldOut ? 'text-slate-500' : '')}">${escapeHtml(ev.title)}</h2>
            ${projected ? '<span class="text-[10px] font-bold tracking-wider uppercase text-slate-500 bg-slate-100 border border-dashed border-slate-300 px-2 py-1 rounded-md whitespace-nowrap">Projected</span>'
              : soldOut ? '<span class="text-[10px] font-bold tracking-wider uppercase text-rose-700 bg-rose-50 border border-rose-200 px-2 py-1 rounded-md whitespace-nowrap">Sold out</span>'
              : ''}
          </div>
          <div class="mt-3 space-y-1.5 text-sm text-slate-600">
            <div class="flex items-start gap-2">
              <svg class="mt-0.5 flex-shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
              <span>${fmtDayHeader(start)} · ${fmtTime(start)}${end ? ' – ' + fmtTime(end) : ''}</span>
            </div>
            ${loc ? `
              <div class="flex items-start gap-2">
                <svg class="mt-0.5 flex-shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
                <span>${escapeHtml(loc)}</span>
              </div>
            ` : ''}
            ${ev.price && !projected ? `
              <div class="flex items-start gap-2">
                <svg class="mt-0.5 flex-shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg>
                <span>${escapeHtml(ev.price)}</span>
              </div>
            ` : ''}
            ${ev.attendees != null ? `
              <div class="flex items-start gap-2">
                <svg class="mt-0.5 flex-shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
                <span>${ev.attendees} going</span>
              </div>
            ` : ''}
          </div>
          ${cats.length ? `
            <div class="mt-4 flex flex-wrap gap-1.5">
              ${cats.map(c => `<span class="cat-${c} cat-chip text-xs px-2.5 py-1 rounded-full font-medium capitalize">${c}</span>`).join('')}
            </div>
          ` : ''}
          ${projected ? `
            <div class="mt-5 p-4 rounded-xl bg-slate-50 border border-dashed border-slate-300 text-sm text-slate-600 leading-relaxed">
              <strong class="block font-semibold text-slate-900 mb-1">Tickets not yet released</strong>
              ${escapeHtml(STATE.sources[ev.source]?.shortName || 'This event')} typically releases tickets a few days after the previous month's event. Check back closer to the date.
            </div>
          ` : (links.tickets ? `
            <a href="${escapeHtml(links.tickets)}" target="_blank" rel="noopener" class="mt-6 w-full inline-flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-800 text-white font-medium px-4 py-3 rounded-xl transition">
              View event
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
            </a>
          ` : '')}
          ${secondaryLinks.length ? `
            <div class="mt-3 flex flex-wrap gap-2">
              ${secondaryLinks.map(l => `
                <a href="${escapeHtml(l.href)}" target="_blank" rel="noopener" class="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-lg border border-slate-200 text-sm font-medium text-slate-700 hover:bg-slate-50">
                  ${l.label}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                </a>
              `).join('')}
            </div>
          ` : ''}
          ${(() => {
            // Curated Instagram post embed, opted-in per source via
            // `instagramFeaturedByTitle: { "<title>": "<post-id>" }`.
            // Carousels (multi-photo posts) and reels both work through
            // the same /p/<id>/ URL — the embed widget handles paging
            // through carousel images inline.
            const postId = src?.instagramFeaturedByTitle?.[ev.title];
            if (!postId) return '';
            const permalink = `https://www.instagram.com/p/${postId}/`;
            return `
              <div class="mt-5 -mx-5 px-5 pt-5 border-t border-slate-100">
                <p class="text-xs uppercase tracking-wider font-semibold text-slate-500 mb-3">From their Instagram</p>
                <blockquote class="instagram-media" data-instgrm-permalink="${permalink}" data-instgrm-version="14"
                  style="background:#FFF; border:0; border-radius:3px; box-shadow:0 0 1px 0 rgba(0,0,0,0.5),0 1px 10px 0 rgba(0,0,0,0.15); margin:0; max-width:540px; min-width:280px; padding:0; width:100%;">
                  <div style="padding:16px;">
                    <a href="${permalink}" target="_blank" rel="noopener" style="color:#0f172a; font-size:14px;">View on Instagram</a>
                  </div>
                </blockquote>
              </div>
            `;
          })()}
        </div>
      </div>
    </div>
  `;
}

// ---------- Event handlers ----------
function attachHandlers() {
  document.querySelectorAll('[data-action]').forEach(el => {
    el.addEventListener('click', handleAction);
  });
}

function handleAction(e) {
  const el = e.currentTarget;
  const action = el.dataset.action;
  const view = effectiveView();
  switch (action) {
    case 'prev-period':
      if (view === 'list') {
        // Base on what's actually visible at the top, not the anchor.
        jumpListToMonth(addMonths(STATE.displayedMonth || STATE.month, -1));
        render();
        window.scrollTo({ top: 0, behavior: 'auto' });
      } else {
        STATE.month = view === 'year' ? addYears(STATE.month, -1) : addMonths(STATE.month, -1);
        render();
      }
      break;
    case 'next-period':
      if (view === 'list') {
        jumpListToMonth(addMonths(STATE.displayedMonth || STATE.month, 1));
        render();
        window.scrollTo({ top: 0, behavior: 'auto' });
      } else {
        STATE.month = view === 'year' ? addYears(STATE.month,  1) : addMonths(STATE.month,  1);
        render();
      }
      break;
    case 'today': {
      const todayMonth = startOfMonth(new Date());
      if (view === 'list') jumpListToMonth(todayMonth);
      else STATE.month = view === 'year' ? new Date(new Date().getFullYear(), 0, 1) : todayMonth;
      render();
      // In list view, also scroll to today's section. Other views just scroll to top.
      setTimeout(() => {
        if (view === 'list') {
          const todayHeader = [...document.querySelectorAll('section h2')]
            .find(h => h.textContent.trim().toLowerCase().startsWith('today'));
          if (todayHeader) {
            todayHeader.scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
          }
        }
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }, 0);
      break;
    }
    case 'view-list':  STATE.view = 'list';  render(); break;
    case 'view-month': STATE.view = 'month'; render(); break;
    case 'view-year':  STATE.view = 'year';  render(); break;
    case 'toggle-filters':
      STATE.filtersOpen = !STATE.filtersOpen;
      render(); break;
    case 'toggle-fav': {
      const code = el.dataset.code;
      if (!code) break;
      if (STATE.favorites.has(code)) STATE.favorites.delete(code);
      else STATE.favorites.add(code);
      saveFavorites();
      render(); break;
    }
    case 'toggle-fav-filter':
      STATE.filters.favoritesOnly = !STATE.filters.favoritesOnly;
      render(); break;
    case 'toggle-shared-filter':
      STATE.filters.sharedOnly = !STATE.filters.sharedOnly;
      render(); break;
    case 'toggle-past-events':
      STATE.showPastEvents = !STATE.showPastEvents;
      render(); break;
    case 'share':
      doShare(); break;
    case 'clear-share':
      STATE.sharedFavorites = new Set();
      STATE.sharedNotFound = 0;
      STATE.filters.sharedOnly = false;
      // Strip the hash from the URL but keep query params (filter state).
      history.replaceState(null, '', location.pathname + location.search);
      render(); break;
    case 'save-shared': {
      let added = 0;
      for (const code of STATE.sharedFavorites) {
        if (!STATE.favorites.has(code)) {
          STATE.favorites.add(code);
          added++;
        }
      }
      saveFavorites();
      showToast(added > 0 ? `Saved ${added} to favorites` : 'Already in favorites');
      render(); break;
    }
    case 'prompt-clear-favorites':
      STATE.modal = 'clear-favorites';
      render(); break;
    case 'open-contact':
      STATE.modal = 'contact';
      render(); break;
    case 'do-clear-favorites': {
      const n = STATE.favorites.size;
      STATE.favorites = new Set();
      saveFavorites();
      STATE.modal = null;
      // Drop the favorites-only filter if it was on — nothing left to filter to.
      STATE.filters.favoritesOnly = false;
      showToast(`Removed ${n} favorite${n === 1 ? '' : 's'}`);
      render(); break;
    }
    case 'close-modal':
      STATE.modal = null;
      render(); break;
    case 'toggle-cat': {
      const c = el.dataset.cat;
      if (STATE.filters.categories.has(c)) STATE.filters.categories.delete(c);
      else STATE.filters.categories.add(c);
      render(); break;
    }
    case 'toggle-src': {
      const s = el.dataset.src;
      if (STATE.filters.sources.has(s)) STATE.filters.sources.delete(s);
      else STATE.filters.sources.add(s);
      render(); break;
    }
    case 'clear-filters':
      STATE.filters.categories.clear();
      STATE.filters.sources.clear();
      STATE.filters.favoritesOnly = false;
      STATE.filters.sharedOnly = false;
      render(); break;
    case 'open-event':
      STATE.openEvent = el.dataset.id;
      render(); break;
    case 'close-event':
      STATE.openEvent = null;
      // Surgical close — see swipe-close comment in attachDrawerSwipeHandlers.
      document.querySelector('[data-drawer-card]')?.closest('.fixed')?.remove();
      syncBodyScrollLock();
      break;
    case 'open-month': {
      const y = parseInt(el.dataset.year, 10);
      const m = parseInt(el.dataset.month, 10);
      STATE.month = new Date(y, m, 1);
      STATE.view = 'month';
      render(); break;
    }
    case 'open-day': {
      const k = el.dataset.date;
      const [y, m, d] = k.split('-').map(Number);
      jumpListToMonth(new Date(y, m-1, 1));
      STATE.view = 'list';
      render();
      setTimeout(() => {
        const headers = [...document.querySelectorAll('section h2')];
        const target = headers.find(h => h.textContent.includes(`${d} ${MONTHS[m-1]}`) || h.textContent.includes(`${d} ${MONTHS[m-1].slice(0,3)}`));
        target && target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 0);
      break;
    }
  }
}

// ---------- Utils ----------
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));
}
// Returns the location to show, or '' if it's generic / unknown
function displayLocation(loc) {
  if (!loc) return '';
  const trimmed = String(loc).trim();
  if (/^(london|uk|united kingdom|england|location tbc|tbc|tba|location revealed.*)$/i.test(trimmed)) return '';
  // strip "London"/"UK" suffix if present, return first meaningful part
  const parts = trimmed.split(',').map(s => s.trim()).filter(Boolean);
  if (parts.length === 0) return '';
  const first = parts[0];
  if (/^(london|uk|united kingdom)$/i.test(first)) return parts[1] || '';
  return first;
}
function isFreeEvent(ev) {
  return ev.price && /^(free|0)$/i.test(String(ev.price).trim());
}
function isProjected(ev) {
  return ev.status === 'projected';
}
function isSoldOut(ev) {
  return ev.soldOut === true;
}
// Public links to surface. Falls back to ev.url for confirmed events so older
// data (TRYBZ/BGO) without the explicit links object keeps working.
function getLinks(ev) {
  const l = ev.links || {};
  const src = STATE.sources[ev.source] || {};
  // Event-level overrides source-level. Source-level fills in defaults
  // (e.g. website / instagram) so individual events don't need to repeat
  // the same social links.
  return {
    tickets: l.tickets || (isProjected(ev) ? null : ev.url),
    website: l.website || src.website || null,
    instagram: l.instagram || src.instagram || null,
  };
}
function renderSourceAvatar(sourceId, size = 16) {
  const src = STATE.sources[sourceId];
  if (!src) return '';
  const letter = (src.letter || src.shortName || src.name || sourceId)[0].toUpperCase();
  const color = src.color || '#64748b';
  const font = Math.max(8, Math.round(size * 0.58));
  if (src.logo) {
    return `<img src="${src.logo}" alt="${escapeHtml(src.name)}" loading="lazy" decoding="async"
      class="rounded-full flex-shrink-0 object-cover"
      style="width:${size}px;height:${size}px;background:${color}"
      onerror="this.outerHTML='<span class=\\'inline-flex items-center justify-center rounded-full flex-shrink-0 text-white font-bold leading-none\\' style=\\'width:${size}px;height:${size}px;background:${color};font-size:${font}px\\'>${letter}</span>'" />`;
  }
  return `<span class="inline-flex items-center justify-center rounded-full flex-shrink-0 text-white font-bold leading-none"
    style="width:${size}px;height:${size}px;background:${color};font-size:${font}px">${letter}</span>`;
}

// ---------- Go ----------
init();
