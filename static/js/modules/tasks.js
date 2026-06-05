/**
 * tasks.js — Task actions + swipe/longpress + quick-actions
 */
window.TasksModule = (function() {

  // ── View toggle ─────────────────────────────────────────
  function toggleView() {
    window.isKanban = !window.isKanban;
    const lv  = document.getElementById('listView');
    const kv  = document.getElementById('kanbanView');
    const btn = document.getElementById('viewBtn');
    if (lv)  lv.style.display  = window.isKanban ? 'none'  : 'block';
    if (kv)  kv.style.display  = window.isKanban ? 'block' : 'none';
    if (btn) { btn.textContent = window.isKanban ? '☰' : '⊞'; btn.classList.toggle('active-view', window.isKanban); }
    render();
    window.showToast(window.isKanban ? '⊞ Канбан' : '☰ Список', '');
  }

  function render() {
    if (window.isKanban) window.RenderModule.renderKanban();
    else                 window.RenderModule.renderTasks();
  }

  // ── Toggle done ──────────────────────────────────────────
  async function toggleDone(id) {
    const task = window.tasks.find(t => t.id === id);
    if (!task) return;
    const ns = task.status === 'done' ? 'todo' : 'done';
    task.status = ns;
    render();
    window.updateStats();
    window.updateStreak();
    await window.apiCall('PATCH', `/tasks/${id}`, { status: ns, user_id: window.userId });
    if (window.tg) window.tg.HapticFeedback?.impactOccurred('light');
    if (ns === 'done') window.showToast('🎉 Выполнено!', 'success');
  }

  // ── Swipe-to-complete ────────────────────────────────────
  function attachSwipeHandlers() {
    document.querySelectorAll('.task-card').forEach(card => {
      let startX, startY, swiping = false;
      const id   = card.dataset.id;
      const hint = card.querySelector('.swipe-hint');

      card.addEventListener('touchstart', e => {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        swiping = false;
      }, { passive: true });

      card.addEventListener('touchmove', e => {
        const dx = e.touches[0].clientX - startX;
        const dy = Math.abs(e.touches[0].clientY - startY);
        if (dy > 20 || dx < 0) return;
        if (dx > 15) {
          swiping = true;
          card.style.transform = `translateX(${Math.min(dx * 0.4, 60)}px)`;
          if (hint) { hint.classList.add('show'); hint.style.width = (Math.min(dx / 160, 1) * 70) + 'px'; }
        }
      }, { passive: true });

      card.addEventListener('touchend', e => {
        const dx = e.changedTouches[0].clientX - startX;
        card.style.transform = '';
        if (hint) { hint.classList.remove('show'); hint.style.width = '0'; }
        if (swiping && dx > 80) {
          const task = window.tasks.find(t => t.id === id);
          if (task && task.status !== 'done') {
            card.classList.add('swipe-done');
            setTimeout(() => toggleDone(id), 200);
            window.tg?.HapticFeedback?.notificationOccurred('success');
          }
        }
      }, { passive: true });
    });
  }

  // ── Long-press → Quick Actions ───────────────────────────
  function attachLongPressHandlers() {
    document.querySelectorAll('.task-card').forEach(card => {
      let timer;
      const id = card.dataset.id;
      card.addEventListener('touchstart', () => {
        timer = setTimeout(() => {
          window.QuickActions?.open(id);
          window.tg?.HapticFeedback?.impactOccurred('medium');
        }, 500);
      }, { passive: true });
      card.addEventListener('touchend',  () => clearTimeout(timer), { passive: true });
      card.addEventListener('touchmove', () => clearTimeout(timer), { passive: true });
      card.addEventListener('contextmenu', e => { e.preventDefault(); window.QuickActions?.open(id); });
    });
  }

  // ── Pull-to-refresh ──────────────────────────────────────
  function initPullToRefresh() {
    let ptrStartY = 0, active = false;
    const bar = document.getElementById('ptrBar');

    document.addEventListener('touchstart', e => { ptrStartY = e.touches[0].clientY; }, { passive: true });
    document.addEventListener('touchmove', e => {
      if (window.scrollY === 0 && e.touches[0].clientY - ptrStartY > 60 && !active) {
        active = true; if (bar) bar.classList.add('show');
      }
    }, { passive: true });
    document.addEventListener('touchend', async () => {
      if (active) {
        active = false;
        await window.loadTasks();
        if (bar) bar.classList.remove('show');
      }
    }, { passive: true });
  }

  return { toggleView, render, toggleDone, attachSwipeHandlers, attachLongPressHandlers, initPullToRefresh };
})();

// ── Quick Actions sheet ──────────────────────────────────
window.QuickActions = (function() {
  let targetId = null;

  function open(id) {
    const task = window.tasks.find(t => t.id === id);
    if (!task) return;
    targetId = id;
    const el = document.getElementById('qaTaskName');
    if (el) el.textContent = task.title;
    document.getElementById('qaOverlay')?.classList.add('open');
  }

  function close() {
    document.getElementById('qaOverlay')?.classList.remove('open');
    targetId = null;
  }

  async function setStatus(status) {
    if (!targetId) return;
    const task = window.tasks.find(t => t.id === targetId);
    if (!task) return;
    task.status = status;
    window.TasksModule.render();
    window.updateStats(); window.updateStreak();
    await window.apiCall('PATCH', `/tasks/${targetId}`, { status, user_id: window.userId });
    close();
    if (status === 'done') window.showToast('🎉 Выполнено!', 'success');
    else window.showToast('✓ Статус обновлён', 'success');
  }

  function edit() { const id = targetId; close(); if (id) window.ModalsModule?.openEdit(id); }

  async function deleteTask() {
    if (!targetId || !confirm('Удалить задачу?')) return;
    const id = targetId; close();
    await window.apiCall('DELETE', `/tasks/${id}`);
    window.tasks = window.tasks.filter(t => t.id !== id);
    window.TasksModule.render(); window.updateStats();
    window.showToast('Удалено', 'error');
  }

  return { open, close, setStatus, edit, deleteTask };
})();

// Global exports
window.toggleView  = ()       => window.TasksModule.toggleView();
window.qaSetStatus = (status) => window.QuickActions.setStatus(status);
window.qaEdit      = ()       => window.QuickActions.edit();
window.qaDelete    = ()       => window.QuickActions.deleteTask();
window.closeQA     = ()       => window.QuickActions.close();
