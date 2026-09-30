"""python3 tools/test_trailsegments.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trailsegments as ts

# The rule: highest value with at least MIN_RUN_M continuous
assert ts.decide({0: 200, 1: 80, 2: 60}, {0: 200, 1: 80, 2: 60}, 340) == (2, 60)
# 2 occurs only 20 m in a row: does not count, 1 applies
assert ts.decide({0: 200, 1: 80, 2: 20}, {0: 200, 1: 80, 2: 40}, 320) == (1, 80)
# short segment (40 m covered): the limit becomes 20 m
assert ts.decide({0: 20, 2: 20}, {0: 20, 2: 20}, 40) == (2, 20)
# nothing reaches the limit: most meters wins
assert ts.decide({0: 10, 1: 10}, {0: 30, 1: 10}, 40) == (0, 10)
# None values (missing assessment) are ignored
assert ts.decide({None: 500, 1: 60}, {None: 500, 1: 60}, 560) == (1, 60)

# Splitting at junction nodes
ways = [{'id': 1, 'nodes': [1, 2, 3, 4], 'geometry': [{'lat': 0, 'lon': 0}, {'lat': 0, 'lon': .001}, {'lat': 0, 'lon': .002}, {'lat': 0, 'lon': .003}], 'tags': {'highway': 'path'}},
        {'id': 2, 'nodes': [3, 5], 'geometry': [{'lat': 0, 'lon': .002}, {'lat': .001, 'lon': .002}], 'tags': {'highway': 'path'}}]
segs = ts.split_ways(ways)
assert [s['way'] for s in segs] == [1, 1, 2], segs
assert len(segs[0]['coords']) == 3 and len(segs[1]['coords']) == 2

# Smoothing out short switches
assert ts._smooth([0, 0, 0, 1, 0, 0, 0]) == [0] * 7
assert ts._smooth([0, 0, 0, 1, 1, 1, 2, 2, 2]) == [0, 0, 0, 1, 1, 1, 2, 2, 2]

# Matching: points along way 1, one point far away
prof = [[i * 5, 0, 0, 0, i * 0.00005, 1, 0] for i in range(60)] + [[300, 0, 0, 0.01, 0.01, 1, 0]] * 3
m = ts.match(prof, segs)
assert m[0] == 0 and m[-1] == -1, m
secs_prof = [[i * 5, 0, 0, .001 - i * 0.00001, .002, 1, 0] for i in range(60)] + [[300 + i * 5, 0, 0, 0, i * 0.00005, 1, 0] for i in range(60)]
mm = ts.match(secs_prof, segs)
res, mo = ts.aggregate(secs_prof, mm, segs, None, 1, 5)
assert [(r['id'], r['way']) for r in res] == [(1, 2), (2, 1), (3, 1)], [(r['id'], r['way']) for r in res]
assert mo[0] == 0 and mo[-1] == 2

# Trail that crosses the track without a shared node: the track runs 10 m north of way 1, and the
# 4 points nearest the crossing are closer to way 3. They must not count as ridden on way 3.
cross = segs + ts.split_ways([{'id': 3, 'nodes': [6, 7], 'geometry': [{'lat': -.001, 'lon': .0015}, {'lat': .001, 'lon': .0015}], 'tags': {'highway': 'path'}}])
along = [[i * 5, 0, 0, 0.00009, i * 0.00005, 1, 0] for i in range(60)]
mc = ts.match(along, cross)
assert 3 not in mc and set(mc) == {0, 1}, mc
# Half of way 2 ridden (55 m of 111) and then back: counts, since 55 m >= MIN_RUN_M
half = [[i * 5, 0, 0, i * 0.00005, .002, 1, 0] for i in range(11)] + [[55 + i * 5, 0, 0, .0005 - i * 0.00005, .002, 1, 0] for i in range(11)]
assert ts.match(half, segs) == [2] * 22, ts.match(half, segs)
# Short 24 m connector trail where only 3 points (10 m) were matched: counts as ridden,
# since the points are 5 m apart and can miss one step at each end.
ident = lambda lat, lon: (lon, lat)
pp = [[i * 5, 0, 0, 0, i * 5 - 20, 1, 0] for i in range(13)]
xy = [[(-100, 0), (-5, 0)], [(-5, 0), (19, 0)], [(19, 0), (100, 0)]]
assert ts._drop_glancing(pp, [0] * 5 + [1] * 3 + [2] * 5, xy, ident) == [0] * 5 + [1] * 3 + [2] * 5
# The same three points crossing a long trail: removed and assigned to the previous segment
xy2 = [[(-100, 0), (100, 0)], [(-2, -60), (-2, 60)], [(100, 0), (200, 0)]]
assert ts._drop_glancing(pp, [0] * 5 + [1] * 3 + [0] * 5, xy2, ident) == [0] * 13
print('trailsegments: all tests passed')

# ---- Comparison with OSM ----
assert ts.osm_int('2') == 2 and ts.osm_int('2+') == 2 and ts.osm_int('3-') == 3 and ts.osm_int(None) is None and ts.osm_int('x') is None
assert ts.diff_class(1, None) == 'missing'
assert ts.diff_class(None, 2) is None
assert ts.diff_class(2, 2) == 'equal'
assert ts.diff_class(1, 2) == 'osm_higher'
assert ts.diff_class(2, 1) == 'osm_lower'

def seg(id, way, scale, runs, level=None, lruns=None, covered=None, osm=None):
    return {'id': id, 'way': way, 'name': None, 'highway': 'path', 'osm_scale': osm, 'tags': {},
            'scale': scale, 'scale_runs': runs, 'level': level, 'level_runs': lruns or [],
            'covered_m': covered or sum(t for _, _, t in runs), 'length_m': 100, 'passes': 1}
# two parts of the same way: part A is 0 (200 m), part B is 2 (60 m in a row). The way becomes 2 and should be split.
segs = [seg(1, 10, 0, [[0, 200, 200]], osm='1'), seg(2, 10, 2, [[2, 60, 60], [1, 30, 40]], osm='1')]
ways = ts.build_ways(segs)
assert len(ways) == 1
w = ways[0]
assert w['scale'] == 2 and w['scale_m'] == 60, w
assert w['split'] is True
assert w['diff'] == 'osm_lower', w
assert segs[0]['diff'] == 'osm_higher' and segs[1]['diff'] == 'osm_lower'
# a way without a tag
segs = [seg(3, 11, 1, [[1, 80, 80]])]
w = ts.build_ways(segs)[0]
assert w['diff'] == 'missing' and w['split'] is False
# parts outside the network are not included
assert ts.build_ways([seg('u1', None, 1, [[1, 80, 80]])]) == []
# ways in riding order: way 20 was ridden first (segment 1), way 10 after
ws = ts.build_ways([seg(2, 10, 1, [[1, 80, 80]]), seg(1, 20, 1, [[1, 80, 80]])])
assert [w['way'] for w in ws] == [20, 10], ws
# 2 occurring only 20 m in one part is not enough for the way: 1 applies
segs = [seg(4, 12, 1, [[1, 120, 120]], osm='2'), seg(5, 12, 2, [[2, 20, 20]], covered=20, osm='2')]
w = ts.build_ways(segs)[0]
assert w['scale'] == 1 and w['diff'] == 'osm_higher', w
print('osm comparison: all tests passed')
