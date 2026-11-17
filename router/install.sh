#!/bin/sh
# Run as root ON THE ROUTER after this directory has been copied there.
# Only creates /opt/doomsday-watch, /etc/doomsday-watch and the approved log dir.
set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST=/opt/doomsday-watch
TOKEN_DIR=/etc/doomsday-watch
LOG_DIR=/mnt/seagate/doomsday/logs

mkdir -p "$DEST" "$TOKEN_DIR" "$LOG_DIR"
chmod 700 "$TOKEN_DIR"

for file in config.json collector.uc collect.sh; do
    if [ -f "$DEST/$file" ]; then
        cp "$DEST/$file" "$DEST/$file.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    fi
    cp "$SRC/$file" "$DEST/$file"
done
chmod 644 "$DEST/config.json" "$DEST/collector.uc"
chmod 755 "$DEST/collect.sh"
[ -f "$DEST/state.json" ] && chmod 600 "$DEST/state.json"

if [ "${1:-}" = "--enable-cron" ]; then
    CURRENT=$(mktemp)
    crontab -l 2>/dev/null | grep -v 'doomsday-watch/collect.sh' > "$CURRENT" || true
    printf '7 * * * * /opt/doomsday-watch/collect.sh >> /mnt/seagate/doomsday/logs/cron.log 2>&1\n' >> "$CURRENT"
    crontab "$CURRENT"
    rm -f "$CURRENT"
    echo "Installed exactly one Doomsday cron entry:"
    crontab -l | grep 'doomsday-watch/collect.sh'
else
    echo "Cron not changed. Re-run with --enable-cron after manual tests and PAT setup."
fi

echo "Collector files installed in $DEST"
echo "Token path (not created): $TOKEN_DIR/token"
