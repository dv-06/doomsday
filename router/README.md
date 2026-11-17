# OpenWrt Indian-egress collector

This collector runs on the JioRouter AX6000 (OpenWrt 25.12-SNAPSHOT,
aarch64) once per hour. It fetches District's public Bengaluru movie page over
the home connection, extracts the six configured cinemas and the two target
dates, validates the result, and uploads one compact inbox file:

```
data/inbox/district.json
```

It does not fetch BookMyShow, bypass Cloudflare/Akamai, use proxies, or invent
seats. BookMyShow remains a separately reported, blocked source. GitHub
Actions ingests the inbox through the existing Python pipeline and deploys
Pages.

## Files on the router

| Path | Purpose |
|---|---|
| `/opt/doomsday-watch/collect.sh` | lock, fetch, validate, upload, log |
| `/opt/doomsday-watch/collector.uc` | `__NEXT_DATA__` extraction and filtering |
| `/opt/doomsday-watch/config.json` | movie URL, cinema IDs, target dates, limits |
| `/opt/doomsday-watch/state.json` | last successful hash/upload (created at runtime) |
| `/etc/doomsday-watch/token` | fine-grained PAT, mode `600`, never in the repo |
| `/mnt/seagate/doomsday/logs/` | daily logs, 14-day retention, 5 MB cap per file |

Temporary HTML/JSON lives in `/tmp` and is deleted on exit. No packages are
installed and no network, firewall, Samba or Tailscale settings are changed.

## Install

Copy this directory to the router (for example `/tmp/doomsday-router`), then:

```sh
cd /tmp/doomsday-router
sh install.sh                 # files only, no cron
# after the PAT is in place and manual tests pass:
sh install.sh --enable-cron
```

The cron entry is exactly:

```cron
7 * * * * /opt/doomsday-watch/collect.sh >> /mnt/seagate/doomsday/logs/cron.log 2>&1
```

`collect.sh` also takes an internal `flock`, so a slow run cannot overlap the
next hour.

## PAT

Create a fine-grained PAT limited to `dv-06/doomsday` with **Contents: Read and
write** only. Transfer it without putting it in a command line, shell history,
repository file or log, and write it to `/etc/doomsday-watch/token` with mode
`600`. The collector sends the Authorization header through `openssl s_client`
stdin, so the token is not visible in process arguments.

## Manual test

Dry run (no upload, no state changes):

```sh
DW_UPLOAD=0 /opt/doomsday-watch/collect.sh
tail -n 20 /mnt/seagate/doomsday/logs/collector-$(date -u +%Y%m%d).log
```

Force a real upload after PAT setup (bounded, one retry on 409):

```sh
DW_FORCE=1 /opt/doomsday-watch/collect.sh
```

## Failure behaviour

* Low memory (<80 MB available): abort before fetching.
* Fetch timeout / non-200 / oversized or tiny page: abort, preserve state.
* Missing/malformed `__NEXT_DATA__`: abort, preserve state.
* No configured cinema IDs or no movie metadata: abort, preserve state.
* GitHub 401/403 or network failure: log status, keep local state so the next
  run retries the same content.
* GitHub 409: refresh the file SHA and retry once.
* Unchanged content hash: skip upload; only update the local check timestamp.

## Rollback

```sh
sh uninstall.sh
```

This removes only the Doomsday cron entry, `/opt/doomsday-watch` and the token.
It leaves logs, dashboard data, history, Samba, Tailscale and all other router
configuration untouched.
