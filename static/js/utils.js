/**
 * utils.js — Pure utility functions + UI helpers
 * Загружать после state.js
 */

// ── HTML escaping ──────────────────────────────────────────
window.escHtml = function(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
};

window.escAttr = function(s) {
  return String(s)
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
};

// ── Date helpers ───────────────────────────────────────────
window.todayDate = function() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
};

window.safeDate = function(s) {
  try {
    const d = new Date(s);
    if (isNaN(d)) return new Date(9999, 0, 1);
    d.setHours(0, 0, 0, 0);
    return d;
  } catch {
    return new Date(9999, 0, 1);
  }
};

/**
 * Returns deadline display info for a task.
 * @returns {{ label: string, isOverdue: boolean, isToday: boolean, raw: Date } | null}
 */
window.deadlineStr = function(task) {
  if (!task.deadline) return null;
  const d  = new Date(task.deadline);
  if (isNaN(d)) return null;
  d.setHours(0, 0, 0, 0);

  const td       = window.todayDate();
  const tomorrow = new Date(td);
  tomorrow.setDate(tomorrow.getDate() + 1);

  const isOverdue  = d < td && task.status !== 'done';
  const isToday    = d.toDateString() === td.toDateString();
  const isTomorrow = d.toDateString() === tomorrow.toDateString();

  let label;
  if (isToday)    label = 'Сегодня';
  else if (isTomorrow) label = 'Завтра';
  else label = d.toLocaleDateString('ru', { day: 'numeric', month: 'short' });

  if (isOverdue) label = '⚠ ' + label;

  return { label, isOverdue, isToday, raw: d };
};

// ── Task filtering & sorting ───────────────────────────────
window.filterTasks = function(tasks, filter, query = '') {
  const td = window.todayDate();

  let result = tasks.filter(t => {
    switch (filter) {
      case 'todo':    return t.status === 'todo';
      case 'doing':   return t.status === 'doing';
      case 'done':    return t.status === 'done';
      case 'high':    return t.priority === 'high' && t.status !== 'done';
      case 'today':
        return t.deadline && t.status !== 'done' &&
          new Date(t.deadline).toDateString() === td.toDateString();
      case 'overdue':
        return t.deadline && t.status !== 'done' &&
          window.safeDate(t.deadline) < td;
      default:        return true; // 'all'
    }
  });

  if (query) {
    const q = query.trim().toLowerCase();
    result = result.filter(t =>
      t.title.toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q) ||
      (t.assignee || '').toLowerCase().includes(q)
    );
  }

  return result;
};

window.sortTasks = function(tasks, sort) {
  return [...tasks].sort((a, b) => {
    switch (sort) {
      case 'date_asc':  return (a.created_at || '').localeCompare(b.created_at || '');
      case 'date_desc': return (b.created_at || '').localeCompare(a.created_at || '');
      case 'deadline':  return (a.deadline || '9999').localeCompare(b.deadline || '9999');
      case 'priority':  return window.PRIORITY_ORDER[a.priority] - window.PRIORITY_ORDER[b.priority];
      case 'title':     return a.title.localeCompare(b.title, 'ru');
      default:          return (b.created_at || '').localeCompare(a.created_at || '');
    }
  });
};

// ── Toast ──────────────────────────────────────────────────
window.showToast = function(msg, type = '') {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className   = `toast show ${type}`.trim();
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2500);
};

// ── Stats + progress ───────────────────────────────────────
window.updateStats = function() {
  const total   = window.tasks.length;
  const doing   = window.tasks.filter(t => t.status === 'doing').length;
  const done    = window.tasks.filter(t => t.status === 'done').length;
  const td      = window.todayDate();
  const overdue = window.tasks.filter(t =>
    t.deadline && window.safeDate(t.deadline) < td && t.status !== 'done'
  ).length;

  _animateStat('statTotal',   total);
  _animateStat('statDoing',   doing);
  _animateStat('statDone',    done);
  _animateStat('statOverdue', overdue);

  const pct  = total ? Math.round(done / total * 100) : 0;
  const pEl  = document.getElementById('progressPct');
  const fEl  = document.getElementById('progressFill');
  if (pEl) pEl.textContent    = pct + '%';
  if (fEl) fEl.style.width    = pct + '%';

  // Keep sidebar in sync
  window.SidebarModule?.updateCounts();
};

function _animateStat(id, val) {
  const el = document.getElementById(id);
  if (!el || el.textContent == val) return;
  el.textContent = val;
  el.classList.remove('pop');
  void el.offsetWidth;          // force reflow
  el.classList.add('pop');
}

// ── Streak ─────────────────────────────────────────────────
window.updateStreak = function() {
  const todayStr = new Date().toISOString().slice(0, 10);
  const count    = window.tasks.filter(t =>
    t.status === 'done' && (t.updated_at || '').startsWith(todayStr)
  ).length;
  const badge = document.getElementById('streakBadge');
  const num   = document.getElementById('streakNum');
  if (!badge || !num) return;
  num.textContent = count;
  badge.classList.toggle('hidden', count === 0);
};

// ── Last sync time ─────────────────────────────────────────
window.updateLastSync = function() {
  const el = document.getElementById('lastSync');
  if (el) {
    el.textContent = 'Обновлено в ' +
      new Date().toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
  }
};
