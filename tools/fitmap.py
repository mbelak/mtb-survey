#!/usr/bin/env python3
"""Gör en färgkodad karta av en FIT-fil från MTB Survey.

Spåret delas i segment där mtb_scale är konstant. Resultat:
  <namn>.html     fristående Leaflet-karta (kräver internet för kartbilderna)
  <namn>.geojson  ett LineString per segment med egenskapen "mtb:scale" (för JOSM/QGIS)
  <namn>_stigsegment.geojson  ett objekt per stig mellan två korsningar (OSM-way-del), med
                  det sammanvägda värdet. Kräver internet (Overpass) första gången, se trailsegments.py.

Användning:  python3 tools/fitmap.py aktivitet.fit [utmapp] [--site mapp] [--no-osm] [--mount arm|styre]

--no-osm hoppar över stigsegmenten (ingen Overpass-fråga).
--mount arm|styre   anger var klockan satt för hela passet. Utan flaggan avgörs det från pulsen.
--osm-client-id ID  slår på skrivning av mtb:scale till OSM från kartsidan (OAuth 2, PKCE).
--osm-api URL       OSM-server för inloggning och skrivning, standard https://www.openstreetmap.org.
                    Testservern är https://master.apis.dev.openstreetmap.org (egen app-registrering).

--site skriver dessutom en mapp för webbhotell: index.html, style.css, app.js
och leaflet/ lokalt. Ingen css eller js ligger inbäddad i html-filen och inga
style-attribut används, så sidan fungerar under en strikt Content Security
Policy (style-src 'self'; script-src 'self').
"""
import hashlib, json, math, os, shutil, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fitdump import parse
import trailanalysis
import trailsegments

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
# Ordinal ramp, ljus -> mörk, validerad med dataviz-skillens validate_palette.js --ordinal
RAMP = ['#f0a30a', '#e8601c', '#d42a4f', '#a21d86', '#6a1f9c', '#33257a', '#130d2b']


def dist_m(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def build_segments(rows):
    """Segment = följd av records med samma mtb_scale. Bryts även vid paus."""
    segs, cur, broken = [], None, True
    for kind, m, dev in rows:
        if kind == 'event' and m.get('event') == 0 and m.get('type') in (1, 4):
            broken = True               # timer stop: dra ingen linje över pausen
            continue
        if kind != 'record' or m['lat'] is None or m['lon'] is None:
            continue
        scale = dev.get('mtb_scale')
        if scale is None:
            broken = True
            continue
        pt = (m['lat'], m['lon'], m['ts'])
        if cur is not None and not broken and scale != cur['scale']:
            # Värdet byttes mellan två records. Sträckan fram till den nya punkten
            # hör till det gamla värdet, så linjerna hänger ihop utan glapp.
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


STEP_M = 5          # profilen samplas om var 5:e meter längs spåret
MIN_GRADE = 8.0     # procent; brantare än så räknas som brant backe
MIN_LEN_M = 20      # kortare branta partier än så ignoreras
MIN_DH_M = 3        # ... liksom de med mindre höjdskillnad


def build_profile(rows):
    """Höjd mot sträcka, omsamplad till STEP_M. Varje punkt:
    [d, alt, lutning %, lat, lon, scale, ts, fart km/h, roughness, steer, kadens]
    (index 6- används av trailanalysis; kartsidan läser bara 0-5)."""
    recs, d_calc, prev = [], 0.0, None
    for kind, m, dev in rows:
        if kind != 'record' or m['lat'] is None or m.get('alt') is None:
            continue
        if prev is not None:
            d_calc += dist_m(prev, (m['lat'], m['lon']))
        prev = (m['lat'], m['lon'])
        d = m['dist'] if m.get('dist') is not None else d_calc
        if recs and d <= recs[-1][0]:
            continue                    # stillastående: samma sträcka, hoppa över
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
    n, k = len(grid), 2                 # glidande medel ±2 sampel (~25 m) mot brus
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
    """Sammanhängande partier där lutningen är minst MIN_GRADE i samma riktning."""
    sign = [(1 if p[2] >= MIN_GRADE else -1 if p[2] <= -MIN_GRADE else 0) for p in prof]
    runs = []
    for i, s in enumerate(sign):
        if s == 0:
            continue
        if runs and runs[-1][0] == s and i - runs[-1][2] <= 3:   # glapp ≤ 10 m slås ihop
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
        hills.append({'id': len(hills) + 1, 'dir': 'upp' if s > 0 else 'ned',
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
<html lang="sv"><head><meta charset="utf-8">
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
  /* Rubrikraden ligger fast under kartan. Det kräver att omslaget inte scrollar i sidled,
     så på smala skärmar behålls sidscrollen i stället. */
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
<div id="map" role="img" aria-label="Karta över spåret, färgkodat efter mtb:scale. Samma data finns i tabellen nedan."></div>
<div class="legend"><span class="mode" role="group" aria-label="Färglägg spåret efter">
  <button type="button" data-mode="auto" aria-pressed="true">Automatisk</button><button type="button" data-mode="manual" aria-pressed="false">Din bedömning</button><button type="button" data-mode="osm" aria-pressed="false">Mot OSM</button></span>
  <span id="legend" class="legend"></span></div>
</div>
<section id="profsec">
<h2>Höjdprofil</h2>
<div id="prof" role="img" aria-label="Höjdprofil mot sträcka. Linjen är färgad efter mtb:scale, grå band är branta backar. Samma backar finns i tabellen nedan."><svg></svg><div class="tip"></div></div>
<h2>Branta backar <span class="h2sub">(minst __MINGRADE__ % lutning över minst __MINLEN__ m)</span></h2>
<div class="tablewrap"><table><thead><tr><th></th><th>Riktning</th><th>Vid</th><th>Längd</th><th>Höjdskillnad</th><th>Snitt</th><th>Max</th><th>mtb:scale</th></tr></thead><tbody id="hills"></tbody></table></div>
</section>
<section id="autosec">
<h2>Automatisk bedömning <span class="h2sub">(sektioner om __SECM__ m, sensorvärden utjämnade över __SMOOTHM__ m, gränser kalibrerade 2026-09-30)</span></h2>
<div class="tablewrap"><table><thead><tr><th>Nivå</th><th>Längd</th><th>Andel</th><th>Vanligaste skäl</th></tr></thead><tbody id="autosum"></tbody></table></div>
<p class="note" id="mountnote"></p>
<h2>Långa backar <span class="h2sub">(sammanhängande stigning, minst __LONGGAIN__ m upp över minst __LONGLEN__ m)</span></h2>
<div class="tablewrap"><table><thead><tr><th>#</th><th>Vid</th><th>Längd</th><th>Stigning</th><th>Snitt</th></tr></thead><tbody id="climbs"></tbody></table></div>
<h2>Mätvärden per mtb:scale <span class="h2sub">(median per sektion, för att kalibrera gränserna)</span></h2>
<div class="tablewrap"><table><thead id="calhead"></thead><tbody id="cal"></tbody></table></div>
<p class="note">Stämmer mätvärdena med din bedömning ska de öka från rad till rad. Gränserna står i <code>LIMITS</code> och <code>MOUNT_LIMITS</code> i <code>tools/trailanalysis.py</code>.</p>
</section>
<section id="osmsec">
<h2>Jämförelse med OSM <span class="h2sub">(en rad per cyklad OSM-way, ditt sammanvägda värde mot taggen mtb:scale i OSM)</span></h2>
<p class="note" id="osmsum"></p>
<p class="note" id="osmauth"></p>
<div class="tablewrap"><table><thead><tr><th>OSM-way</th><th>Stig</th><th>Cyklat</th><th>OSM idag</th><th>Din</th><th>Automatisk</th><th>Avvikelse</th><th>Underlag i OSM</th><th>Skriv till OSM</th></tr></thead><tbody id="osmrows"></tbody></table></div>
<p class="note">Knapparna <i>0 1 2 3</i> skriver valt värde som <code>mtb:scale</code> på hela wayen i OSM, i ett eget changeset, efter inloggning och ett andra tryck för att bekräfta. Ditt eget värde har fet ram. Värdet som redan finns i OSM är mörkt ifyllt och går inte att välja. Har OSM ett annat värde, till exempel <code>2+</code>, står det före knapparna. Knapparna visas bara för stigar (path, track, footway, bridleway). Tagga inte en way som ska delas förrän den är delad. Avvikelsen jämför ditt värde med OSM siffra mot siffra. <b>Dela</b> betyder att delarna mellan korsningarna fått olika värden av dig, så wayen bör delas i OSM innan den taggas. Sådana ways visar sina delar som indragna rader. Klick på en rad visar wayen på kartan.</p>
</section>
<section id="trailsec">
<h2>Stigsegment <span class="h2sub">(hela stigen mellan två korsningar i OSM får det högsta värde som förekommer minst __MINRUN__ m i följd)</span></h2>
<div class="tablewrap"><table><thead><tr><th>#</th><th>Stig</th><th>OSM-way</th><th>Längd</th><th>Cyklat</th><th>Din</th><th>Automatisk</th><th>OSM idag</th></tr></thead><tbody id="trailrows"></tbody></table></div>
<p class="note">Din och Automatisk är segmentets sammanvägda värde, med de meter som motiverar det inom parentes. Kryssa i <i>stigsegment</i> ovanför kartan för att se dem. Rader utan OSM-way är partier där ingen väg fanns inom __MATCHM__ m.</p>
</section>
<h2>Segment</h2>
<div class="tablewrap"><table><thead><tr><th>#</th><th>mtb:scale</th><th>Längd</th><th>Tid</th><th>Start</th><th>Punkter</th></tr></thead><tbody id="rows"></tbody></table></div>
<h2>Summa per värde</h2>
<div class="tablewrap"><table><thead><tr><th>mtb:scale</th><th>Längd</th><th>Andel</th><th>Segment</th></tr></thead><tbody id="sum"></tbody></table></div>
<p class="note">Kartbilder © OpenStreetMap-bidragsgivare. Filen innehåller dina GPS-positioner, så dela den bara med dem som får se var du har varit.</p>
</div>
<script id="osmedit">
__OSMEDIT__
</script>
<script>
const SEGS = __SEGS__, RAMP = __RAMP__, EPOCH = Date.UTC(1989, 11, 31);
const PROF = __PROF__, HILLS = __HILLS__, STEP = __STEP__, AUTO = __AUTO__, TRAILS = __TRAILS__;
const OSMCFG = __OSMCFG__, OSM_EDITABLE = __OSMEDITABLE__;
let trailsOn = false;
const LVLC = ['#0ca30c', '#fab219', '#d03b3b'];   // dataviz-statuspalett: good / warning / critical, alltid med text
const PER = AUTO ? AUTO.section_m / STEP : 1;
let mode = 'manual';  // PROF: [d, höjd, lutning %, lat, lon, scale]
const fmtLen = m => m >= 1000 ? (m / 1000).toFixed(2) + ' km' : m.toFixed(0) + ' m';
const fmtDur = s => s >= 60 ? Math.floor(s / 60) + ' min ' + (s % 60) + ' s' : s + ' s';
const fmtTime = ts => new Date(EPOCH + ts * 1000).toLocaleTimeString('sv-SE');
const fmtDate = ts => new Date(EPOCH + ts * 1000).toLocaleDateString('sv-SE');

const map = L.map('map', { maxZoom: 22 });
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxNativeZoom: 19, maxZoom: 22, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);

// Branta backar: färgad halo under spåret, röd uppför och grön nedför, i en egen pane under linjerna
const HILLC = { upp: '#d03b3b', ned: '#0ca30c' };
map.createPane('hills').style.zIndex = 390;
const hillLayer = L.featureGroup().addTo(map), hillLayers = {};
const fmtPct = v => (v > 0 ? '+' : '') + v.toFixed(1).replace('.', ',') + ' %';
const arrow = h => h.dir === 'upp' ? '▲' : '▼';
HILLS.forEach(h => {
  const tip = `<b>${arrow(h)} ${h.dir}för</b><br>${fmtLen(h.length_m)} · ${h.dh > 0 ? '+' : ''}${h.dh.toFixed(1)} m<br>snitt ${fmtPct(h.avg)} · max ${fmtPct(h.max)}`;
  const g = L.featureGroup().addTo(hillLayer);
  L.polyline(h.coords, { pane: 'hills', color: HILLC[h.dir], weight: 20, opacity: .45, lineCap: 'round', lineJoin: 'round' })
    .addTo(g).bindTooltip(tip, { sticky: true });
  L.marker(h.coords[0], { icon: L.divIcon({ className: '', iconSize: null, iconAnchor: [-8, 22],
    html: `<div class="hilllabel ${h.dir === 'upp' ? 'up' : 'down'}">${arrow(h)} ${Math.abs(h.max).toFixed(0)} %</div>` }) }).addTo(g).bindTooltip(tip);
  g.on('mouseover', () => { hlHill(h.id, true); }); g.on('mouseout', () => { hlHill(h.id, false); });
  hillLayers[h.id] = g;
});

const layers = {}, all = [], manualLayer = L.featureGroup().addTo(map);
SEGS.forEach(s => {
  const color = RAMP[s.scale] || '#52514e';
  const tip = `<b>mtb:scale ${s.scale}</b><br>${fmtLen(s.length_m)} · ${fmtDur(s.end_ts - s.start_ts)}<br>${fmtTime(s.start_ts)}–${fmtTime(s.end_ts)}`;
  const g = L.featureGroup().addTo(manualLayer);
  if (s.coords.length > 1) {
    L.polyline(s.coords, { color: '#fff', weight: 9, opacity: .95, lineCap: 'round', lineJoin: 'round', interactive: false }).addTo(g); // vit kant
    const line = L.polyline(s.coords, { color, weight: 5, opacity: 1, lineCap: 'round', lineJoin: 'round' }).addTo(g);
    L.polyline(s.coords, { color, weight: 22, opacity: 0 }).addTo(g).bindTooltip(tip, { sticky: true });          // stor träffyta
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
  L.circleMarker(all[all.length - 1], { radius: 6, color: '#0b0b0b', weight: 2, fillColor: '#fff', fillOpacity: 1 }).addTo(map).bindTooltip('Slut');
} else { map.setView([62, 15], 5); }

// Automatiskt lager: en linje per sektion, färg efter nivå.
// s.level/s.why sätts från varianten utan (0) eller med (1) kurvighet.
const autoLayer = L.featureGroup();
function applyVariant(v) {
  AUTO.sections.forEach(s => { s.level = s.lv[v]; s.why = s.whys[v]; });
  AUTO.per_scale.forEach(p => { p.levels = p.levels_v[v]; });
}
function renderAutoLayer() {
autoLayer.clearLayers();
AUTO.sections.forEach(s => {
  const tip = `<b>${AUTO.levels[s.level]}</b> · ${(s.start_d / 1000).toFixed(2).replace('.', ',')} km` +
    (s.why.length ? `<br>${s.why.join(', ')}` : '') +
    (s.mount === 'arm' ? '<br><i>klockan på armen</i>' : '') +
    `<br><span class="dim">fart ${s.speed ?? '–'} km/h` + (s.v_rel != null ? ` (${Math.round(100 * s.v_rel)} % av vägfarten)` : '') + ` · max ${s.grade.toFixed(0)} % · kurv ${s.curv}°/100 m` +
    (s.roughness != null ? ` · skak ${s.roughness}` : '') + (s.steer != null ? ` · styr ${s.steer}` : '') +
    (s.scale != null ? ` · din: ${s.scale}` : '') + '</span>';
  s.tip = tip;
});
// alla vita kanter först, sedan färgerna, annars skär kanterna av grannsektionerna
AUTO.sections.forEach(s => L.polyline(s.coords, { color: '#fff', weight: 9, opacity: .95, lineCap: 'round', interactive: false }).addTo(autoLayer));
// sektioner mätta med klockan på armen streckas: osäkrare bedömning
AUTO.sections.forEach(s => L.polyline(s.coords, { color: LVLC[s.level], weight: 5, opacity: 1, lineCap: s.mount === 'arm' ? 'butt' : 'round',
  dashArray: s.mount === 'arm' ? '8 5' : null, interactive: false }).addTo(autoLayer));
AUTO.sections.forEach(s => L.polyline(s.coords, { weight: 22, opacity: 0 }).addTo(autoLayer).bindTooltip(s.tip, { sticky: true }));
}
if (AUTO) { applyVariant(AUTO.use_curv ? 1 : 0); renderAutoLayer(); }
// Stigsegment: hela OSM-segmentet mellan två korsningar, färgat efter sammanvägt värde
const trailLayer = L.featureGroup(), trailLabels = L.featureGroup(), trailLines = [], trailGroups = {}, trailLineById = {};
const trailVal = t => mode === 'auto' ? t.level : t.scale;
const DIFFC = { saknas: '#898781', lika: '#0ca30c', 'osm_lägre': '#2f6fdd', 'osm_högre': '#d03b3b' };
const DIFFN = { saknas: 'saknas i OSM', lika: 'lika', 'osm_lägre': 'OSM lägre än du', 'osm_högre': 'OSM högre än du' };
const dcls = d => 'df-' + (d ? d.replace('ä', 'a').replace('ö', 'o') : 'none');
const diffCell = d => d ? `<span class="key"><span class="sw ${dcls(d)}"></span>${DIFFN[d]}</span>` : '–';
const trailColor = t => {
  if (mode === 'osm') return DIFFC[t.diff] || '#c9c8c1';
  const v = trailVal(t); return v == null ? '#52514e' : (mode === 'auto' ? LVLC[v] : RAMP[v]); };
const osmTags = t => Object.entries(t.tags || {}).map(([k, v]) => `${k}=${v}`).join(' · ');
const trailName = t => t.name || (t.highway ? { path: 'stig', track: 'skogsväg', footway: 'gångväg', cycleway: 'cykelväg',
  service: 'serviceväg', residential: 'gata', unclassified: 'väg', steps: 'trappa' }[t.highway] || t.highway : 'utanför OSM-nätet');
function trailTip(t) {
  if (mode === 'osm') return `<b>${trailName(t)}</b>` + (t.way ? ` · way ${t.way}` : '') +
    `<br>${t.way ? (DIFFN[t.diff] || 'ingen egen bedömning') : 'utanför OSM-nätet'}` +
    `<br><span class="dim">OSM idag ${t.osm_scale ?? '–'} · din ${t.scale ?? '–'}` + (t.level != null ? ` · auto ${t.level}` : '') +
    (osmTags(t) ? `<br>${osmTags(t)}` : '') + '</span>';
  const v = trailVal(t), basis = mode === 'auto' ? t.level_m : t.scale_m;
  return `<b>${trailName(t)}</b>` + (t.way ? ` · way ${t.way}` : '') +
    `<br>${mode === 'auto' ? (v == null ? '–' : AUTO.levels[v]) : 'mtb:scale ' + (v ?? '–')}` +
    (v != null ? ` <span class="dim">(${basis} m i följd)</span>` : '') +
    `<br><span class="dim">${fmtLen(t.length_m)} stig · cyklat ${fmtLen(t.covered_m)}${t.passes > 1 ? ' i ' + t.passes + ' pass' : ''}` +
    (t.osm_scale != null ? ` · OSM idag ${t.osm_scale}` : '') + '</span>';
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
// Rader i OSM-tabellen som hör till segmentet: wayens rad och delens rad. Scrollar raden i sikte,
// kartan ligger fast så sidan under den får röra sig.
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
map.on('zoomend', () => { if (trailsOn) updateLayers(); });   // etiketterna bara inzoomat
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
    : '<b>mtb:scale</b><span>lättare</span>' +
      RAMP.map((c, i) => `<span class="key ${present.has(i) ? '' : 'absent'}"><span class="sw sc${i}"></span>${i}</span>`).join('') +
      '<span>svårare</span>';
}
drawLegend();
if (HILLS.length) document.querySelector('.legend').insertAdjacentHTML('beforeend',
  '<label class="toggle"><input type="checkbox" id="showhills" checked>branta backar <span class="halo up"></span>uppför <span class="halo down"></span>nedför (max lutning)</label>' +
  (TRAILS ? '<label class="toggle" id="trailwrap"><input type="checkbox" id="showtrails">stigsegment (hela stigen mellan två korsningar)</label>' : ''));
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
  ? `${fmtDate(SEGS[0].start_ts)} · ${fmtLen(total)}${PROF.length ? ' · ↑ ' + climb.toFixed(0) + ' m' : ''} · ${SEGS.length} segment · peka på en linje för detaljer`
  : 'Filen innehåller inga records med både position och mtb_scale.';

// ---- Branta backar: tabell ----
function hlHill(id, on) {
  const r = document.getElementById('hill' + id); if (r) r.classList.toggle('hl', on);
  const b = document.getElementById('band' + id); if (b) b.setAttribute('fill-opacity', on ? .3 : .14);
}
document.getElementById('hills').innerHTML = HILLS.length ? HILLS.map(h =>
  `<tr id="hill${h.id}" data-id="${h.id}"><td><span class="halo ${h.dir === 'upp' ? 'up' : 'down'}"></span></td><td>${arrow(h)} ${h.dir}för</td><td>${(h.start_d / 1000).toFixed(2).replace('.', ',')} km</td>` +
  `<td>${fmtLen(h.length_m)}</td><td>${h.dh > 0 ? '+' : ''}${h.dh.toFixed(1).replace('.', ',')} m</td><td>${fmtPct(h.avg)}</td><td>${fmtPct(h.max)}</td>` +
  `<td>${h.scale == null ? '–' : `<span class="key"><span class="sw sc${h.scale}"></span>${h.scale}</span>`}</td></tr>`).join('')
  : '<tr class="nohl"><td colspan="8">Inga partier brantare än gränsen.</td></tr>';
document.querySelectorAll('#hills tr[data-id]').forEach(tr => {
  tr.addEventListener('click', () => {
    if (cb && !cb.checked) { cb.checked = true; hillLayer.addTo(map); }
    map.fitBounds(hillLayers[tr.dataset.id].getBounds().pad(0.6), { maxZoom: 19 });
  });
  tr.addEventListener('mouseenter', () => hlHill(tr.dataset.id, true));
  tr.addEventListener('mouseleave', () => hlHill(tr.dataset.id, false));
});

// ---- Automatisk bedömning: tabeller ----
if (!AUTO) document.getElementById('autosec').remove();
else renderAutoTables();
function renderAutoTables() {
  const tot = AUTO.sections.reduce((a, s) => a + s.length_m, 0);
  const km = m => (m / 1000).toFixed(1).replace('.', ',') + ' km', mm = AUTO.mount_m || {};
  document.getElementById('mountnote').innerHTML =
    `Stig räknas från styrningen. Svår stig räknas från styrningen och farten relativt dagens vägfart, ` +
    `<b>${String(AUTO.v_road).replace('.', ',')} km/h</b> (lutningsjusterad fart på passets lugnaste delar). ` +
    (mm.arm ? `Klockan satt på armen ${km(mm.arm)}${AUTO.mount_forced ? ' (angivet)' : ', avgjort från pulsen'}; de delarna är streckade på kartan. ` +
      `På armen skiljer bara farten lätt stig från svår, och gränsen mellan väg och stig är preliminär.` :
      `Klockan satt på styret${AUTO.mount_forced ? ' (angivet)' : ''}.`);
  document.getElementById('autosum').innerHTML = AUTO.levels.map((n, L) => {
    const ss = AUTO.sections.filter(s => s.level === L), len = ss.reduce((a, s) => a + s.length_m, 0);
    const cnt = {}; ss.forEach(s => s.why.forEach(w => { const k = w.replace(/\s*[+-]?\d[\d.,]*\s*(%|m|s)?/g, '').trim(); cnt[k] = (cnt[k] || 0) + 1; }));
    const top = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 3).map(e => e[0]).join(', ');
    return `<tr class="nohl"><td><span class="lvl"><span class="dot lv${L}"></span>${n}</span></td>` +
           `<td>${fmtLen(len)}</td><td>${tot ? (100 * len / tot).toFixed(0) : 0} %</td><td class="why">${top || '–'}</td></tr>`; }).join('');
  document.getElementById('climbs').innerHTML = AUTO.climbs.length ? AUTO.climbs.map(c =>
    `<tr class="nohl"><td>L${c.id}</td><td>${(c.start_d / 1000).toFixed(2).replace('.', ',')} km</td><td>${fmtLen(c.length_m)}</td>` +
    `<td>+${c.gain.toFixed(1).replace('.', ',')} m</td><td>${c.avg.toFixed(1).replace('.', ',')} %</td></tr>`).join('')
    : '<tr class="nohl"><td colspan="5">Inga långa backar.</td></tr>';
  const cols = [['speed', 'Fart km/h'], ['cv', 'Ryckighet'], ['grade', 'Max lutning %'], ['curv', 'Kurvighet °/100 m'], ['stops_per_km', 'Stopp/km']]
    .concat(AUTO.has.roughness ? [['roughness', 'Skak mG']] : []).concat(AUTO.has.steer ? [['steer', 'Styr °/s']] : []);
  document.getElementById('calhead').innerHTML = '<tr><th>mtb:scale</th><th>Längd</th>' + cols.map(c => `<th>${c[1]}</th>`).join('') +
    '<th>Automatiskt: lätt / vana / svårt</th></tr>';
  document.getElementById('cal').innerHTML = AUTO.per_scale.map(p =>
    `<tr class="nohl"><td><span class="key"><span class="sw sc${p.scale}"></span>${p.scale}</span></td><td>${fmtLen(p.length_m)}</td>` +
    cols.map(c => `<td>${p[c[0]] ?? '–'}</td>`).join('') + `<td>${p.levels.join(' / ')} %</td></tr>`).join('');
}

// ---- Skrivning till OSM (OAuth 2 med PKCE, ett changeset per way) ----
// Värden att välja mellan. OSM:s skala går till 6, men 4-6 är extrem terräng.
const SCALE_CHOICES = [0, 1, 2, 3];
function writeCell(w) {
  if (!OSMCFG) return '';
  if (!OSM_EDITABLE.includes(w.highway)) return '<span class="dim">inte stig</span>';
  const other = w.osm_scale != null && !SCALE_CHOICES.some(v => w.osm_scale === String(v));
  return (other ? `<span class="osmnow">i OSM: ${w.osm_scale}</span>` : '') + '<span class="pick">' + SCALE_CHOICES.map(v => {
    const cur = w.osm_scale === String(v), mine = w.scale === v;
    const title = cur ? 'finns redan i OSM' : mine ? 'ditt värde' : `tagga mtb:scale=${v}`;
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
    if (!p || p.state !== q.get('state')) throw new Error('fel state i OAuth-svaret');
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
  /** Skriver key=value på wayen i ett eget changeset. expected = värdet tabellen tror finns i OSM (kontroll). */
  async tagWay(wayId, key, value, expected, comment) {
    const cur = await this.api('GET', 'way/' + wayId);
    const now = OsmEdit.getWayTag(cur, key);
    if ((now ?? null) !== (expected ?? null)) throw new Error(`OSM har ändrats: ${key} är nu ${now ?? 'saknas'}. Ladda om kartan innan du skriver.`);
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
  if (!OSMCFG) { box.innerHTML = 'Skrivning till OSM är avstängd. Generera kartan med <code>--osm-client-id</code> för att slå på den.'; return; }
  // OSM kräver en registrerad http(s)-adress att skicka tillbaka till. En lokal fil har ingen.
  if (location.protocol === 'file:') {
    box.innerHTML = 'Inloggning på OSM fungerar inte när kartan öppnas som lokal fil. Generera med <code>--site &lt;mapp&gt;</code>, kör ' +
      '<code>python3 -m http.server 8767 --bind 127.0.0.1</code> i mappen och öppna <code>http://127.0.0.1:8767/index.html</code> ' +
      '(adressen ska finnas bland redirect-adresserna i OAuth-appen).';
    return;
  }
  const buttons = () => document.querySelectorAll('#osmrows button.act');
  const render = () => {
    box.innerHTML = osm.user
      ? `Inloggad på ${OSMCFG.base.replace('https://', '')} som <b>${osm.user}</b>. <a href="#" id="osmlogout">Logga ut</a>`
      : `<button type="button" class="act" id="osmlogin">Logga in på OSM</button> <span class="dim">för att kunna tagga ways nedan · redirect-adress att registrera i OAuth-appen: <code>${osm.redirect()}</code></span>`;
    buttons().forEach(b => { b.disabled = !osm.user || b.classList.contains('cur'); });
    const lo = document.getElementById('osmlogout'); if (lo) lo.addEventListener('click', e => { e.preventDefault(); osm.logout(); render(); });
    const li = document.getElementById('osmlogin'); if (li) li.addEventListener('click', () => osm.login());
  };
  try {
    await osm.finishLogin();
    osm.token = sessionStorage.getItem('osm_token');
    if (osm.token) await osm.whoami();
  } catch (e) { osm.logout(); box.innerHTML = `<span class="err">Inloggning misslyckades: ${e.message}</span> `; }
  render();
  buttons().forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    const way = ways.find(w => w.way == b.dataset.way), td = b.closest('td'), v = Number(b.dataset.value);
    const reset = x => { x.classList.remove('confirm'); x.textContent = x.dataset.value; };
    if (!b.classList.contains('confirm')) {
      td.querySelectorAll('button.confirm').forEach(reset);   // bara ett värde i taget väntar på bekräftelse
      b.classList.add('confirm'); b.textContent = `Bekräfta mtb:scale=${v} på way ${way.way}`;
      setTimeout(() => { if (b.classList.contains('confirm')) reset(b); }, 8000);
      return;
    }
    td.querySelectorAll('button').forEach(x => { x.disabled = true; }); b.textContent = 'skriver…';
    try {
      const r = await osm.tagWay(way.way, 'mtb:scale', v, way.osm_scale, 'mtb:scale från fältkartering med cykel');
      way.osm_scale = String(v); way.osm_n = v; way.diff = diffClass(way.scale, v); way.diff_auto = diffClass(way.level, v);
      TRAILS.segments.filter(t => t.way === way.way).forEach(t => { t.osm_scale = String(v); t.diff = diffClass(t.scale, v); t.diff_auto = diffClass(t.level, v); });
      const tr = b.closest('tr'); tr.children[3].textContent = way.osm_scale; tr.children[6].innerHTML = diffCell(way.diff) + (way.split ? ' · <b>dela</b>' : '');
      td.innerHTML = `<span class="ok">skrivet mtb:scale=${v}</span> · <a href="${OSMCFG.base}/changeset/${r.changeset}" target="_blank" rel="noopener">changeset ${r.changeset}</a>`;
      if (mode === 'osm') { styleTrails(); drawProfile(); }
    } catch (err) {
      td.innerHTML = `<span class="err">${err.message}</span>`;
    }
  }));
}
/** Aktuellt mtb:scale för ways direkt från OSM:s API. Sidans värden kommer från Overpass när kartan
 *  genererades och är gamla så fort någon, till exempel du själv, har taggat. Returnerar antal ändrade. */
async function refreshOsm(ways) {
  const base = OSMCFG ? OSMCFG.base : 'https://www.openstreetmap.org', now = {};
  const ids = ways.map(w => w.way);
  for (let i = 0; i < ids.length; i += 200) {
    const r = await fetch(`${base}/api/0.6/ways.json?ways=${ids.slice(i, i + 200).join(',')}`);
    if (!r.ok) throw new Error('OSM svarade ' + r.status);
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
function diffClass(mine, o) { return mine == null ? null : o == null ? 'saknas' : mine === o ? 'lika' : o > mine ? 'osm_högre' : 'osm_lägre'; }

// ---- Jämförelse med OSM ----
if (TRAILS && TRAILS.ways.length) (async () => {
  const segById = Object.fromEntries(TRAILS.segments.map(t => [t.id, t]));
  const ways = TRAILS.ways;   // i den ordning de cyklades
  let fresh;
  try {
    const n = await refreshOsm(ways);
    fresh = `OSM-värdena är hämtade direkt från OSM ${new Date().toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' })}` +
      (n ? `, ${n} har ändrats sedan kartan genererades` : '') + '. ';
    if (n) {
      document.querySelectorAll('#trailrows tr[data-id]').forEach(tr => { tr.lastElementChild.textContent = segById[tr.dataset.id].osm_scale ?? '–'; });
      if (mode === 'osm') { styleTrails(); drawProfile(); }
    }
  } catch (e) { fresh = `<span class="err">Kunde inte hämta aktuella värden från OSM (${e.message}), tabellen visar läget när kartan genererades.</span> `; }
  const valCell = (v, cls, m) => v == null ? '–' : `<span class="nw"><span class="key"><span class="sw ${cls}${v}"></span>${v}</span>` + (m ? ` <span class="dim">(${m} m)</span>` : '') + '</span>';
  const cnt = {}; ways.forEach(w => { cnt[w.diff] = (cnt[w.diff] || 0) + 1; });
  document.getElementById('osmsum').innerHTML = fresh + `${ways.length} cyklade ways i cykelordning: ` +
    Object.keys(DIFFN).map(k => `${cnt[k] || 0} ${DIFFN[k]}`).join(', ') + `. ${ways.filter(w => w.split).length} bör delas. ` +
    `<a href="#" id="partsall">visa alla delar</a> · <a href="#" id="partsnone">dölj alla delar</a>`;
  document.getElementById('osmrows').innerHTML = ways.map(w => {
    const parts = w.parts.map(id => segById[id]).filter(Boolean);
    const open = w.split || parts.some(t => t.diff !== w.diff);   // delar med avvikelse visas från start
    const tg = parts.length > 1 ? `<button type="button" class="tg" aria-expanded="${open}" aria-label="visa eller dölj delar">${open ? '▾' : '▸'}</button>` : '<span class="tg"></span>';
    return `<tr id="way${w.way}" data-way="${w.way}"><td>${tg}<a href="https://www.openstreetmap.org/way/${w.way}" target="_blank" rel="noopener">${w.way}</a></td>` +
      `<td>${trailName(w)}</td><td>${fmtLen(w.covered_m)}</td><td>${w.osm_scale ?? '–'}</td>` +
      `<td>${valCell(w.scale, 'sc', w.scale_m)}</td><td>${valCell(w.level, 'lv', w.level_m)}</td>` +
      `<td>${diffCell(w.diff)}${w.split ? ' · <b>dela</b>' : ''}</td><td class="dim">${osmTags(w) || '–'}</td><td class="write">${writeCell(w)}</td></tr>` +
      (parts.length > 1 ? parts.map(t => `<tr class="part" data-way="${w.way}" data-id="${t.id}"${open ? '' : ' hidden'}><td>del ${t.id}</td><td></td><td>${fmtLen(t.covered_m)}</td><td></td>` +
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

// ---- Stigsegment-tabell ----
if (TRAILS && TRAILS.segments.length) {
  const cell = (v, cls, m) => v == null ? '–' : `<span class="key"><span class="sw ${cls}${v}"></span>${AUTO && cls === 'lv' ? AUTO.levels[v] : v}</span> <span class="dim">(${m} m)</span>`;
  document.getElementById('trailrows').innerHTML = TRAILS.segments.map(t =>
    `<tr id="trail${t.id}" data-id="${t.id}"><td>${t.id}</td><td>${trailName(t)}</td>` +
    `<td>${t.way ? `<a href="https://www.openstreetmap.org/way/${t.way}" target="_blank" rel="noopener">${t.way}</a>` : '–'}</td>` +
    `<td>${fmtLen(t.length_m)}</td><td>${fmtLen(t.covered_m)}${t.passes > 1 ? ' · ' + t.passes + ' pass' : ''}</td>` +
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

// ---- Höjdprofil (SVG) ----
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
  // rutnät och axlar, recessiva
  for (let a = aMin; a <= aMax + 1e-9; a += yStep) {
    el('line', { x1: m.l, x2: W - m.r, y1: y(a), y2: y(a), stroke: '#e1e0d9', 'stroke-width': 1 }, svg);
    el('text', { x: m.l - 6, y: y(a) + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#898781' }, svg).textContent = a + ' m';
  }
  const xStep = niceStep(dMax / 1000, Math.max(3, Math.floor(W / 110)));
  for (let k = 0; k <= dMax / 1000 + 1e-9; k += xStep)
    el('text', { x: x(k * 1000), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: '#898781' }, svg).textContent =
      (+k.toFixed(2)).toString().replace('.', ',') + ' km';
  // branta backar som band bakom kurvan
  HILLS.forEach(h => {
    el('rect', { id: 'band' + h.id, x: x(h.start_d), y: m.t, width: Math.max(2, x(h.end_d) - x(h.start_d)), height: H - m.t - m.b,
                 fill: HILLC[h.dir], 'fill-opacity': .14 }, svg);
  });
  // yta + linje färgad per mtb:scale
  el('path', { d: `M${x(0)},${y(aMin)} ` + PROF.map(p => `L${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ') +
               ` L${x(dMax)},${y(aMin)} Z`, fill: '#e1e0d9', 'fill-opacity': .55 }, svg);
  // långa backar: tunn stapel längst ned i plottytan
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
  // hårkors
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
  tipEl.innerHTML = `<b>${(p[0] / 1000).toFixed(2).replace('.', ',')} km</b> · <b>${p[1].toFixed(1).replace('.', ',')} m</b><br>` +
    `lutning <b>${fmtPct(p[2])}</b>` + (p[5] != null ? ` · mtb:scale <b>${p[5]}</b>` : '') +
    (p[7] != null ? ` · <b>${p[7].toFixed(0)} km/h</b>` : '') +
    (hill ? `<br>${arrow(hill)} brant ${hill.dir}för, max ${fmtPct(hill.max)}` : '') +
    (trailAt(i) ? `<br>stigsegment ${trailAt(i).id}: ${trailName(trailAt(i))} · ${mode === 'osm' ? (DIFFN[trailAt(i).diff] || 'utanför OSM') + ' (OSM ' + (trailAt(i).osm_scale ?? '–') + ', din ' + (trailAt(i).scale ?? '–') + ')' : mode === 'auto' ? AUTO.levels[trailAt(i).level] ?? '–' : 'mtb:scale ' + (trailAt(i).scale ?? '–')}` : '') +
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
// tabellernas rubrikrader fästs precis under den fasta kartan
const stickEl = document.querySelector('.stick');
const setStickH = () => document.documentElement.style.setProperty('--stickh', stickEl.offsetHeight + 'px');
setStickH(); new ResizeObserver(setStickH).observe(stickEl);
</script></body></html>
"""


LEAFLET_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/'
OSM_BASE = 'https://www.openstreetmap.org'
OSM_EDITABLE = ['path', 'track', 'footway', 'bridleway']   # vägtyper där mtb:scale hör hemma
LEVEL_COLORS = ['#0ca30c', '#fab219', '#d03b3b']   # samma som LVLC i skriptet
DIFF_COLORS = {'saknas': '#898781', 'lika': '#0ca30c', 'osm_lagre': '#2f6fdd', 'osm_hogre': '#d03b3b', 'none': '#c9c8c1'}


def color_css():
    """Klasser för färgerna, så att inga style-attribut behövs (CSP)."""
    out = []
    for i, c in enumerate(RAMP):
        out.append('  .sw.sc%d, .dot.sc%d { background:%s; } .seglabel.sc%d { border-color:%s; }' % (i, i, c, i, c))
    for i, c in enumerate(LEVEL_COLORS):
        out.append('  .sw.lv%d, .dot.lv%d { background:%s; }' % (i, i, c))
    for k, c in DIFF_COLORS.items():
        out.append('  .sw.df-%s, .dot.df-%s { background:%s; }' % (k, k, c))
    return '\n'.join(out)


def write_site(html, site, geojson_paths):
    """Mapp för webbhotell: index.html utan inbäddad css/js, style.css, app.js, leaflet/."""
    os.makedirs(site, exist_ok=True)
    a, rest = html.split('<style>\n', 1)
    css, rest = rest.split('</style>', 1)
    b, rest = rest.rsplit('<script>\n', 1)
    js, tail = rest.rsplit('</script>', 1)
    b0, rest2 = b.split('<script id="osmedit">', 1)
    osmedit, b1 = rest2.split('</script>', 1)
    # ?v=<innehållshash> så att webbläsaren inte visar en annan turs app.js ur cachen
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
            sys.exit('--mount ska vara ' + ' eller '.join(trailanalysis.MOUNTS))
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
        except Exception as e:  # noqa: BLE001 - nätverksfel ska inte stoppa kartan
            print('Stigsegment hoppas över:', e, file=sys.stderr)
    geojsons = [os.path.join(outdir, name + '.geojson')]
    if trails:
        geojsons.append(os.path.join(outdir, name + '_stigsegment.geojson'))
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
        print('segment %d  mtb:scale=%s  %6.1f m  %3d s  %d punkter' % (
            s['id'], s['scale'], s['length_m'], s['end_ts'] - s['start_ts'], len(s['coords'])))
    for h in hills:
        print('backe %d  %sför  vid %.2f km  %4d m  %+5.1f m  snitt %+5.1f %%  max %+5.1f %%' % (
            h['id'], h['dir'], h['start_d'] / 1000, h['length_m'], h['dh'], h['avg'], h['max']))
    print('Skrev', os.path.join(outdir, name + '.html'))
    for g in geojsons:
        print('Skrev', g)
    if trails:
        segs_t = trails['segments']
        print('stigsegment: %d cyklade av %d i OSM-nätet (%d ways), %d utanför nätet' % (
            len(segs_t), trails['osm_segments'], trails['osm_ways'], sum(1 for t in segs_t if t['way'] is None)))
    if site:
        print('Skrev webbmapp', site)


if __name__ == '__main__':
    main()
