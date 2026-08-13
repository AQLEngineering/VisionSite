const SUPABASE_URL = 'https://djeijlkqypvaznmlvtxe.supabase.co';
const ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqZWlqbGtxeXB2YXpubWx2dHhlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjI0MjE0OTksImV4cCI6MjA3Nzk5NzQ5OX0.h7bUzjND3FYyCmL-WX0x7vC3Ll9AZXkzlW0etOK4sDI';
let selectedKitId = null;

const apiHeaders = { apikey: ANON_KEY, Authorization: `Bearer ${ANON_KEY}` };
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

async function restRows(table, query) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${query}`, { headers: apiHeaders });
  if (!response.ok) throw new Error(`${table}: HTTP ${response.status}`);
  return response.json();
}

async function downloadKitAgent(kitId) {
  const encoded = encodeURIComponent(kitId);
  const [kits, cameras, sensors] = await Promise.all([
    restRows('aql_kits', `kit_id=eq.${encoded}&select=*`),
    restRows('aql_cameras', `kit_id=eq.${encoded}&select=*`),
    restRows('aql_sensors', `kit_id=eq.${encoded}&select=*`),
  ]);
  const kit = kits[0];
  if (!kit) throw new Error('Kit não encontrado');

  const configuration = {
    schema: 'aql-kit.v3',
    generated_at: new Date().toISOString(),
    authentication: { header: 'X-AQL-Device-Token', value: '<AQL_DEVICE_TOKEN>' },
    endpoints: {
      heartbeat: `${SUPABASE_URL}/functions/v1/vision-device-heartbeat`,
      live_capture: `${SUPABASE_URL}/functions/v1/vision-captures/live`,
      sensor_ingest: `${SUPABASE_URL}/functions/v1/vision-sensor-ingest`,
    },
    runtime: {
      heartbeat_interval_seconds: 120,
      frame_interval_ms: kit.frame_interval_ms ?? 2000,
      capture_interval_seconds: kit.capture_interval_seconds ?? 30,
      offline_buffer_hours: kit.offline_buffer_hours ?? 72,
      bulk_batch_size: kit.bulk_batch_size ?? 500,
    },
    kit,
    cameras,
    sensors,
  };

  downloadBlob(JSON.stringify(configuration, null, 2), 'application/json;charset=utf-8', `aql-kit-${safeName(kit.name)}.json`);
  window.setTimeout(() => {
    const link = document.createElement('a');
    link.href = '/downloads/aql-vision-raspberry-package.zip';
    link.download = 'aql-vision-raspberry-package.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, 250);
}

function edgeEditor() {
  return Array.from(document.querySelectorAll('h1,h2,h3')).find((heading) => heading.textContent?.trim() === 'Editar Unidades Edge')?.closest('[role="dialog"]')
    ?? Array.from(document.querySelectorAll('h1,h2,h3')).find((heading) => heading.textContent?.trim() === 'Editar Unidades Edge')?.parentElement?.parentElement;
}

function decorateEdgeEditor() {
  const editor = edgeEditor();
  if (!editor || editor.querySelector('[data-aql-kit-agent-button="true"]')) return;
  const saveButton = Array.from(editor.querySelectorAll('button')).find((button) => button.textContent?.trim() === 'Guardar');
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
      window.alert('Não foi possível preparar o agente deste kit.');
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
