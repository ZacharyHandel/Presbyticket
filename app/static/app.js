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
