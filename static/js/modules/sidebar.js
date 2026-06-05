/**
 * sidebar.js — Left-drawer navigation
 */
window.SidebarModule = (function() {
  let _open = false;

  function init() {
    const overlay = document.getElementById('sbOverlay');
    const closeBtn = document.getElementById('sbCloseBtn');
    const addBtn   = document.getElementById('sbAddBtn');
    const hamburger = document.getElementById('hamburgerBtn');
    const logo     = document.getElementById('logoBtn');

    overlay?.addEventListener('click', e => { if (e.target === overlay) close(); });
    closeBtn?.addEventListener('click', close);
    hamburger?.addEventListener('click', open);
    logo?.addEventListener('click', open);
    addBtn?.addEventListener('click', () => { close(); setTimeout(() => window.ModalsModule?.openAdd(), 150); });

    // Nav items
    document.querySelectorAll('.sb-nav-item[data-filter]').forEach(item => {
      item.addEventListener('click', e => { e.stopPropagation(); _navigate(item.dataset.filter, item); });
    });

    // Section collapse headers
    document.querySelectorAll('.sb-section-header[data-section]').forEach(hdr => {
      hdr.addEventListener('click', e => { e.stopPropagation(); toggleSection(hdr.dataset.section); });
    });

    // Action items
    document.querySelectorAll('.sb-nav-item[data-action]').forEach(item => {
      item.addEventListener('click', e => {
        e.stopPropagation();
        const act = item.dataset.action;
        if (act === 'toggleView') { close(); setTimeout(() => window.TasksModule?.toggleView(), 150); }
        if (act === 'refresh')    { close(); setTimeout(() => window.loadTasks(), 150); }
      });
    });

    // Edge swipe (mobile only)
    if (window.isMobile) _initEdgeSwipe();

    updateCounts();
  }

  function open() {
    document.getElementById('sbOverlay')?.classList.add('open');
    document.body.style.overflow = 'hidden';
    _open = true;
    window.tg?.HapticFeedback?.impactOccurred('light');
    updateCounts();
  }

  function close() {
    document.getElementById('sbOverlay')?.classList.remove('open');
    document.body.style.overflow = '';
    _open = false;
  }

  function toggle() { _open ? close() : open(); }

  function toggleSection(id) {
    document.getElementById(id)?.classList.toggle('collapsed');
  }

  function _navigate(filter, el) {
    setActiveItem(filter);
    window.FiltersModule?.setFilter(filter);
    close();
  }

  function setActiveItem(filter) {
    document.querySelectorAll('.sb-nav-item[data-filter]').forEach(i => {
      i.classList.toggle('active', i.dataset.filter === filter);
    });
  }

  function updateCounts() {
    if (!window.tasks) return;
    const td = window.todayDate();
    const c  = {
      all:     window.tasks.filter(t => t.status !== 'done').length,
      doing:   window.tasks.filter(t => t.status === 'doing').length,
      todo:    window.tasks.filter(t => t.status === 'todo').length,
      done:    window.tasks.filter(t => t.status === 'done').length,
      today:   window.tasks.filter(t => t.deadline && t.status !== 'done' && new Date(t.deadline).toDateString() === td.toDateString()).length,
      overdue: window.tasks.filter(t => t.deadline && t.status !== 'done' && window.safeDate(t.deadline) < td).length,
      high:    window.tasks.filter(t => t.priority === 'high' && t.status !== 'done').length,
    };
    Object.entries(c).forEach(([k, v]) => {
      const el = document.getElementById('sbCnt-' + k);
      if (el) el.textContent = v > 0 ? v : '';
    });

    // Stats bar
    const n = { sbStatAll: window.tasks.length, sbStatDoing: c.doing, sbStatOverdue: c.overdue };
    Object.entries(n).forEach(([id, v]) => { const el = document.getElementById(id); if (el) el.textContent = v; });

    // Progress bar
    const total = window.tasks.length;
    const done  = window.tasks.filter(t => t.status === 'done').length;
    const pct   = total ? Math.round(done / total * 100) : 0;
    const pEl   = document.getElementById('sbPct'), fEl = document.getElementById('sbFill');
    if (pEl) pEl.textContent = pct + '%';
    if (fEl) fEl.style.width = pct + '%';

    // User name
    const name = window.tg?.initDataUnsafe?.user?.first_name || window.userName || '';
    const nEl  = document.getElementById('sbUserName');
    if (nEl && name) nEl.textContent = name;
  }

  function _initEdgeSwipe() {
    const zone = document.getElementById('sbEdgeZone');
    if (!zone) return;
    let startX = 0, startY = 0, tracking = false;
    zone.addEventListener('touchstart', e => {
      startX = e.touches[0].clientX; startY = e.touches[0].clientY; tracking = true;
    }, { passive: true });
    document.addEventListener('touchmove', e => {
      if (!tracking) return;
      const dx = e.touches[0].clientX - startX;
      const dy = Math.abs(e.touches[0].clientY - startY);
      if (dx > 40 && dy < 60) { tracking = false; open(); }
    }, { passive: true });
    document.addEventListener('touchend', () => { tracking = false; }, { passive: true });
  }

  // Keyboard ESC
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && _open) close(); });

  // Init after DOM ready
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  return { open, close, toggle, toggleSection, setActiveItem, updateCounts, isOpen: () => _open };
})();

window.openSidebar  = () => window.SidebarModule.open();
window.closeSidebar = () => window.SidebarModule.close();
