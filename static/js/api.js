/**
 * api.js — Network layer
 * ✅ Telegram init только здесь (не дублировать в app.js)
 */

const CONFIG = {
  API_URL: 'https://taskmanager-production-6032.up.railway.app',
  POLL_MS: 30000,
};

// Telegram — инициализируем ОДИН РАЗ здесь
window.tg = window.Telegram?.WebApp;
if (window.tg) {
  window.tg.ready();
  window.tg.expand();
  window.tg.setBackgroundColor('#EEF3FF');
  window.tg.setHeaderColor('#2563EB');
}

window.userId   = window.tg?.initDataUnsafe?.user?.id?.toString() || '';
window.userName = window.tg?.initDataUnsafe?.user?.username
               || window.tg?.initDataUnsafe?.user?.first_name
               || '';

// ── Caches (subtasks + comments) ──────────────────────────
// Объявляем здесь, используем во всех модулях
window.subCache = new Map();  // taskId → subtask[]
window.comCache = new Map();  // taskId → comment[]

// ── Core fetch helper ──────────────────────────────────────
window.apiCall = async function(method, endpoint, body = null) {
  try {
    const opts = {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': String(window.userId),
      },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(CONFIG.API_URL + endpoint, opts);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error('API error:', e);
    return null;
  }
};

// ── Load all tasks ─────────────────────────────────────────
window.loadTasks = async function() {
  const btn = document.getElementById('syncBtn');
  if (btn) btn.classList.add('syncing');

  const data = await window.apiCall('GET', `/tasks?user_id=${window.userId}`);
  if (data?.tasks) {
    window.tasks = data.tasks; // no fake subtasks field
    if (window.TasksModule) window.TasksModule.render();
    if (window.updateStats) window.updateStats();
    if (window.updateStreak) window.updateStreak();
    if (window.updateLastSync) window.updateLastSync();
    if (window.SidebarModule) window.SidebarModule.updateCounts();
  }

  if (btn) btn.classList.remove('syncing');
};

// ── Subtask API ────────────────────────────────────────────
// ✅ POST   /tasks/{id}/subtasks
window.createSubtask = async function(taskId, title) {
  return await window.apiCall('POST', `/tasks/${taskId}/subtasks`, { title, user_id: window.userId });
};
// ✅ PATCH  /subtasks/{id}
window.updateSubtask = async function(subId, status) {
  return await window.apiCall('PATCH', `/subtasks/${subId}`, { status });
};
// ✅ DELETE /subtasks/{id}
window.deleteSubtask = async function(subId) {
  return await window.apiCall('DELETE', `/subtasks/${subId}`);
};
// ✅ GET    /tasks/{id}/subtasks
window.getSubtasks = async function(taskId) {
  const data = await window.apiCall('GET', `/tasks/${taskId}/subtasks`);
  const subs = data?.subtasks || [];
  window.subCache.set(taskId, subs);
  return subs;
};

// ── Comment API ────────────────────────────────────────────
window.getComments = async function(taskId) {
  const data = await window.apiCall('GET', `/tasks/${taskId}/comments`);
  const coms = data?.comments || [];
  window.comCache.set(taskId, coms);
  return coms;
};
window.createComment = async function(taskId, text) {
  return await window.apiCall('POST', `/tasks/${taskId}/comments`, {
    text, user_id: window.userId, user_name: window.userName,
  });
};
window.deleteComment = async function(commentId) {
  return await window.apiCall('DELETE', `/comments/${commentId}`);
};
