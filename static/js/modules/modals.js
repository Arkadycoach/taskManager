/**
 * modals.js — Task create/edit modal
 */
window.ModalsModule = (function() {

  function openAdd() {
    window.editingId = null;
    _setField('modalTitle', null, 'Новая задача');
    _val('taskTitle', ''); _val('taskDesc', '');
    _val('taskStatus', 'todo'); _val('taskPriority', 'medium');
    _val('taskDeadline', ''); _val('taskAssignee', '');
    _setDisplay('deleteBtn', 'none');
    if (window.setEditorHtml) window.setEditorHtml('');
    document.getElementById('taskModal')?.classList.add('open');
    setTimeout(() => document.getElementById('taskTitle')?.focus(), 350);
    window.tg?.HapticFeedback?.impactOccurred('light');
  }

  function openEdit(id) {
    const task = window.tasks.find(t => t.id === id);
    if (!task) return;
    window.editingId = id;
    _setField('modalTitle', null, 'Редактировать');
    _val('taskTitle',    task.title);
    _val('taskStatus',   task.status);
    _val('taskPriority', task.priority);
    _val('taskDeadline', task.deadline || '');
    _val('taskAssignee', task.assignee || '');
    if (window.setEditorHtml) window.setEditorHtml(task.description || '');
    else _val('taskDesc', task.description || '');
    _setDisplay('deleteBtn', 'flex');
    document.getElementById('taskModal')?.classList.add('open');
    window.tg?.HapticFeedback?.impactOccurred('light');
  }

  function close() {
    document.getElementById('taskModal')?.classList.remove('open');
    window.editingId = null;
  }

  async function save() {
    const title = document.getElementById('taskTitle')?.value.trim();
    if (!title) { window.showToast('Введи название', 'error'); return; }

    const description = window.getEditorHtml
      ? window.getEditorHtml()
      : (document.getElementById('taskDesc')?.value || '');

    const data = {
      title,
      description,
      status:    document.getElementById('taskStatus')?.value   || 'todo',
      priority:  document.getElementById('taskPriority')?.value || 'medium',
      deadline:  document.getElementById('taskDeadline')?.value || '',
      assignee:  document.getElementById('taskAssignee')?.value.trim() || '',
      user_id:   window.userId,
      user_name: window.userName,
      // ✅ subtasks хранятся ОТДЕЛЬНО — не передаём здесь
    };

    if (window.editingId) {
      await window.apiCall('PATCH', `/tasks/${window.editingId}`, data);
      const idx = window.tasks.findIndex(t => t.id === window.editingId);
      if (idx !== -1) window.tasks[idx] = { ...window.tasks[idx], ...data };
      window.showToast('✓ Обновлено', 'success');
    } else {
      const res = await window.apiCall('POST', '/tasks', data);
      if (res?.task) window.tasks.unshift(res.task);
      window.showToast('✓ Задача добавлена', 'success');
    }

    close();
    window.TasksModule.render();
    window.updateStats();
    window.SidebarModule?.updateCounts();
    window.tg?.HapticFeedback?.notificationOccurred('success');
  }

  async function deleteTask() {
    if (!window.editingId || !confirm('Удалить задачу?')) return;
    const id = window.editingId;
    await window.apiCall('DELETE', `/tasks/${id}`);
    window.tasks = window.tasks.filter(t => t.id !== id);
    window.subCache?.delete(id);
    window.comCache?.delete(id);
    close();
    window.TasksModule.render();
    window.updateStats();
    window.showToast('Удалено', 'error');
  }

  // Helpers
  function _val(id, v) { const el = document.getElementById(id); if (el) el.value = v; }
  function _setField(id, prop, val) {
    const el = document.getElementById(id);
    if (!el) return;
    if (prop) el[prop] = val; else el.textContent = val;
  }
  function _setDisplay(id, v) { const el = document.getElementById(id); if (el) el.style.display = v; }

  return { openAdd, openEdit, close, save, deleteTask };
})();

// Global aliases
window.openAddModal  = ()  => window.ModalsModule.openAdd();
window.openEditModal = (id)=> window.ModalsModule.openEdit(id);
window.closeModal    = ()  => window.ModalsModule.close();
window.saveTask      = ()  => window.ModalsModule.save();
window.deleteTask    = ()  => window.ModalsModule.deleteTask();
