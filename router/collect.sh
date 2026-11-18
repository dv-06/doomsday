#!/bin/sh
#
# Doomsday Watch / OpenWrt Indian-egress collector.
#
# Allowed writes: /opt/doomsday-watch (state/temp is in /tmp),
# /mnt/seagate/doomsday/logs, and the GitHub inbox through the API.
# No packages, services, network or cron changes are made by this script.

set -u
umask 077

BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG="$BASE/config.json"
STATE="$BASE/state.json"
LOG_DIR="/mnt/seagate/doomsday/logs"
TOKEN_FILE="/etc/doomsday-watch/token"
CA_FILE="/etc/ssl/cert.pem"
LOCK_FILE="/tmp/doomsday-watch.lock"
FORCE="${DW_FORCE:-0}"
UPLOAD="${DW_UPLOAD:-1}"

mkdir -p "$LOG_DIR" || exit 1
LOG="$LOG_DIR/collector-$(date -u +%Y%m%d).log"

log() {
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"
}

rotate_logs() {
    if [ -f "$LOG" ] && [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
        tail -n 5000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
    fi
    find "$LOG_DIR" -name 'collector-*.log' -mtime +14 -delete 2>/dev/null || true
}

rotate_logs

# ---------- config ----------
if [ ! -r "$CONFIG" ]; then
    log "FATAL config missing: $CONFIG"
    exit 1
fi
MOVIE_IDS=$(jsonfilter -e '@.movies[*].id' < "$CONFIG" 2>/dev/null)
REPO=$(jsonfilter -e '@.repository' < "$CONFIG" 2>/dev/null)
BRANCH=$(jsonfilter -e '@.branch' < "$CONFIG" 2>/dev/null)
INBOX=$(jsonfilter -e '@.inbox_path' < "$CONFIG" 2>/dev/null)
UA=$(jsonfilter -e '@.user_agent' < "$CONFIG" 2>/dev/null)
MIN_MB=$(jsonfilter -e '@.limits.min_available_mb' < "$CONFIG" 2>/dev/null)
MAX_BYTES=$(jsonfilter -e '@.limits.max_html_bytes' < "$CONFIG" 2>/dev/null)
TIMEOUT=$(jsonfilter -e '@.limits.fetch_timeout_seconds' < "$CONFIG" 2>/dev/null)
MIN_MB=${MIN_MB:-80}
MAX_BYTES=${MAX_BYTES:-3000000}
TIMEOUT=${TIMEOUT:-30}
if [ -z "$MOVIE_IDS" ]; then
    log "FATAL config has no movies: $CONFIG"
    exit 1
fi
for value in "$REPO" "$BRANCH" "$INBOX" "$UA"; do
    if [ -z "$value" ]; then
        log "FATAL incomplete config: $CONFIG"
        exit 1
    fi
done

# ---------- memory guard ----------
AVAIL_MB=$(awk '/^MemAvailable:/{printf "%d", $2/1024; exit}' /proc/meminfo 2>/dev/null)
if [ -z "$AVAIL_MB" ] || [ "$AVAIL_MB" -lt "$MIN_MB" ]; then
    log "FATAL low memory: ${AVAIL_MB:-unknown} MB available, need ${MIN_MB} MB"
    exit 1
fi

# ---------- single-instance lock ----------
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another collector run holds the lock; exiting"
    exit 0
fi

TMP=$(mktemp -d /tmp/doomsday.XXXXXX) || { log "FATAL cannot create temp dir"; exit 1; }
PAYLOAD="$TMP/payload.json"
CONTENT="$TMP/content.json"
MANIFEST="$TMP/manifest.json"
ERR="$TMP/parse.err"
cleanup() {
    rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

COLLECTED_AT=$(TZ=IST-5:30 date '+%Y-%m-%dT%H:%M:%S+05:30')
MOVIE_COUNT=$(printf '%s\n' "$MOVIE_IDS" | wc -w)
log "start host=openwrt movies=$MOVIE_COUNT available_mb=$AVAIL_MB upload=$UPLOAD force=$FORCE"

# ---------- fetch every movie/date page (bounded retries, no bypass) ----------
# District returns only one date's sessions per page unless ?fromdate= is used.
printf '{"collected_at":"%s","pages":[' "$COLLECTED_AT" > "$MANIFEST"
fetch_ok_count=0
movie_index=0
page_index=0
first_item=1
for MOVIE_ID in $MOVIE_IDS; do
    URL=$(jsonfilter -e "@.movies[$movie_index].movie_url" < "$CONFIG" 2>/dev/null)
    if [ -z "$URL" ]; then
        log "FATAL movie $MOVIE_ID has no movie_url"
        exit 1
    fi
    DATES=$(jsonfilter -e "@.movies[$movie_index].target_dates[*]" < "$CONFIG" 2>/dev/null)
    if [ -z "$DATES" ]; then
        DATES=""
    fi
    movie_ok=0
    movie_pages=0
    for DATE in $DATES; do
        PAGE_URL="$URL?fromdate=$DATE"
        HTML="$TMP/district-$movie_index-$page_index.html"
        fetch_ok=0
        attempt=1
        while [ "$attempt" -le 2 ]; do
            if wget -q -T "$TIMEOUT" -U "$UA" -O "$HTML" "$PAGE_URL"; then
                fetch_ok=1
                break
            fi
            rc=$?
            log "fetch $MOVIE_ID $DATE attempt $attempt failed rc=$rc"
            attempt=$((attempt + 1))
            [ "$attempt" -le 2 ] && sleep 5
        done
        item_ok=0
        item_error=""
        if [ "$fetch_ok" -eq 1 ]; then
            BYTES=$(wc -c < "$HTML" 2>/dev/null || echo 0)
            if [ "$BYTES" -ge 100000 ] && [ "$BYTES" -le "$MAX_BYTES" ]; then
                item_ok=1
                fetch_ok_count=$((fetch_ok_count + 1))
                movie_ok=$((movie_ok + 1))
                log "fetch $MOVIE_ID $DATE ok bytes=$BYTES"
            else
                item_error="response size ${BYTES} outside allowed range"
                log "fetch $MOVIE_ID $DATE rejected: $item_error"
            fi
        else
            item_error="date page fetch failed"
            log "fetch $MOVIE_ID $DATE failed; other dates continue"
        fi
        if [ "$first_item" -eq 0 ]; then printf ',' >> "$MANIFEST"; fi
        first_item=0
        printf '{"movie_id":"%s","date":"%s","html":"%s","ok":%s,"error":"%s"}'             "$MOVIE_ID" "$DATE" "$HTML" "$item_ok" "$item_error" >> "$MANIFEST"
        page_index=$((page_index + 1))
        movie_pages=$((movie_pages + 1))
    done
    if [ "$movie_pages" -eq 0 ]; then
        # Backwards-compatible single-page fetch when a movie has no date rule.
        HTML="$TMP/district-$movie_index-$page_index.html"
        if wget -q -T "$TIMEOUT" -U "$UA" -O "$HTML" "$URL"; then
            BYTES=$(wc -c < "$HTML" 2>/dev/null || echo 0)
            if [ "$BYTES" -ge 100000 ] && [ "$BYTES" -le "$MAX_BYTES" ]; then
                fetch_ok_count=$((fetch_ok_count + 1))
                movie_ok=$((movie_ok + 1))
                if [ "$first_item" -eq 0 ]; then printf ',' >> "$MANIFEST"; fi
                first_item=0
                printf '{"movie_id":"%s","date":"","html":"%s","ok":1,"error":""}' "$MOVIE_ID" "$HTML" >> "$MANIFEST"
                log "fetch $MOVIE_ID undated ok bytes=$BYTES"
            fi
        fi
        page_index=$((page_index + 1))
    fi
    if [ "$movie_ok" -eq 0 ]; then
        log "movie $MOVIE_ID: no date page succeeded; other movies continue"
    fi
    movie_index=$((movie_index + 1))
done
printf ']}' >> "$MANIFEST"

if [ "$fetch_ok_count" -eq 0 ]; then
    log "FATAL every District date page failed; previous snapshot and state preserved"
    exit 1
fi

# ---------- extract each movie + validate ----------
if ! ucode "$BASE/collector.uc" "$CONFIG" "$MANIFEST" "$CONTENT" > "$PAYLOAD" 2>"$ERR"; then
    log "FATAL District parse failed: $(head -c 300 "$ERR" | tr '\n' ' ')"
    exit 1
fi
if ! jsonfilter -e '@.movies[0].id' < "$PAYLOAD" >/dev/null 2>&1; then
    log "FATAL parsed payload failed validation; previous snapshot preserved"
    exit 1
fi

HASH=$(sha256sum "$CONTENT" | awk '{print $1}')
if [ -z "$HASH" ]; then
    log "FATAL could not hash content"
    exit 1
fi

# ---------- state ----------
LAST_HASH=""
LAST_UPLOAD=""
LAST_COLLECTED=""
LAST_COMMIT=""
if [ -f "$STATE" ]; then
    LAST_HASH=$(jsonfilter -e '@.last_hash' < "$STATE" 2>/dev/null || true)
    LAST_UPLOAD=$(jsonfilter -e '@.last_upload_at' < "$STATE" 2>/dev/null || true)
    LAST_COLLECTED=$(jsonfilter -e '@.last_collected_at' < "$STATE" 2>/dev/null || true)
    LAST_COMMIT=$(jsonfilter -e '@.last_commit' < "$STATE" 2>/dev/null || true)
fi

write_state() {
    tmp="$STATE.tmp.$$"
    printf '{"schema_version":1,"last_checked_at":"%s","last_hash":"%s","last_upload_at":"%s","last_collected_at":"%s","last_commit":"%s"}\n' \
        "$COLLECTED_AT" "$HASH" "${LAST_UPLOAD:-}" "${LAST_COLLECTED:-}" "${LAST_COMMIT:-}" > "$tmp" || return 1
    mv "$tmp" "$STATE" || return 1
}

if [ "$HASH" = "$LAST_HASH" ] && [ "$FORCE" != "1" ]; then
    log "unchanged hash=${HASH}; upload skipped"
    write_state
    exit 0
fi

if [ "$UPLOAD" = "0" ]; then
    log "dry-run hash=${HASH} bytes=${BYTES}; upload disabled"
    exit 0
fi

if [ ! -r "$TOKEN_FILE" ]; then
    log "FATAL PAT missing at $TOKEN_FILE; upload skipped, previous snapshot preserved"
    exit 4
fi
TOKEN=$(cat "$TOKEN_FILE")
if [ -z "$TOKEN" ]; then
    log "FATAL PAT file is empty; upload skipped"
    exit 4
fi

# ---------- GitHub API over TLS (token only on stdin, never argv) ----------
http_status() {
    head -1 "$1" 2>/dev/null | tr -d '\r' | awk '{print $2}'
}

extract_body() {
    ucode -e 'import {readfile,writefile} from "fs"; let s=readfile(ARGV[0]); let i=index(s,"\r\n\r\n"); if(i<0) die("no HTTP body"); writefile(ARGV[1],substr(s,i+4));' "$1" "$2" 2>/dev/null
}

api_request() {
    method="$1"
    path="$2"
    body="${3:-}"
    out="$4"
    {
        printf '%s %s HTTP/1.1\r\n' "$method" "$path"
        printf 'Host: api.github.com\r\n'
        printf 'Authorization: Bearer %s\r\n' "$TOKEN"
        printf 'Accept: application/vnd.github+json\r\n'
        printf 'User-Agent: DoomsdayWatch-NAS/1.0\r\n'
        printf 'X-GitHub-Api-Version: 2022-11-28\r\n'
        printf 'Connection: close\r\n'
        if [ -n "$body" ]; then
            printf 'Content-Type: application/json\r\n'
            printf 'Content-Length: %s\r\n' "$(wc -c < "$body" | tr -d ' ')"
        fi
        printf '\r\n'
        if [ -n "$body" ]; then cat "$body"; fi
    } | openssl s_client -quiet -verify_return_error -connect api.github.com:443 \
        -servername api.github.com -CAfile "$CA_FILE" > "$out" 2>"$TMP/tls.err"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        log "TLS/upload failed rc=$rc: $(head -c 200 "$TMP/tls.err" | tr '\n' ' ')"
        return 1
    fi
    return 0
}

load_sha() {
    if ! api_request GET "/repos/$REPO/contents/$INBOX?ref=$BRANCH" "" "$TMP/get.resp"; then
        return 1
    fi
    st=$(http_status "$TMP/get.resp")
    case "$st" in
        200)
            extract_body "$TMP/get.resp" "$TMP/get.body" || return 1
            SHA=$(jsonfilter -e '@.sha' < "$TMP/get.body" 2>/dev/null)
            if [ -z "$SHA" ]; then
                log "GitHub GET returned 200 without a file SHA"
                return 1
            fi
            ;;
        404)
            SHA=""
            ;;
        401|403)
            log "GitHub authentication failed (HTTP $st); PAT may be expired or lack Contents:write"
            return 1
            ;;
        *)
            log "GitHub GET failed (HTTP ${st:-none})"
            return 1
            ;;
    esac
    return 0
}

build_put_body() {
    ucode -e 'import {readfile,writefile} from "fs"; let b64=readfile(ARGV[0]); let doc={message:ARGV[1],content:b64,branch:ARGV[2]}; if(ARGV[3]!="-") doc.sha=ARGV[3]; writefile(ARGV[4],sprintf("%J",doc));' \
        "$TMP/payload.b64" "$1" "$BRANCH" "${2:--}" "$TMP/put.json" 2>/dev/null
}

if ! ucode -e 'import {readfile,writefile} from "fs"; writefile(ARGV[1],b64enc(readfile(ARGV[0])));' "$PAYLOAD" "$TMP/payload.b64" 2>/dev/null; then
    log "FATAL base64 encoding failed"
    exit 1
fi

MSG="data(nas): District multi-movie snapshot ${COLLECTED_AT}"
COMMIT=""
upload_ok=0
attempt=1
if ! load_sha; then
    log "FATAL could not read current inbox metadata"
    exit 5
fi
while [ "$attempt" -le 2 ]; do
    if ! build_put_body "$MSG" "$SHA"; then
        log "FATAL could not build GitHub request body"
        exit 5
    fi
    if ! api_request PUT "/repos/$REPO/contents/$INBOX" "$TMP/put.json" "$TMP/put.resp"; then
        exit 5
    fi
    st=$(http_status "$TMP/put.resp")
    case "$st" in
        200|201)
            extract_body "$TMP/put.resp" "$TMP/put.body" || true
            COMMIT=$(jsonfilter -e '@.commit.sha' < "$TMP/put.body" 2>/dev/null)
            upload_ok=1
            break
            ;;
        409)
            log "GitHub 409 conflict on attempt $attempt; refreshing SHA"
            attempt=$((attempt + 1))
            sleep 2
            load_sha || { log "FATAL conflict recovery failed"; exit 5; }
            ;;
        401|403)
            log "GitHub authentication failed (HTTP $st); PAT may be expired or lack Contents:write"
            exit 5
            ;;
        *)
            log "GitHub PUT failed (HTTP ${st:-none})"
            exit 5
            ;;
    esac
done

if [ "$upload_ok" -ne 1 ]; then
    log "FATAL upload did not complete after retries"
    exit 5
fi

LAST_UPLOAD="$COLLECTED_AT"
LAST_COLLECTED="$COLLECTED_AT"
LAST_COMMIT="$COMMIT"
write_state || { log "FATAL upload succeeded but local state write failed"; exit 1; }

log "uploaded hash=${HASH} bytes=${BYTES} commit=${COMMIT:-unknown} http=$st"
exit 0
