#!/usr/bin/ucode
/*
 * Doomsday Watch / OpenWrt ucode District extractor.
 *
 * Inputs (ARGV):
 *   0  config.json
 *   1  saved District HTML
 *   2  collected_at (UTC ISO-8601)
 *   3  content-only JSON output path (stable hash input)
 *
 * Output: compact JSON on stdout. No network, no secrets, no seat guessing.
 */

import { readfile, writefile } from 'fs';

const cfg = json(readfile(ARGV[0]));
const html = readfile(ARGV[1]);
const collected_at = ARGV[2];
const content_out = ARGV[3];

if (type(cfg) != 'object') die('config.json is not an object');
if (type(cfg.cinemas) != 'array' || length(cfg.cinemas) == 0) die('config has no cinemas');
if (type(cfg.target_dates) != 'array' || length(cfg.target_dates) == 0) die('config has no target_dates');

/* ---------- extract the server-rendered Next.js payload ---------- */
let tag = index(html, '<script id="__NEXT_DATA__"');
if (tag < 0) die('District page has no __NEXT_DATA__ (layout changed or block page)');
let open = index(substr(html, tag), '>');
if (open < 0) die('District __NEXT_DATA__ tag is malformed');
let body_start = tag + open + 1;
let close = index(substr(html, body_start), '</script>');
if (close < 0) die('District __NEXT_DATA__ has no closing script tag');

let data;
try {
    data = json(substr(html, body_start, close));
} catch (e) {
    die('District __NEXT_DATA__ is not valid JSON: ' + e);
}

let page_props = (((data.props || {}).pageProps) || {});
let state = page_props.initialState || {};
let page_content_id = '' + (((page_props.data || {}).contentId) || (cfg.content_id || ''));
if (cfg.content_id && page_content_id != cfg.content_id)
    die('District content_id mismatch: page=' + page_content_id + ' config=' + cfg.content_id);

/* ---------- movie metadata ---------- */
let movie = null;
let movie_data = ((state.mdpV2 || {}).movieData) || {};
if (movie_data[cfg.content_id] && movie_data[cfg.content_id].movie)
    movie = movie_data[cfg.content_id].movie;
if (!movie) {
    for (let key in movie_data) {
        if (movie_data[key] && movie_data[key].movie) { movie = movie_data[key].movie; break; }
    }
}
if (!movie || !movie.name) die('District page parsed but no movie metadata was found');

/* ---------- find cinema/session groups anywhere in the state ---------- */
let groups = [];
function walk(node, depth) {
    if (depth > 8 || node == null) return;
    if (type(node) == 'object') {
        if (type(node.arrangedSessions) == 'array') {
            for (let item in node.arrangedSessions) push(groups, item);
        }
        for (let key in node) walk(node[key], depth + 1);
    } else if (type(node) == 'array') {
        for (let item in node) walk(item, depth + 1);
    }
}
walk(state, 0);
if (length(groups) == 0) die('District page has no arrangedSessions');

/* ---------- filter configured cinemas; keep sessions for IST filtering ---------- */
/* District returns naive UTC clocks. Sending all sessions for the six cinemas
 * lets the Python ingest convert to Asia/Kolkata first and then apply the exact
 * target dates, including sessions whose UTC date is the previous day.        */
let wanted = {};
for (let cinema in cfg.cinemas) wanted['' + cinema.district_id] = cinema;

function compact_area(a) {
    if (type(a) != 'object') return null;
    return {
        label: a.label || a.description || 'General',
        code: a.code,
        price: a.price,
        sTotal: a.sTotal,
        sAvail: a.sAvail,
        seatStatus: a.seatStatus,
        disableClick: a.disableClick,
        seatClasses: a.seatClasses,
        description: a.description
    };
}

function compact_session(s) {
    let areas = [];
    if (type(s.areas) == 'array') {
        for (let a in s.areas) {
            let out = compact_area(a);
            if (out) push(areas, out);
        }
    }
    return {
        sid: s.sid,
        showTime: s.showTime,
        audi: s.audi,
        scrnFmt: s.scrnFmt,
        total: s.total,
        avail: s.avail,
        seatStatus: s.seatStatus,
        mcd: s.mcd,
        encSessionId: s.encSessionId,
        tags: s.tags,
        areas: areas
    };
}

let out_groups = [];
let seen = {};
let target_sessions = 0;
for (let group in groups) {
    let blob = group.data || {};
    let id = '' + (blob.id || '');
    if (!wanted[id] || seen[id]) continue;
    seen[id] = true;

    let sessions = [];
    let available_dates = {};
    let all_sessions = (type(group.sessions) == 'array') ? group.sessions : [];
    for (let session in all_sessions) {
        if (type(session) != 'object') continue;
        let show_time = '' + (session.showTime || '');
        if (length(show_time) < 16 || index(show_time, 'T') < 0) continue;
        let day = substr(show_time, 0, 10);
        available_dates[day] = true;
        push(sessions, compact_session(session));
        target_sessions++;
    }

    let dates = sort(keys(available_dates));
    push(out_groups, {
        data: {
            id: id,
            name: blob.name,
            address: blob.address,
            distanceFromUser: blob.distanceFromUser
        },
        entityUrl: group.entityUrl,
        entityName: group.entityName,
        sessions: sessions,
        available_dates: dates
    });
}

if (length(out_groups) == 0)
    die('District page contained none of the configured cinema IDs');

let max_sessions = ((cfg.limits || {}).max_sessions) || 500;
if (target_sessions > max_sessions)
    die('too many sessions: ' + target_sessions + ' > ' + max_sessions);

let content = {
    content_id: '' + cfg.content_id,
    movie: {
        content_id: '' + (((movie.content_id) || cfg.content_id)),
        title: movie.name,
        release_date: movie.release_date,
        duration_minutes: movie.duration,
        primary_language: movie.primary_language,
        languages: movie.languages,
        poster: movie.poster || movie.horizontal_poster
    },
    groups: out_groups
};

let payload = {
    schema_version: 1,
    source: 'district',
    collected_at: collected_at,
    collector: {
        name: 'openwrt-ucode',
        version: '1.0.0',
        host: 'openwrt',
        egress: 'IN',
        parser: 'district-next-data'
    },
    content_id: '' + cfg.content_id,
    movie_url: cfg.movie_url,
    movie: content.movie,
    groups: out_groups
};

writefile(content_out, sprintf('%J', content));
print(sprintf('%J', payload));
