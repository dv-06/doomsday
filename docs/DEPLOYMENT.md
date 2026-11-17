# Deployment (free tier only)

Target: GitHub Actions + GitHub Pages + Telegram/ntfy. No paid API, database, proxy
or hosting. Total cost ₹0 for a public repository.

## 1. Push to GitHub

```bash
git add .
git commit -m "Doomsday Watch"
git branch -M main
git remote add origin https://github.com/<you>/doomsday-watch.git
git push -u origin main
```

The repository must be **public** for free Pages (private repos need a paid plan).

## 2. Enable Pages

**Settings → Pages → Build and deployment**

- Source: **GitHub Actions** (not "Deploy from a branch").

## 3. Allow the monitor to commit

**Settings → Actions → General → Workflow permissions**

- Select **Read and write permissions**.
- Save.

Without this, the hourly job can scrape but cannot commit `data/`.

## 4. Add secrets (optional but recommended)

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | [@userinfobot](https://t.me/userinfobot) after messaging your bot |
| `NTFY_TOPIC` | Any unguessable topic, subscribe in the ntfy app |
| `NOTIFY_WEBHOOK_URL` | Your webhook endpoint (optional) |

`DASHBOARD_URL` can be added as a repository **variable** (not secret) so alert
messages link to the live site.

## 5. First run

**Actions → Hourly ticket watch → Run workflow** (leave `dry_run` unchecked).

Expected log lines:

```
config ok: 6 theatres, dates=('2026-12-17', '2026-12-18'), interval=60m
status=partial shows=20 3D=20 InfinityVision3D=20 theatres_with_listings=3/6 ...
```

Then the job commits `data/`, builds `frontend/`, uploads the Pages artifact and
deploys. The site appears at:

```
https://<user>.github.io/<repo>/
```

The schedule (`5 * * * *`, UTC) takes over from the next hour. Test alerts locally
with `python -m doomsday_watch notify-test`.

## 6. Verify

- `data/latest.json` has a fresh `checked_at` in IST.
- `data/history/runs.jsonl` gains one line per hour.
- The dashboard footer shows the same check time.
- Actions → Pages shows a successful deployment for the same commit.

## Scheduler reality check

GitHub's cron is **best-effort**, not a guarantee:

- Runs can start 5–20 minutes late during peak load.
- Scheduled workflows are disabled after **60 days of repository inactivity**.
  This project writes a data commit most hours, which counts as activity.
- A manual run does not reset the schedule.
- GitHub Actions free minutes are unlimited for public repositories on standard
  runners; a run here takes roughly 1–2 minutes, well within any limit.
- Concurrency is serialised (`concurrency: doomsday-watch`) so two runs never write
  the repo at once.

## Why the monitor deploys Pages itself

Pushes made with the default `GITHUB_TOKEN` do **not** trigger other workflows, so a
separate "deploy on push" workflow would never see the hourly data commit. Instead,
`monitor.yml` commits, builds and deploys in one job. `pages.yml` covers code and
documentation pushes made by a human.

## Custom domain (optional, free)

1. **Settings → Pages → Custom domain**, enter e.g. `doomsday.example.com`.
2. At your DNS provider add `CNAME doomsday → <user>.github.io`.
3. Enable **Enforce HTTPS** once the certificate is issued.

The site uses relative asset paths and HashRouter, so no `base` change is needed.

## Local API (not deployed)

The FastAPI service is optional and local-only:

```bash
pip install -r requirements-api.txt
PYTHONPATH=backend python -m doomsday_watch serve --port 8000
```

Endpoints: `/api/health`, `/api/latest`, `/api/meta`, `/api/events`, `/api/runs`,
`/api/theatres`, and `POST /api/run` (requires `ADMIN_TOKEN` Bearer token). Static
Pages cannot run it; do not expose it publicly without auth and rate limiting.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Permission denied` / push fails | Enable read-write workflow permissions (step 3). |
| Pages 404 | Confirm Source = GitHub Actions and that the deploy job succeeded. |
| BookMyShow `blocked` | Expected. Cloudflare protects showtimes; the UI labels it and keeps the last snapshot. |
| Status `degraded` | Both sources failed. Check the run artifact log; data is preserved. The next run usually recovers. |
| No Telegram alerts | Run `notify-test` locally; check secret names and that you messaged the bot first. |
| Chart empty | `data/history/runs.jsonl` has no rows yet; run the monitor once. |
| Wrong cinema matched | Check the Sources page verification table; correct the ID in `config/monitor.json`. |
| Workflow disabled | Re-enable it in Actions; commit or manually run at least once every 60 days. |

## Cost table

| Service | Usage | Cost |
|---|---|---|
| GitHub Actions (public repo) | ~24 runs/day × ~2 min | ₹0 |
| GitHub Pages (public repo) | static hosting, 100 GB/month soft limit | ₹0 |
| District / BookMyShow pages | 1–2 requests/hour | ₹0 |
| Telegram Bot API | a few messages/hour | ₹0 |
| ntfy.sh | free public topics | ₹0 |

No credit card, trial or paid tier is required at any step.
