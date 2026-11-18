# Browser notifications

Status: **foreground browser notifications are implemented; background Web Push is not.**

The live dashboard is a static GitHub Pages site. It can display a notification through
its service worker only while a dashboard tab is open. Nothing is delivered after Chrome
is closed, after Android freezes the backgrounded tab, or while the phone is locked.

## Why alerts previously appeared not to arrive

1. Notifications are intentionally disabled by default, and there was no test button or
   delivery diagnostics, so there was no way to distinguish "off" from "broken".
2. The first load marks every existing history event as already seen. Enabling
   notifications after that only alerts on **new** changes. On a quiet day there is
   nothing to deliver.
3. Availability events did not always carry a source format label, so a structured
   movie/cinema/date/time/format/event-type notification could not be built reliably.
4. Service-worker readiness had no timeout and failures were swallowed, leaving the
   Settings page claiming a worker was installed even when delivery could not happen.
5. Clicking a notification only focused an exactly matching URL; otherwise it opened a
   second window instead of navigating the existing app to the movie/date history link.

## Implemented rules

- Permission is requested only from an explicit Enable/test action. Never on page load.
- Every notification contains:
  - movie title;
  - monitored cinema;
  - target/show date;
  - IST showtime;
  - source format label;
  - event type.
- Ramayana alerts require all of:
  - one of the exact ten target dates;
  - one of the eight configured 4DX Bengaluru venues;
  - an explicit source format that normalises to **4DX 3D**.
  Plain `3D`, `4DX`, `IMAX 3D`, and `Infinity Vision 4DX 3D` do not qualify.
- Avengers uses its configured venues and source-supported formats without a Ramayana
  format restriction.
- Event types: new show, first show for a target date, newly discovered qualifying venue,
  new format, booking opened, sold-out change, and source-reported seat-count drop.
- Stable backend event IDs plus a `localStorage` seen set suppress unchanged sessions and
  repeated snapshots.
- At most three notifications are delivered per five-minute poll. Further events remain
  unseen and are delivered on the next poll, so they are delayed rather than lost.
- Each movie has its own preference switch.
- A notification click lands on
  `#/history?movie=<movie>&date=<date>`, where the History page applies both filters.
- The service worker focus path now reuses and navigates an existing same-origin tab.
- The Settings page reports permission, worker state and scope, push subscription state,
  last notification attempt, and test-delivery result.

## Android instructions

1. Open <https://dv-06.github.io/doomsday/#/settings> in Chrome.
2. Confirm **Service worker — Active**.
3. Turn on **Browser notifications**. Accept Chrome's site permission prompt.
4. Press **Send test notification**.
5. Allow Chrome/Android notification permission for the browser if Android asks.
6. Keep the dashboard tab open to receive new-session alerts.

If the page says **Blocked**, open Chrome's site settings for
`dv-06.github.io`, allow notifications, reload, and retry. Chrome does not allow a page to
re-prompt after a permanent denial.

## Foreground capability

| State | Browser notification |
|---|---|
| Dashboard open and visible | Yes, within the five-minute poll |
| Dashboard backgrounded, Chrome alive | Best effort only; Chrome may throttle or freeze timers |
| Chrome closed | No |
| Phone locked | No |
| Installed PWA closed | No |

## Why genuine background Web Push is absent

GitHub Pages only serves static files. It cannot receive or persist a browser
`PushSubscription`, sign a Web Push request, or hold a VAPID private key. GitHub Actions
can run a sender and could hold a VAPID private key as an encrypted repository secret, but
it still needs a secure, writeable subscription intake endpoint and store. A public
repository cannot hold live subscription endpoints and keys, and GitHub Actions secrets
cannot be created by a browser. The missing approved components are therefore:

1. an HTTPS endpoint that accepts new/renewed/unsubscribed push subscriptions;
2. a private subscription store;
3. a sender that holds `VAPID_PRIVATE_KEY` and runs after hourly ingestion;
4. lifecycle handling for renewal and unsubscribe.

No paid or third-party service was added, and no VAPID key pair or fake subscription flow
was committed. The Settings page therefore reports **Push subscription — Not subscribed**
and **Background delivery — Unavailable**.

## Test coverage

Automated Playwright checks cover:

- granted permission and service-worker `showNotification`;
- denied permission UI;
- unsupported Notification API UI;
- test notification content and last-event diagnostics;
- Ramayana 4DX/date/venue gating;
- separate movie preferences;
- event-type filtering;
- duplicate suppression and deferred delivery beyond three events;
- history deep-link filters;
- mobile overflow and 40px control sizes.

A physical Android device was not available. Service-worker scope and foreground
delivery were tested in Chromium with mobile viewport emulation, not on a real phone.
