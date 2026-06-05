/**
 * app.js — Entry point
 * ⚠️  Telegram init уже сделан в api.js — здесь НЕ делаем повторно
 */

// Platform detection
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
  // Telegram Back Button
  if (window.isTelegram && window.tg?.BackButton) {
    window.tg.BackButton.onClick(() => {
      if (document.getElementById('dpOverlay')?.classList.contains('open'))    { window.DetailsModule?.close(); return; }
      if (document.getElementById('taskModal')?.classList.contains('open'))    { window.ModalsModule?.close();  return; }
      if (document.getElementById('qaOverlay')?.classList.contains('open'))    { window.QuickActions?.close();  return; }
      if (document.getElementById('sbOverlay')?.classList.contains('open'))    { window.SidebarModule?.close(); return; }
    });
  }

  // Initial data load
  await window.loadTasks();

  // Hide loading screen
  const loading = document.getElementById('loading');
  if (loading) setTimeout(() => loading.classList.add('hidden'), 300);

  // Pull-to-refresh (mobile only)
  if (window.isMobile) window.TasksModule?.initPullToRefresh();

  // Notifications
  window.NotificationsModule?.init();

  // Auto-refresh (less frequent on desktop)
  setInterval(window.loadTasks, window.isMobile ? 30000 : 60000);
}

init();
