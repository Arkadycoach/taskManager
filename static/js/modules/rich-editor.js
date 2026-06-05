/**
 * Rich text editor module
 */

window.RichEditor = (function() {
  let savedRange = null;
  
  function saveRange() {
    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0) {
      savedRange = sel.getRangeAt(0).cloneRange();
    }
  }
  
  function restoreRange() {
    const ed = document.getElementById('taskDesc');
    if (!ed) return;
    ed.focus();
    if (savedRange) {
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(savedRange);
    }
  }
  
  function execFormat(cmd, value = null) {
    const ed = document.getElementById('taskDesc');
    if (ed) ed.focus();
    document.execCommand(cmd, false, value);
  }
  
  function makeCLItem(text, checked = false) {
    const wrap = document.createElement('div');
    wrap.className = 'cl-item' + (checked ? ' done' : '');
    wrap.setAttribute('data-cl', '1');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'cl-cb';
    cb.checked = checked;
    cb.addEventListener('change', function() {
      this.closest('.cl-item').classList.toggle('done', this.checked);
    });
    const span = document.createElement('span');
    span.className = 'cl-text';
    span.contentEditable = 'true';
    span.textContent = text;
    wrap.appendChild(cb);
    wrap.appendChild(span);
    return wrap;
  }
  
  function insertChecklist() {
    const ed = document.getElementById('taskDesc');
    if (!ed) return;
    ed.focus();
    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0) {
      const anchor = sel.anchorNode;
      const inCL = anchor.nodeType === 3 
        ? anchor.parentElement?.closest('.cl-item')
        : anchor.closest?.('.cl-item');
      if (inCL) return;
    }
    const item = makeCLItem('');
    if (sel && sel.rangeCount > 0) {
      const range = sel.getRangeAt(0);
      const selText = range.toString();
      range.deleteContents();
      range.insertNode(item);
      if (selText) item.querySelector('.cl-text').textContent = selText;
    } else {
      ed.appendChild(item);
    }
    const span = item.querySelector('.cl-text');
    const r = document.createRange();
    r.setStart(span, 0);
    r.collapse(true);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }
  
  function openLinkDialog() {
    saveRange();
    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0) {
      const txt = sel.getRangeAt(0).toString();
      const linkText = document.getElementById('linkText');
      if (linkText && txt) linkText.value = txt;
    }
    const dialog = document.getElementById('linkDialog');
    if (dialog) dialog.classList.add('open');
    const linkUrl = document.getElementById('linkUrl');
    if (linkUrl) linkUrl.focus();
  }
  
  function closeLinkDialog() {
    const dialog = document.getElementById('linkDialog');
    if (dialog) dialog.classList.remove('open');
    const linkUrl = document.getElementById('linkUrl');
    const linkText = document.getElementById('linkText');
    if (linkUrl) linkUrl.value = '';
    if (linkText) linkText.value = '';
  }
  
  function insertLink() {
    const url = document.getElementById('linkUrl')?.value.trim();
    const text = document.getElementById('linkText')?.value.trim() || url;
    if (!url) {
      closeLinkDialog();
      return;
    }
    closeLinkDialog();
    restoreRange();
    document.execCommand('insertHTML', false,
      `<a href="${window.escAttr(url)}" target="_blank" rel="noopener">${window.escHtml(text)}</a>`);
  }
  
  function insertImageUrl() {
    const url = prompt('Вставь URL картинки:');
    if (!url) return;
    const ed = document.getElementById('taskDesc');
    if (ed) ed.focus();
    document.execCommand('insertHTML', false,
      `<img src="${window.escAttr(url)}" alt="image" style="max-width:100%;border-radius:8px;margin:4px 0;display:block">`);
  }
  
  function handleImageFile(input) {
    const file = input.files[0];
    if (!file) return;
    if (file.size > 400000) {
      window.showToast('Макс. размер картинки — 400KB', 'error');
      input.value = '';
      return;
    }
    const r = new FileReader();
    r.onload = e => {
      const ed = document.getElementById('taskDesc');
      if (ed) ed.focus();
      document.execCommand('insertHTML', false,
        `<img src="${e.target.result}" alt="${window.escAttr(file.name)}" style="max-width:100%;border-radius:8px;margin:4px 0;display:block">`);
    };
    r.readAsDataURL(file);
    input.value = '';
  }
  
  function handleFileAttach(input) {
    const file = input.files[0];
    if (!file) return;
    const MAX = 150000;
    if (file.size > MAX) {
      const ed = document.getElementById('taskDesc');
      if (ed) ed.focus();
      document.execCommand('insertHTML', false,
        `<a class="file-link" href="#" data-fname="${window.escAttr(file.name)}">📎 ${window.escHtml(file.name)} <span style="opacity:.6;font-size:10px">(добавь URL вручную)</span></a> `);
      window.showToast('Файл > 150KB — замени # на реальный URL', '');
    } else {
      const r = new FileReader();
      r.onload = e => {
        const ed = document.getElementById('taskDesc');
        if (ed) ed.focus();
        document.execCommand('insertHTML', false,
          `<a class="file-link" href="${e.target.result}" download="${window.escAttr(file.name)}">📎 ${window.escHtml(file.name)}</a> `);
      };
      r.readAsDataURL(file);
    }
    input.value = '';
  }
  
  function getEditorHtml() {
    const ed = document.getElementById('taskDesc');
    if (!ed) return '';
    const clone = ed.cloneNode(true);
    clone.querySelectorAll('.cl-item').forEach(item => {
      const cb = item.querySelector('.cl-cb');
      if (cb?.checked) item.setAttribute('data-checked', '1');
      else item.removeAttribute('data-checked');
    });
    return clone.innerHTML;
  }
  
  function setEditorHtml(html) {
    const ed = document.getElementById('taskDesc');
    if (!ed) return;
    ed.innerHTML = html || '';
    ed.querySelectorAll('.cl-item').forEach(item => {
      const cb = item.querySelector('.cl-cb');
      if (!cb) return;
      if (item.dataset.checked === '1') {
        cb.checked = true;
        item.classList.add('done');
      }
      cb.addEventListener('change', function() {
        this.closest('.cl-item').classList.toggle('done', this.checked);
      });
    });
  }
  
  function handleEditorKeydown(e) {
    const sel = window.getSelection();
    const node = sel?.anchorNode;
    const clItem = node?.nodeType === 3
      ? node.parentElement?.closest('.cl-item')
      : node?.closest?.('.cl-item');
    
    if (e.key === 'Enter' && clItem && !e.shiftKey) {
      e.preventDefault();
      const textEl = clItem.querySelector('.cl-text');
      if (!textEl.textContent.trim()) {
        const br = document.createElement('br');
        clItem.replaceWith(br);
        const r = document.createRange();
        r.setStartAfter(br);
        r.collapse(true);
        sel.removeAllRanges();
        sel.addRange(r);
        return;
      }
      const next = makeCLItem('');
      clItem.parentNode.insertBefore(next, clItem.nextSibling);
      const span = next.querySelector('.cl-text');
      const r2 = document.createRange();
      r2.setStart(span, 0);
      r2.collapse(true);
      sel.removeAllRanges();
      sel.addRange(r2);
      return;
    }
    
    if (e.key === 'Backspace' && clItem) {
      const textEl = clItem.querySelector('.cl-text');
      if (!textEl.textContent) {
        e.preventDefault();
        clItem.remove();
      }
    }
    
    if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
      e.preventDefault();
      execFormat('bold');
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
      e.preventDefault();
      execFormat('italic');
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      openLinkDialog();
    }
  }
  
  function handleEditorPaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (file.size > 400000) {
          window.showToast('Картинка слишком большая (макс 400KB)', 'error');
          return;
        }
        const r = new FileReader();
        r.onload = ev => {
          document.execCommand('insertHTML', false,
            `<img src="${ev.target.result}" alt="paste" style="max-width:100%;border-radius:8px;margin:4px 0;display:block">`);
        };
        r.readAsDataURL(file);
        return;
      }
    }
  }
  
  function descPreview(html) {
    if (!html) return '';
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const checks = tmp.querySelectorAll('.cl-item');
    if (checks.length) {
      const total = checks.length;
      const done = [...checks].filter(c => c.classList.contains('done') || c.dataset.checked === '1').length;
      const chips = [...checks].slice(0, 3).map(c => {
        const isDone = c.classList.contains('done') || c.dataset.checked === '1';
        const text = (c.querySelector('.cl-text')?.textContent || c.textContent).trim().slice(0, 22);
        return `<span class="rp-check${isDone ? ' done' : ''}">${isDone ? '☑' : '☐'} ${window.escHtml(text)}</span>`;
      }).join('');
      const more = total > 3 ? `<span style="color:var(--muted2);font-size:10px"> +${total - 3}</span>` : '';
      return `<div style="margin-bottom:2px">${chips}${more}</div><div style="font-size:10px;color:var(--muted2)">☑ ${done}/${total} выполнено</div>`;
    }
    const plain = (tmp.textContent || tmp.innerText || '').replace(/\s+/g, ' ').trim();
    if (!plain) return '';
    const safe = window.escHtml(plain.slice(0, 120)) + (plain.length > 120 ? '…' : '');
    return `<span class="rp-text">${safe}</span>`;
  }
  
  return {
    execFormat,
    insertChecklist,
    openLinkDialog,
    closeLinkDialog,
    insertLink,
    insertImageUrl,
    handleImageFile,
    handleFileAttach,
    getEditorHtml,
    setEditorHtml,
    handleEditorKeydown,
    handleEditorPaste,
    descPreview
  };
})();

// Make functions globally available for inline handlers
window.efmt = (cmd) => window.RichEditor.execFormat(cmd);
window.eChecklist = () => window.RichEditor.insertChecklist();
window.eLinkOpen = () => window.RichEditor.openLinkDialog();
window.closeLinkDialog = () => window.RichEditor.closeLinkDialog();
window.confirmLink = () => window.RichEditor.insertLink();
window.eImageUrl = () => window.RichEditor.insertImageUrl();
window.handleImgFile = (input) => window.RichEditor.handleImageFile(input);
window.handleFileAttach = (input) => window.RichEditor.handleFileAttach(input);
window.editorKeyDown = (e) => window.RichEditor.handleEditorKeydown(e);
window.editorPaste = (e) => window.RichEditor.handleEditorPaste(e);
window.getEditorHtml = () => window.RichEditor.getEditorHtml();
window.setEditorHtml = (html) => window.RichEditor.setEditorHtml(html);
window.descPreview = (html) => window.RichEditor.descPreview(html);