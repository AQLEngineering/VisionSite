const BUTTON_SELECTOR = 'button[title="Exportar configuração do kit"]';

function decorateKitDownloadButtons() {
  document.querySelectorAll(BUTTON_SELECTOR).forEach((button) => {
    if (button.dataset.aqlAgentDownload === 'true') return;
    button.dataset.aqlAgentDownload = 'true';
    button.title = 'Descarregar agente e configuração do kit';
    button.setAttribute('aria-label', button.title);
    button.classList.remove('w-10');
    button.classList.add('w-auto', 'gap-2', 'px-3');
    const label = document.createElement('span');
    label.textContent = 'Descarregar agente';
    label.className = 'text-xs font-bold';
    button.appendChild(label);
  });
}

document.addEventListener('click', (event) => {
  const button = event.target instanceof Element ? event.target.closest('[data-aql-agent-download="true"]') : null;
  if (!button) return;
  window.setTimeout(() => {
    const link = document.createElement('a');
    link.href = '/downloads/aql-vision-raspberry-package.zip';
    link.download = 'aql-vision-raspberry-package.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, 250);
});

new MutationObserver(decorateKitDownloadButtons).observe(document.documentElement, {
  childList: true,
  subtree: true,
});

decorateKitDownloadButtons();
