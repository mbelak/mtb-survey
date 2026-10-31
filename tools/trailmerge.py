#!/usr/bin/env python3
"""Combine several rides into one assessment per trail segment.

Each ride is analysed on its own (tools/trailanalysis.py) and matched to the same OSM trail network
(tools/trailsegments.py). Each time a ride covers a trail segment is a pass with its own level.
The passes are then combined per segment:

- Only sections with the watch on the handlebar count. The wrist is not repeatable between days.
- The level is meant for dry conditions, like mtb:scale in OSM. Passes from dry rides decide when
  there are any. A segment ridden only in the wet gets the wet passes' level and is marked "wet only".
- The level is the median of the passes' levels, weighted by the metres covered, see combine().

Usage:  python3 tools/trailmerge.py ride.fit[:dry|:wet] ... [--out dir] [--name name]

A ride without :dry or :wet counts as dry. Output in --out (default: the first ride's directory):
  <name>_merged.html           map of the combined levels
  <name>_merged_trails.geojson one feature per trail segment with the combined level and the passes
The OSM trail network is fetched from Overpass the first time and cached in --out.
"""
import json, os, re, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fitdump import parse
import fitmap
import trailanalysis
import trailsegments

CONDITIONS = ('dry', 'wet')
LEVELS = trailanalysis.LEVELS
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
# A ride counts as assessed with the buttons when at least this many metres have mtb_scale above 0.
# Short presses, such as a quick UP and DOWN to mark a lap, do not make it an assessment.
LABELLED_MIN_M = 250


def parse_arg(arg):
    """'ride.fit:wet' -> ('ride.fit', 'wet'). Without a suffix the ride counts as dry."""
    for c in CONDITIONS:
        if arg.endswith(':' + c):
            return arg[:-len(c) - 1], c
    return arg, 'dry'


def load_ride(path, conditions='dry', mount=None):
    rows = parse(path)
    prof = fitmap.build_profile(rows)
    auto = trailanalysis.analyze(rows, prof, mount=mount) if prof else None
    ts = next((m['ts'] for k, m, dev in rows if k == 'record' and m.get('ts') is not None), None)
    return {'name': os.path.splitext(os.path.basename(path))[0], 'conditions': conditions,
            'date': (FIT_EPOCH + timedelta(seconds=ts)).date().isoformat() if ts is not None else None,
            'prof': prof, 'auto': auto,
            'labelled': is_labelled(prof)}


def is_labelled(prof, step=fitmap.STEP_M):
    return sum(step for p in prof if p[5]) >= LABELLED_MIN_M


def fetch_network(rides, cache_dirs):
    """OSM ways around all rides. Fetched per ride, so the cache fitmap.py already wrote for a ride is
    reused, and combined by way id. Overpass returns whole ways, so the union is exact."""
    by_id = {}
    for r in rides:
        if not r['prof']:
            continue
        bbox = trailsegments.bbox_of(r['prof'])
        ways = next((trailsegments.cached_ways(bbox, d) for d in cache_dirs
                     if trailsegments.cached_ways(bbox, d) is not None), None)
        if ways is None:
            ways = trailsegments.fetch_ways(bbox, cache_dirs[0])
        for w in ways:
            by_id[w['id']] = w
    return [by_id[k] for k in sorted(by_id)]


def handlebar_only(secs):
    """Copy of the sections where the wrist sections have no level, so they do not count."""
    return [dict(s, level=s['level'] if s.get('mount', 'handlebar') == 'handlebar' else None) for s in secs]


def ride_passes(ride, segs, step=fitmap.STEP_M):
    """{OSM segment index: pass} for one ride. Stretches outside the OSM network are left out,
    since they cannot be matched between rides."""
    prof, auto = ride['prof'], ride['auto']
    if not prof or not auto:
        return {}
    m = trailsegments.match(prof, segs)
    secs = handlebar_only(auto['sections'])
    result, _ = trailsegments.aggregate(prof, m, segs, secs, auto['section_m'] // step, step)
    out = {}
    for s in result:
        if s['osm_seg'] is None:
            continue
        out[s['osm_seg']] = {'ride': ride['name'], 'date': ride['date'], 'conditions': ride['conditions'],
                             'level': s['level'] if any(v is not None for v, b, t in s['level_runs']) else None,
                             'scale': s['scale'] if ride['labelled'] else None,
                             'covered_m': s['covered_m']}
    return out


def weighted_median(values):
    """values: [(value, weight)]. The lower median when the weights split exactly in half."""
    values = sorted((v, w) for v, w in values if v is not None and w > 0)
    if not values:
        return None
    total, acc = sum(w for v, w in values), 0.0
    for v, w in values:
        acc += w
        if acc >= total / 2:
            return v


def combine(passes):
    """Combined level of one segment from its passes.

    Dry passes decide when there are any; otherwise the wet ones, and the result is marked wet only.
    The level is the median of the passes' levels weighted by covered metres. Taking the highest level
    seen on any pass, as within one ride, would make a segment harder the more often it is ridden.
    Your own assessment (mtb:scale from the buttons) is combined the same way, from labelled rides."""
    def pick(key):
        ps = [p for p in passes if p.get(key) is not None]
        dry = [p for p in ps if p['conditions'] == 'dry']
        use = dry or ps
        if not use:
            return None, None
        return weighted_median([(min(2, p[key]), p['covered_m']) for p in use]), ('dry' if dry else 'wet only')
    level, basis = pick('level')
    scale, scale_basis = pick('scale')
    lv = [p['level'] for p in passes if p.get('level') is not None]
    return {'level': level, 'basis': basis, 'scale': scale, 'scale_basis': scale_basis,
            'passes_dry': sum(1 for p in passes if p['conditions'] == 'dry' and p.get('level') is not None),
            'passes_wet': sum(1 for p in passes if p['conditions'] == 'wet' and p.get('level') is not None),
            'agree': (len(set(lv)) <= 1) if lv else None}


def merge(rides, cache_dirs):
    segs = trailsegments.split_ways(fetch_network(rides, cache_dirs))
    by_seg = {}
    for r in rides:
        for si, p in ride_passes(r, segs).items():
            by_seg.setdefault(si, []).append(p)
    out = []
    for si in sorted(by_seg):
        seg = segs[si]
        c = combine(by_seg[si])
        out.append(dict(c, id=len(out) + 1, way=seg['way'], highway=seg['highway'], name=seg['name'],
                        osm_scale=seg['osm_scale'], tags=seg['tags'], coords=seg['coords'],
                        length_m=seg['length_m'], passes=by_seg[si]))
    return out


def to_geojson(merged):
    feats = []
    for s in merged:
        props = {'segment': s['id'], 'auto_level': s['level'],
                 'auto': LEVELS[s['level']] if s['level'] is not None else None,
                 'basis': s['basis'], 'passes_dry': s['passes_dry'], 'passes_wet': s['passes_wet'],
                 'passes_agree': s['agree'], 'mtb:scale': s['scale'], 'scale_basis': s['scale_basis'],
                 'osm_way': s['way'], 'highway': s['highway'], 'name': s['name'], 'osm_mtb_scale': s['osm_scale'],
                 'length_m': s['length_m'],
                 'passes': [{k: p[k] for k in ('date', 'conditions', 'level', 'scale', 'covered_m')} for p in s['passes']]}
        for k, v in s['tags'].items():
            props['osm_' + k] = v
        feats.append({'type': 'Feature', 'properties': props,
                      'geometry': {'type': 'LineString', 'coordinates': [[c[1], c[0]] for c in s['coords']]}})
    return {'type': 'FeatureCollection', 'features': feats}


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MTB Survey – __TITLE__</title>
<link rel="stylesheet" href="__LEAFLET__leaflet.min.css">
<script src="__LEAFLET__leaflet.min.js"></script>
<style>
  :root { --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --hair:#e1e0d9; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--plane); color:var(--ink); font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
  .wrap { margin:0 auto; padding:16px 16px 32px; }
  h1 { font-size:20px; margin:0 0 2px; } .sub { color:var(--ink2); margin:0 0 12px; }
  h2 { font-size:15px; margin:22px 0 0; } .h2sub { font-weight:400; color:var(--ink2); }
  #map { height:min(60vh,640px); min-height:280px; border:1px solid var(--hair); border-radius:8px; background:#e9e8e2; }
  .legend { display:flex; flex-wrap:wrap; gap:6px 14px; margin:12px 0 4px; color:var(--ink2); }
  .key { display:inline-flex; align-items:center; gap:6px; }
  .sw { width:22px; height:6px; border-radius:3px; display:inline-block; outline:1px solid rgba(11,11,11,.18); }
  .sw.dash { background:repeating-linear-gradient(90deg, currentColor 0 6px, transparent 6px 10px); outline:0; }
  .lv0 { background:#0ca30c; color:#0ca30c; } .lv1 { background:#fab219; color:#fab219; } .lv2 { background:#d03b3b; color:#d03b3b; }
  .lvn { background:#c9c8c1; color:#c9c8c1; } .sw.dash.lv2 { background-color:transparent; }
  .tablewrap { overflow-x:auto; margin-top:12px; }
  table { border-collapse:collapse; width:100%; min-width:640px; background:var(--surface); border:1px solid var(--hair); border-radius:8px; }
  th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--hair); font-variant-numeric:tabular-nums; }
  th { color:var(--ink2); font-weight:600; font-size:12px; } tr:last-child td { border-bottom:0; }
  tbody tr.click { cursor:pointer; } tbody tr.click:hover, tbody tr.hl { background:#f0efec; }
  .dot { width:10px; height:10px; border-radius:50%; display:inline-block; outline:1px solid rgba(11,11,11,.18); }
  .note { color:var(--muted); font-size:12px; margin-top:10px; }
  .dim { color:var(--ink2); }
</style></head><body><div class="wrap">
<h1>MTB Survey – __TITLE__</h1>
<p class="sub" id="sub"></p>
<div id="map" role="img" aria-label="Map of the ridden trail segments, coloured by the combined level. The same data is in the table below."></div>
<div class="legend" id="legend"></div>
<h2>Rides</h2>
<div class="tablewrap"><table><thead><tr><th>Ride</th><th>Date</th><th>Conditions</th><th>Handlebar</th><th>Wrist (not used)</th><th>Your assessment</th><th>Road speed</th></tr></thead><tbody id="rides"></tbody></table></div>
<h2>Trail segments <span class="h2sub">(between two junctions in OSM; the level is the median over the passes, weighted by metres, dry passes first)</span></h2>
<div class="tablewrap"><table><thead><tr><th>#</th><th>Trail</th><th>Length</th><th>Level</th><th>Basis</th><th>Passes</th><th>Levels per pass</th><th>Yours</th><th>OSM mtb:scale</th></tr></thead><tbody id="segs"></tbody></table></div>
<p class="note">Only sections with the watch on the handlebar count. The level is meant for dry conditions: dry passes decide when there are any, and a segment ridden only in the wet is dashed. Clicking a row shows the segment on the map. Map tiles © OpenStreetMap contributors. The page contains your GPS positions.</p>
</div>
<script>
const SEGS = __SEGS__, RIDES = __RIDES__, LEVELS = __LEVELS__;
const LVLC = ['#0ca30c', '#fab219', '#d03b3b'], NONE = '#c9c8c1';
const fmtLen = m => m >= 1000 ? (m / 1000).toFixed(2) + ' km' : m.toFixed(0) + ' m';
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const lvName = L => L == null ? '–' : LEVELS[L];
const trail = s => esc(s.name || s.highway || 'unnamed');
const map = L.map('map', { maxZoom: 22 });
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxNativeZoom: 19, maxZoom: 22, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);
const layers = {}, all = L.featureGroup().addTo(map);
SEGS.forEach(s => {
  const color = s.level == null ? NONE : LVLC[s.level], wet = s.basis === 'wet only';
  const tip = `<b>${trail(s)}</b> · ${fmtLen(s.length_m)}<br>${lvName(s.level)}${wet ? ' (wet only)' : ''}` +
    `<br>${s.passes_dry} dry, ${s.passes_wet} wet pass${s.passes_dry + s.passes_wet === 1 ? '' : 'es'}: ` +
    s.passes.map(p => `${p.date} ${p.conditions} ${p.level ?? '–'}`).join(', ') +
    (s.scale != null ? `<br>yours ${s.scale}` : '') + (s.osm_scale != null ? ` · OSM ${esc(s.osm_scale)}` : '');
  const g = L.featureGroup().addTo(all);
  L.polyline(s.coords, { color: '#fff', weight: 9, opacity: .95, interactive: false }).addTo(g);
  const line = L.polyline(s.coords, { color, weight: 5, dashArray: wet ? '6 6' : null }).addTo(g);
  L.polyline(s.coords, { weight: 20, opacity: 0 }).addTo(g).bindTooltip(tip, { sticky: true });
  g.on('mouseover', () => { line.setStyle({ weight: 8 }); hl(s.id, true); });
  g.on('mouseout', () => { line.setStyle({ weight: 5 }); hl(s.id, false); });
  layers[s.id] = g;
});
if (SEGS.length) map.fitBounds(all.getBounds().pad(0.05)); else map.setView([0, 0], 2);
function hl(id, on) { const r = document.getElementById('s' + id); if (r) r.classList.toggle('hl', on); }
const tot = SEGS.reduce((a, s) => a + s.length_m, 0);
document.getElementById('sub').textContent = `${RIDES.length} rides · ${SEGS.length} trail segments · ${fmtLen(tot)} · point at a line for details`;
document.getElementById('legend').innerHTML = LEVELS.map((n, L) => {
  const m = SEGS.filter(s => s.level === L).reduce((a, s) => a + s.length_m, 0);
  return `<span class="key"><span class="sw lv${L}"></span>${n} ${tot ? (100 * m / tot).toFixed(0) : 0} %</span>`;
}).join('') + '<span class="key"><span class="sw dash lv2"></span>wet only</span>' +
  `<span class="key"><span class="sw lvn"></span>no handlebar data ${tot ? (100 * SEGS.filter(s => s.level == null).reduce((a, s) => a + s.length_m, 0) / tot).toFixed(0) : 0} %</span>`;
document.getElementById('rides').innerHTML = RIDES.map(r =>
  `<tr><td>${esc(r.name)}</td><td>${r.date || '–'}</td><td>${r.conditions}</td><td>${fmtLen(r.handlebar_m)}</td>` +
  `<td>${r.wrist_m ? fmtLen(r.wrist_m) : '–'}</td><td>${r.labelled ? 'yes' : 'no'}</td><td>${r.v_road} km/h</td></tr>`).join('');
document.getElementById('segs').innerHTML = SEGS.map(s =>
  `<tr id="s${s.id}" class="click" data-id="${s.id}"><td>${s.id}</td><td>${trail(s)}</td><td>${fmtLen(s.length_m)}</td>` +
  `<td>${s.level == null ? '–' : `<span class="key"><span class="dot lv${s.level}"></span>${lvName(s.level)}</span>`}</td>` +
  `<td>${s.basis || '–'}</td><td>${s.passes_dry} dry, ${s.passes_wet} wet</td>` +
  `<td class="dim">${s.passes.map(p => (p.level ?? '–') + (p.conditions === 'wet' ? 'w' : '')).join(' ')}${s.agree === false ? ' · differ' : ''}</td>` +
  `<td>${s.scale ?? '–'}</td><td>${s.osm_scale != null ? esc(s.osm_scale) : '–'}</td></tr>`).join('');
document.querySelectorAll('#segs tr[data-id]').forEach(tr => {
  tr.addEventListener('click', () => map.fitBounds(layers[tr.dataset.id].getBounds().pad(0.6), { maxZoom: 19 }));
  tr.addEventListener('mouseenter', () => hl(tr.dataset.id, true));
  tr.addEventListener('mouseleave', () => hl(tr.dataset.id, false));
});
</script></body></html>
"""


def render(title, merged, summary):
    """The map page. All placeholders are replaced in one pass, so text from OSM or a file name can never
    be taken for a placeholder, and the data is escaped for the <script> element (fitmap.js_json)."""
    esc = lambda t: t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    vals = {'TITLE': esc(title), 'LEAFLET': fitmap.LEAFLET_CDN, 'SEGS': fitmap.js_json(merged),
            'RIDES': fitmap.js_json(summary), 'LEVELS': fitmap.js_json(LEVELS)}
    return re.sub(r'__(TITLE|LEAFLET|SEGS|RIDES|LEVELS)__', lambda m: vals[m.group(1)], HTML)


def ride_summary(r):
    a = r['auto'] or {}
    mm = a.get('mount_m', {})
    return {'name': r['name'], 'date': r['date'], 'conditions': r['conditions'], 'labelled': r['labelled'],
            'handlebar_m': mm.get('handlebar', 0), 'wrist_m': mm.get('wrist', 0), 'v_road': a.get('v_road')}


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    out = name = None
    if '--out' in args:
        i = args.index('--out'); out = args[i + 1]; del args[i:i + 2]
    if '--name' in args:
        i = args.index('--name'); name = args[i + 1]; del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    files = [parse_arg(a) for a in args]
    out = out or os.path.dirname(os.path.abspath(files[0][0]))
    os.makedirs(out, exist_ok=True)
    rides = [load_ride(p, c) for p, c in files]
    name = name or rides[0]['name']
    # the caches fitmap.py wrote next to each ride are reused
    cache_dirs = [out] + sorted({os.path.dirname(os.path.abspath(p)) for p, c in files} - {out})
    merged = merge(rides, cache_dirs)
    summary = [ride_summary(r) for r in rides]
    gj = os.path.join(out, name + '_merged_trails.geojson')
    with open(gj, 'w') as f:
        json.dump(to_geojson(merged), f, indent=1)
    page = render(name + ' and %d more' % (len(rides) - 1) if len(rides) > 1 else name, merged, summary)
    html = os.path.join(out, name + '_merged.html')
    with open(html, 'w') as f:
        f.write(page)
    for r in summary:
        print('%s  %s  %-3s  handlebar %.1f km%s%s' % (
            r['name'], r['date'], r['conditions'], r['handlebar_m'] / 1000,
            ', wrist %.1f km not used' % (r['wrist_m'] / 1000) if r['wrist_m'] else '',
            ', labelled' if r['labelled'] else ''))
    total = sum(s['length_m'] for s in merged)
    for L, n in enumerate(LEVELS):
        m = sum(s['length_m'] for s in merged if s['level'] == L)
        print('%-17s %6.0f m  %3.0f %%' % (n, m, 100 * m / total if total else 0))
    multi = [s for s in merged if s['passes_dry'] + s['passes_wet'] > 1]
    print('%d trail segments, %d ridden more than once (passes agree on %d), %d wet only' % (
        len(merged), len(multi), sum(1 for s in multi if s['agree']), sum(1 for s in merged if s['basis'] == 'wet only')))
    print('Wrote', html)
    print('Wrote', gj)


if __name__ == '__main__':
    main()
