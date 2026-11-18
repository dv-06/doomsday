/* Foreground-notification helper.
 *
 * This is NOT a Web Push service worker: there is no VAPID key or server-side
 * push sender in this deployment, so nothing is delivered while the site is
 * closed. The worker exists to display notifications requested by an open page
 * and to handle their click-through deep links.
 */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "./", self.registration.scope).href;

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (windows) => {
      const sameOrigin = windows.find((client) => new URL(client.url).origin === new URL(target).origin);
      if (sameOrigin) {
        try {
          if (sameOrigin.url !== target && "navigate" in sameOrigin) {
            await sameOrigin.navigate(target);
          }
        } catch {
          // Navigation can be refused while a client is being torn down; focus still helps.
        }
        return sameOrigin.focus();
      }
      return self.clients.openWindow(target);
    }),
  );
});
