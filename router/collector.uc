#!/usr/bin/ucode
/*
 * Doomsday Watch / OpenWrt ucode District extractor (multi-movie).
 *
 * Usage: collector.uc config.json manifest.json content-out.json
 *
 * The shell fetches each configured movie page and writes a manifest:
 *   {"collected_at": "...", "items": [{"id": "...", "html": "/tmp/x", "ok": 1}, ...]}
 *
 * Output: one compact schema-v2 payload on stdout. No network, no secrets,
 * no seat guessing. A single unavailable movie never blocks the other movie.
 */

import { readfile, writefile } from 'fs';

const cfg = json(readfile(ARGV[0]));
const manifest = json(readfile(ARGV[1]));
const content_out = ARGV[2];

if (type(cfg) != 'object') die('config.json is not an object');
if (type(cfg.cinemas) != 'array' || length(cfg.cinemas) == 0) die('config has no cinemas');

let movie_cfgs = [];
if (type(cfg.movies) == 'array' && length(cfg.movies) > 0) {
    movie_cfgs = cfg.movies;
} else if (cfg.movie_url && cfg.content_id) {
    movie_cfgs = [{
        id: 'avengers-doomsday',
        title: 'Avengers: Doomsday',
        content_id: cfg.content_id,
        movie_url: cfg.movie_url,
        target_dates: cfg.target_dates
    }];
} else {
    die('config has no movies');
}

let manifest_by_id = {};
for (let item in (manifest.items || []))
    if (item && item.id) manifest_by_id['' + item.id] = item;

let max_sessions = ((cfg.limits || {}).max_sessions) || 500;
let total_sessions = 0;

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

function find_movie_meta(state, content_id) {
    let movie_data = ((state.mdpV2 || {}).movieData) || {};
    if (movie_data[content_id] && movie_data[content_id].movie)
        return movie_data[content_id].movie;
    for (let key in movie_data)
        if (movie_data[key] && movie_data[key].movie) return movie_data[key].movie;
    return null;
}

function wanted_for(movie_cfg) {
    let wanted = {};
    let allowed = (type(movie_cfg.cinema_ids) == 'array' && length(movie_cfg.cinema_ids) > 0)
        ? movie_cfg.cinema_ids : null;
    let allowed_ids = {};
    if (allowed) for (let id in allowed) allowed_ids['' + id] = true;
    for (let cinema in cfg.cinemas) {
        let configured = '' + (cinema.id || '');
        if (allowed_ids[configured] || (!allowed && cinema.district_id))
            wanted['' + cinema.district_id] = cinema;
    }
    return wanted;
}

function has_4dx_3d(group) {
    let sessions = (type(group.sessions) == 'array') ? group.sessions : [];
    for (let session in sessions) {
        if (!session || type(session) != 'object') continue;
        let raw = session.scrnFmt;
        let fmt = lc(type(raw) == 'string' ? raw : '');
        if (index(fmt, '4dx') >= 0 && index(fmt, '3d') >= 0) return true;
    }
    return false;
}

function extract(movie_cfg, html) {
    let tag = index(html, '<script id="__NEXT_DATA__"');
    if (tag < 0) return { status: 'unavailable', error: 'District page has no __NEXT_DATA__ (layout changed or block page)' };
    let open = index(substr(html, tag), '>');
    if (open < 0) return { status: 'unavailable', error: 'District __NEXT_DATA__ tag is malformed' };
    let body_start = tag + open + 1;
    let close = index(substr(html, body_start), '</script>');
    if (close < 0) return { status: 'unavailable', error: 'District __NEXT_DATA__ has no closing script tag' };

    let data;
    try {
        data = json(substr(html, body_start, close));
    } catch (e) {
        return { status: 'unavailable', error: 'District __NEXT_DATA__ is not valid JSON: ' + e };
    }

    let page_props = (((data.props || {}).pageProps) || {});
    let state = page_props.initialState || {};
    let page_content_id = '' + (((page_props.data || {}).contentId) || (movie_cfg.content_id || ''));
    if (movie_cfg.content_id && page_content_id != movie_cfg.content_id)
        return { status: 'unavailable', error: 'District content_id mismatch: page=' + page_content_id + ' config=' + movie_cfg.content_id };

    let movie = find_movie_meta(state, movie_cfg.content_id);
    if (!movie || !movie.name)
        return { status: 'error', error: 'District page parsed but no movie metadata was found' };

    let groups = [];
    let saw_sessions_array = false;
    function walk(node, depth) {
        if (depth > 8 || node == null) return;
        if (type(node) == 'object') {
            if (type(node.arrangedSessions) == 'array') {
                saw_sessions_array = true;
                for (let item in node.arrangedSessions) push(groups, item);
            }
            for (let key in node) walk(node[key], depth + 1);
        } else if (type(node) == 'array') {
            for (let item in node) walk(item, depth + 1);
        }
    }
    walk(state, 0);
    if (!saw_sessions_array)
        return { status: 'unavailable', error: 'District page has no arrangedSessions' };

    let wanted = wanted_for(movie_cfg);
    let out_groups = [];
    let seen = {};
    let session_count = 0;
    for (let group in groups) {
        let blob = group.data || {};
        let id = '' + (blob.id || '');
        if (!wanted[id]) {
            /* Newly listed 4DX venues are discovered from explicit sessions,
             * not from guessed venue capability fields. */
            if (!movie_cfg.discover_4dx_3d || !has_4dx_3d(group)) continue;
        }
        if (seen[id]) continue;
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
            session_count++;
        }

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
            available_dates: sort(keys(available_dates))
        });
    }

    total_sessions += session_count;
    return {
        status: 'ok',
        content_id: '' + movie_cfg.content_id,
        movie: {
            content_id: '' + (((movie.content_id) || movie_cfg.content_id)),
            title: movie.name,
            release_date: movie.release_date,
            duration_minutes: movie.duration,
            primary_language: movie.primary_language,
            languages: movie.languages,
            poster: movie.poster || movie.horizontal_poster
        },
        groups: out_groups,
        session_count: session_count
    };
}

let payloads = [];
let contents = [];
for (let movie_cfg in movie_cfgs) {
    if (!movie_cfg.id || !movie_cfg.content_id) die('movie entry is missing id/content_id');
    let item = manifest_by_id['' + movie_cfg.id];
    let outcome;
    if (!item || item.ok != 1) {
        outcome = { status: 'unavailable', error: (item && item.error) || 'page fetch failed' };
    } else {
        outcome = extract(movie_cfg, readfile(item.html));
    }
    let entry = {
        id: '' + movie_cfg.id,
        title: movie_cfg.title || movie_cfg.id,
        status: outcome.status,
        content_id: '' + movie_cfg.content_id,
        movie_url: movie_cfg.movie_url || '',
        error: outcome.error || '',
        movie: outcome.movie || null,
        groups: outcome.groups || []
    };
    push(payloads, entry);
    push(contents, {
        id: entry.id,
        content_id: entry.content_id,
        status: entry.status,
        movie: entry.movie,
        groups: entry.groups
    });
}

if (total_sessions > max_sessions)
    die('too many sessions: ' + total_sessions + ' > ' + max_sessions);

let content = { schema_version: 2, movies: contents };
let payload = {
    schema_version: 2,
    source: 'district',
    collected_at: manifest.collected_at || '',
    collector: {
        name: 'openwrt-ucode',
        version: '2.0.0',
        host: 'openwrt',
        egress: 'IN',
        parser: 'district-next-data'
    },
    movies: payloads
};

writefile(content_out, sprintf('%J', content));
print(sprintf('%J', payload));
