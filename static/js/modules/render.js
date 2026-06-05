/**
 * render.js — Task list and kanban rendering
 * Depends on: state.js, utils.js, api.js (subCache)
 */
window.RenderModule = (function() {

  const STATUS_SHORT = { todo: 'Новая', doing: 'В работе', done: 'Готово' };

  // ── Task card HTML ───────────────────────────────────────
  function taskCardHTML(task, index = 0) {
    const dl     = window.deadlineStr(task);
    const today  = window.todayDate();
    const isDone = task.status === 'done';
    const isToday = task.deadline && !isDone &&
      new Date(task.deadline).toDateString() === today.toDateString();

    // Due date badge
    let dueBadge = '';
    if (dl && !isDone) {
      const raw    = dl.raw || new Date(task.deadline);
      const diff   = Math.round((raw - today) / 864e5);
      let cls  = diff < 0 ? 'overdue' : diff === 0 ? 'today' : diff <= 3 ? 'soon' : 'normal';
      let icon = diff < 0 ? '⚠' : diff === 0 ? '●' : '○';
      let lbl  = diff === 0 ? 'Сегодня' : diff === 1 ? 'Завтра' : dl.label.replace('⚠ ', '');
      dueBadge = `<div class="task-due"><span class="task-due-badge ${cls}">${icon} ${lbl}</span></div>`;
    } else if (dl && isDone) {
      dueBadge = `<div class="task-due"><span class="task-due-badge normal">○ ${dl.label}</span></div>`;
    }

    // Subtask progress (only if cached)
    const subs   = window.subCache?.get(task.id) || [];
    const subN   = subs.length;
    const subD   = subs.filter(s => s.status === 'done').length;
    const subPct = subN ? Math.round(subD / subN * 100) : 0;

    const subBadge = window.subCache?.has(task.id) && subN
      ? `<div style="display:flex;align-items:center;gap:6px;margin-top:4px">
           <div style="flex:1;height:3px;background:var(--border);border-radius:99px;overflow:hidden">
             <div style="height:100%;width:${subPct}%;background:var(--green);border-radius:99px"></div>
           </div>
           <span style="font-size:10px;color:var(--muted2);font-weight:600">${subD}/${subN}</span>
         </div>`
      : (subN ? `<div style="font-size:10px;color:var(--muted);margin-top:3px">📋 ${subN} подзадач</div>` : '');

    // Assignee
    let assigneeHTML = '';
    if (task.assignee) {
      const letter = task.assignee.replace('@','').slice(0,1).toUpperCase();
      assigneeHTML = `
        <span class="task-meta-sep"></span>
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
      <div class="task-card p-${task.priority}${isToday ? ' today-pinned' : ''}${isDone ? ' done-card' : ''}"
           data-id="${task.id}"
           style="animation-delay:${index * 0.03}s"
           onclick="window.DetailsModule?.open('${task.id}')">
        <div class="swipe-hint" id="sh_${task.id}">✅</div>
        <div class="task-card-inner">
          <div class="task-row1">
            <div class="task-check ${isDone ? 'checked' : ''}"
                 onclick="event.stopPropagation();window.TasksModule.toggleDone('${task.id}')"></div>
            <div class="task-body">
              <div class="task-title ${isDone ? 'done' : ''}">${window.escHtml(task.title)}</div>
              ${descHTML}
              ${subBadge}
            </div>
            ${dueBadge}
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

  // ── List render ──────────────────────────────────────────
  function renderTasks() {
    const list = document.getElementById('tasksList');
    if (!list) return;

    const search   = document.getElementById('searchInput')?.value || '';
    let   filtered = window.filterTasks(window.tasks, window.currentFilter, search);
    filtered = window.sortTasks(filtered, window.currentSort);

    const cntEl = document.getElementById('tasksCount');
    if (cntEl) cntEl.textContent = filtered.length;

    const EMPTY = {
      all:     '📭 Задач нет.\nНажми + чтобы добавить первую',
      todo:    '🎉 Нет новых задач!',
      doing:   '😎 Нет задач в работе',
      done:    '✅ Ещё ничего не выполнено',
      high:    '✅ Нет срочных задач',
      overdue: '🎊 Нет просроченных!',
      today:   '☀️ Сегодня дедлайнов нет',
    };

    if (!filtered.length) {
      const [icon, ...rest] = (EMPTY[window.currentFilter] || '📭 Ничего не найдено').split('\n');
      list.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">${icon}</div>
          <p>${rest.join('<br>') || icon}</p>
        </div>`;
      return;
    }

    let html = '';
    if (window.currentFilter === 'all') {
      const today    = window.todayDate();
      const overdue  = filtered.filter(t => t.deadline && window.safeDate(t.deadline) < today && t.status !== 'done');
      const todayArr = filtered.filter(t => t.deadline && !overdue.includes(t) &&
        new Date(t.deadline).toDateString() === today.toDateString() && t.status !== 'done');
      const rest     = filtered.filter(t => !overdue.includes(t) && !todayArr.includes(t));

      if (overdue.length) {
        html += `<div class="section-divider">
          <span class="section-divider-label">Просрочены</span>
          <div class="section-divider-line"></div>
          <span class="section-count red">${overdue.length}</span>
        </div>`;
        html += overdue.map((t, i) => taskCardHTML(t, i)).join('');
      }
      if (todayArr.length) {
        html += `<div class="section-divider">
          <span class="section-divider-label">📅 Сегодня</span>
          <div class="section-divider-line"></div>
          <span class="section-count yel">${todayArr.length}</span>
        </div>`;
        html += todayArr.map((t, i) => taskCardHTML(t, i)).join('');
      }
      if (rest.length) {
        if (overdue.length || todayArr.length) {
          html += `<div class="section-divider">
            <span class="section-divider-label">Остальные</span>
            <div class="section-divider-line"></div>
            <span class="section-count">${rest.length}</span>
          </div>`;
        }
        html += rest.map((t, i) => taskCardHTML(t, i)).join('');
      }
    } else {
      html = filtered.map((t, i) => taskCardHTML(t, i)).join('');
    }

    list.innerHTML = html;
    window.TasksModule.attachSwipeHandlers();
    window.TasksModule.attachLongPressHandlers();
  }

  // ── Kanban render ────────────────────────────────────────
  function renderKanban() {
    const board = document.getElementById('kanbanBoard');
    if (!board) return;

    const search = document.getElementById('searchInput')?.value || '';
    const cols = [
      { key: 'todo',  label: 'Новые',    cls: 'todo',  icon: '🔵' },
      { key: 'doing', label: 'В работе', cls: 'doing', icon: '🟡' },
      { key: 'done',  label: 'Готово',   cls: 'done',  icon: '✅' },
    ];

    board.innerHTML = cols.map(col => {
      let colTasks = window.tasks.filter(t => t.status === col.key);
      if (search) colTasks = colTasks.filter(t =>
        t.title.toLowerCase().includes(search.toLowerCase()) ||
        (t.assignee || '').toLowerCase().includes(search.toLowerCase())
      );

      const cards = colTasks.map(t => {
        const dl   = window.deadlineStr(t);
        const subs = window.subCache?.get(t.id) || [];
        const subD = subs.filter(s => s.status === 'done').length;
        const dlColor = dl ? (dl.isOverdue ? 'var(--red)' : dl.isToday ? '#B45309' : 'var(--muted)') : '';
        return `
          <div class="kanban-card p-${t.priority}" onclick="window.DetailsModule?.open('${t.id}')">
            <div class="kanban-card-inner">
              <div class="kanban-card-title">${window.escHtml(t.title)}</div>
              <div class="kanban-card-meta">
                <span class="km-dot ${t.priority}"></span>
                ${dl ? `<span style="color:${dlColor};font-weight:600">📅 ${dl.label}</span>` : ''}
                ${subs.length ? `<span>📋 ${subD}/${subs.length}</span>` : ''}
                ${t.assignee ? `<span>@${window.escHtml(t.assignee.replace('@',''))}</span>` : ''}
              </div>
            </div>
          </div>`;
      }).join('') || `<div style="padding:14px;text-align:center;color:var(--muted2);font-size:12px;font-weight:500">Нет задач</div>`;

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
