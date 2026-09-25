const themeButton = document.querySelector('[data-theme-toggle]');
function updateThemeButton() {
  if (!themeButton) return;
  const isDark = document.documentElement.dataset.theme === 'dark';
  themeButton.setAttribute('aria-label', `Switch to ${isDark ? 'light' : 'dark'} mode`);
  themeButton.setAttribute('aria-pressed', String(isDark));
  themeButton.querySelector('.theme-icon').textContent = isDark ? '☀' : '☾';
  themeButton.querySelector('.theme-label').textContent = isDark ? 'Light mode' : 'Dark mode';
}
updateThemeButton();
themeButton?.addEventListener('click', () => {
  const isDark = document.documentElement.dataset.theme === 'dark';
  document.documentElement.dataset.theme = isDark ? 'light' : 'dark';
  try { localStorage.setItem('presbyticket-theme', isDark ? 'light' : 'dark'); } catch (_) {}
  updateThemeButton();
});

const selectAllButton = document.querySelector('[data-select-all]');
const reportCheckboxes = [...document.querySelectorAll('.report-ticket input[type="checkbox"]')];
function updateSelectAllButton() {
  if (selectAllButton) selectAllButton.textContent = reportCheckboxes.every(box => box.checked) ? 'Clear all' : 'Select all';
}
updateSelectAllButton();
selectAllButton?.addEventListener('click', () => {
  const shouldSelect = !reportCheckboxes.every(box => box.checked);
  reportCheckboxes.forEach(box => { box.checked = shouldSelect; });
  updateSelectAllButton();
});
reportCheckboxes.forEach(box => box.addEventListener('change', updateSelectAllButton));

document.querySelector('[data-copy-report]')?.addEventListener('click', async () => {
  const report = document.getElementById('report-text');
  const status = document.querySelector('.copy-status');
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(report.value);
    } else {
      report.select();
      if (!document.execCommand('copy')) throw new Error('Copy failed');
      report.setSelectionRange(0, 0);
    }
    status.textContent = 'Copied. Paste it into your email.';
  } catch (_) {
    report.select();
    status.textContent = 'Select the text and copy it with Ctrl+C or Cmd+C.';
  }
});

const dialog = document.getElementById('ticket-dialog');
document.querySelectorAll('[data-open-dialog]').forEach(button => button.addEventListener('click', () => dialog?.showModal()));
document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog?.close()));
dialog?.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
document.body.addEventListener('ticketCreated', () => {
  dialog?.querySelector('form')?.reset();
  dialog?.close();
  window.location.reload();
});

let draggedId = null;
// Keep native controls usable inside draggable cards.
document.addEventListener('pointerdown', event => {
  const picker = event.target.closest('[data-priority-picker]');
  const card = picker?.closest('.ticket-card');
  if (card) card.draggable = false;
});
document.addEventListener('pointerup', () => {
  document.querySelectorAll('.ticket-card').forEach(card => { card.draggable = true; });
});
document.addEventListener('change', async event => {
  const picker = event.target.closest('[data-priority-picker]');
  if (!picker) return;
  const previous = picker.dataset.savedPriority;
  picker.disabled = true;
  try {
    const response = await fetch(`/tickets/${picker.dataset.ticketId}/priority`, {
      method: 'POST', body: new URLSearchParams({ priority: picker.value }),
    });
    if (!response.ok) throw new Error('Could not save priority. Please try again.');
    const result = await response.json();
    picker.classList.remove(`priority-${previous.toLowerCase()}`);
    picker.classList.add(`priority-${result.priority.toLowerCase()}`);
    picker.dataset.savedPriority = result.priority;
    picker.value = result.priority;
    // Reapply board filters and priority sorting after a change.
    if (picker.closest('.ticket-card')) window.location.reload();
  } catch (error) {
    picker.value = previous;
    alert(error.message);
  } finally {
    picker.disabled = false;
  }
});
document.addEventListener('dragstart', event => {
  const card = event.target.closest('.ticket-card');
  if (!card) return;
  draggedId = card.dataset.ticketId;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', draggedId);
  card.classList.add('dragging');
});
document.addEventListener('dragend', () => {
  document.querySelectorAll('.dragging, .drag-over').forEach(el => el.classList.remove('dragging', 'drag-over'));
  draggedId = null;
});
document.addEventListener('dragover', event => {
  const column = event.target.closest('.board-column');
  if (!column || !draggedId) return;
  event.preventDefault();
  document.querySelectorAll('.drag-over').forEach(el => { if (el !== column) el.classList.remove('drag-over'); });
  column.classList.add('drag-over');
});
document.addEventListener('drop', async event => {
  const column = event.target.closest('.board-column');
  if (!column || !draggedId) return;
  event.preventDefault();
  const ticketId = draggedId;
  column.classList.remove('drag-over');
  try {
    const body = new URLSearchParams({ status: column.dataset.status });
    const response = await fetch(`/tickets/${ticketId}/move`, { method: 'POST', body });
    if (!response.ok) throw new Error('Unable to move ticket');
    window.location.reload();
  } catch (error) { alert(error.message); }
});
const detailsDialog = document.getElementById('ticket-details-dialog');
let detailsRequest = null;
document.addEventListener('click', async event => {
  if (event.target.closest('[data-close-details]')) {
    detailsDialog.close();
    return;
  }
  const link = event.target.closest('a[data-ticket-details]');
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  detailsRequest?.abort();
  const controller = new AbortController();
  detailsRequest = controller;
  detailsDialog.innerHTML = '<div class="dialog-head"><h2 id="ticket-details-title">Loading ticket…</h2><button type="button" class="icon-button" data-close-details aria-label="Close ticket details">×</button></div><p role="status">Loading details…</p>';
  if (!detailsDialog.open) detailsDialog.showModal();
  try {
    const response = await fetch(link.href + '?fragment=true', { signal: controller.signal });
    if (!response.ok) throw new Error('Unable to load ticket details.');
    const html = await response.text();
    if (controller.signal.aborted) return;
    detailsDialog.innerHTML = html;
    detailsDialog.scrollTop = 0;
    detailsDialog.querySelector('[data-close-details]')?.focus();
  } catch (error) {
    if (error.name === 'AbortError') return;
    detailsDialog.querySelector('h2').textContent = 'Ticket details unavailable';
    detailsDialog.querySelector('[role="status"]').textContent = 'Could not load this ticket. Close this dialog and try again.';
  }
});
detailsDialog?.addEventListener('click', event => {
  if (event.target === detailsDialog) {
    const bounds = detailsDialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) detailsDialog.close();
  }
});
detailsDialog?.addEventListener('close', () => detailsRequest?.abort());
