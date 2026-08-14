const SUPABASE_URL = 'https://djeijlkqypvaznmlvtxe.supabase.co';
const ANON_KEY = 'sb_publishable__gKHTQEwUBtQqcMi0-XNiQ_cU4fpPAN';
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

async function modelRequest(kitId, method = 'GET', body = null) {
  const sessionToken = accessToken();
  if (!sessionToken) throw new Error('Sessão autenticada não encontrada. Volta a iniciar sessão.');
  const response = await fetch(`${SUPABASE_URL}/functions/v1/vision-kit-model?kit_id=${encodeURIComponent(kitId)}`, {
    method,
    headers: { apikey: ANON_KEY, Authorization: `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify({ kit_id: kitId, ...body }) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function field(label, input) {
  const wrapper = document.createElement('label');
  wrapper.style.cssText = 'display:grid;gap:8px;color:#e2e8f0;font-size:14px;font-weight:700';
  const title = document.createElement('span');
  title.textContent = label;
  input.style.cssText = 'min-height:48px;width:100%;border:1px solid rgba(71,85,105,.8);border-radius:12px;background:#0f172a;color:#e2e8f0;padding:0 14px;font:inherit';
  wrapper.append(title, input);
  return wrapper;
}

async function addModelControls(editor, footer) {
  if (editor.querySelector('[data-aql-model-controls="true"]') || !selectedKitId) return;
  const panel = document.createElement('section');
  panel.dataset.aqlModelControls = 'true';
  panel.style.cssText = 'display:grid;gap:14px;margin:20px 28px;padding:18px;border:1px solid rgba(56,189,248,.28);border-radius:16px;background:rgba(14,165,233,.06)';
  panel.innerHTML = '<div style="color:#f8fafc;font-size:17px;font-weight:800">Modelo de inferência Edge</div><div data-status style="color:#94a3b8;font-size:13px">A carregar projetos do AQL Vision Lab…</div>';
  footer.parentElement?.insertBefore(panel, footer);
  try {
    const payload = await modelRequest(selectedKitId);
    if (!panel.isConnected || selectedKitId !== payload.assignment.kit_id) return;
    const project = document.createElement('select');
    project.append(new Option('Sem modelo associado', ''));
    payload.projects.forEach((item) => project.append(new Option(`${item.name} — ${item.study_object}`, item.id)));
    const policy = document.createElement('select');
    policy.append(new Option('Usar sempre a última versão aprovada', 'latest_approved'), new Option('Fixar uma versão específica', 'pinned'));
    const version = document.createElement('select');
    const status = panel.querySelector('[data-status]');
    const refreshVersions = () => {
      const selected = payload.projects.find((item) => item.id === project.value);
      version.replaceChildren();
      (selected?.versions || []).forEach((item) => version.append(new Option(`v${item.version}${item.edge_status === 'approved' ? ' — aprovada' : ' — anterior'}`, String(item.version))));
      version.disabled = policy.value !== 'pinned';
      version.parentElement.style.display = policy.value === 'pinned' ? 'grid' : 'none';
    };
    project.value = payload.assignment.vision_lab_project_id || '';
    policy.value = payload.assignment.vision_model_policy || 'latest_approved';
    panel.append(field('Projeto do AQL Vision Lab', project), field('Política da versão', policy), field('Versão ONNX fixa', version));
    project.addEventListener('change', refreshVersions);
    policy.addEventListener('change', refreshVersions);
    refreshVersions();
    if (payload.assignment.vision_model_version) version.value = String(payload.assignment.vision_model_version);
    const save = document.createElement('button');
    save.type = 'button';
    save.textContent = 'Guardar modelo Edge';
    save.style.cssText = 'min-height:48px;border:1px solid rgba(56,189,248,.55);border-radius:12px;background:rgba(14,165,233,.18);color:#7dd3fc;font-weight:800;cursor:pointer';
    save.addEventListener('click', async () => {
      save.disabled = true;
      save.textContent = 'A guardar…';
      try {
        await modelRequest(selectedKitId, 'PATCH', {
          vision_lab_project_id: project.value || null,
          vision_model_policy: policy.value,
          vision_model_version: policy.value === 'pinned' ? Number(version.value) : null,
        });
        status.textContent = project.value ? 'Associação guardada. O Raspberry receberá o modelo automaticamente.' : 'Associação removida.';
        save.textContent = 'Guardado';
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : 'Não foi possível guardar.';
        save.textContent = 'Guardar modelo Edge';
      } finally {
        save.disabled = false;
      }
    });
    panel.append(save);
    status.textContent = 'A versão é resolvida pelo servidor; o endereço privado do ficheiro nunca fica gravado no kit.';
  } catch (error) {
    panel.querySelector('[data-status]').textContent = error instanceof Error ? error.message : 'Não foi possível carregar os modelos.';
  }
}

function decorateEdgeEditor() {
  if (!document.body?.textContent?.includes('Editar Unidades Edge')) return;
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

  addModelControls(editor, footer);

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

let decorationScheduled = false;
function scheduleEdgeEditorDecoration() {
  if (decorationScheduled) return;
  decorationScheduled = true;
  window.requestAnimationFrame(() => {
    decorationScheduled = false;
    decorateEdgeEditor();
  });
}

document.addEventListener('click', (event) => {
  const node = event.target instanceof Element ? event.target.closest('.react-flow__node[data-id^="kit:"]') : null;
  if (node) selectedKitId = node.getAttribute('data-id').slice(4);
}, true);

new MutationObserver(scheduleEdgeEditorDecoration).observe(document.documentElement, { childList: true, subtree: true });
scheduleEdgeEditorDecoration();
