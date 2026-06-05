/**
 * details.js — Task detail panel with subtasks + comments
 * ✅ Subtasks: uses /tasks/{id}/subtasks, /subtasks/{id}
 * ✅ Comments: uses /tasks/{id}/comments, /comments/{id}
 */
window.DetailsModule = (function() {

  // ── Open panel ───────────────────────────────────────────
  async function open(id) {
    window.currentDetailId = id;
    const task = window.tasks.find(t => t.id === id);
    if (!task) return;

    document.getElementById('dpOverlay')?.classList.add('open');
    document.body.style.overflow = 'hidden';
    window.tg?.HapticFeedback?.impactOccurred('light');

    _renderHeader(task);

    // Avatar initial
    const myAv = document.getElementById('dpMyAv');
    if (myAv) myAv.textContent = (window.userName || window.userId || 'Я').slice(0,1).toUpperCase();

    // Load subtasks + comments in parallel (use cache if available)
    const [subs, coms] = await Promise.all([
      window.subCache.has(id) ? window.subCache.get(id) : _loadSubs(id),
      window.comCache.has(id) ? window.comCache.get(id) : _loadComs(id),
    ]);

    _renderSubs(id, subs);
    _renderComs(id, coms);
  }

  function close() {
    document.getElementById('dpOverlay')?.classList.remove('open');
    document.body.style.overflow = '';
    window.currentDetailId = null;
    const ni = document.getElementById('dpNewSub');  if (ni) ni.value = '';
    const nc = document.getElementById('dpNewCom');  if (nc) { nc.value = ''; nc.style.height = 'auto'; }
    const sa = document.getElementById('dpSubActs'); if (sa) sa.style.display = 'none';
    const sb = document.getElementById('dpSendBtn'); if (sb) sb.style.display = 'none';
  }

  // ── Header ───────────────────────────────────────────────
  function _renderHeader(task) {
    const check = document.getElementById('dpCheck');
    if (check) check.className = 'dp-check' + (task.status === 'done' ? ' done' : '');

    const title = document.getElementById('dpTitle');
    if (title) { title.textContent = task.title; title.className = 'dp-title' + (task.status === 'done' ? ' done' : ''); }

    const today = window.todayDate();
    const d = task.deadline ? new Date(task.deadline) : null;
    let dlCls = 'dl', dlStr = '';
    if (d) {
      dlStr = d.toLocaleDateString('ru', { day: 'numeric', month: 'short', year: 'numeric' });
      if (d < today && task.status !== 'done') dlCls = 'dl overdue';
      else if (d.toDateString() === today.toDateString()) dlCls = 'dl today';
    }

    const meta = document.getElementById('dpMeta');
    if (meta) meta.innerHTML = `
      <span class="dp-chip s-${task.status}">${window.STATUS_LABELS[task.status]}</span>
      <span class="dp-chip p-${task.priority}">${window.PRIORITY_LABELS[task.priority]}</span>
      ${d ? `<span class="dp-chip ${dlCls}">📅 ${dlStr}</span>` : ''}
      ${task.assignee ? `<span class="dp-chip asgn">👤 ${window.escHtml(task.assignee)}</span>` : ''}`;

    const descEl = document.getElementById('dpDesc');
    if (descEl) {
      if (task.description?.trim()) {
        const tmp = document.createElement('div');
        tmp.innerHTML = task.description;
        tmp.querySelectorAll('script,style').forEach(e => e.remove());
        tmp.querySelectorAll('input[type=checkbox]').forEach(cb => cb.setAttribute('disabled', ''));
        descEl.innerHTML = tmp.innerHTML;
        descEl.style.display = '';
      } else {
        descEl.innerHTML = ''; descEl.style.display = 'none';
      }
    }
  }

  // ── Toggle done from detail ──────────────────────────────
  async function toggleDone() {
    if (!window.currentDetailId) return;
    const task = window.tasks.find(t => t.id === window.currentDetailId);
    if (!task) return;
    const ns = task.status === 'done' ? 'todo' : 'done';
    task.status = ns;
    _renderHeader(task);
    window.TasksModule.render(); window.updateStats(); window.updateStreak();
    await window.apiCall('PATCH', `/tasks/${window.currentDetailId}`, { status: ns, user_id: window.userId });
    window.tg?.HapticFeedback?.notificationOccurred(ns === 'done' ? 'success' : 'warning');
    if (ns === 'done') window.showToast('🎉 Выполнено!', 'success');
  }

  function edit() { const id = window.currentDetailId; close(); if (id) setTimeout(() => window.ModalsModule.openEdit(id), 80); }

  async function deleteTask() {
    if (!window.currentDetailId || !confirm('Удалить задачу и все её подзадачи?')) return;
    const id = window.currentDetailId; close();
    await window.apiCall('DELETE', `/tasks/${id}`);
    window.tasks = window.tasks.filter(t => t.id !== id);
    window.subCache.delete(id); window.comCache.delete(id);
    window.TasksModule.render(); window.updateStats();
    window.showToast('Задача удалена', 'error');
  }

  // ══════════════════════════════════════════════════════
  //  SUBTASKS — ✅ правильный API
  // ══════════════════════════════════════════════════════
  async function _loadSubs(taskId) {
    const data = await window.apiCall('GET', `/tasks/${taskId}/subtasks`);
    const subs = data?.subtasks || [];
    window.subCache.set(taskId, subs);
    return subs;
  }

  function _renderSubs(taskId, subs) {
    const container = document.getElementById('dpSubsContainer');
    if (!container) return;

    const total = subs.length;
    const done  = subs.filter(s => s.status === 'done').length;
    const pct   = total ? Math.round(done / total * 100) : 0;

    container.innerHTML = `
      <div class="dp-section">
        <div class="dp-sec-head">
          <span class="dp-sec-title">📋 Подзадачи</span>
          ${total ? `<span class="dp-sec-badge">${done}/${total}</span>` : ''}
        </div>
        ${total ? `
          <div style="padding:0 20px 14px;display:flex;align-items:center;gap:12px">
            <div style="flex:1;height:5px;background:var(--border);border-radius:99px;overflow:hidden">
              <div style="height:100%;width:${pct}%;background:var(--blue);border-radius:99px;transition:width .4s"></div>
            </div>
            <span style="font-size:11px;font-weight:700;color:var(--muted2);white-space:nowrap">${done} из ${total}</span>
          </div>` : ''}
        <div id="dpSubList">
          ${subs.map(s => `
            <div class="dp-sub-item">
              <div class="dp-sub-cb ${s.status==='done'?'done':''}" onclick="window.DetailsModule.toggleSub('${taskId}','${s.id}')"></div>
              <span class="dp-sub-text ${s.status==='done'?'done':''}">${window.escHtml(s.title)}</span>
              <button class="dp-sub-del" onclick="window.DetailsModule.deleteSub('${taskId}','${s.id}')">✕</button>
            </div>`).join('')}
        </div>
        <div class="dp-add-sub-row">
          <div class="dp-add-sub-icon">+</div>
          <input class="dp-add-sub-inp" id="dpNewSub" placeholder="Добавить подзадачу..."
                 onkeydown="if(event.key==='Enter'){window.DetailsModule.addSub('${taskId}');event.preventDefault()}">
        </div>
        <div id="dpSubActs" style="display:none" class="dp-add-sub-actions">
          <button class="dp-btn-ok"     onclick="window.DetailsModule.addSub('${taskId}')">Добавить</button>
          <button class="dp-btn-cancel" onclick="document.getElementById('dpNewSub').value='';document.getElementById('dpSubActs').style.display='none'">Отмена</button>
        </div>
      </div>`;

    // Show actions on focus
    const inp = document.getElementById('dpNewSub');
    if (inp) {
      inp.addEventListener('focus',  () => { document.getElementById('dpSubActs').style.display = 'flex'; });
      inp.addEventListener('blur',   () => {
        setTimeout(() => { if (!inp.value.trim()) document.getElementById('dpSubActs').style.display = 'none'; }, 150);
      });
    }
  }

  // ✅ POST /tasks/{id}/subtasks
  async function addSub(taskId) {
    const inp   = document.getElementById('dpNewSub');
    const title = inp?.value.trim();
    if (!title) return;
    if (inp) inp.value = '';
    const acts = document.getElementById('dpSubActs');
    if (acts) acts.style.display = 'none';
    const res = await window.apiCall('POST', `/tasks/${taskId}/subtasks`, { title, user_id: window.userId });
    if (res?.subtask) {
      const arr = window.subCache.get(taskId) || [];
      arr.push(res.subtask);
      window.subCache.set(taskId, arr);
      _renderSubs(taskId, arr);
      _refreshCard(taskId);
      window.tg?.HapticFeedback?.impactOccurred('light');
    }
  }

  // ✅ PATCH /subtasks/{id}
  async function toggleSub(taskId, subId) {
    const arr = window.subCache.get(taskId) || [];
    const sub = arr.find(s => s.id === subId);
    if (!sub) return;
    const ns  = sub.status === 'done' ? 'todo' : 'done';
    sub.status = ns;
    _renderSubs(taskId, arr);
    _refreshCard(taskId);
    await window.apiCall('PATCH', `/subtasks/${subId}`, { status: ns });
    window.tg?.HapticFeedback?.impactOccurred('light');
  }

  // ✅ DELETE /subtasks/{id}
  async function deleteSub(taskId, subId) {
    await window.apiCall('DELETE', `/subtasks/${subId}`);
    const arr = (window.subCache.get(taskId) || []).filter(s => s.id !== subId);
    window.subCache.set(taskId, arr);
    _renderSubs(taskId, arr);
    _refreshCard(taskId);
  }

  // Refresh card subtask progress without full re-render
  function _refreshCard(taskId) {
    const subs  = window.subCache.get(taskId) || [];
    const subN  = subs.length;
    const subD  = subs.filter(s => s.status === 'done').length;
    const pct   = subN ? Math.round(subD / subN * 100) : 0;
    const card  = document.querySelector(`.task-card[data-id="${taskId}"]`);
    if (!card) return;
    // Update inline progress bar in card
    const bar   = card.querySelector('.sub-prog-fill');
    const label = card.querySelector('.sub-prog-label');
    if (bar)   bar.style.width    = pct + '%';
    if (label) label.textContent = `${subD}/${subN}`;
  }

  // ══════════════════════════════════════════════════════
  //  COMMENTS — ✅ правильный API
  // ══════════════════════════════════════════════════════
  async function _loadComs(taskId) {
    const data = await window.apiCall('GET', `/tasks/${taskId}/comments`);
    const coms = data?.comments || [];
    window.comCache.set(taskId, coms);
    return coms;
  }

  const AV_COLORS = ['#3B5BDB','#0CA678','#E08C00','#E03131','#7048E8','#0D9488','#EC4899'];
  function _avColor(name) {
    let h = 0; for (const c of (name || '')) h = ((h<<5) - h) + c.charCodeAt(0);
    return AV_COLORS[Math.abs(h) % AV_COLORS.length];
  }
  function _fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso), now = new Date();
    const m = Math.floor((now - d) / 60000);
    if (m < 1)  return 'только что';
    if (m < 60) return m + ' мин. назад';
    const h = Math.floor(m / 60);
    if (h < 24) return h + ' ч. назад';
    return d.toLocaleDateString('ru', { day: 'numeric', month: 'short' });
  }

  function _renderComs(taskId, coms) {
    const container = document.getElementById('dpComsContainer');
    if (!container) return;

    const myLetter = (window.userName || window.userId || '?').slice(0, 1).toUpperCase();
    const myColor  = _avColor(window.userName || window.userId);

    container.innerHTML = `
      <div class="dp-section">
        <div class="dp-sec-head">
          <span class="dp-sec-title">💬 Комментарии</span>
          ${coms.length ? `<span class="dp-sec-badge" style="background:var(--grn-soft);color:var(--green)">${coms.length}</span>` : ''}
        </div>
        <div id="dpComList">
          ${coms.map(c => {
            const letter = (c.user_name || c.user_id || '?').slice(0, 1).toUpperCase();
            const isMe   = c.user_id === window.userId;
            return `
              <div class="dp-comment">
                <div class="dp-com-head">
                  <div class="dp-com-av" style="background:${_avColor(c.user_name||c.user_id)}">${letter}</div>
                  <span class="dp-com-name">${window.escHtml(c.user_name || c.user_id || 'Пользователь')}</span>
                  <span class="dp-com-time">${_fmtTime(c.created_at)}</span>
                  ${isMe ? `<button class="dp-com-del" onclick="window.DetailsModule.deleteCom('${taskId}','${c.id}')">✕</button>` : ''}
                </div>
                <div class="dp-com-text">${window.escHtml(c.text)}</div>
              </div>`;
          }).join('')}
        </div>
        <div class="dp-add-com">
          <div class="dp-my-av" id="dpMyAv" style="background:${myColor}">${myLetter}</div>
          <div style="flex:1">
            <textarea class="dp-com-inp" id="dpNewCom"
              placeholder="Написать комментарий... (Ctrl+Enter — отправить)"
              rows="1"
              oninput="this.style.height='auto';this.style.height=Math.min(this.scrollHeight,120)+'px';document.getElementById('dpSendBtn').style.display=this.value.trim()?'flex':'none'"
              onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();window.DetailsModule.addCom('${taskId}')}"></textarea>
            <button id="dpSendBtn" class="dp-com-send" style="display:none"
                    onclick="window.DetailsModule.addCom('${taskId}')">↑ Отправить</button>
          </div>
        </div>
      </div>`;
  }

  // ✅ POST /tasks/{id}/comments
  async function addCom(taskId) {
    const inp  = document.getElementById('dpNewCom');
    const text = inp?.value.trim();
    if (!text) return;
    if (inp) { inp.value = ''; inp.style.height = 'auto'; }
    const sb = document.getElementById('dpSendBtn'); if (sb) sb.style.display = 'none';
    const res = await window.apiCall('POST', `/tasks/${taskId}/comments`, {
      text, user_id: window.userId, user_name: window.userName
    });
    if (res?.comment) {
      const arr = window.comCache.get(taskId) || [];
      arr.push(res.comment);
      window.comCache.set(taskId, arr);
      _renderComs(taskId, arr);
      window.tg?.HapticFeedback?.impactOccurred('light');
    }
  }

  // ✅ DELETE /comments/{id}
  async function deleteCom(taskId, comId) {
    await window.apiCall('DELETE', `/comments/${comId}`);
    const arr = (window.comCache.get(taskId) || []).filter(c => c.id !== comId);
    window.comCache.set(taskId, arr);
    _renderComs(taskId, arr);
  }

  return { open, close, toggleDone, edit, deleteTask, addSub, toggleSub, deleteSub, addCom, deleteCom };
})();

// Global exports
window.openDetail   = (id) => window.DetailsModule.open(id);
window.closeDetail  = ()   => window.DetailsModule.close();
window.dpToggleDone = ()   => window.DetailsModule.toggleDone();
window.dpEdit       = ()   => window.DetailsModule.edit();
window.dpDelete     = ()   => window.DetailsModule.deleteTask();
