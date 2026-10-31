"""python3 tools/test_trailmerge.py"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trailmerge as tm
import trailsegments as ts

# --- Conditions from the file argument --------------------------------------------
assert tm.parse_arg('a.fit:wet') == ('a.fit', 'wet')
assert tm.parse_arg('a.fit:dry') == ('a.fit', 'dry')
assert tm.parse_arg('dir/a.fit') == ('dir/a.fit', 'dry')

# --- Weighted median -------------------------------------------------------------
assert tm.weighted_median([(2, 100), (1, 40), (1, 40)]) == 2
assert tm.weighted_median([(2, 50), (1, 50)]) == 1          # an exact split gives the lower value
assert tm.weighted_median([(None, 100), (0, 10)]) == 0
assert tm.weighted_median([]) is None


def p(level, cond='dry', m=100, scale=None):
    return {'ride': 'r', 'date': '2026-10-31', 'conditions': cond, 'level': level, 'scale': scale, 'covered_m': m}


# --- Combining passes --------------------------------------------------------------
# The median, not the highest: one hard pass among three easy ones does not make the trail hard
c = tm.combine([p(1), p(1), p(2)])
assert c['level'] == 1 and c['basis'] == 'dry' and c['agree'] is False, c
# Dry passes decide; wet passes are counted but do not move the level
c = tm.combine([p(1), p(2, 'wet'), p(2, 'wet')])
assert c['level'] == 1 and c['passes_dry'] == 1 and c['passes_wet'] == 2, c
# Ridden only in the wet: the wet passes decide, and the result is marked
c = tm.combine([p(2, 'wet'), p(2, 'wet', m=50)])
assert c['level'] == 2 and c['basis'] == 'wet only' and c['agree'] is True, c
# Passes without handlebar data have no level and are not counted
c = tm.combine([p(None), p(0)])
assert c['level'] == 0 and c['passes_dry'] == 1, c
assert tm.combine([p(None)])['level'] is None
# Your own assessment is combined the same way, and 3 counts as 2
c = tm.combine([p(1, scale=3), p(1, 'wet', scale=1)])
assert c['scale'] == 2 and c['scale_basis'] == 'dry', c

# --- Assessed or not: a lap marker is not an assessment ------------------------------
assert not tm.is_labelled([[0, 0, 0, 0, 0, 1 if k < 4 else 0, 0] for k in range(400)])      # 20 m of 1
assert tm.is_labelled([[0, 0, 0, 0, 0, 1 if k < 60 else 0, 0] for k in range(400)])         # 300 m of 1

# --- Only the handlebar counts ----------------------------------------------------
secs = tm.handlebar_only([{'level': 2, 'mount': 'wrist'}, {'level': 1, 'mount': 'handlebar'}, {'level': 0}])
assert [s['level'] for s in secs] == [None, 1, 0], secs


# --- Network from the rides' caches, combined by way id -------------------------------
def way(i, nodes, lon0):
    return {'id': i, 'nodes': nodes, 'tags': {'highway': 'path'},
            'geometry': [{'lat': 0, 'lon': lon0 + k * 0.001} for k in range(len(nodes))]}


def ride(lons, levels, cond='dry', labelled=False):
    prof = [[k * 5, 0, 0, 0.0, lon, 1 if labelled else None, k] for k, lon in enumerate(lons)]
    per = 5
    secs = [{'level': levels[min(i // per, len(levels) - 1)], 'mount': 'handlebar'} for i in range(0, len(prof), per)]
    return {'name': 'r', 'date': '2026-10-31', 'conditions': cond, 'labelled': labelled, 'prof': prof,
            'auto': {'sections': secs, 'section_m': 25, 'mount_m': {'handlebar': 1}}}


with tempfile.TemporaryDirectory() as d:
    r1 = ride([k * 0.00005 for k in range(40)], [1])                  # 0 ... 0.002 east
    r2 = ride([0.002 + k * 0.00005 for k in range(40)], [2], 'wet')   # 0.002 ... 0.004 east
    for r, ways in ((r1, [way(1, [1, 2, 3], 0.0)]), (r2, [way(1, [1, 2, 3], 0.0), way(2, [3, 4, 5], 0.002)])):
        with open(ts._cache_path(ts.bbox_of(r['prof']), d), 'w') as f:
            json.dump({'elements': ways}, f)
    net = tm.fetch_network([r1, r2], [d])
    assert [w['id'] for w in net] == [1, 2], net                     # way 1 is in both caches, kept once
    merged = tm.merge([r1, r2], [d])
    by_way = {s['way']: s for s in merged}
    assert by_way[1]['level'] == 1 and by_way[1]['basis'] == 'dry', by_way[1]
    assert by_way[2]['level'] == 2 and by_way[2]['basis'] == 'wet only', by_way[2]
    feats = tm.to_geojson(merged)['features']
    assert {f['properties']['osm_way'] for f in feats} == {1, 2}
    assert all(f['properties']['passes'] for f in feats)

# --- Text from OSM cannot break out of the page's script ----------------------------
evil = [dict(by_way[1], name='</script><script>alert(1)</script> __RIDES__')]
page = tm.render('<b>t</b>', evil, [])
script = page.rsplit('<script>', 1)[1]
assert '</script><script>alert' not in page and script.count('</script>') == 1, 'OSM name broke out of the script'
assert '\\u003c/script\\u003e' in page and '__RIDES__' in page and '<b>t</b>' not in page
assert json.loads(page.split('const SEGS = ', 1)[1].split(', RIDES = ', 1)[0])[0]['name'] == evil[0]['name']

print('trailmerge: all tests passed')
