#!/usr/bin/env python3
"""Make a colour-coded map of a FIT file from MTB Survey.

The track is split into segments where mtb_scale is constant. Output:
  <name>.html     standalone Leaflet map (needs internet for the map tiles)
  <name>.geojson  one LineString per segment with the property "mtb:scale" (for JOSM/QGIS)
  <name>_trails.geojson  one feature per trail between two junctions (part of an OSM way), with
                  the combined value. Needs internet (Overpass) the first time, see trailsegments.py.

Usage:  python3 tools/fitmap.py activity.fit [outdir] [--site dir] [--no-osm] [--mount wrist|handlebar]

--no-osm skips the trail segments (no Overpass query).
--mount wrist|handlebar  says where the watch was for the whole ride. Without the flag it is decided from the heart rate.
--osm-client-id ID  enables writing mtb:scale to OSM from the map page (OAuth 2, PKCE).
--osm-api URL       OSM server for login and writing, default https://www.openstreetmap.org.
                    The test server is https://master.apis.dev.openstreetmap.org (separate app registration).

--site also writes a directory for a web host: index.html, style.css, app.js
and leaflet/ locally. No css or js is embedded in the html file and no
style attributes are used, so the page works under a strict Content Security
Policy (style-src 'self'; script-src 'self').
"""
import hashlib, json, math, os, shutil, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fitdump import parse
import trailanalysis
import trailsegments

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
# Ordinal ramp, light -> dark, validated with the dataviz skill's validate_palette.js --ordinal
RAMP = ['#f0a30a', '#e8601c', '#d42a4f', '#a21d86', '#6a1f9c', '#33257a', '#130d2b']


def dist_m(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def build_segments(rows):
    """Segment = run of records with the same mtb_scale. Also broken at pauses."""
    segs, cur, broken = [], None, True
    for kind, m, dev in rows:
        if kind == 'event' and m.get('event') == 0 and m.get('type') in (1, 4):
            broken = True               # timer stop: draw no line across the pause
            continue
        if kind != 'record' or m['lat'] is None or m['lon'] is None:
            continue
        scale = dev.get('mtb_scale')
        if scale is None:
            broken = True
            continue
        pt = (m['lat'], m['lon'], m['ts'])
        if cur is not None and not broken and scale != cur['scale']:
            # The value changed between two records. The stretch up to the new point
            # belongs to the old value, so the lines join up without gaps.
            cur['pts'].append(pt)
        if cur is None or broken or scale != cur['scale']:
            cur = {'scale': scale, 'pts': []}
            segs.append(cur)
        cur['pts'].append(pt)
        broken = False
    out = []
    for i, s in enumerate(segs):
        p = s['pts']
        length = sum(dist_m(p[j], p[j + 1]) for j in range(len(p) - 1))
        out.append({'id': i + 1, 'scale': s['scale'], 'length_m': round(length, 1),
                    'start_ts': p[0][2], 'end_ts': p[-1][2],
                    'coords': [[q[0], q[1]] for q in p]})
    return out


STEP_M = 5          # the profile is resampled every 5 m along the track
MIN_GRADE = 8.0     # percent; steeper than this counts as a steep slope
MIN_LEN_M = 20      # steep stretches shorter than this are ignored
MIN_DH_M = 3        # ... as are those with less elevation difference


def build_profile(rows):
    """Elevation against distance, resampled to STEP_M. Each point:
    [d, alt, grade %, lat, lon, scale, ts, speed km/h, roughness, steer, cadence]
    (index 6+ is used by trailanalysis; the map page only reads 0-5)."""
    recs, d_calc, prev = [], 0.0, None
    for kind, m, dev in rows:
        if kind != 'record' or m['lat'] is None or m.get('alt') is None:
            continue
        if prev is not None:
            d_calc += dist_m(prev, (m['lat'], m['lon']))
        prev = (m['lat'], m['lon'])
        d = m['dist'] if m.get('dist') is not None else d_calc
        if recs and d <= recs[-1][0]:
            continue                    # standing still: same distance, skip
        recs.append((d, m['alt'], m['lat'], m['lon'], dev.get('mtb_scale'), m['ts'],
                     None if m.get('speed') is None else m['speed'] * 3.6,
                     dev.get('roughness'), dev.get('steer'), m.get('cad')))
    if len(recs) < 2:
        return []
    grid, j, d = [], 0, recs[0][0]
    while d <= recs[-1][0]:
        while recs[j + 1][0] < d:
            j += 1
        a, b = recs[j], recs[j + 1]
        f = (d - a[0]) / (b[0] - a[0])
        near = a if f < 0.5 else b
        grid.append([d - recs[0][0], a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]),
                     a[3] + f * (b[3] - a[3]), near[4], a[5] + f * (b[5] - a[5])] + list(near[6:]))
        d += STEP_M
    n, k = len(grid), 2                 # moving average ±2 samples (~25 m) against noise
    smooth = [sum(g[1] for g in grid[max(0, i - k):i + k + 1]) / len(grid[max(0, i - k):i + k + 1])
              for i in range(n)]
    out = []
    for i, g in enumerate(grid):
        lo, hi = max(0, i - k), min(n - 1, i + k)
        grade = 100 * (smooth[hi] - smooth[lo]) / ((hi - lo) * STEP_M) if hi > lo else 0.0
        out.append([round(g[0], 1), round(smooth[i], 1), round(grade, 1),
                    round(g[2], 6), round(g[3], 6), g[4], round(g[5], 1)] +
                   [None if v is None else round(v, 2) for v in g[6:]])
    return out


def find_hills(prof):
    """Continuous stretches where the grade is at least MIN_GRADE in the same direction."""
    sign = [(1 if p[2] >= MIN_GRADE else -1 if p[2] <= -MIN_GRADE else 0) for p in prof]
    runs = []
    for i, s in enumerate(sign):
        if s == 0:
            continue
        if runs and runs[-1][0] == s and i - runs[-1][2] <= 3:   # gaps ≤ 10 m are merged
            runs[-1][2] = i
        else:
            runs.append([s, i, i])
    hills = []
    for s, a, b in runs:
        length = (b - a) * STEP_M
        dh = prof[b][1] - prof[a][1]
        if length < MIN_LEN_M or abs(dh) < MIN_DH_M or (dh > 0) != (s > 0):
            continue
        part = prof[a:b + 1]
        scales = [p[5] for p in part if p[5] is not None]
        hills.append({'id': len(hills) + 1, 'dir': 'up' if s > 0 else 'down',
                      'start_d': prof[a][0], 'end_d': prof[b][0], 'length_m': length,
                      'dh': round(dh, 1), 'avg': round(100 * dh / length, 1),
                      'max': max(abs(p[2]) for p in part) * s,
                      'scale': max(set(scales), key=scales.count) if scales else None,
                      'coords': [[p[3], p[4]] for p in part]})
    return hills


def iso(ts):
    return (FIT_EPOCH + timedelta(seconds=ts)).isoformat().replace('+00:00', 'Z')


def to_geojson(segs):
    feats = []
    for s in segs:
        geom_type = 'LineString' if len(s['coords']) > 1 else 'Point'
        coords = [[c[1], c[0]] for c in s['coords']]
        feats.append({'type': 'Feature',
                      'properties': {'mtb:scale': str(s['scale']), 'segment': s['id'],
                                     'length_m': s['length_m'], 'start': iso(s['start_ts']),
                                     'end': iso(s['end_ts'])},
                      'geometry': {'type': geom_type, 'coordinates': coords if geom_type == 'LineString' else coords[0]}})
    return {'type': 'FeatureCollection', 'features': feats}


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MTB Survey – __TITLE__</title>
<link rel="stylesheet" href="__LEAFLET_CSS__">
<script src="__LEAFLET_JS__"></script>
<style>
  :root { --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --hair:#e1e0d9; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--plane); color:var(--ink); font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
  .wrap { margin:0 auto; padding-inline:16px; padding-block:16px 32px; }
  h1 { font-size:20px; margin:0 0 2px; } .sub { color:var(--ink2); margin:0 0 12px; }
  #map { height:min(50vh,560px); min-height:280px; border:1px solid var(--hair); border-radius:8px; background:#e9e8e2; }
  .stick { position:sticky; top:0; z-index:600; background:var(--plane); padding-top:8px; margin-top:-8px; }
  .legend { display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px; margin:12px 0 4px; color:var(--ink2); }
  .legend b { color:var(--ink); font-weight:600; }
  .key { display:inline-flex; align-items:center; gap:6px; }
  .key.absent { opacity:.38; }
  .sw { width:22px; height:6px; border-radius:3px; display:inline-block; outline:1px solid rgba(11,11,11,.18); }
  .seglabel { background:#fff; color:var(--ink); border:2px solid; border-radius:10px; font-weight:700; font-size:12px;
              line-height:16px; min-width:20px; height:20px; text-align:center; padding:0 4px; box-shadow:0 1px 2px rgba(0,0,0,.3); }
  .tablewrap { overflow-x:auto; margin-top:16px; }
  /* The header row sticks below the map. That requires the wrapper not to scroll sideways,
     so on narrow screens the sideways scroll is kept instead. */
  thead th { position:sticky; top:var(--stickh, 0px); z-index:500; background:var(--surface); box-shadow:inset 0 -1px 0 var(--hair); }
  @media (min-width: 960px) { .tablewrap { overflow:visible; } }
  table { border-collapse:collapse; width:100%; min-width:520px; background:var(--surface); border:1px solid var(--hair); border-radius:8px; }
  th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--hair); font-variant-numeric:tabular-nums; }
  th { color:var(--ink2); font-weight:600; font-size:12px; } tr:last-child td { border-bottom:0; }
  tbody tr { cursor:pointer; } tbody tr:hover, tbody tr.hl { background:#f0efec; }
  h2 { font-size:15px; margin:22px 0 0; }
  .note { color:var(--muted); font-size:12px; margin-top:10px; }
  .toggle { display:inline-flex; align-items:center; gap:6px; color:var(--ink2); cursor:pointer; }
  .halo { width:22px; height:10px; border-radius:5px; display:inline-block; background:rgba(11,11,11,.3); }
  .halo.up { background:rgba(208,59,59,.5); } .halo.down { background:rgba(12,163,12,.5); }
  .hilllabel { color:#fff; border-radius:4px; font-weight:700; font-size:11px; line-height:16px;
               padding:1px 5px; white-space:nowrap; box-shadow:0 1px 2px rgba(0,0,0,.35); }
  .hilllabel.up { background:#b02e2e; } .hilllabel.down { background:#0a7a0a; }
  #prof { position:relative; margin-top:12px; background:var(--surface); border:1px solid var(--hair); border-radius:8px; touch-action:pan-y; }
  #prof svg { display:block; width:100%; height:220px; }
  #prof .tip { position:absolute; pointer-events:none; background:var(--surface); border:1px solid var(--hair); border-radius:6px;
               padding:6px 8px; font-size:12px; line-height:1.4; box-shadow:0 2px 6px rgba(0,0,0,.12); white-space:nowrap; display:none; }
  #prof .tip b { font-variant-numeric:tabular-nums; }
  .h2sub { font-weight:400; color:var(--ink2); }
  #legend { margin:0; }
  .dim { color:#52514e; }
  tbody tr.nohl { cursor:default; }
  tr.part td:first-child { padding-left:28px; color:var(--ink2); }
  .act { font:inherit; font-size:12px; border:1px solid var(--hair); border-radius:6px; background:var(--surface); color:var(--ink); padding:3px 8px; cursor:pointer; white-space:nowrap; }
  .act.confirm { background:var(--ink); color:#fff; border-color:var(--ink); }
  .act:disabled { opacity:.5; cursor:default; }
  .pick { display:inline-flex; gap:4px; }
  .pick .act { min-width:26px; padding:3px 6px; }
  .pick .act.mine { border-color:var(--ink); font-weight:600; }
  .pick .act.cur, .pick .act.cur:disabled { background:var(--ink2); border-color:var(--ink2); color:#fff; opacity:1; }
  .osmnow { font-size:12px; color:var(--ink2); margin-right:6px; white-space:nowrap; }
  .err { color:#b3261e; } .ok { color:#0a7a0a; }
  .tg { display:inline-block; width:18px; font:inherit; border:0; background:none; color:var(--ink2); cursor:pointer; padding:0; text-align:left; }
  #osmsec table { min-width:900px; } #osmsec .key, #trailsec .key, .nw, #osmsec td:first-child, #osmsec td:nth-child(3) { white-space:nowrap; }
  tr.part td { font-size:13px; }
__COLORCSS__
  .mode { display:inline-flex; border:1px solid var(--hair); border-radius:6px; overflow:hidden; margin-right:6px; }
  .mode button { font:inherit; font-size:13px; border:0; background:var(--surface); color:var(--ink2); padding:4px 10px; cursor:pointer; }
  .mode button[aria-pressed="true"] { background:var(--ink); color:#fff; }
  .lvl { display:inline-flex; align-items:center; gap:6px; }
  .dot { width:10px; height:10px; border-radius:50%; display:inline-block; outline:1px solid rgba(11,11,11,.18); }
  .why { color:var(--ink2); }
</style></head><body><div class="wrap">
<h1>MTB Survey – __TITLE__</h1>
<p class="sub" id="sub"></p>
<div class="stick">
<div id="map" role="img" aria-label="Map of the track, colour-coded by mtb:scale. The same data is in the table below."></div>
<div class="legend"><span class="mode" role="group" aria-label="Colour the track by">
  <button type="button" data-mode="auto" aria-pressed="true">Automatic</button><button type="button" data-mode="manual" aria-pressed="false">Your assessment</button><button type="button" data-mode="osm" aria-pressed="false">vs OSM</button></span>
  <span id="legend" class="legend"></span></div>
</div>
<section id="profsec">
<h2>Elevation profile</h2>
<div id="prof" role="img" aria-label="Elevation profile against distance. The line is coloured by mtb:scale, grey bands are steep slopes. The same slopes are in the table below."><svg></svg><div class="tip"></div></div>
<h2>Steep slopes <span class="h2sub">(at least __MINGRADE__ % grade over at least __MINLEN__ m)</span></h2>
<div class="tablewrap"><table><thead><tr><th></th><th>Direction</th><th>At</th><th>Length</th><th>Elevation diff.</th><th>Average</th><th>Max</th><th>mtb:scale</th></tr></thead><tbody id="hills"></tbody></table></div>
</section>
<section id="autosec">
<h2>Automatic assessment <span class="h2sub">(sections of __SECM__ m, sensor values smoothed over __SMOOTHM__ m, limits calibrated 2026-09-30)</span></h2>
<div class="tablewrap"><table><thead><tr><th>Level</th><th>Length</th><th>Share</th><th>Most common reasons</th></tr></thead><tbody id="autosum"></tbody></table></div>
<p class="note" id="mountnote"></p>
<h2>Long climbs <span class="h2sub">(continuous ascent, at least __LONGGAIN__ m up over at least __LONGLEN__ m)</span></h2>
<div class="tablewrap"><table><thead><tr><th>#</th><th>At</th><th>Length</th><th>Ascent</th><th>Average</th></tr></thead><tbody id="climbs"></tbody></table></div>
<h2>Measurements per mtb:scale <span class="h2sub">(median per section, for calibrating the limits)</span></h2>
<div class="tablewrap"><table><thead id="calhead"></thead><tbody id="cal"></tbody></table></div>
<p class="note">If the measurements agree with your assessment, they should increase from row to row. The limits are in <code>LIMITS</code> and <code>MOUNT_LIMITS</code> in <code>tools/trailanalysis.py</code>.</p>
</section>
<section id="osmsec">
<h2>Comparison with OSM <span class="h2sub">(one row per ridden OSM way, your combined value against the mtb:scale tag in OSM)</span></h2>
<p class="note" id="osmsum"></p>
<p class="note" id="osmauth"></p>
<div class="tablewrap"><table><thead><tr><th>OSM way</th><th>Trail</th><th>Ridden</th><th>OSM today</th><th>Yours</th><th>Automatic</th><th>Difference</th><th>Tags in OSM</th><th>Write to OSM</th></tr></thead><tbody id="osmrows"></tbody></table></div>
<p class="note">The buttons <i>0 1 2 3</i> write the chosen value as <code>mtb:scale</code> on the whole way in OSM, in a changeset of its own, after login and a second press to confirm. Your own value has a bold border. The value already in OSM is filled dark and cannot be chosen. If OSM has some other value, for example <code>2+</code>, it is shown before the buttons. The buttons are only shown for trails (path, track, footway, bridleway). Do not tag a way that should be split until it has been split. The difference compares your value with OSM digit by digit. <b>Split</b> means you gave the parts between the junctions different values, so the way should be split in OSM before it is tagged. Such ways show their parts as indented rows. Clicking a row shows the way on the map.</p>
</section>
<section id="trailsec">
<h2>Trail segments <span class="h2sub">(the whole trail between two junctions in OSM gets the highest value that occurs for at least __MINRUN__ m in a row)</span></h2>
<div class="tablewrap"><table><thead><tr><th>#</th><th>Trail</th><th>OSM way</th><th>Length</th><th>Ridden</th><th>Yours</th><th>Automatic</th><th>OSM today</th></tr></thead><tbody id="trailrows"></tbody></table></div>
<p class="note">Yours and Automatic are the combined value of the segment, with the metres that justify it in parentheses. Tick <i>trail segments</i> above the map to see them. Rows without an OSM way are stretches with no way within __MATCHM__ m.</p>
</section>
<h2>Segments</h2>
<div class="tablewrap"><table><thead><tr><th>#</th><th>mtb:scale</th><th>Length</th><th>Time</th><th>Start</th><th>Points</th></tr></thead><tbody id="rows"></tbody></table></div>
<h2>Total per value</h2>
<div class="tablewrap"><table><thead><tr><th>mtb:scale</th><th>Length</th><th>Share</th><th>Segments</th></tr></thead><tbody id="sum"></tbody></table></div>
<p class="note">Map tiles © OpenStreetMap contributors. The file contains your GPS positions, so only share it with people who may see where you have been.</p>
</div>
<script id="osmedit">
__OSMEDIT__
</script>
<script>
const SEGS = __SEGS__, RAMP = __RAMP__, EPOCH = Date.UTC(1989, 11, 31);
const PROF = __PROF__, HILLS = __HILLS__, STEP = __STEP__, AUTO = __AUTO__, TRAILS = __TRAILS__;
const OSMCFG = __OSMCFG__, OSM_EDITABLE = __OSMEDITABLE__;
let trailsOn = false;
const LVLC = ['#0ca30c', '#fab219', '#d03b3b'];   // dataviz status palette: good / warning / critical, always with text
const PER = AUTO ? AUTO.section_m / STEP : 1;
let mode = 'manual';  // PROF: [d, elevation, grade %, lat, lon, scale]
const fmtLen = m => m >= 1000 ? (m / 1000).toFixed(2) + ' km' : m.toFixed(0) + ' m';
const fmtDur = s => s >= 60 ? Math.floor(s / 60) + ' min ' + (s % 60) + ' s' : s + ' s';
const fmtTime = ts => new Date(EPOCH + ts * 1000).toLocaleTimeString('en-GB');
const fmtDate = ts => new Date(EPOCH + ts * 1000).toLocaleDateString('en-CA');

const map = L.map('map', { maxZoom: 22 });
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxNativeZoom: 19, maxZoom: 22, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);

// Steep slopes: coloured halo under the track, red uphill and green downhill, in a pane of its own below the lines
const HILLC = { up: '#d03b3b', down: '#0ca30c' };
map.createPane('hills').style.zIndex = 390;
const hillLayer = L.featureGroup().addTo(map), hillLayers = {};
const fmtPct = v => (v > 0 ? '+' : '') + v.toFixed(1) + ' %';
const arrow = h => h.dir === 'up' ? '▲' : '▼';
HILLS.forEach(h => {
  const tip = `<b>${arrow(h)} ${h.dir}hill</b><br>${fmtLen(h.length_m)} · ${h.dh > 0 ? '+' : ''}${h.dh.toFixed(1)} m<br>average ${fmtPct(h.avg)} · max ${fmtPct(h.max)}`;
  const g = L.featureGroup().addTo(hillLayer);
  L.polyline(h.coords, { pane: 'hills', color: HILLC[h.dir], weight: 20, opacity: .45, lineCap: 'round', lineJoin: 'round' })
    .addTo(g).bindTooltip(tip, { sticky: true });
  L.marker(h.coords[0], { icon: L.divIcon({ className: '', iconSize: null, iconAnchor: [-8, 22],
    html: `<div class="hilllabel ${h.dir}">${arrow(h)} ${Math.abs(h.max).toFixed(0)} %</div>` }) }).addTo(g).bindTooltip(tip);
  g.on('mouseover', () => { hlHill(h.id, true); }); g.on('mouseout', () => { hlHill(h.id, false); });
  hillLayers[h.id] = g;
});

const layers = {}, all = [], manualLayer = L.featureGroup().addTo(map);
SEGS.forEach(s => {
  const color = RAMP[s.scale] || '#52514e';
  const tip = `<b>mtb:scale ${s.scale}</b><br>${fmtLen(s.length_m)} · ${fmtDur(s.end_ts - s.start_ts)}<br>${fmtTime(s.start_ts)}–${fmtTime(s.end_ts)}`;
  const g = L.featureGroup().addTo(manualLayer);
  if (s.coords.length > 1) {
    L.polyline(s.coords, { color: '#fff', weight: 9, opacity: .95, lineCap: 'round', lineJoin: 'round', interactive: false }).addTo(g); // white edge
    const line = L.polyline(s.coords, { color, weight: 5, opacity: 1, lineCap: 'round', lineJoin: 'round' }).addTo(g);
    L.polyline(s.coords, { color, weight: 22, opacity: 0 }).addTo(g).bindTooltip(tip, { sticky: true });          // large hit area
    g.on('mouseover', () => { line.setStyle({ weight: 8 }); hl(s.id, true); });
    g.on('mouseout', () => { line.setStyle({ weight: 5 }); hl(s.id, false); });
  }
  const mid = s.coords[Math.floor((s.coords.length - 1) / 2)];
  L.marker(mid, { icon: L.divIcon({ className: '', iconSize: null, iconAnchor: [10, 10],
    html: `<div class="seglabel sc${s.scale}">${s.scale}</div>` }) }).addTo(g).bindTooltip(tip);
  layers[s.id] = g; s.coords.forEach(c => all.push(c));
});
if (all.length) {
  map.fitBounds(L.latLngBounds(all).pad(0.25), { maxZoom: 21 });
  L.circleMarker(all[0], { radius: 6, color: '#fff', weight: 2, fillColor: '#0b0b0b', fillOpacity: 1 }).addTo(map).bindTooltip('Start');
  L.circleMarker(all[all.length - 1], { radius: 6, color: '#0b0b0b', weight: 2, fillColor: '#fff', fillOpacity: 1 }).addTo(map).bindTooltip('End');
} else { map.setView([62, 15], 5); }

// Automatic layer: one line per section, coloured by level.
// s.level/s.why are set from the variant without (0) or with (1) curviness.
const autoLayer = L.featureGroup();
function applyVariant(v) {
  AUTO.sections.forEach(s => { s.level = s.lv[v]; s.why = s.whys[v]; });
  AUTO.per_scale.forEach(p => { p.levels = p.levels_v[v]; });
}
function renderAutoLayer() {
autoLayer.clearLayers();
AUTO.sections.forEach(s => {
  const tip = `<b>${AUTO.levels[s.level]}</b> · ${(s.start_d / 1000).toFixed(2)} km` +
    (s.why.length ? `<br>${s.why.join(', ')}` : '') +
    (s.mount === 'wrist' ? '<br><i>watch on the wrist</i>' : '') +
    `<br><span class="dim">speed ${s.speed ?? '–'} km/h` + (s.v_rel != null ? ` (${Math.round(100 * s.v_rel)} % of road speed)` : '') + ` · max ${s.grade.toFixed(0)} % · curv ${s.curv}°/100 m` +
    (s.roughness != null ? ` · shake ${s.roughness}` : '') + (s.steer != null ? ` · steer ${s.steer}` : '') +
    (s.scale != null ? ` · yours: ${s.scale}` : '') + '</span>';
  s.tip = tip;
});
// all white edges first, then the colours, otherwise the edges cut off the neighbouring sections
AUTO.sections.forEach(s => L.polyline(s.coords, { color: '#fff', weight: 9, opacity: .95, lineCap: 'round', interactive: false }).addTo(autoLayer));
// sections measured with the watch on the wrist are dashed: less certain assessment
AUTO.sections.forEach(s => L.polyline(s.coords, { color: LVLC[s.level], weight: 5, opacity: 1, lineCap: s.mount === 'wrist' ? 'butt' : 'round',
  dashArray: s.mount === 'wrist' ? '8 5' : null, interactive: false }).addTo(autoLayer));
AUTO.sections.forEach(s => L.polyline(s.coords, { weight: 22, opacity: 0 }).addTo(autoLayer).bindTooltip(s.tip, { sticky: true }));
}
if (AUTO) { applyVariant(AUTO.use_curv ? 1 : 0); renderAutoLayer(); }
// Trail segments: the whole OSM segment between two junctions, coloured by combined value
const trailLayer = L.featureGroup(), trailLabels = L.featureGroup(), trailLines = [], trailGroups = {}, trailLineById = {};
const trailVal = t => mode === 'auto' ? t.level : t.scale;
const DIFFC = { missing: '#898781', equal: '#0ca30c', osm_lower: '#2f6fdd', osm_higher: '#d03b3b' };
const DIFFN = { missing: 'missing in OSM', equal: 'equal', osm_lower: 'OSM lower than yours', osm_higher: 'OSM higher than yours' };
const dcls = d => 'df-' + (d || 'none');
const diffCell = d => d ? `<span class="key"><span class="sw ${dcls(d)}"></span>${DIFFN[d]}</span>` : '–';
const trailColor = t => {
  if (mode === 'osm') return DIFFC[t.diff] || '#c9c8c1';
  const v = trailVal(t); return v == null ? '#52514e' : (mode === 'auto' ? LVLC[v] : RAMP[v]); };
const osmTags = t => Object.entries(t.tags || {}).map(([k, v]) => `${k}=${v}`).join(' · ');
const trailName = t => t.name || (t.highway ? { path: 'trail', track: 'forest road', footway: 'footpath', cycleway: 'cycle path',
  service: 'service road', residential: 'street', unclassified: 'road', steps: 'steps' }[t.highway] || t.highway : 'outside the OSM network');
function trailTip(t) {
  if (mode === 'osm') return `<b>${trailName(t)}</b>` + (t.way ? ` · way ${t.way}` : '') +
    `<br>${t.way ? (DIFFN[t.diff] || 'no assessment of yours') : 'outside the OSM network'}` +
    `<br><span class="dim">OSM today ${t.osm_scale ?? '–'} · yours ${t.scale ?? '–'}` + (t.level != null ? ` · auto ${t.level}` : '') +
    (osmTags(t) ? `<br>${osmTags(t)}` : '') + '</span>';
  const v = trailVal(t), basis = mode === 'auto' ? t.level_m : t.scale_m;
  return `<b>${trailName(t)}</b>` + (t.way ? ` · way ${t.way}` : '') +
    `<br>${mode === 'auto' ? (v == null ? '–' : AUTO.levels[v]) : 'mtb:scale ' + (v ?? '–')}` +
    (v != null ? ` <span class="dim">(${basis} m in a row)</span>` : '') +
    `<br><span class="dim">${fmtLen(t.length_m)} trail · ridden ${fmtLen(t.covered_m)}${t.passes > 1 ? ' in ' + t.passes + ' passes' : ''}` +
    (t.osm_scale != null ? ` · OSM today ${t.osm_scale}` : '') + '</span>';
}
if (TRAILS) TRAILS.segments.forEach(t => {
  const g = L.featureGroup().addTo(trailLayer);
  L.polyline(t.coords, { color: '#fff', weight: 9, opacity: .95, lineCap: 'round', lineJoin: 'round', interactive: false }).addTo(g);
  const line = L.polyline(t.coords, { color: trailColor(t), weight: 5, opacity: 1, lineCap: 'round', lineJoin: 'round' }).addTo(g);
  L.polyline(t.coords, { weight: 22, opacity: 0 }).addTo(g).bindTooltip(() => trailTip(t), { sticky: true });
  g.on('mouseover', () => { line.setStyle({ weight: 8 }); line.bringToFront(); hlTrail(t.id, true); hlRows(t, true); });
  g.on('mouseout', () => { line.setStyle({ weight: 5 }); hlTrail(t.id, false); hlRows(t, false); });
  const mid = t.coords[Math.floor((t.coords.length - 1) / 2)];
  const lab = L.marker(mid, { icon: L.divIcon({ className: '', iconSize: null, iconAnchor: [10, 10],
    html: `<div class="seglabel sc${t.scale}">${t.scale ?? '–'}</div>` }) }).addTo(trailLabels).bindTooltip(() => trailTip(t));
  trailLines.push([t, line]); trailGroups[t.id] = g; trailLineById[t.id] = line;
});
// Rows in the OSM table that belong to the segment: the way's row and the part's row. Scrolls the row into view;
// the map is sticky, so the page below it may move.
function hlRows(t, on) {
  const rows = [document.getElementById('way' + t.way), document.querySelector(`#osmrows tr.part[data-id="${t.id}"]`)].filter(Boolean);
  rows.forEach(r => r.classList.toggle('hl', on));
  if (on && rows[0] && mode === 'osm') rows[0].scrollIntoView({ block: 'nearest' });
}
function hlTrailMap(ids, on) {
  ids.forEach(id => { const l = trailLineById[id]; if (l) { l.setStyle({ weight: on ? 9 : 5 }); if (on) l.bringToFront(); } });
}
function styleTrails() { trailLines.forEach(([t, line]) => line.setStyle({ color: trailColor(t) })); }
function updateLayers() {
  manualLayer.remove(); autoLayer.remove(); trailLayer.remove(); trailLabels.remove();
  const tw = document.getElementById('trailwrap'); if (tw) tw.hidden = mode === 'osm';
  if (mode === 'osm') { trailLayer.addTo(map); styleTrails(); }
  else if (trailsOn) { trailLayer.addTo(map); styleTrails(); if (mode !== 'auto' && map.getZoom() >= 16) trailLabels.addTo(map); }
  else if (mode === 'auto') autoLayer.addTo(map); else manualLayer.addTo(map);
}
map.on('zoomend', () => { if (trailsOn) updateLayers(); });   // labels only when zoomed in
function hlTrail(id, on) { const r = document.getElementById('trail' + id); if (r) r.classList.toggle('hl', on); }
function setMode(m) {
  mode = m;
  document.querySelectorAll('.mode button').forEach(b => b.setAttribute('aria-pressed', b.dataset.mode === m));
  updateLayers(); drawLegend(); drawProfile();
}
document.querySelectorAll('.mode button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
if (!AUTO) document.querySelector('.mode').remove();
else if (!TRAILS || !TRAILS.ways.length) document.querySelector('.mode button[data-mode="osm"]').remove();

function hl(id, on) { const r = document.getElementById('row' + id); if (r) r.classList.toggle('hl', on); }

const present = new Set(SEGS.map(s => s.scale));
function drawLegend() {
  document.getElementById('legend').innerHTML = mode === 'osm'
    ? Object.keys(DIFFN).map(k => `<span class="key"><span class="sw ${dcls(k)}"></span>${DIFFN[k]}</span>`).join('')
    : mode === 'auto'
    ? AUTO.levels.map((n, i) => `<span class="key"><span class="sw lv${i}"></span>${n}</span>`).join('')
    : '<b>mtb:scale</b><span>easier</span>' +
      RAMP.map((c, i) => `<span class="key ${present.has(i) ? '' : 'absent'}"><span class="sw sc${i}"></span>${i}</span>`).join('') +
      '<span>harder</span>';
}
drawLegend();
if (HILLS.length) document.querySelector('.legend').insertAdjacentHTML('beforeend',
  '<label class="toggle"><input type="checkbox" id="showhills" checked>steep slopes <span class="halo up"></span>uphill <span class="halo down"></span>downhill (max grade)</label>' +
  (TRAILS ? '<label class="toggle" id="trailwrap"><input type="checkbox" id="showtrails">trail segments (the whole trail between two junctions)</label>' : ''));
const cb = document.getElementById('showhills');
if (cb) cb.addEventListener('change', () => cb.checked ? hillLayer.addTo(map) : hillLayer.remove());
const tcb = document.getElementById('showtrails');
if (tcb) tcb.addEventListener('change', () => { trailsOn = tcb.checked; updateLayers(); drawProfile(); });
function setTrails(on) { trailsOn = on; if (tcb) tcb.checked = on; updateLayers(); drawProfile(); }

document.getElementById('rows').innerHTML = SEGS.map(s =>
  `<tr id="row${s.id}" data-id="${s.id}"><td>${s.id}</td><td><span class="key"><span class="sw sc${s.scale}"></span>${s.scale}</span></td>` +
  `<td>${fmtLen(s.length_m)}</td><td>${fmtDur(s.end_ts - s.start_ts)}</td><td>${fmtTime(s.start_ts)}</td><td>${s.coords.length}</td></tr>`).join('');
document.querySelectorAll('#rows tr').forEach(tr => tr.addEventListener('click', () =>
  map.fitBounds(layers[tr.dataset.id].getBounds().pad(0.4), { maxZoom: 22 })));

const total = SEGS.reduce((a, s) => a + s.length_m, 0);
document.getElementById('sum').innerHTML = RAMP.map((c, i) => {
  const ss = SEGS.filter(s => s.scale === i); if (!ss.length) return '';
  const len = ss.reduce((a, s) => a + s.length_m, 0);
  return `<tr class="nohl"><td><span class="key"><span class="sw sc${i}"></span>${i}</span></td><td>${fmtLen(len)}</td>` +
         `<td>${total ? (100 * len / total).toFixed(0) : 0} %</td><td>${ss.length}</td></tr>`; }).join('');
let climb = 0; for (let i = 1; i < PROF.length; i++) climb += Math.max(0, PROF[i][1] - PROF[i - 1][1]);
document.getElementById('sub').textContent = SEGS.length
  ? `${fmtDate(SEGS[0].start_ts)} · ${fmtLen(total)}${PROF.length ? ' · ↑ ' + climb.toFixed(0) + ' m' : ''} · ${SEGS.length} segments · point at a line for details`
  : 'The file contains no records with both position and mtb_scale.';

// ---- Steep slopes: table ----
function hlHill(id, on) {
  const r = document.getElementById('hill' + id); if (r) r.classList.toggle('hl', on);
  const b = document.getElementById('band' + id); if (b) b.setAttribute('fill-opacity', on ? .3 : .14);
}
document.getElementById('hills').innerHTML = HILLS.length ? HILLS.map(h =>
  `<tr id="hill${h.id}" data-id="${h.id}"><td><span class="halo ${h.dir}"></span></td><td>${arrow(h)} ${h.dir}hill</td><td>${(h.start_d / 1000).toFixed(2)} km</td>` +
  `<td>${fmtLen(h.length_m)}</td><td>${h.dh > 0 ? '+' : ''}${h.dh.toFixed(1)} m</td><td>${fmtPct(h.avg)}</td><td>${fmtPct(h.max)}</td>` +
  `<td>${h.scale == null ? '–' : `<span class="key"><span class="sw sc${h.scale}"></span>${h.scale}</span>`}</td></tr>`).join('')
  : '<tr class="nohl"><td colspan="8">No stretches steeper than the limit.</td></tr>';
document.querySelectorAll('#hills tr[data-id]').forEach(tr => {
  tr.addEventListener('click', () => {
    if (cb && !cb.checked) { cb.checked = true; hillLayer.addTo(map); }
    map.fitBounds(hillLayers[tr.dataset.id].getBounds().pad(0.6), { maxZoom: 19 });
  });
  tr.addEventListener('mouseenter', () => hlHill(tr.dataset.id, true));
  tr.addEventListener('mouseleave', () => hlHill(tr.dataset.id, false));
});

// ---- Automatic assessment: tables ----
if (!AUTO) document.getElementById('autosec').remove();
else renderAutoTables();
function renderAutoTables() {
  const tot = AUTO.sections.reduce((a, s) => a + s.length_m, 0);
  const km = m => (m / 1000).toFixed(1) + ' km', mm = AUTO.mount_m || {};
  document.getElementById('mountnote').innerHTML =
    `Trail is judged from the steering. Hard trail is judged from the steering and the speed relative to the day's road speed, ` +
    `<b>${AUTO.v_road} km/h</b> (grade-adjusted speed on the calmest parts of the ride). ` +
    (mm.wrist ? `The watch was on the wrist for ${km(mm.wrist)}${AUTO.mount_forced ? ' (specified)' : ', decided from the heart rate'}; those parts are dashed on the map. ` +
      `On the wrist only the speed separates easy trail from hard, and the limit between road and trail is preliminary.` :
      `The watch was on the handlebar${AUTO.mount_forced ? ' (specified)' : ''}.`);
  document.getElementById('autosum').innerHTML = AUTO.levels.map((n, L) => {
    const ss = AUTO.sections.filter(s => s.level === L), len = ss.reduce((a, s) => a + s.length_m, 0);
    const cnt = {}; ss.forEach(s => s.why.forEach(w => { const k = w.replace(/\s*[+-]?\d[\d.,]*\s*(%|m|s)?/g, '').trim(); cnt[k] = (cnt[k] || 0) + 1; }));
    const top = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 3).map(e => e[0]).join(', ');
    return `<tr class="nohl"><td><span class="lvl"><span class="dot lv${L}"></span>${n}</span></td>` +
           `<td>${fmtLen(len)}</td><td>${tot ? (100 * len / tot).toFixed(0) : 0} %</td><td class="why">${top || '–'}</td></tr>`; }).join('');
  document.getElementById('climbs').innerHTML = AUTO.climbs.length ? AUTO.climbs.map(c =>
    `<tr class="nohl"><td>L${c.id}</td><td>${(c.start_d / 1000).toFixed(2)} km</td><td>${fmtLen(c.length_m)}</td>` +
    `<td>+${c.gain.toFixed(1)} m</td><td>${c.avg.toFixed(1)} %</td></tr>`).join('')
    : '<tr class="nohl"><td colspan="5">No long climbs.</td></tr>';
  const cols = [['speed', 'Speed km/h'], ['cv', 'Unevenness'], ['grade', 'Max grade %'], ['curv', 'Curviness °/100 m'], ['stops_per_km', 'Stops/km']]
    .concat(AUTO.has.roughness ? [['roughness', 'Shake mG']] : []).concat(AUTO.has.steer ? [['steer', 'Steer °/s']] : []);
  document.getElementById('calhead').innerHTML = '<tr><th>mtb:scale</th><th>Length</th>' + cols.map(c => `<th>${c[1]}</th>`).join('') +
    '<th>Automatic: easy / experience / hard</th></tr>';
  document.getElementById('cal').innerHTML = AUTO.per_scale.map(p =>
    `<tr class="nohl"><td><span class="key"><span class="sw sc${p.scale}"></span>${p.scale}</span></td><td>${fmtLen(p.length_m)}</td>` +
    cols.map(c => `<td>${p[c[0]] ?? '–'}</td>`).join('') + `<td>${p.levels.join(' / ')} %</td></tr>`).join('');
}

// ---- Writing to OSM (OAuth 2 with PKCE, one changeset per way) ----
// Values to choose from. The OSM scale goes to 6, but 4-6 is extreme terrain.
const SCALE_CHOICES = [0, 1, 2, 3];
function writeCell(w) {
  if (!OSMCFG) return '';
  if (!OSM_EDITABLE.includes(w.highway)) return '<span class="dim">not a trail</span>';
  const other = w.osm_scale != null && !SCALE_CHOICES.some(v => w.osm_scale === String(v));
  return (other ? `<span class="osmnow">in OSM: ${w.osm_scale}</span>` : '') + '<span class="pick">' + SCALE_CHOICES.map(v => {
    const cur = w.osm_scale === String(v), mine = w.scale === v;
    const title = cur ? 'already in OSM' : mine ? 'your value' : `tag mtb:scale=${v}`;
    return `<button type="button" class="act${mine ? ' mine' : ''}${cur ? ' cur' : ''}" data-way="${w.way}" data-value="${v}" title="${title}" disabled>${v}</button>`;
  }).join('') + '</span>';
}
const osm = {
  token: null, user: null,
  redirect() { return location.origin + (location.pathname.endsWith('/') ? location.pathname + 'index.html' : location.pathname); },
  async login() {
    const rnd = n => { const a = new Uint8Array(n); crypto.getRandomValues(a); return btoa(String.fromCharCode(...a)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
    const verifier = rnd(48), state = rnd(12);
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    const challenge = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    sessionStorage.setItem('osm_pkce', JSON.stringify({ verifier, state, hash: location.hash }));
    const q = new URLSearchParams({ response_type: 'code', client_id: OSMCFG.client_id, redirect_uri: this.redirect(),
      scope: 'write_api read_prefs', code_challenge: challenge, code_challenge_method: 'S256', state });
    location.href = OSMCFG.base + '/oauth2/authorize?' + q;
  },
  async finishLogin() {
    const q = new URLSearchParams(location.search);
    if (!q.get('code')) return;
    const p = JSON.parse(sessionStorage.getItem('osm_pkce') || 'null');
    sessionStorage.removeItem('osm_pkce');
    history.replaceState(null, '', location.pathname + (p && p.hash ? p.hash : '#osm'));
    if (!p || p.state !== q.get('state')) throw new Error('wrong state in the OAuth response');
    const r = await fetch(OSMCFG.base + '/oauth2/token', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ grant_type: 'authorization_code', code: q.get('code'), redirect_uri: this.redirect(), client_id: OSMCFG.client_id, code_verifier: p.verifier }) });
    if (!r.ok) throw new Error('token: ' + r.status + ' ' + (await r.text()).slice(0, 200));
    sessionStorage.setItem('osm_token', (await r.json()).access_token);
  },
  async api(method, path, body, type) {
    const r = await fetch(OSMCFG.base + '/api/0.6/' + path, { method, headers: { Authorization: 'Bearer ' + this.token, ...(body ? { 'Content-Type': type || 'text/xml' } : {}) }, body });
    const text = await r.text();
    if (!r.ok) throw new Error(method + ' ' + path + ': ' + r.status + ' ' + text.slice(0, 200));
    return text;
  },
  async whoami() { const u = JSON.parse(await this.api('GET', 'user/details.json')).user; this.user = u.display_name; return u; },
  logout() { sessionStorage.removeItem('osm_token'); this.token = null; this.user = null; },
  /** Writes key=value on the way in a changeset of its own. expected = the value the table believes is in OSM (check). */
  async tagWay(wayId, key, value, expected, comment) {
    const cur = await this.api('GET', 'way/' + wayId);
    const now = OsmEdit.getWayTag(cur, key);
    if ((now ?? null) !== (expected ?? null)) throw new Error(`OSM has changed: ${key} is now ${now ?? 'missing'}. Reload the map before writing.`);
    const cs = (await this.api('PUT', 'changeset/create', OsmEdit.changesetXml({ created_by: 'MTB Survey fitmap 0.3', comment, source: 'survey' }))).trim();
    try {
      const upd = OsmEdit.setWayTag(cur, key, value, cs);
      const version = (await this.api('PUT', 'way/' + wayId, upd.xml)).trim();
      return { changeset: cs, version, old: upd.old };
    } finally { await this.api('PUT', 'changeset/' + cs + '/close').catch(() => {}); }
  }
};
async function initOsmWrite(ways) {
  const box = document.getElementById('osmauth');
  if (!OSMCFG) { box.innerHTML = 'Writing to OSM is turned off. Generate the map with <code>--osm-client-id</code> to turn it on.'; return; }
  // OSM requires a registered http(s) address to redirect back to. A local file has none.
  if (location.protocol === 'file:') {
    box.innerHTML = 'Logging in to OSM does not work when the map is opened as a local file. Generate with <code>--site &lt;dir&gt;</code>, run ' +
      '<code>python3 -m http.server 8767 --bind 127.0.0.1</code> in the directory and open <code>http://127.0.0.1:8767/index.html</code> ' +
      '(the address must be among the redirect addresses of the OAuth app).';
    return;
  }
  const buttons = () => document.querySelectorAll('#osmrows button.act');
  const render = () => {
    box.innerHTML = osm.user
      ? `Logged in to ${OSMCFG.base.replace('https://', '')} as <b>${osm.user}</b>. <a href="#" id="osmlogout">Log out</a>`
      : `<button type="button" class="act" id="osmlogin">Log in to OSM</button> <span class="dim">to be able to tag the ways below · redirect address to register in the OAuth app: <code>${osm.redirect()}</code></span>`;
    buttons().forEach(b => { b.disabled = !osm.user || b.classList.contains('cur'); });
    const lo = document.getElementById('osmlogout'); if (lo) lo.addEventListener('click', e => { e.preventDefault(); osm.logout(); render(); });
    const li = document.getElementById('osmlogin'); if (li) li.addEventListener('click', () => osm.login());
  };
  try {
    await osm.finishLogin();
    osm.token = sessionStorage.getItem('osm_token');
    if (osm.token) await osm.whoami();
  } catch (e) { osm.logout(); box.innerHTML = `<span class="err">Login failed: ${e.message}</span> `; }
  render();
  buttons().forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    const way = ways.find(w => w.way == b.dataset.way), td = b.closest('td'), v = Number(b.dataset.value);
    const reset = x => { x.classList.remove('confirm'); x.textContent = x.dataset.value; };
    if (!b.classList.contains('confirm')) {
      td.querySelectorAll('button.confirm').forEach(reset);   // only one value at a time awaits confirmation
      b.classList.add('confirm'); b.textContent = `Confirm mtb:scale=${v} on way ${way.way}`;
      setTimeout(() => { if (b.classList.contains('confirm')) reset(b); }, 8000);
      return;
    }
    td.querySelectorAll('button').forEach(x => { x.disabled = true; }); b.textContent = 'writing…';
    try {
      const r = await osm.tagWay(way.way, 'mtb:scale', v, way.osm_scale, 'mtb:scale from field survey by bike');
      way.osm_scale = String(v); way.osm_n = v; way.diff = diffClass(way.scale, v); way.diff_auto = diffClass(way.level, v);
      TRAILS.segments.filter(t => t.way === way.way).forEach(t => { t.osm_scale = String(v); t.diff = diffClass(t.scale, v); t.diff_auto = diffClass(t.level, v); });
      const tr = b.closest('tr'); tr.children[3].textContent = way.osm_scale; tr.children[6].innerHTML = diffCell(way.diff) + (way.split ? ' · <b>split</b>' : '');
      td.innerHTML = `<span class="ok">wrote mtb:scale=${v}</span> · <a href="${OSMCFG.base}/changeset/${r.changeset}" target="_blank" rel="noopener">changeset ${r.changeset}</a>`;
      if (mode === 'osm') { styleTrails(); drawProfile(); }
    } catch (err) {
      td.innerHTML = `<span class="err">${err.message}</span>`;
    }
  }));
}
/** Current mtb:scale for ways directly from the OSM API. The page's values come from Overpass when the map
 *  was generated and are stale as soon as someone, for example you, has tagged. Returns the number changed. */
async function refreshOsm(ways) {
  const base = OSMCFG ? OSMCFG.base : 'https://www.openstreetmap.org', now = {};
  const ids = ways.map(w => w.way);
  for (let i = 0; i < ids.length; i += 200) {
    const r = await fetch(`${base}/api/0.6/ways.json?ways=${ids.slice(i, i + 200).join(',')}`);
    if (!r.ok) throw new Error('OSM responded ' + r.status);
    (await r.json()).elements.forEach(e => { now[e.id] = (e.tags && e.tags['mtb:scale']) ?? null; });
  }
  let changed = 0;
  ways.forEach(w => {
    if (!(w.way in now) || now[w.way] === (w.osm_scale ?? null)) return;
    changed++;
    w.osm_scale = now[w.way]; w.osm_n = osmInt(w.osm_scale);
    w.diff = diffClass(w.scale, w.osm_n); w.diff_auto = diffClass(w.level, w.osm_n);
    TRAILS.segments.filter(t => t.way === w.way).forEach(t => {
      t.osm_scale = w.osm_scale; t.diff = diffClass(t.scale, w.osm_n); t.diff_auto = diffClass(t.level, w.osm_n);
    });
  });
  return changed;
}
function osmInt(v) { const m = v == null ? null : /^\s*(\d+)[+-]?\s*$/.exec(v); return m ? Number(m[1]) : null; }
function diffClass(mine, o) { return mine == null ? null : o == null ? 'missing' : mine === o ? 'equal' : o > mine ? 'osm_higher' : 'osm_lower'; }

// ---- Comparison with OSM ----
if (TRAILS && TRAILS.ways.length) (async () => {
  const segById = Object.fromEntries(TRAILS.segments.map(t => [t.id, t]));
  const ways = TRAILS.ways;   // in the order they were ridden
  let fresh;
  try {
    const n = await refreshOsm(ways);
    fresh = `The OSM values were fetched directly from OSM at ${new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}` +
      (n ? `, ${n} have changed since the map was generated` : '') + '. ';
    if (n) {
      document.querySelectorAll('#trailrows tr[data-id]').forEach(tr => { tr.lastElementChild.textContent = segById[tr.dataset.id].osm_scale ?? '–'; });
      if (mode === 'osm') { styleTrails(); drawProfile(); }
    }
  } catch (e) { fresh = `<span class="err">Could not fetch current values from OSM (${e.message}), the table shows the state when the map was generated.</span> `; }
  const valCell = (v, cls, m) => v == null ? '–' : `<span class="nw"><span class="key"><span class="sw ${cls}${v}"></span>${v}</span>` + (m ? ` <span class="dim">(${m} m)</span>` : '') + '</span>';
  const cnt = {}; ways.forEach(w => { cnt[w.diff] = (cnt[w.diff] || 0) + 1; });
  document.getElementById('osmsum').innerHTML = fresh + `${ways.length} ridden ways in riding order: ` +
    Object.keys(DIFFN).map(k => `${cnt[k] || 0} ${DIFFN[k]}`).join(', ') + `. ${ways.filter(w => w.split).length} should be split. ` +
    `<a href="#" id="partsall">show all parts</a> · <a href="#" id="partsnone">hide all parts</a>`;
  document.getElementById('osmrows').innerHTML = ways.map(w => {
    const parts = w.parts.map(id => segById[id]).filter(Boolean);
    const open = w.split || parts.some(t => t.diff !== w.diff);   // parts with a difference are shown from the start
    const tg = parts.length > 1 ? `<button type="button" class="tg" aria-expanded="${open}" aria-label="show or hide parts">${open ? '▾' : '▸'}</button>` : '<span class="tg"></span>';
    return `<tr id="way${w.way}" data-way="${w.way}"><td>${tg}<a href="https://www.openstreetmap.org/way/${w.way}" target="_blank" rel="noopener">${w.way}</a></td>` +
      `<td>${trailName(w)}</td><td>${fmtLen(w.covered_m)}</td><td>${w.osm_scale ?? '–'}</td>` +
      `<td>${valCell(w.scale, 'sc', w.scale_m)}</td><td>${valCell(w.level, 'lv', w.level_m)}</td>` +
      `<td>${diffCell(w.diff)}${w.split ? ' · <b>split</b>' : ''}</td><td class="dim">${osmTags(w) || '–'}</td><td class="write">${writeCell(w)}</td></tr>` +
      (parts.length > 1 ? parts.map(t => `<tr class="part" data-way="${w.way}" data-id="${t.id}"${open ? '' : ' hidden'}><td>part ${t.id}</td><td></td><td>${fmtLen(t.covered_m)}</td><td></td>` +
        `<td>${valCell(t.scale, 'sc', t.scale_m)}</td><td>${valCell(t.level, 'lv', t.level_m)}</td><td>${diffCell(t.diff)}</td><td></td><td></td></tr>`).join('') : '');
  }).join('');
  initOsmWrite(ways);
  function setParts(way, open) {
    document.querySelectorAll(`#osmrows tr.part[data-way="${way}"]`).forEach(r => { r.hidden = !open; });
    const b = document.querySelector(`#way${way} .tg`); if (b && b.tagName === 'BUTTON') { b.setAttribute('aria-expanded', open); b.textContent = open ? '▾' : '▸'; }
  }
  document.querySelectorAll('#osmrows button.tg').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation(); setParts(b.closest('tr').dataset.way, b.getAttribute('aria-expanded') !== 'true');
  }));
  document.getElementById('partsall').addEventListener('click', e => { e.preventDefault(); ways.forEach(w => setParts(w.way, true)); });
  document.getElementById('partsnone').addEventListener('click', e => { e.preventDefault(); ways.forEach(w => setParts(w.way, false)); });
  document.querySelectorAll('#osmrows tr').forEach(tr => {
    const ids = () => tr.dataset.id ? [tr.dataset.id] : TRAILS.ways.find(w => w.way == tr.dataset.way).parts;
    tr.addEventListener('click', e => { if (e.target.classList.contains('tg')) e.stopImmediatePropagation(); }, true);
    tr.addEventListener('mouseenter', () => hlTrailMap(ids(), true));
    tr.addEventListener('mouseleave', () => hlTrailMap(ids(), false));
    tr.addEventListener('click', e => {
      if (e.target.tagName === 'A') return;
      if (mode !== 'osm') setMode('osm');
      const b = L.latLngBounds([]); ids().forEach(id => { if (trailGroups[id]) b.extend(trailGroups[id].getBounds()); });
      if (b.isValid()) map.fitBounds(b.pad(0.6), { maxZoom: 19 });
    });
  });
})(); else document.getElementById('osmsec').remove();

// ---- Trail segment table ----
if (TRAILS && TRAILS.segments.length) {
  const cell = (v, cls, m) => v == null ? '–' : `<span class="key"><span class="sw ${cls}${v}"></span>${AUTO && cls === 'lv' ? AUTO.levels[v] : v}</span> <span class="dim">(${m} m)</span>`;
  document.getElementById('trailrows').innerHTML = TRAILS.segments.map(t =>
    `<tr id="trail${t.id}" data-id="${t.id}"><td>${t.id}</td><td>${trailName(t)}</td>` +
    `<td>${t.way ? `<a href="https://www.openstreetmap.org/way/${t.way}" target="_blank" rel="noopener">${t.way}</a>` : '–'}</td>` +
    `<td>${fmtLen(t.length_m)}</td><td>${fmtLen(t.covered_m)}${t.passes > 1 ? ' · ' + t.passes + ' passes' : ''}</td>` +
    `<td>${cell(t.scale, 'sc', t.scale_m)}</td><td>${cell(t.level, 'lv', t.level_m)}</td><td>${t.osm_scale ?? '–'}</td></tr>`).join('');
  document.querySelectorAll('#trailrows tr').forEach(tr => {
    const g = trailGroups[tr.dataset.id];
    tr.addEventListener('mouseenter', () => { tr.classList.add('hl'); hlTrailMap([tr.dataset.id], true); });
    tr.addEventListener('mouseleave', () => { tr.classList.remove('hl'); hlTrailMap([tr.dataset.id], false); });
    tr.addEventListener('click', e => {
      if (e.target.tagName === 'A') return;
      if (!trailsOn) setTrails(true);
      map.fitBounds(g.getBounds().pad(0.6), { maxZoom: 19 });
    });
  });
} else document.getElementById('trailsec').remove();

// ---- Elevation profile (SVG) ----
if (!PROF.length) document.getElementById('profsec').remove();
const box = document.getElementById('prof'), svg = box && box.querySelector('svg'), tipEl = box && box.querySelector('.tip');
const cursor = L.circleMarker([0, 0], { radius: 7, color: '#fff', weight: 3, fillColor: '#0b0b0b', fillOpacity: 1, interactive: false });
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
let geo = null;

function niceStep(range, target) {
  const raw = range / target, p = Math.pow(10, Math.floor(Math.log10(raw)));
  return [1, 2, 5, 10].map(m => m * p).find(s => s >= raw);
}
function drawProfile() {
  if (!PROF.length) return;
  const W = box.clientWidth, H = 220, m = { l: 42, r: 14, t: 14, b: 26 };
  svg.innerHTML = ''; svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const dMax = PROF[PROF.length - 1][0];
  let aMin = Math.min(...PROF.map(p => p[1])), aMax = Math.max(...PROF.map(p => p[1]));
  const yStep = niceStep(aMax - aMin || 1, 4);
  aMin = Math.floor(aMin / yStep) * yStep; aMax = Math.ceil(aMax / yStep) * yStep;
  const x = d => m.l + (W - m.l - m.r) * d / dMax, y = a => m.t + (H - m.t - m.b) * (aMax - a) / (aMax - aMin);
  geo = { x, m, W, H, dMax };
  // grid and axes, recessive
  for (let a = aMin; a <= aMax + 1e-9; a += yStep) {
    el('line', { x1: m.l, x2: W - m.r, y1: y(a), y2: y(a), stroke: '#e1e0d9', 'stroke-width': 1 }, svg);
    el('text', { x: m.l - 6, y: y(a) + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#898781' }, svg).textContent = a + ' m';
  }
  const xStep = niceStep(dMax / 1000, Math.max(3, Math.floor(W / 110)));
  for (let k = 0; k <= dMax / 1000 + 1e-9; k += xStep)
    el('text', { x: x(k * 1000), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: '#898781' }, svg).textContent =
      (+k.toFixed(2)).toString() + ' km';
  // steep slopes as bands behind the curve
  HILLS.forEach(h => {
    el('rect', { id: 'band' + h.id, x: x(h.start_d), y: m.t, width: Math.max(2, x(h.end_d) - x(h.start_d)), height: H - m.t - m.b,
                 fill: HILLC[h.dir], 'fill-opacity': .14 }, svg);
  });
  // area + line coloured by mtb:scale
  el('path', { d: `M${x(0)},${y(aMin)} ` + PROF.map(p => `L${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ') +
               ` L${x(dMax)},${y(aMin)} Z`, fill: '#e1e0d9', 'fill-opacity': .55 }, svg);
  // long climbs: thin bar at the bottom of the plot area
  if (AUTO) AUTO.climbs.forEach(c => {
    el('rect', { x: x(c.start_d), y: H - m.b - 5, width: x(c.end_d) - x(c.start_d), height: 5, rx: 2, fill: '#52514e' }, svg);
    el('text', { x: x(c.start_d) + 3, y: H - m.b - 8, 'font-size': 10, 'font-weight': 700, fill: '#52514e' }, svg).textContent = 'L' + c.id;
  });
  let run = [PROF[0]];
  const flush = c => el('polyline', { points: run.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' '),
    fill: 'none', stroke: c, 'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
  for (let i = 1; i < PROF.length; i++) {
    run.push(PROF[i]);
    if (colorAt(i) !== colorAt(i - 1) || i === PROF.length - 1) { flush(colorAt(i - 1)); run = [PROF[i]]; }
  }
  // crosshair
  geo.cross = el('line', { y1: m.t, y2: H - m.b, stroke: '#0b0b0b', 'stroke-width': 1, visibility: 'hidden' }, svg);
  geo.dot = el('circle', { r: 4.5, fill: '#0b0b0b', stroke: '#fff', 'stroke-width': 2, visibility: 'hidden' }, svg);
  geo.y = y;
}
function secAt(i) { return AUTO && AUTO.sections[Math.min(Math.floor(i / PER), AUTO.sections.length - 1)]; }
function trailAt(i) { return (trailsOn || mode === 'osm') && TRAILS && TRAILS.match[i] >= 0 ? TRAILS.segments[TRAILS.match[i]] : null; }
function colorAt(i) {
  const t = trailAt(i); if (t) return trailColor(t);
  return mode === 'auto' ? LVLC[secAt(i).level] : (RAMP[PROF[i][5]] || '#52514e');
}
function showAt(i) {
  const p = PROF[i], px = geo.x(p[0]);
  geo.cross.setAttribute('x1', px); geo.cross.setAttribute('x2', px); geo.cross.setAttribute('visibility', 'visible');
  geo.dot.setAttribute('cx', px); geo.dot.setAttribute('cy', geo.y(p[1])); geo.dot.setAttribute('visibility', 'visible');
  const hill = HILLS.find(h => p[0] >= h.start_d && p[0] <= h.end_d);
  tipEl.innerHTML = `<b>${(p[0] / 1000).toFixed(2)} km</b> · <b>${p[1].toFixed(1)} m</b><br>` +
    `grade <b>${fmtPct(p[2])}</b>` + (p[5] != null ? ` · mtb:scale <b>${p[5]}</b>` : '') +
    (p[7] != null ? ` · <b>${p[7].toFixed(0)} km/h</b>` : '') +
    (hill ? `<br>${arrow(hill)} steep ${hill.dir}hill, max ${fmtPct(hill.max)}` : '') +
    (trailAt(i) ? `<br>trail segment ${trailAt(i).id}: ${trailName(trailAt(i))} · ${mode === 'osm' ? (DIFFN[trailAt(i).diff] || 'outside OSM') + ' (OSM ' + (trailAt(i).osm_scale ?? '–') + ', yours ' + (trailAt(i).scale ?? '–') + ')' : mode === 'auto' ? AUTO.levels[trailAt(i).level] ?? '–' : 'mtb:scale ' + (trailAt(i).scale ?? '–')}` : '') +
    (AUTO ? `<br><span class="lvl"><span class="dot lv${secAt(i).level}"></span>${AUTO.levels[secAt(i).level]}</span>` +
            (secAt(i).why.length ? ` <span class="why">(${secAt(i).why.join(', ')})</span>` : '') : '');
  tipEl.style.display = 'block';
  const tw = tipEl.offsetWidth;
  tipEl.style.left = Math.min(Math.max(0, px + 12 + tw > geo.W ? px - tw - 12 : px + 12), geo.W - tw) + 'px';
  tipEl.style.top = '8px';
  cursor.setLatLng([p[3], p[4]]).addTo(map);
}
function hideCursor() {
  if (!geo) return;
  geo.cross.setAttribute('visibility', 'hidden'); geo.dot.setAttribute('visibility', 'hidden');
  tipEl.style.display = 'none'; cursor.remove();
}
if (PROF.length) {
  drawProfile();
  window.addEventListener('resize', drawProfile);
  box.addEventListener('pointermove', e => {
    const r = box.getBoundingClientRect(), d = (e.clientX - r.left - geo.m.l) / (geo.W - geo.m.l - geo.m.r) * geo.dMax;
    showAt(Math.max(0, Math.min(PROF.length - 1, Math.round(d / STEP))));
  });
  box.addEventListener('pointerleave', hideCursor);
  box.addEventListener('click', e => { if (cursor._map) map.panTo(cursor.getLatLng()); });
}
const flags = new Set(location.hash.slice(1).split(','));
setMode(flags.has('osm') && TRAILS && TRAILS.ways.length ? 'osm' : AUTO && !flags.has('manual') ? 'auto' : 'manual');
if (TRAILS && flags.has('trails')) setTrails(true);
// the tables' header rows stick right below the sticky map
const stickEl = document.querySelector('.stick');
const setStickH = () => document.documentElement.style.setProperty('--stickh', stickEl.offsetHeight + 'px');
setStickH(); new ResizeObserver(setStickH).observe(stickEl);
</script></body></html>
"""


LEAFLET_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/'
OSM_BASE = 'https://www.openstreetmap.org'
OSM_EDITABLE = ['path', 'track', 'footway', 'bridleway']   # way types where mtb:scale belongs
LEVEL_COLORS = ['#0ca30c', '#fab219', '#d03b3b']   # same as LVLC in the script
DIFF_COLORS = {'missing': '#898781', 'equal': '#0ca30c', 'osm_lower': '#2f6fdd', 'osm_higher': '#d03b3b', 'none': '#c9c8c1'}


def color_css():
    """Classes for the colours, so no style attributes are needed (CSP)."""
    out = []
    for i, c in enumerate(RAMP):
        out.append('  .sw.sc%d, .dot.sc%d { background:%s; } .seglabel.sc%d { border-color:%s; }' % (i, i, c, i, c))
    for i, c in enumerate(LEVEL_COLORS):
        out.append('  .sw.lv%d, .dot.lv%d { background:%s; }' % (i, i, c))
    for k, c in DIFF_COLORS.items():
        out.append('  .sw.df-%s, .dot.df-%s { background:%s; }' % (k, k, c))
    return '\n'.join(out)


def write_site(html, site, geojson_paths):
    """Directory for a web host: index.html without embedded css/js, style.css, app.js, leaflet/."""
    os.makedirs(site, exist_ok=True)
    a, rest = html.split('<style>\n', 1)
    css, rest = rest.split('</style>', 1)
    b, rest = rest.rsplit('<script>\n', 1)
    js, tail = rest.rsplit('</script>', 1)
    b0, rest2 = b.split('<script id="osmedit">', 1)
    osmedit, b1 = rest2.split('</script>', 1)
    # ?v=<content hash> so the browser does not show another ride's app.js from its cache
    v = lambda body: hashlib.sha1(body.encode()).hexdigest()[:10]
    b = b0 + '<script src="osmedit.js?v=%s"></script>' % v(osmedit) + b1
    page = (a + '<link rel="stylesheet" href="style.css?v=%s">' % v(css) + b + '<script src="app.js?v=%s"></script>' % v(js) + tail)
    page = page.replace('__LEAFLET_CSS__', 'leaflet/leaflet.css').replace('__LEAFLET_JS__', 'leaflet/leaflet.js')
    for fn, body in (('index.html', page), ('style.css', css), ('app.js', js), ('osmedit.js', osmedit)):
        with open(os.path.join(site, fn), 'w') as f:
            f.write(body)
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'leaflet')
    dst = os.path.join(site, 'leaflet')
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for g in geojson_paths:
        shutil.copy(g, site)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    args = sys.argv[1:]
    site = None
    if '--site' in args:
        i = args.index('--site'); site = args[i + 1]; del args[i:i + 2]
    mount = None
    if '--mount' in args:
        i = args.index('--mount'); mount = args[i + 1]; del args[i:i + 2]
        if mount not in trailanalysis.MOUNTS:
            sys.exit('--mount must be ' + ' or '.join(trailanalysis.MOUNTS))
    no_osm = '--no-osm' in args
    if no_osm:
        args.remove('--no-osm')
    osm_cfg = None
    if '--osm-client-id' in args:
        i = args.index('--osm-client-id'); osm_cfg = {'client_id': args[i + 1], 'base': OSM_BASE}; del args[i:i + 2]
    if '--osm-api' in args:
        i = args.index('--osm-api')
        if osm_cfg:
            osm_cfg['base'] = args[i + 1].rstrip('/')
        del args[i:i + 2]
    src = args[0]
    outdir = args[1] if len(args) > 1 else os.path.dirname(os.path.abspath(src))
    os.makedirs(outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(src))[0]
    rows = parse(src)
    segs = build_segments(rows)
    prof = build_profile(rows)
    hills = find_hills(prof)
    auto = trailanalysis.analyze(rows, prof, mount=mount) if prof else None
    trails = None
    if prof and not no_osm:
        try:
            trails = trailsegments.build(prof, auto, outdir, STEP_M)
        except Exception as e:  # noqa: BLE001 - network errors must not stop the map
            print('Skipping trail segments:', e, file=sys.stderr)
    geojsons = [os.path.join(outdir, name + '.geojson')]
    if trails:
        geojsons.append(os.path.join(outdir, name + '_trails.geojson'))
        with open(geojsons[1], 'w') as f:
            json.dump(trailsegments.to_geojson(trails, auto), f, indent=1)
    with open(os.path.join(outdir, name + '.geojson'), 'w') as f:
        json.dump(to_geojson(segs), f, indent=1)
    html = (HTML.replace('__TITLE__', name).replace('__SEGS__', json.dumps(segs))
                .replace('__RAMP__', json.dumps(RAMP)).replace('__PROF__', json.dumps(prof, separators=(',', ':')))
                .replace('__HILLS__', json.dumps(hills)).replace('__STEP__', str(STEP_M))
                .replace('__AUTO__', json.dumps(auto, separators=(',', ':')))
                .replace('__TRAILS__', json.dumps(trails, separators=(',', ':')))
                .replace('__MINRUN__', str(trailsegments.MIN_RUN_M)).replace('__MATCHM__', str(trailsegments.MATCH_M))
                .replace('__OSMCFG__', json.dumps(osm_cfg)).replace('__OSMEDITABLE__', json.dumps(OSM_EDITABLE))
                .replace('__OSMEDIT__', open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'osmedit.js')).read())
                .replace('__SECM__', str(trailanalysis.SECTION_M)).replace('__SMOOTHM__', str(trailanalysis.SECTION_M * trailanalysis.SMOOTH_N)).replace('__LONGGAIN__', str(trailanalysis.LONG_MIN_GAIN_M))
                .replace('__LONGLEN__', str(trailanalysis.LONG_MIN_LEN_M))
                .replace('__MINGRADE__', '%g' % MIN_GRADE).replace('__MINLEN__', str(MIN_LEN_M))
                .replace('__COLORCSS__', color_css()))
    with open(os.path.join(outdir, name + '.html'), 'w') as f:
        f.write(html.replace('__LEAFLET_CSS__', LEAFLET_CDN + 'leaflet.min.css')
                    .replace('__LEAFLET_JS__', LEAFLET_CDN + 'leaflet.min.js'))
    if site:
        write_site(html, site, geojsons)
    for s in segs:
        print('segment %d  mtb:scale=%s  %6.1f m  %3d s  %d points' % (
            s['id'], s['scale'], s['length_m'], s['end_ts'] - s['start_ts'], len(s['coords'])))
    for h in hills:
        print('slope %d  %shill  at %.2f km  %4d m  %+5.1f m  avg %+5.1f %%  max %+5.1f %%' % (
            h['id'], h['dir'], h['start_d'] / 1000, h['length_m'], h['dh'], h['avg'], h['max']))
    print('Wrote', os.path.join(outdir, name + '.html'))
    for g in geojsons:
        print('Wrote', g)
    if trails:
        segs_t = trails['segments']
        print('trail segments: %d ridden of %d in the OSM network (%d ways), %d outside the network' % (
            len(segs_t), trails['osm_segments'], trails['osm_ways'], sum(1 for t in segs_t if t['way'] is None)))
    if site:
        print('Wrote web directory', site)


if __name__ == '__main__':
    main()
