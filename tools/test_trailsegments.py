"""python3 tools/test_trailsegments.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trailsegments as ts

# Regeln: högsta värde med minst MIN_RUN_M sammanhängande
assert ts.decide({0: 200, 1: 80, 2: 60}, {0: 200, 1: 80, 2: 60}, 340) == (2, 60)
# 2 förekommer bara 20 m i följd: räknas inte, 1 gäller
assert ts.decide({0: 200, 1: 80, 2: 20}, {0: 200, 1: 80, 2: 40}, 320) == (1, 80)
# kort segment (40 m täckt): gränsen blir 20 m
assert ts.decide({0: 20, 2: 20}, {0: 20, 2: 20}, 40) == (2, 20)
# inget når gränsen: flest meter vinner
assert ts.decide({0: 10, 1: 10}, {0: 30, 1: 10}, 40) == (0, 10)
# None-värden (saknad bedömning) ignoreras
assert ts.decide({None: 500, 1: 60}, {None: 500, 1: 60}, 560) == (1, 60)

# Delning vid korsningsnoder
ways = [{'id': 1, 'nodes': [1, 2, 3, 4], 'geometry': [{'lat': 0, 'lon': 0}, {'lat': 0, 'lon': .001}, {'lat': 0, 'lon': .002}, {'lat': 0, 'lon': .003}], 'tags': {'highway': 'path'}},
        {'id': 2, 'nodes': [3, 5], 'geometry': [{'lat': 0, 'lon': .002}, {'lat': .001, 'lon': .002}], 'tags': {'highway': 'path'}}]
segs = ts.split_ways(ways)
assert [s['way'] for s in segs] == [1, 1, 2], segs
assert len(segs[0]['coords']) == 3 and len(segs[1]['coords']) == 2

# Utslätning av korta byten
assert ts._smooth([0, 0, 0, 1, 0, 0, 0]) == [0] * 7
assert ts._smooth([0, 0, 0, 1, 1, 1, 2, 2, 2]) == [0, 0, 0, 1, 1, 1, 2, 2, 2]

# Matchning: punkter längs way 1, en punkt långt bort
prof = [[i * 5, 0, 0, 0, i * 0.00005, 1, 0] for i in range(60)] + [[300, 0, 0, 0.01, 0.01, 1, 0]] * 3
m = ts.match(prof, segs)
assert m[0] == 0 and m[-1] == -1, m
secs_prof = [[i * 5, 0, 0, .001 - i * 0.00001, .002, 1, 0] for i in range(60)] + [[300 + i * 5, 0, 0, 0, i * 0.00005, 1, 0] for i in range(60)]
mm = ts.match(secs_prof, segs)
res, mo = ts.aggregate(secs_prof, mm, segs, None, 1, 5)
assert [(r['id'], r['way']) for r in res] == [(1, 2), (2, 1), (3, 1)], [(r['id'], r['way']) for r in res]
assert mo[0] == 0 and mo[-1] == 2

# Stig som korsar spåret utan gemensam nod: spåret går 10 m norr om way 1, och de
# 4 punkterna närmast korsningen ligger närmare way 3. De ska inte räknas som cyklade på way 3.
cross = segs + ts.split_ways([{'id': 3, 'nodes': [6, 7], 'geometry': [{'lat': -.001, 'lon': .0015}, {'lat': .001, 'lon': .0015}], 'tags': {'highway': 'path'}}])
along = [[i * 5, 0, 0, 0.00009, i * 0.00005, 1, 0] for i in range(60)]
mc = ts.match(along, cross)
assert 3 not in mc and set(mc) == {0, 1}, mc
# Halva way 2 cyklad (55 m av 111) och sedan tillbaka: räknas, eftersom 55 m >= MIN_RUN_M
half = [[i * 5, 0, 0, i * 0.00005, .002, 1, 0] for i in range(11)] + [[55 + i * 5, 0, 0, .0005 - i * 0.00005, .002, 1, 0] for i in range(11)]
assert ts.match(half, segs) == [2] * 22, ts.match(half, segs)
# Kort förbindelsestig på 24 m där bara 3 punkter (10 m) matchats: räknas som cyklad,
# eftersom punkterna ligger var 5:e meter och kan missa ett steg i varje ände.
ident = lambda lat, lon: (lon, lat)
pp = [[i * 5, 0, 0, 0, i * 5 - 20, 1, 0] for i in range(13)]
xy = [[(-100, 0), (-5, 0)], [(-5, 0), (19, 0)], [(19, 0), (100, 0)]]
assert ts._drop_glancing(pp, [0] * 5 + [1] * 3 + [2] * 5, xy, ident) == [0] * 5 + [1] * 3 + [2] * 5
# Samma tre punkter på tvären över en lång stig: tas bort och går till föregående segment
xy2 = [[(-100, 0), (100, 0)], [(-2, -60), (-2, 60)], [(100, 0), (200, 0)]]
assert ts._drop_glancing(pp, [0] * 5 + [1] * 3 + [0] * 5, xy2, ident) == [0] * 13
print('trailsegments: alla test ok')

# ---- Jämförelse med OSM ----
assert ts.osm_int('2') == 2 and ts.osm_int('2+') == 2 and ts.osm_int('3-') == 3 and ts.osm_int(None) is None and ts.osm_int('x') is None
assert ts.diff_class(1, None) == 'saknas'
assert ts.diff_class(None, 2) is None
assert ts.diff_class(2, 2) == 'lika'
assert ts.diff_class(1, 2) == 'osm_högre'
assert ts.diff_class(2, 1) == 'osm_lägre'

def seg(id, way, scale, runs, level=None, lruns=None, covered=None, osm=None):
    return {'id': id, 'way': way, 'name': None, 'highway': 'path', 'osm_scale': osm, 'tags': {},
            'scale': scale, 'scale_runs': runs, 'level': level, 'level_runs': lruns or [],
            'covered_m': covered or sum(t for _, _, t in runs), 'length_m': 100, 'passes': 1}
# två delar av samma way: del A är 0 (200 m), del B är 2 (60 m i följd). Wayen blir 2 och ska delas.
segs = [seg(1, 10, 0, [[0, 200, 200]], osm='1'), seg(2, 10, 2, [[2, 60, 60], [1, 30, 40]], osm='1')]
ways = ts.build_ways(segs)
assert len(ways) == 1
w = ways[0]
assert w['scale'] == 2 and w['scale_m'] == 60, w
assert w['split'] is True
assert w['diff'] == 'osm_lägre', w
assert segs[0]['diff'] == 'osm_högre' and segs[1]['diff'] == 'osm_lägre'
# en way utan tagg
segs = [seg(3, 11, 1, [[1, 80, 80]])]
w = ts.build_ways(segs)[0]
assert w['diff'] == 'saknas' and w['split'] is False
# delar utanför nätet ingår inte
assert ts.build_ways([seg('u1', None, 1, [[1, 80, 80]])]) == []
# ways i cykelordning: way 20 cyklades först (segment 1), way 10 sedan
ws = ts.build_ways([seg(2, 10, 1, [[1, 80, 80]]), seg(1, 20, 1, [[1, 80, 80]])])
assert [w['way'] for w in ws] == [20, 10], ws
# 2 som bara förekommer 20 m i den ena delen räcker inte för wayen: 1 gäller
segs = [seg(4, 12, 1, [[1, 120, 120]], osm='2'), seg(5, 12, 2, [[2, 20, 20]], covered=20, osm='2')]
w = ts.build_ways(segs)[0]
assert w['scale'] == 1 and w['diff'] == 'osm_högre', w
print('osm-jämförelse: alla test ok')
