/**
 * filters.js — Filter & sort state
 */
window.FiltersModule = (function() {

  function setFilter(filter) {
    window.currentFilter = filter;
    document.querySelectorAll('.tab[data-filter]').forEach(t => {
      t.classList.toggle('active', t.dataset.filter === filter);
    });
    const labelEl = document.getElementById('tasksLabel');
    if (labelEl) labelEl.textContent = window.FILTER_LABELS[filter] || 'Задачи';
    window.SidebarModule?.setActiveItem(filter);
    window.TasksModule?.render();
  }

  function setSort(sort, el = null) {
    window.currentSort = sort;
    const sortLabel = document.getElementById('sortLabel');
    if (sortLabel) sortLabel.textContent = window.SORT_LABELS[sort] || sort;
    document.querySelectorAll('.sort-item').forEach(i => i.classList.remove('active'));
    el?.classList.add('active');
    closeSortMenu();
    window.TasksModule?.render();
  }

  function toggleSortMenu() {
    const menu = document.getElementById('sortMenu');
    if (!menu) return;
    const hidden = !menu.style.display || menu.style.display === 'none';
    menu.style.display = hidden ? 'block' : 'none';
  }

  function closeSortMenu() {
    const m = document.getElementById('sortMenu');
    if (m) m.style.display = 'none';
  }

  document.addEventListener('click', e => {
    const toolbar = document.querySelector('.toolbar');
    if (toolbar && !toolbar.contains(e.target)) closeSortMenu();
  });

  return { setFilter, setSort, toggleSortMenu, closeSortMenu };
})();

window.setFilter      = (f, el) => window.FiltersModule.setFilter(f);
window.setSort        = (s, el) => window.FiltersModule.setSort(s, el);
window.toggleSortMenu = ()      => window.FiltersModule.toggleSortMenu();
