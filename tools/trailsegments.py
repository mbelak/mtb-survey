#!/usr/bin/env python3
"""Stigsegment: hela stigen mellan två korsningar får ett sammanvägt värde.

Stignätet hämtas från OpenStreetMap (Overpass) för spårets område och cachas
i utmappen. Varje OSM-way delas vid noder som delas av flera ways, alltså
korsningar. Spåret matchas mot närmaste segment inom MATCH_M meter.

Sammanvägning per segment, både för din bedömning (mtb:scale) och för den
automatiska nivån: det högsta värde som förekommer sammanhängande under minst
MIN_RUN_M meter gäller. Är segmentet kortare används halva den täckta längden
som gräns. Har samma stig cyklats flera gånger räknas alla passen.
Delar av spåret som saknar OSM-väg inom MATCH_M blir egna segment ("u1", "u2" ...)
med spårets egen geometri.
"""
import hashlib, json, math, os, sys, urllib.parse, urllib.request

ENDPOINTS = ['https://lz4.overpass-api.de/api/interpreter',
             'https://overpass-api.de/api/interpreter',
             'https://overpass.kumi.systems/api/interpreter']
HIGHWAYS = ('path|track|footway|cycleway|bridleway|unclassified|service|residential|'
            'tertiary|secondary|primary|living_street|pedestrian|steps')
MATCH_M = 25        # spårpunkt längre från alla OSM-vägar än så räknas som omatchad
MIN_RUN_M = 50      # minsta sammanhängande längd för att ett värde ska styra segmentet
MIN_RUN_PTS = 3     # kortare matchningsbyten än så (15 m) slätas ut
MIN_COVER_FRAC = 0.5  # spåret måste följa segmentet minst så stor del av längden, eller MIN_RUN_M
MARGIN_DEG = 0.001  # marginal runt spåret i grader lat (lon dubblas)
EXTRA_TAGS = ('surface', 'smoothness', 'trail_visibility')   # följer med från OSM, till hjälp vid taggning
DIFF = ['saknas', 'lika', 'osm_lägre', 'osm_högre']          # avvikelseklasser mot OSM:s mtb:scale
USER_AGENT = 'mtb-survey-fitmap/0.3'


def bbox_of(prof):
    lats = [p[3] for p in prof]; lons = [p[4] for p in prof]
    return (round(min(lats) - MARGIN_DEG, 4), round(min(lons) - 2 * MARGIN_DEG, 4),
            round(max(lats) + MARGIN_DEG, 4), round(max(lons) + 2 * MARGIN_DEG, 4))


def fetch_ways(bbox, cache_dir):
    """OSM-ways i området, från cache om den finns."""
    q = '[out:json][timeout:60];way[highway~"^(%s)$"](%s);out geom;' % (HIGHWAYS, ','.join('%.4f' % v for v in bbox))
    key = hashlib.sha1(q.encode()).hexdigest()[:12]
    path = os.path.join(cache_dir, 'osm_%s.json' % key)
    if os.path.exists(path):
        return json.load(open(path))['elements']
    data = urllib.parse.urlencode({'data': q}).encode()
    err = None
    for url in ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT})
            raw = urllib.request.urlopen(req, timeout=90).read()
            d = json.loads(raw)
            if 'elements' not in d:
                raise ValueError('oväntat svar')
            with open(path, 'w') as f:
                f.write(raw.decode('utf-8'))
            return d['elements']
        except Exception as e:  # noqa: BLE001
            err = e
            print('Overpass %s: %s' % (url, e), file=sys.stderr)
    raise RuntimeError('Overpass svarade inte: %s' % err)


def split_ways(ways):
    """Delar varje way vid korsningsnoder. Returnerar segment med koordinater [lat, lon]."""
    count = {}
    for w in ways:
        for n in w.get('nodes', []):
            count[n] = count.get(n, 0) + 1
    segs = []
    for w in ways:
        nodes, geom, tags = w.get('nodes', []), w.get('geometry', []), w.get('tags', {})
        if len(nodes) != len(geom) or len(nodes) < 2:
            continue
        start = 0
        for i in range(1, len(nodes)):
            if i == len(nodes) - 1 or count[nodes[i]] >= 2:
                coords = [[g['lat'], g['lon']] for g in geom[start:i + 1]]
                segs.append({'id': len(segs) + 1, 'way': w['id'], 'highway': tags.get('highway'),
                             'name': tags.get('name'), 'osm_scale': tags.get('mtb:scale'),
                             'tags': {k: tags[k] for k in EXTRA_TAGS if k in tags},
                             'coords': coords, 'length_m': round(_length(coords))})
                start = i
    return segs


def _length(coords):
    return sum(_haversine(coords[i - 1], coords[i]) for i in range(1, len(coords)))


def _haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _projector(lat0):
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    return lambda lat, lon: (lon * kx, lat * ky)


def _pt_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def match(prof, segs):
    """Index i segs för varje profilpunkt, eller -1. Korta byten slätas ut."""
    if not prof or not segs:
        return [-1] * len(prof)
    proj = _projector(prof[0][3])
    cs = MATCH_M
    grid = {}
    xy = []
    for si, s in enumerate(segs):
        pts = [proj(c[0], c[1]) for c in s['coords']]
        xy.append(pts)
        for ei in range(1, len(pts)):
            (ax, ay), (bx, by) = pts[ei - 1], pts[ei]
            for cx in range(int(min(ax, bx) // cs), int(max(ax, bx) // cs) + 1):
                for cy in range(int(min(ay, by) // cs), int(max(ay, by) // cs) + 1):
                    grid.setdefault((cx, cy), []).append((si, ei))
    out = []
    for p in prof:
        px, py = proj(p[3], p[4])
        cx, cy = int(px // cs), int(py // cs)
        best, bd = -1, MATCH_M
        seen = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for si, ei in grid.get((cx + dx, cy + dy), ()):
                    if (si, ei) in seen:
                        continue
                    seen.add((si, ei))
                    (ax, ay), (bx, by) = xy[si][ei - 1], xy[si][ei]
                    d = _pt_seg(px, py, ax, ay, bx, by)
                    if d < bd:
                        best, bd = si, d
        out.append(best)
    return _drop_glancing(prof, _smooth(out), xy, proj)


def _along(px, py, pts):
    """Position längs polylinjen pts för den punkt på linjen som ligger närmast (px, py)."""
    best, bd, acc = 0.0, float('inf'), 0.0
    for i in range(1, len(pts)):
        (ax, ay), (bx, by) = pts[i - 1], pts[i]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        t = 0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (L * L)))
        d = math.hypot(px - ax - t * dx, py - ay - t * dy)
        if d < bd:
            best, bd = acc + t * L, d
        acc += L
    return best


def _drop_glancing(prof, m, xy, proj):
    """Tar bort matchningar där spåret bara nuddar ett segment: vid en korsning, eller
    där en gren löper nära spåret de första metrarna. Spåret måste följa segmentet
    minst MIN_COVER_FRAC av dess längd, eller MIN_RUN_M. Annars går punkterna till
    grannsegmentet, i första hand det föregående. Punkterna ligger ett steg isär och
    kan missa upp till ett steg i varje ände, så ett steg räknas som marginal.
    Spårets första och sista del behålls alltid, eftersom turen kan börja och sluta mitt på en stig."""
    step = prof[1][0] - prof[0][0] if len(prof) > 1 else 0
    runs = _runs(m)
    for k, r in enumerate(runs):
        si = r[2]
        if si < 0 or k == 0 or k == len(runs) - 1:
            continue
        pts = xy[si]
        length = sum(math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) for i in range(1, len(pts)))
        pos = [_along(*proj(prof[i][3], prof[i][4]), pts) for i in range(r[0], r[1])]
        if max(pos) - min(pos) + step >= min(MIN_COVER_FRAC * length, MIN_RUN_M):
            continue
        prev = runs[k - 1][2] if k > 0 else -1
        nxt = runs[k + 1][2] if k + 1 < len(runs) else -1
        r[2] = prev if prev >= 0 else nxt
    return [r[2] for r in runs for _ in range(r[0], r[1])]


def _runs(values):
    runs = []
    for i, v in enumerate(values):
        if runs and runs[-1][2] == v:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1, v])
    return runs


def _smooth(m):
    runs = _runs(m)
    for k, r in enumerate(runs):
        if r[1] - r[0] < MIN_RUN_PTS:
            if k > 0:
                r[2] = runs[k - 1][2]
            elif k + 1 < len(runs):
                r[2] = runs[k + 1][2]
    return [r[2] for r in runs for _ in range(r[0], r[1])]


def decide(runs_by_value, total_by_value, covered_m, min_run_m=MIN_RUN_M):
    """Värdet som gäller för segmentet, och hur många meter som motiverar det.

    runs_by_value: {värde: längsta sammanhängande längd}, total_by_value: {värde: meter totalt}.
    """
    limit = min(min_run_m, covered_m / 2)
    cands = [v for v, L in runs_by_value.items() if v is not None and L >= limit]
    if cands:
        v = max(cands)
        return v, runs_by_value[v]
    if total_by_value:
        v = max(total_by_value, key=lambda k: (total_by_value[k], k))
        return v, runs_by_value.get(v, 0)
    return None, 0


def aggregate(prof, m, segs, secs, per, step):
    """Sammanväger värden per segment. Returnerar (segment med värden, match-index per punkt)."""
    used = {}
    for r in _runs(m):
        if r[2] >= 0:
            used.setdefault(r[2], []).append(r)
    # omatchade partier blir egna segment
    unmatched = [r for r in _runs(m) if r[2] < 0 and r[1] - r[0] >= 2]
    # segmenten numreras i den ordning de först cyklades
    items = [(runs[0][0], si, dict(segs[si]), runs) for si, runs in used.items()]
    for k, r in enumerate(unmatched):
        coords = [[p[3], p[4]] for p in prof[r[0]:r[1]]]
        s = {'way': None, 'highway': None, 'name': None, 'osm_scale': None, 'tags': {},
             'coords': coords, 'length_m': round(_length(coords))}
        items.append((r[0], ('u', k), s, [r]))
        for i in range(r[0], r[1]):
            m[i] = ('u', k)
    items.sort(key=lambda t: t[0])
    out, index = [], {}
    for n, (first, key, s, runs) in enumerate(items):
        s['id'] = n + 1
        s['osm_seg'] = key if isinstance(key, int) else None
        index[key] = n
        out.append((s, runs))
    result = []
    for s, runs in out:
        best_s, tot_s, best_l, tot_l = {}, {}, {}, {}
        covered = 0
        for r in runs:
            covered += (r[1] - r[0]) * step
            for sub in _runs([prof[i][5] for i in range(r[0], r[1])]):
                L = (sub[1] - sub[0]) * step
                best_s[sub[2]] = max(best_s.get(sub[2], 0), L); tot_s[sub[2]] = tot_s.get(sub[2], 0) + L
            if secs:
                for sub in _runs([secs[min(i // per, len(secs) - 1)]['level'] for i in range(r[0], r[1])]):
                    L = (sub[1] - sub[0]) * step
                    best_l[sub[2]] = max(best_l.get(sub[2], 0), L); tot_l[sub[2]] = tot_l.get(sub[2], 0) + L
        s['covered_m'] = covered
        s['passes'] = len(runs)
        s['scale'], s['scale_m'] = decide(best_s, tot_s, covered)
        s['level'], s['level_m'] = decide(best_l, tot_l, covered) if secs else (None, 0)
        # sparas så att hela wayen kan sammanvägas med samma regel
        s['scale_runs'] = [[v, best_s[v], tot_s[v]] for v in best_s]
        s['level_runs'] = [[v, best_l[v], tot_l[v]] for v in best_l]
        result.append(s)
    match_out = [index.get(v, -1) if v != -1 else -1 for v in m]
    return result, match_out


def osm_int(v):
    """mtb:scale i OSM kan vara '2', '2+' eller '3-'. Siffran räknas."""
    if v is None:
        return None
    v = str(v).strip().rstrip('+-')
    return int(v) if v.isdigit() else None


def diff_class(mine, osm):
    """Avvikelse mellan eget värde och OSM:s. None när eget värde saknas."""
    if mine is None:
        return None
    if osm is None:
        return 'saknas'
    return 'lika' if mine == osm else ('osm_högre' if osm > mine else 'osm_lägre')


def _merge_runs(parts, key):
    best, tot = {}, {}
    for p in parts:
        for v, b, t in p.get(key, []):
            best[v] = max(best.get(v, 0), b); tot[v] = tot.get(v, 0) + t
    return best, tot


def build_ways(segments):
    """En post per cyklad OSM-way: sammanvägt värde för hela wayen, avvikelse mot OSM,
    och om delarna mellan korsningarna skiljer sig (wayen bör då delas i OSM).
    Sätter också diff/diff_auto på varje del. Delar utan way ingår inte."""
    by_way = {}
    for s in segments:
        if s.get('way') is not None:
            by_way.setdefault(s['way'], []).append(s)
    out = []
    for way, parts in sorted(by_way.items(), key=lambda kv: kv[1][0]['id']):   # cykelordning
        first = parts[0]
        osm_raw = next((p.get('osm_scale') for p in parts if p.get('osm_scale') is not None), None)
        osm = osm_int(osm_raw)
        covered = sum(p['covered_m'] for p in parts)
        best_s, tot_s = _merge_runs(parts, 'scale_runs')
        best_l, tot_l = _merge_runs(parts, 'level_runs')
        scale, scale_m = decide(best_s, tot_s, covered)
        level, level_m = decide(best_l, tot_l, covered) if best_l else (None, 0)
        for p in parts:
            p['diff'] = diff_class(p.get('scale'), osm)
            p['diff_auto'] = diff_class(p.get('level'), osm)
        vals = {p.get('scale') for p in parts if p.get('scale') is not None}
        out.append({'way': way, 'name': first.get('name'), 'highway': first.get('highway'),
                    'osm_scale': osm_raw, 'osm_n': osm, 'tags': first.get('tags', {}),
                    'parts': [p['id'] for p in parts], 'covered_m': covered,
                    'length_m': sum(p['length_m'] for p in parts),
                    'scale': scale, 'scale_m': scale_m, 'level': level, 'level_m': level_m,
                    'diff': diff_class(scale, osm), 'diff_auto': diff_class(level, osm),
                    'split': len(vals) > 1})
    return out


def build(prof, auto, cache_dir, step):
    ways = fetch_ways(bbox_of(prof), cache_dir)
    segs = split_ways(ways)
    m = match(prof, segs)
    secs = auto['sections'] if auto else None
    per = (auto['section_m'] // step) if auto else 1
    result, match_out = aggregate(prof, m, segs, secs, per, step)
    ways_out = build_ways(result)
    return {'segments': result, 'ways': ways_out, 'match': match_out, 'min_run_m': MIN_RUN_M, 'match_m': MATCH_M,
            'osm_ways': len(ways), 'osm_segments': len(segs), 'diff': DIFF}


def to_geojson(trails, auto):
    levels = auto['levels'] if auto else []
    ways = {w['way']: w for w in trails.get('ways', [])}
    feats = []
    for s in trails['segments']:
        props = {'segment': s['id'], 'mtb:scale': s['scale'], 'scale_basis_m': s['scale_m'],
                 'auto': levels[s['level']] if s['level'] is not None else None, 'auto_level': s['level'],
                 'osm_way': s['way'], 'highway': s['highway'], 'name': s['name'], 'osm_mtb_scale': s['osm_scale'],
                 'length_m': s['length_m'], 'covered_m': s['covered_m'], 'passes': s['passes'],
                 'diff': s.get('diff'), 'diff_auto': s.get('diff_auto'),
                 'way_mtb_scale': ways.get(s['way'], {}).get('scale'), 'way_split': ways.get(s['way'], {}).get('split')}
        for k, v in s.get('tags', {}).items():
            props['osm_' + k] = v
        feats.append({'type': 'Feature', 'properties': props,
                      'geometry': {'type': 'LineString', 'coordinates': [[c[1], c[0]] for c in s['coords']]}})
    return {'type': 'FeatureCollection', 'features': feats}
