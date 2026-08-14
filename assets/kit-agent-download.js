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

async function controlRequest(kitId, method = 'GET', body = null) {
  const sessionToken = accessToken();
  if (!sessionToken) throw new Error('Sessão autenticada não encontrada. Volta a iniciar sessão.');
  const response = await fetch(`${SUPABASE_URL}/functions/v1/vision-device-control?kit_id=${encodeURIComponent(kitId)}`, {
    method,
    headers: { apikey: ANON_KEY, Authorization: `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify({ kit_id: kitId, ...body }) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function alertRulesRequest(kitId, method = 'GET', body = null) {
  const sessionToken = accessToken();
  if (!sessionToken) throw new Error('Sessão autenticada não encontrada. Volta a iniciar sessão.');
  const response = await fetch(`${SUPABASE_URL}/functions/v1/vision-alert-rules?kit_id=${encodeURIComponent(kitId)}`, {
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

function acquisitionButton(label, enabled) {
  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.enabled = String(enabled);
  const render = () => {
    const active = button.dataset.enabled === 'true';
    button.textContent = `${label}: ${active ? 'Em aquisição' : 'Parado'}`;
    button.style.cssText = `min-height:48px;border:1px solid ${active ? 'rgba(52,211,153,.55)' : 'rgba(248,113,113,.5)'};border-radius:12px;background:${active ? 'rgba(16,185,129,.14)' : 'rgba(239,68,68,.12)'};color:${active ? '#6ee7b7' : '#fca5a5'};font-weight:800;cursor:pointer`;
  };
  button.addEventListener('click', () => { button.dataset.enabled = String(button.dataset.enabled !== 'true'); render(); });
  render();
  return button;
}

async function addAcquisitionControls(editor, footer) {
  if (editor.querySelector('[data-aql-acquisition-controls="true"]') || !selectedKitId) return;
  const panel = document.createElement('section');
  panel.dataset.aqlAcquisitionControls = 'true';
  panel.style.cssText = 'display:grid;gap:14px;margin:20px 28px;padding:18px;border:1px solid rgba(52,211,153,.25);border-radius:16px;background:rgba(16,185,129,.05)';
  panel.innerHTML = '<div style="color:#f8fafc;font-size:17px;font-weight:800">Aquisição do kit</div><div data-control-status style="color:#94a3b8;font-size:13px">A carregar estado…</div>';
  footer.parentElement?.insertBefore(panel, footer);
  try {
    const payload = await controlRequest(selectedKitId);
    const acquisition = payload.acquisition;
    if (!panel.isConnected || selectedKitId !== acquisition.kit_id) return;
    const buttons = {};
    if (acquisition.video.available) {
      buttons.video = acquisitionButton('Vídeo', acquisition.video.enabled);
      panel.append(buttons.video);
    }
    if (acquisition.sensors.available) {
      buttons.sensors = acquisitionButton('Sondas', acquisition.sensors.enabled);
      panel.append(buttons.sensors);
    }
    const status = panel.querySelector('[data-control-status]');
    status.textContent = Object.keys(buttons).length ? 'Escolhe o estado e guarda. O heartbeat mantém-se ativo.' : 'Este kit ainda não tem câmaras nem sondas ligadas.';
    if (!Object.keys(buttons).length) return;
    const save = document.createElement('button');
    save.type = 'button';
    save.textContent = 'Aplicar Start / Stop';
    save.style.cssText = 'min-height:48px;border:1px solid rgba(52,211,153,.5);border-radius:12px;background:rgba(16,185,129,.16);color:#6ee7b7;font-weight:800;cursor:pointer';
    save.addEventListener('click', async () => {
      save.disabled = true;
      save.textContent = 'A aplicar…';
      try {
        await controlRequest(selectedKitId, 'PATCH', {
          ...(buttons.video ? { video_enabled: buttons.video.dataset.enabled === 'true' } : {}),
          ...(buttons.sensors ? { sensors_enabled: buttons.sensors.dataset.enabled === 'true' } : {}),
        });
        status.textContent = 'Comando guardado. O Edge recebe-o em até 5 segundos.';
        save.textContent = 'Aplicado';
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : 'Não foi possível aplicar o comando.';
        save.textContent = 'Aplicar Start / Stop';
      } finally {
        save.disabled = false;
      }
    });
    panel.append(save);
  } catch (error) {
    panel.querySelector('[data-control-status]').textContent = error instanceof Error ? error.message : 'Não foi possível carregar o estado.';
  }
}

function compactInput(type = 'text') {
  const input = document.createElement('input');
  input.type = type;
  input.style.cssText = 'min-height:42px;width:100%;border:1px solid rgba(71,85,105,.8);border-radius:10px;background:#0f172a;color:#e2e8f0;padding:0 11px;font:inherit';
  return input;
}

function ruleCard(rule, classes, onDelete) {
  const card = document.createElement('div');
  card.style.cssText = 'display:grid;gap:11px;padding:14px;border:1px solid rgba(148,163,184,.2);border-radius:14px;background:rgba(15,23,42,.65)';
  card.dataset.ruleId = rule.rule_id || '';
  const name = compactInput(); name.value = rule.name || 'Nova regra';
  const classLabel = document.createElement('select');
  [...new Set([...(classes || []), rule.class_label].filter(Boolean))].forEach((item) => classLabel.append(new Option(item, item)));
  if (!classLabel.options.length) classLabel.append(new Option('Escreve a classe no nome do modelo primeiro', ''));
  classLabel.value = rule.class_label || classLabel.options[0]?.value || '';
  const confidence = compactInput('number'); confidence.min = '0'; confidence.max = '100'; confidence.step = '1'; confidence.value = String(Math.round(Number(rule.min_confidence ?? .6) * 100));
  const metric = document.createElement('select');
  [['presence','Presença da classe'],['count','Contagem'],['bbox_frame_ratio','Área da caixa / imagem'],['mask_frame_ratio','Área da máscara / imagem'],['lesion_subject_ratio','Área da lesão / sujeito']]
    .forEach(([value,label]) => metric.append(new Option(label,value)));
  metric.value = rule.metric || 'presence';
  const threshold = compactInput('number'); threshold.min = '0'; threshold.step = '0.1';
  threshold.value = metric.value === 'count' ? String(rule.min_count ?? 1) : String(Math.round(Number(rule.min_metric ?? 0) * 1000) / 10);
  const severity = document.createElement('select');
  [['low','Baixa'],['medium','Média'],['high','Alta'],['critical','Crítica']].forEach(([value,label]) => severity.append(new Option(label,value)));
  severity.value = rule.severity || 'medium';
  const hits = compactInput('number'); hits.min = '1'; hits.value = String(rule.persistence_hits ?? 3);
  const windowSize = compactInput('number'); windowSize.min = '1'; windowSize.max = '100'; windowSize.value = String(rule.persistence_window ?? 5);
  const cooldown = compactInput('number'); cooldown.min = '0'; cooldown.value = String(rule.cooldown_seconds ?? 300);
  [classLabel, metric, severity].forEach((input) => { input.style.cssText = name.style.cssText; });
  const grid = document.createElement('div');
  grid.style.cssText = 'display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px';
  grid.append(field('Nome da regra', name), field('Classe do modelo', classLabel), field('Confiança mínima (%)', confidence), field('Métrica de gravidade', metric), field('Limiar (n.º ou %)', threshold), field('Severidade do alerta', severity), field('Persistência: acertos', hits), field('Em quantos frames', windowSize), field('Cooldown (segundos)', cooldown));
  const explanation = document.createElement('div');
  explanation.style.cssText = 'color:#94a3b8;font-size:12px;line-height:1.5';
  const explain = () => {
    explanation.textContent = metric.value === 'lesion_subject_ratio'
      ? 'Exige segmentação/pós-processamento que envie a área da lesão e do sujeito. Não usa a confiança como gravidade.'
      : metric.value === 'presence' ? 'Dispara pela presença confirmada da classe; o limiar de gravidade não é usado.'
      : 'O limiar percentual mede área real relativa; a confiança apenas filtra deteções pouco seguras.';
    threshold.parentElement.style.display = metric.value === 'presence' ? 'none' : 'grid';
  };
  metric.addEventListener('change', explain); explain();
  const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remover regra';
  remove.style.cssText = 'min-height:40px;border:1px solid rgba(248,113,113,.4);border-radius:10px;background:rgba(239,68,68,.08);color:#fca5a5;font-weight:700;cursor:pointer';
  remove.addEventListener('click', () => { card.remove(); onDelete?.(); });
  card.append(grid, explanation, remove);
  card.readRule = () => ({
    ...(card.dataset.ruleId ? { rule_id: card.dataset.ruleId } : {}), name: name.value.trim(), class_label: classLabel.value,
    min_confidence: Number(confidence.value) / 100, metric: metric.value,
    min_metric: metric.value === 'presence' || metric.value === 'count' ? null : Number(threshold.value) / 100,
    min_count: metric.value === 'count' ? Number(threshold.value) : 1,
    persistence_hits: Number(hits.value), persistence_window: Number(windowSize.value), cooldown_seconds: Number(cooldown.value),
    severity: severity.value, enabled: true,
  });
  return card;
}

async function addAlertRuleControls(editor, footer) {
  if (editor.querySelector('[data-aql-alert-rules="true"]') || !selectedKitId) return;
  const panel = document.createElement('section');
  panel.dataset.aqlAlertRules = 'true';
  panel.style.cssText = 'display:grid;gap:14px;margin:20px 28px;padding:18px;border:1px solid rgba(251,191,36,.27);border-radius:16px;background:rgba(245,158,11,.05)';
  panel.innerHTML = '<div style="color:#f8fafc;font-size:17px;font-weight:800">Regras de alerta por inferência</div><div data-rule-status style="color:#94a3b8;font-size:13px">A carregar classes e regras…</div>';
  footer.parentElement?.insertBefore(panel, footer);
  try {
    const payload = await alertRulesRequest(selectedKitId);
    if (!panel.isConnected) return;
    const status = panel.querySelector('[data-rule-status]');
    const classes = payload.model?.classes || [];
    status.textContent = payload.model ? `Modelo v${payload.model.version}: ${classes.length} classe(s). A gravidade vem da regra, não da percentagem de confiança.` : 'Associa primeiro um modelo Edge ao kit para obter as classes.';
    const list = document.createElement('div'); list.style.cssText = 'display:grid;gap:12px';
    const appendRule = (rule = {}) => list.append(ruleCard(rule, classes));
    (payload.rules || []).forEach(appendRule);
    const add = document.createElement('button'); add.type = 'button'; add.textContent = 'Adicionar regra';
    add.style.cssText = 'min-height:44px;border:1px dashed rgba(251,191,36,.5);border-radius:11px;background:rgba(245,158,11,.08);color:#fde68a;font-weight:800;cursor:pointer';
    add.addEventListener('click', () => appendRule({ class_label: classes[0] || '', min_confidence: .6, metric: 'presence', severity: 'medium', persistence_hits: 3, persistence_window: 5, cooldown_seconds: 300 }));
    const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Guardar regras de alerta';
    save.style.cssText = 'min-height:48px;border:1px solid rgba(251,191,36,.5);border-radius:12px;background:rgba(245,158,11,.14);color:#fde68a;font-weight:800;cursor:pointer';
    save.addEventListener('click', async () => {
      save.disabled = true; save.textContent = 'A guardar…';
      try {
        const rules = Array.from(list.children).map((card) => card.readRule());
        await alertRulesRequest(selectedKitId, 'PUT', { rules });
        status.textContent = `${rules.length} regra(s) guardada(s). O próximo resultado do Edge já será avaliado.`;
        save.textContent = 'Guardado';
      } catch (error) { status.textContent = error instanceof Error ? error.message : 'Não foi possível guardar.'; save.textContent = 'Guardar regras de alerta'; }
      finally { save.disabled = false; }
    });
    panel.append(list, add, save);
  } catch (error) { panel.querySelector('[data-rule-status]').textContent = error instanceof Error ? error.message : 'Não foi possível carregar as regras.'; }
}

function fixDeviceTimeCard() {
  const label = Array.from(document.querySelectorAll('div,span,p')).find((element) => element.children.length === 0 && element.textContent?.trim() === 'DEVICE');
  const card = label?.parentElement;
  if (!card || card.dataset.aqlTimeFixed === 'true') return;
  card.dataset.aqlTimeFixed = 'true';
  card.style.minWidth = '190px';
  card.style.overflow = 'hidden';
  Array.from(card.querySelectorAll('div,span,p')).forEach((element) => {
    if (/^\d{2}:\d{2}:\d{2}\.\d{3}$/.test(element.textContent?.trim() || '')) {
      element.style.fontSize = 'clamp(13px, 1.05vw, 17px)';
      element.style.whiteSpace = 'nowrap';
      element.style.letterSpacing = '-0.02em';
    }
  });
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
  addAcquisitionControls(editor, footer);
  addAlertRuleControls(editor, footer);

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
    fixDeviceTimeCard();
  });
}

document.addEventListener('click', (event) => {
  const node = event.target instanceof Element ? event.target.closest('.react-flow__node[data-id^="kit:"]') : null;
  if (node) selectedKitId = node.getAttribute('data-id').slice(4);
}, true);

new MutationObserver(scheduleEdgeEditorDecoration).observe(document.documentElement, { childList: true, subtree: true });
scheduleEdgeEditorDecoration();
