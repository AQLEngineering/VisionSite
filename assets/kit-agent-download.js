const SUPABASE_URL = 'https://djeijlkqypvaznmlvtxe.supabase.co';
const ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqZWlqbGtxeXB2YXpubWx2dHhlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjI0MjE0OTksImV4cCI6MjA3Nzk5NzQ5OX0.h7bUzjND3FYyCmL-WX0x7vC3Ll9AZXkzlW0etOK4sDI';
let selectedKitId = null;

const safeName = (value) => String(value || 'kit').normalize('NFKD').replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-|-$/g, '').toLowerCase();

function downloadBlob(content, type, name) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function accessToken() {
  for (const key of ['visionAlertsToken', 'aql_auth_token']) {
    const value = window.localStorage.getItem(key);
    if (value?.split('.').length === 3) return value;
  }
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index) || '';
    if (!key.startsWith('sb-') || !key.endsWith('-auth-token')) continue;
    try {
      const session = JSON.parse(window.localStorage.getItem(key) || '{}');
      const value = session?.access_token || session?.currentSession?.access_token;
      if (value) return value;
    } catch {}
  }
  return '';
}

async function downloadKitAgent(kitId) {
  const sessionToken = accessToken();
  if (!sessionToken) throw new Error('Sessão autenticada não encontrada. Volta a iniciar sessão.');
  const response = await fetch(`${SUPABASE_URL}/functions/v1/vision-device-agent-config`, {
    method: 'POST',
    headers: { apikey: ANON_KEY, Authorization: `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ kit_id: kitId }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  const kitName = payload.configuration?.kit?.name || kitId;
  downloadBlob(payload.env_text, 'text/plain;charset=utf-8', `agent-${safeName(kitName)}.env`);
  window.setTimeout(() => downloadBlob(
    JSON.stringify(payload.configuration, null, 2),
    'application/json;charset=utf-8',
    `aql-kit-${safeName(kitName)}.json`,
  ), 200);
  window.setTimeout(() => {
    const link = document.createElement('a');
    link.href = '/downloads/aql-vision-raspberry-package.zip';
    link.download = 'aql-vision-raspberry-package.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, 450);
}

function decorateEdgeEditor() {
  const saveButton = Array.from(document.querySelectorAll('button')).find((button) => {
    if (button.textContent?.trim() !== 'Guardar') return false;
    let ancestor = button.parentElement;
    while (ancestor && ancestor !== document.body) {
      if (ancestor.textContent?.includes('Editar Unidades Edge')) return true;
      ancestor = ancestor.parentElement;
    }
    return false;
  });
  if (!saveButton) return;
  let editor = saveButton.parentElement;
  while (editor && editor !== document.body && !editor.textContent?.includes('Editar Unidades Edge')) {
    editor = editor.parentElement;
  }
  if (!editor || editor === document.body || editor.querySelector('[data-aql-kit-agent-button="true"]')) return;
  const footer = saveButton?.parentElement;
  if (!footer) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.aqlKitAgentButton = 'true';
  button.className = 'inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-sky-400/45 bg-sky-500/10 px-5 text-sm font-bold text-sky-300 transition-colors hover:bg-sky-500/20';
  button.textContent = 'Descarregar agente';
  button.addEventListener('click', async () => {
    if (!selectedKitId) {
      window.alert('Fecha o editor e volta a clicar na unidade Edge antes de descarregar.');
      return;
    }
    button.disabled = true;
    button.textContent = 'A preparar…';
    try {
      await downloadKitAgent(selectedKitId);
      button.textContent = 'Descarregado';
    } catch (error) {
      console.error('AQL kit agent download failed', error);
      window.alert(`Não foi possível preparar o agente deste kit. ${error instanceof Error ? error.message : ''}`);
      button.textContent = 'Descarregar agente';
    } finally {
      button.disabled = false;
    }
  });
  footer.insertBefore(button, footer.firstChild);
}

document.addEventListener('click', (event) => {
  const node = event.target instanceof Element ? event.target.closest('.react-flow__node[data-id^="kit:"]') : null;
  if (node) selectedKitId = node.getAttribute('data-id').slice(4);
}, true);

new MutationObserver(decorateEdgeEditor).observe(document.documentElement, { childList: true, subtree: true });
decorateEdgeEditor();
