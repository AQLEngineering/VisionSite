const a=`
// AQL APPS - Inline Service Worker (v1.3.2)
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {
    title: 'AQL Vision',
    body: 'Nova notificação do sistema',
    icon: '/aql-engineering-logo.png',
    badge: '/aql-engineering-logo.png'
  };

  if (event.data) {
    try {
      const json = event.data.json();
      data = Object.assign({}, data, json);
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: data.icon,
    badge: data.badge,
    vibrate: data.vibrate || [100, 50, 100],
    data: data.data || { url: '/demo' },
    actions: data.actions || [
      { action: 'open', title: 'Abrir App' },
      { action: 'close', title: 'Fechar' }
    ],
    tag: data.tag || 'aql-notification',
    renotify: true,
    requireInteraction: data.requireInteraction || false
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const urlToOpen = (event.notification.data && event.notification.data.url) || '/';
  
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          if (client.url.includes(urlToOpen) && 'focus' in client) {
            return client.focus();
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(urlToOpen);
        }
      })
  );
});
`;async function r(){var n;try{const e=new Blob([a],{type:"application/javascript"}),t=URL.createObjectURL(e);return await navigator.serviceWorker.register(t,{scope:"/"})}catch(e){if((n=e==null?void 0:e.message)!=null&&n.includes("protocol")||(e==null?void 0:e.name)==="SecurityError")throw new Error("Service Worker protocols (blob/data) are restricted in this environment");try{const i=`data:application/javascript;charset=utf-8,${encodeURIComponent(a)}`;return await navigator.serviceWorker.register(i,{scope:"/"})}catch{throw new Error("All inline registration methods failed")}}}export{r as registerInlineServiceWorker};
//# sourceMappingURL=service-worker-inline-VazhumOL.js.map
