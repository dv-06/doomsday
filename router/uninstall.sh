#!/bin/sh
# Removes only the Doomsday Watch collector. Dashboard data/history are untouched.
set -eu

if crontab -l 2>/dev/null | grep -q 'doomsday-watch/collect.sh'; then
    CURRENT=$(mktemp)
    crontab -l 2>/dev/null | grep -v 'doomsday-watch/collect.sh' > "$CURRENT" || true
    crontab "$CURRENT"
    rm -f "$CURRENT"
    echo "Removed the Doomsday cron entry."
fi

rm -rf /opt/doomsday-watch
rm -f /etc/doomsday-watch/token
rmdir /etc/doomsday-watch 2>/dev/null || true
echo "Removed collector files and token. Logs remain in /mnt/seagate/doomsday/logs."
