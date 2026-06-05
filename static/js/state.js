/**
 * state.js — Global application state
 * Загружать ПЕРВЫМ перед всеми модулями
 */

// ── Task data ──────────────────────────────────────────────
window.tasks     = [];
window.dpSubs    = [];   // subtasks in open detail panel
window.dpComs    = [];   // comments in open detail panel

// ── UI state ───────────────────────────────────────────────
window.currentFilter  = 'all';
window.currentSort    = 'date_desc';
window.isKanban       = false;
window.editingId      = null;
window.currentDetailId = null;

// ── Platform ───────────────────────────────────────────────
window.isMobile  = false;   // set by app.js
window.isTelegram = false;  // set by app.js

// ── Constants ──────────────────────────────────────────────
window.STATUS_LABELS = {
  todo:  'Новая',
  doing: 'В работе',
  done:  'Готово',
};

window.PRIORITY_LABELS = {
  high:   'Высокий',
  medium: 'Средний',
  low:    'Низкий',
};

window.FILTER_LABELS = {
  all:     'Все задачи',
  todo:    'Новые задачи',
  doing:   'В работе',
  done:    'Выполненные',
  high:    'Срочные',
  overdue: 'Просроченные',
  today:   'Дедлайн сегодня',
};

window.PRIORITY_ORDER = { high: 0, medium: 1, low: 2 };

window.SORT_LABELS = {
  date_desc: 'Дата ↓',
  date_asc:  'Дата ↑',
  deadline:  'Дедлайн',
  priority:  'Приоритет',
  title:     'Название',
};
