/**
 * events.js — Global keyboard shortcuts + search debounce
 * Загружать ПОСЛЕДНИМ перед app.js
 */

// ── Keyboard shortcuts ─────────────────────────────────────
document.addEventListener('keydown', e => {
  const inInput = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);

  // Escape — close all overlays in priority order
  if (e.key === 'Escape') {
    if (document.getElementById('dpOverlay')?.classList.contains('open'))    { window.DetailsModule?.close(); return; }
    if (document.getElementById('taskModal')?.classList.contains('open'))    { window.ModalsModule?.close();  return; }
    if (document.getElementById('qaOverlay')?.classList.contains('open'))    { window.QuickActions?.close();  return; }
    if (document.getElementById('sbOverlay')?.classList.contains('open'))    { window.SidebarModule?.close(); return; }
    if (document.getElementById('linkDialog')?.classList.contains('open'))   { window.RichEditor?.closeLinkDialog?.(); return; }
  }

  if (inInput) return; // don't fire shortcuts when typing

  // N — new task
  if (e.key === 'n' || e.key === 'N') {
    e.preventDefault();
    window.ModalsModule?.openAdd();
  }
  // R — refresh
  if (e.key === 'r' || e.key === 'R') {
    e.preventDefault();
    window.loadTasks?.();
  }
  // K — toggle kanban
  if (e.key === 'k' || e.key === 'K') {
    e.preventDefault();
    window.TasksModule?.toggleView();
  }
  // / — focus search
  if (e.key === '/') {
    e.preventDefault();
    document.getElementById('searchInput')?.focus();
  }
});

// ── Search debounce ────────────────────────────────────────
let _searchTimer;
document.getElementById('searchInput')?.addEventListener('input', () => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => window.TasksModule?.render(), 280);
});

// ── Sort menu: close on outside click ─────────────────────
document.addEventListener('click', e => {
  const toolbar = document.querySelector('.toolbar');
  const menu    = document.getElementById('sortMenu');
  if (menu && toolbar && !toolbar.contains(e.target)) {
    menu.style.display = 'none';
  }
});

// ── Hide loading screen ────────────────────────────────────
window.addEventListener('load', () => {
  const loading = document.getElementById('loading');
  if (loading) setTimeout(() => loading.classList.add('hidden'), 500);
});
