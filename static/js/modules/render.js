/**
 * render.js — Task list + kanban rendering
 * ✅ Done tasks excluded from 'all'
 * ✅ Done tasks grouped by month of completion
 * ✅ Completion date shown on done cards
 */
window.RenderModule = (function() {

  const STATUS_SHORT = { todo: 'Новая', doing: 'В работе', done: 'Готово' };

  // ── Task card HTML ───────────────────────────────────
  function taskCardHTML(task, index = 0) {
    const dl     = window.deadlineStr(task);
    const today  = window.todayDate();
    const isDone = task.status === 'done';
    const isToday = !isDone && task.deadline &&
      new Date(task.deadline).toDateString() === today.toDateString();

    // Due date badge
    let dueBadge = '';
    if (dl && !isDone) {
      const diff = Math.round((dl.raw - today) / 864e5);
      const cls  = diff < 0 ? 'overdue' : diff === 0 ? 'today' : diff <= 3 ? 'soon' : 'normal';
      const icon = diff < 0 ? '⚠' : diff === 0 ? '●' : '○';
      const lbl  = diff === 0 ? 'Сегодня' : diff === 1 ? 'Завтра' : dl.label.replace('⚠ ','');
      dueBadge = `<div class="task-due"><span class="task-due-badge ${cls}">${icon} ${lbl}</span></div>`;
    }

    // ✅ Completion date badge (for done tasks)
    let completedBadge = '';
    if (isDone && task.completed_at) {
      const cd = new Date(task.completed_at);
      const cdStr = cd.toLocaleDateString('ru', {day:'numeric', month:'short'});
      completedBadge = `<div class="task-due"><span class="task-due-badge" style="background:#ECFDF8;color:#065F46">✓ ${cdStr}</span></div>`;
    }

    // Subtask progress (if cached)
    const subs   = window.subCache?.get(task.id) || [];
    const subN   = subs.length;
    const subD   = subs.filter(s => s.status === 'done').length;
    const subPct = subN ? Math.round(subD/subN*100) : 0;
    const subBadge = window.subCache?.has(task.id) && subN
      ? `<div style="display:flex;align-items:center;gap:6px;margin-top:4px">
           <div style="flex:1;height:3px;background:var(--border);border-radius:99px;overflow:hidden">
             <div style="height:100%;width:${subPct}%;background:var(--green);border-radius:99px"></div>
           </div>
           <span style="font-size:10px;color:var(--muted2);font-weight:600">${subD}/${subN}</span>
         </div>`
      : '';

    // Assignee
    let assigneeHTML = '';
    if (task.assignee) {
      const letter = task.assignee.replace('@','').slice(0,1).toUpperCase();
      assigneeHTML = `<span class="task-meta-sep"></span>
        <span class="task-assignee">
          <span class="task-assignee-av">${letter}</span>
          ${window.escHtml(task.assignee.replace('@',''))}
        </span>`;
    }

    // Description preview
    const descHTML = task.description
      ? `<div class="task-rich-preview">${window.descPreview ? window.descPreview(task.description) : window.escHtml(task.description.slice(0,80))}</div>`
      : '';

    return `
      <div class="task-card p-${task.priority}${isToday?' today-pinned':''}${isDone?' done-card':''}"
           data-id="${task.id}" style="animation-delay:${index*0.03}s"
           onclick="window.DetailsModule?.open('${task.id}')">
        <div class="swipe-hint" id="sh_${task.id}">✅</div>
        <div class="task-card-inner">
          <div class="task-row1">
            <div class="task-check ${isDone?'checked':''}"
                 onclick="event.stopPropagation();window.TasksModule.toggleDone('${task.id}')"></div>
            <div class="task-body">
              <div class="task-title ${isDone?'done':''}">${window.escHtml(task.title)}</div>
              ${descHTML}${subBadge}
            </div>
            ${isDone ? completedBadge : dueBadge}
          </div>
          <div class="task-row2">
            <span class="task-status-pill s-${task.status}">
              <span class="task-status-dot"></span>
              ${STATUS_SHORT[task.status]}
            </span>
            <span class="task-meta-sep"></span>
            <span class="task-prio-dot ${task.priority}"></span>
            ${assigneeHTML}
          </div>
        </div>
      </div>`;
  }

  // ── List render ──────────────────────────────────────
  function renderTasks() {
    const list = document.getElementById('tasksList');
    if (!list) return;

    const search   = document.getElementById('searchInput')?.value || '';
    let   filtered = window.filterTasks(window.tasks, window.currentFilter, search);

    // Done view: sort by completion date by default
    const sortKey = window.currentFilter === 'done' ? 'completed' : window.currentSort;
    filtered = window.sortTasks(filtered, sortKey);

    const cntEl = document.getElementById('tasksCount');
    if (cntEl) cntEl.textContent = filtered.length;

    const EMPTY = {
      all:     ['📭', 'Нет активных задач', 'Нажми + чтобы добавить первую'],
      todo:    ['🎉', 'Нет новых задач!', ''],
      doing:   ['😎', 'Нет задач в работе', ''],
      done:    ['📦', 'Архив пуст', 'Выполненные задачи появятся здесь'],
      high:    ['✅', 'Нет срочных задач', ''],
      overdue: ['🎊', 'Нет просроченных!', ''],
      today:   ['☀️', 'Сегодня дедлайнов нет', ''],
    };

    if (!filtered.length) {
      const [icon, title, sub] = EMPTY[window.currentFilter] || ['📭','Ничего не найдено',''];
      list.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">${icon}</div>
          <p><strong>${title}</strong>${sub?`<br><span style="font-size:13px">${sub}</span>`:''}</p>
        </div>`;
      return;
    }

    let html = '';

    // ── "Все" view: группировка по срочности ────────────
    if (window.currentFilter === 'all') {
      const td      = window.todayDate();
      const overdue = filtered.filter(t => t.deadline && window.safeDate(t.deadline) < td && t.status!=='done');
      const todayArr= filtered.filter(t => t.deadline && new Date(t.deadline).toDateString()===td.toDateString() && t.status!=='done');
      const rest    = filtered.filter(t => !overdue.includes(t) && !todayArr.includes(t));

      if (overdue.length) {
        html += _sectionHeader('Просрочены', overdue.length, 'red');
        html += overdue.map((t,i) => taskCardHTML(t,i)).join('');
      }
      if (todayArr.length) {
        html += _sectionHeader('📅 Сегодня', todayArr.length, 'yel');
        html += todayArr.map((t,i) => taskCardHTML(t,i)).join('');
      }
      if (rest.length) {
        if (overdue.length || todayArr.length)
          html += _sectionHeader('Остальные', rest.length, '');
        html += rest.map((t,i) => taskCardHTML(t,i)).join('');
      }

    // ── "Готово" view: группировка по месяцу выполнения ─
    } else if (window.currentFilter === 'done') {
      // Группируем по месяцу (completed_at или updated_at)
      const byMonth = new Map();
      filtered.forEach(t => {
        const dateField = t.completed_at || t.updated_at || '';
        const key = dateField ? dateField.slice(0,7) : 'unknown';
        if (!byMonth.has(key)) byMonth.set(key, []);
        byMonth.get(key).push(t);
      });

      // Сортируем месяцы от нового к старому
      const sortedMonths = [...byMonth.keys()].sort((a,b) => b.localeCompare(a));

      sortedMonths.forEach(key => {
        const monthTasks = byMonth.get(key);
        const label = key === 'unknown' ? 'Дата не указана' : window.monthLabel(key);
        html += _sectionHeader(`📅 ${label}`, monthTasks.length, 'green');
        html += monthTasks.map((t,i) => taskCardHTML(t,i)).join('');
      });

    // ── Остальные фильтры: обычный список ───────────────
    } else {
      html = filtered.map((t,i) => taskCardHTML(t,i)).join('');
    }

    list.innerHTML = html;
    window.TasksModule.attachSwipeHandlers();
    window.TasksModule.attachLongPressHandlers();
  }

  function _sectionHeader(label, count, colorCls) {
    return `<div class="section-divider">
      <span class="section-divider-label">${label}</span>
      <div class="section-divider-line"></div>
      <span class="section-count${colorCls?' '+colorCls:''}">${count}</span>
    </div>`;
  }

  // ── Kanban render ────────────────────────────────────
  function renderKanban() {
    const board = document.getElementById('kanbanBoard');
    if (!board) return;

    const search = document.getElementById('searchInput')?.value || '';
    const cols   = [
      { key:'todo',  label:'Новые',    cls:'todo',  icon:'🔵' },
      { key:'doing', label:'В работе', cls:'doing', icon:'🟡' },
      { key:'done',  label:'Готово',   cls:'done',  icon:'✅' },
    ];

    board.innerHTML = cols.map(col => {
      let colTasks = window.tasks.filter(t => t.status === col.key);
      if (search) colTasks = colTasks.filter(t =>
        t.title.toLowerCase().includes(search.toLowerCase()) ||
        (t.assignee||'').toLowerCase().includes(search.toLowerCase())
      );
      const cards = colTasks.map(t => {
        const dl   = window.deadlineStr(t);
        const subs = window.subCache?.get(t.id) || [];
        const subD = subs.filter(s => s.status==='done').length;
        const dlColor = dl ? (dl.isOverdue?'var(--red)':dl.isToday?'#B45309':'var(--muted)') : '';
        // For done tasks in kanban: show completion date
        const dateInfo = t.status === 'done' && t.completed_at
          ? `<span style="color:#065F46">✓ ${new Date(t.completed_at).toLocaleDateString('ru',{day:'numeric',month:'short'})}</span>`
          : (dl ? `<span style="color:${dlColor}">📅 ${dl.label}</span>` : '');
        return `
          <div class="kanban-card p-${t.priority}" onclick="window.DetailsModule?.open('${t.id}')">
            <div class="kanban-card-inner">
              <div class="kanban-card-title">${window.escHtml(t.title)}</div>
              <div class="kanban-card-meta">
                <span class="km-dot ${t.priority}"></span>
                ${dateInfo}
                ${subs.length ? `<span>📋 ${subD}/${subs.length}</span>` : ''}
                ${t.assignee ? `<span>@${window.escHtml(t.assignee.replace('@',''))}</span>` : ''}
              </div>
            </div>
          </div>`;
      }).join('') || `<div style="padding:14px;text-align:center;color:var(--muted2);font-size:12px">Нет задач</div>`;

      return `
        <div class="kanban-col">
          <div class="kanban-col-header ${col.cls}">
            <span>${col.icon} ${col.label}</span>
            <span style="font-size:11px;opacity:.7">${colTasks.length}</span>
          </div>
          <div class="kanban-col-body">${cards}</div>
        </div>`;
    }).join('');

    const cntEl = document.getElementById('tasksCount');
    if (cntEl) cntEl.textContent = window.tasks.length;
  }

  return { renderTasks, renderKanban, taskCardHTML };
})();
