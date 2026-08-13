const CURRENT_BUILD = 'vision-2026-08-13.5';
const VERSION_CHECK_INTERVAL = 60_000;
let updateNoticeVisible = false;

function showUpdateNotice() {
  if (updateNoticeVisible) return;
  updateNoticeVisible = true;

  const notice = document.createElement('aside');
  notice.setAttribute('role', 'alertdialog');
  notice.setAttribute('aria-label', 'Atualização disponível');
  notice.style.cssText = 'position:fixed;left:50%;top:16px;z-index:2147483647;display:flex;width:calc(100% - 32px);max-width:520px;transform:translateX(-50%);align-items:center;gap:12px;border:1px solid rgba(103,232,249,.35);border-radius:16px;background:rgba(8,20,36,.97);padding:14px;color:#e2e8f0;box-shadow:0 24px 70px rgba(0,0,0,.55);backdrop-filter:blur(18px);font-family:inherit';
  notice.innerHTML = `
    <span style="display:flex;height:42px;width:42px;flex:none;align-items:center;justify-content:center;border-radius:12px;background:rgba(34,211,238,.14);color:#67e8f9;font-size:22px">↻</span>
    <span style="min-width:0;flex:1">
      <strong style="display:block;font-size:14px;color:#fff">Há uma atualização disponível</strong>
      <span style="display:block;margin-top:3px;font-size:12px;line-height:1.4;color:#94a3b8">Queres refrescar agora? A sessão e os dados guardados são mantidos.</span>
    </span>
    <span style="display:flex;flex:none;gap:8px">
      <button data-update-later type="button" style="height:36px;border:1px solid #334155;border-radius:10px;background:transparent;padding:0 12px;color:#cbd5e1;font-weight:700;cursor:pointer">Agora não</button>
      <button data-update-now type="button" style="height:36px;border:0;border-radius:10px;background:#22d3ee;padding:0 14px;color:#06111f;font-weight:900;cursor:pointer">Atualizar</button>
    </span>`;

  notice.querySelector('[data-update-later]').addEventListener('click', () => {
    notice.remove();
    updateNoticeVisible = false;
  });
  notice.querySelector('[data-update-now]').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = 'A atualizar…';
    if ('serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.getRegistration();
      await registration?.update().catch(() => {});
    }
    window.location.reload();
  });
  document.body.appendChild(notice);
}

async function checkForUpdate() {
  if (document.visibilityState !== 'visible' || !navigator.onLine) return;
  try {
    const response = await fetch(`/version.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return;
    const version = await response.json();
    if (version?.buildId && version.buildId !== CURRENT_BUILD) showUpdateNotice();
  } catch {
    // Falhas temporárias de rede voltam a ser verificadas automaticamente.
  }
}

window.setTimeout(checkForUpdate, 15_000);
window.setInterval(checkForUpdate, VERSION_CHECK_INTERVAL);
window.addEventListener('focus', checkForUpdate);
document.addEventListener('visibilitychange', checkForUpdate);
