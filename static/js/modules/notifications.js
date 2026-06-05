/**
 * notifications.js — In-app notification scheduling
 */
window.NotificationsModule = (function() {

  function init() {
    _scheduleDeadlineReminders();
    // Refresh reminders every 10 min
    setInterval(_scheduleDeadlineReminders, 600000);
  }

  function _scheduleDeadlineReminders() {
    if (!window.tasks) return;
    const today   = window.todayDate();
    const todayTasks = window.tasks.filter(t =>
      t.deadline && t.status !== 'done' &&
      new Date(t.deadline).toDateString() === today.toDateString()
    );
    const overdueTasks = window.tasks.filter(t =>
      t.deadline && t.status !== 'done' &&
      window.safeDate(t.deadline) < today
    );
    if (overdueTasks.length) {
      _badge('overdue', overdueTasks.length);
    }
    if (todayTasks.length) {
      _badge('today', todayTasks.length);
    }
  }

  // Update bottom-nav dots if they exist
  function _badge(type, count) {
    const dotMap = { overdue: 'bnDot-overdue', today: 'bnDot-today' };
    const el = document.getElementById(dotMap[type]);
    if (!el) return;
    el.textContent = count > 9 ? '9+' : count;
    el.classList.toggle('show', count > 0);
  }

  return { init };
})();
