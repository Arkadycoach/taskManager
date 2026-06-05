/**
 * app.js — Entry point + ALL button event listeners
 * Главная причина багов: кнопки не имели addEventListener
 */

window.isMobile = (function() {
  if (window.tg?.platform) {
    return ['ios','android','iphone','ipad'].some(p => window.tg.platform.includes(p));
  }
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
})();

window.isTelegram = !!window.tg;
document.body.classList.add(window.isMobile ? 'is-mobile' : 'is-desktop');
if (window.isTelegram) document.body.classList.add('is-telegram');

async function init() {
  // ── Telegram BackButton ──────────────────────────────
  if (window.isTelegram && window.tg?.BackButton) {
    window.tg.BackButton.onClick(() => {
      if (document.getElementById('dpOverlay')?.classList.contains('open'))  { window.DetailsModule?.close(); return; }
      if (document.getElementById('taskModal')?.classList.contains('open'))  { window.ModalsModule?.close();  return; }
      if (document.getElementById('qaOverlay')?.classList.contains('open'))  { window.QuickActions?.close();  return; }
      if (document.getElementById('sbOverlay')?.classList.contains('open'))  { window.SidebarModule?.close(); return; }
    });
  }

  // ── Load data ────────────────────────────────────────
  await window.loadTasks();

  // ── Hide loading ─────────────────────────────────────
  setTimeout(() => document.getElementById('loading')?.classList.add('hidden'), 400);

  // ════════════════════════════════════════════════════
  //  EVENT LISTENERS — все кнопки приложения
  //  Без этого ни одна кнопка не работает!
  // ════════════════════════════════════════════════════

  // ── Header ───────────────────────────────────────────
  document.getElementById('syncBtn')?.addEventListener('click', window.loadTasks);
  document.getElementById('viewBtn')?.addEventListener('click', () => window.TasksModule?.toggleView());
  document.getElementById('hamburgerBtn')?.addEventListener('click', () => window.SidebarModule?.open());
  document.getElementById('logoBtn')?.addEventListener('click', () => window.SidebarModule?.open());

  // ── FAB ──────────────────────────────────────────────
  document.getElementById('fabBtn')?.addEventListener('click', () => {
    window.ModalsModule?.openAdd();
    window.tg?.HapticFeedback?.impactOccurred('light');
  });

  // ── Filter tabs ── (главный баг — тут не было listeners)
  document.querySelectorAll('.tab[data-filter]').forEach(btn => {
    btn.addEventListener('click', () => window.FiltersModule?.setFilter(btn.dataset.filter));
  });

  // ── Stat cards ────────────────────────────────────────
  document.querySelectorAll('.stat-card[data-filter]').forEach(card => {
    card.addEventListener('click', () => window.FiltersModule?.setFilter(card.dataset.filter));
  });

  // ── Sort ─────────────────────────────────────────────
  document.getElementById('sortBtn')?.addEventListener('click', () => window.FiltersModule?.toggleSortMenu());
  document.querySelectorAll('.sort-item[data-sort]').forEach(btn => {
    btn.addEventListener('click', () => window.FiltersModule?.setSort(btn.dataset.sort, btn));
  });

  // ── Task modal ───────────────────────────────────────
  document.getElementById('modalSaveBtn')?.addEventListener('click',   () => window.ModalsModule?.save());
  document.getElementById('modalCancelBtn')?.addEventListener('click', () => window.ModalsModule?.close());
  document.getElementById('modalCloseBtn')?.addEventListener('click',  () => window.ModalsModule?.close());
  document.getElementById('deleteBtn')?.addEventListener('click',      () => window.ModalsModule?.deleteTask());
  document.getElementById('taskModal')?.addEventListener('click', e => {
    if (e.target.id === 'taskModal') window.ModalsModule?.close();
  });

  // ── Detail panel ─────────────────────────────────────
  document.getElementById('dpBackBtn')?.addEventListener('click',   () => window.DetailsModule?.close());
  document.getElementById('dpEditBtn')?.addEventListener('click',   () => window.DetailsModule?.edit());
  document.getElementById('dpDeleteBtn')?.addEventListener('click', () => window.DetailsModule?.deleteTask());
  document.getElementById('dpCheck')?.addEventListener('click',     () => window.DetailsModule?.toggleDone());
  document.getElementById('dpOverlay')?.addEventListener('click', e => {
    if (e.target.id === 'dpOverlay') window.DetailsModule?.close();
  });

  // ── Quick Actions ─────────────────────────────────────
  document.getElementById('qaTodoBtn')?.addEventListener('click',   () => window.QuickActions?.setStatus('todo'));
  document.getElementById('qaDoingBtn')?.addEventListener('click',  () => window.QuickActions?.setStatus('doing'));
  document.getElementById('qaDoneBtn')?.addEventListener('click',   () => window.QuickActions?.setStatus('done'));
  document.getElementById('qaEditBtn')?.addEventListener('click',   () => window.QuickActions?.edit());
  document.getElementById('qaDeleteBtn')?.addEventListener('click', () => window.QuickActions?.deleteTask());
  document.getElementById('qaOverlay')?.addEventListener('click', e => {
    if (e.target.id === 'qaOverlay') window.QuickActions?.close();
  });

  // ── Sidebar ───────────────────────────────────────────
  document.getElementById('sbOverlay')?.addEventListener('click', e => {
    if (e.target.id === 'sbOverlay') window.SidebarModule?.close();
  });

  // ── Mobile ───────────────────────────────────────────
  if (window.isMobile) window.TasksModule?.initPullToRefresh();

  // ── Notifications ─────────────────────────────────────
  window.NotificationsModule?.init();

  // ── Auto-refresh ──────────────────────────────────────
  setInterval(window.loadTasks, window.isMobile ? 30000 : 60000);
}

init();
