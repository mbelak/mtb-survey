"""python3 tools/test_trailanalysis.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trailanalysis as ta


def rec(ts, hr=None):
    return ('record', {'ts': ts, 'hr': hr, 'speed': 4.0, 'lat': 59.4, 'lon': 18.0, 'alt': 10, 'dist': ts * 4.0}, {})


# --- Where was the watch mounted? ----------------------------------------------
# Heart rate without a chest strap = wrist. No heart rate = handlebar.
rows = [rec(t, 120) for t in range(300)] + [rec(t) for t in range(300, 600)]
m = ta.record_mounts(rows)
assert m[0] == (0, 'wrist') and m[299] == (299, 'wrist'), m[299]
assert m[300] == (300, 'handlebar') and m[-1] == (599, 'handlebar'), m[300]

# Short heart rate dropouts on the wrist (under a minute) do not change the mount
rows = [rec(t, 120) for t in range(200)] + [rec(t) for t in range(200, 230)] + [rec(t, 120) for t in range(230, 400)]
assert {mm for _, mm in ta.record_mounts(rows)} == {'wrist'}

# With a chest strap the heart rate says nothing about where the watch was: everything becomes handlebar
strap = [('device_info', {'device_type': 120, 'source_type': 1}, {})]
assert ta.has_hr_strap(strap + rows)
assert not ta.has_hr_strap(rows)
assert {mm for _, mm in ta.record_mounts(strap + rows)} == {'handlebar'}

# Manual override
assert {mm for _, mm in ta.record_mounts(rows, force='handlebar')} == {'handlebar'}
assert {mm for _, mm in ta.record_mounts([rec(t) for t in range(50)], force='wrist')} == {'wrist'}


# --- The day's road speed -------------------------------------------------------
def sec(steer, speed, grade=0.0, mount='handlebar', roughness=300.0):
    return {'steer': steer, 'speed': speed, 'avg_grade': grade, 'mount': mount, 'roughness': roughness,
            'grade': abs(grade), 'climb': 0, 'cv': None, 'stop_s': 0, 'curv': 0}

# The road speed is taken from the calmest sections (lowest steering), not from the trail
secs = [sec(10, 16) for _ in range(12)] + [sec(40, 8) for _ in range(18)]
assert abs(ta.road_speed(secs) - 16) < 0.01, ta.road_speed(secs)
# Steering is compared within each mount, so the wrist's higher level does not interfere
secs += [sec(50, 17, mount='wrist') for _ in range(12)] + [sec(90, 9, mount='wrist') for _ in range(18)]
assert 16 <= ta.road_speed(secs) <= 17, ta.road_speed(secs)
# Uphill is adjusted: 12 km/h at 5 % corresponds to about 14 km/h on flat ground
up = [sec(10, 12, grade=5) for _ in range(12)] + [sec(40, 8) for _ in range(18)]
assert 13.5 < ta.road_speed(up) < 15, ta.road_speed(up)
# Too few sections: the fallback value is used
assert ta.road_speed([sec(10, 30)]) == ta.V_ROAD_DEFAULT


# --- Levels ---------------------------------------------------------------------
def level(**kw):
    s = sec(**{k: v for k, v in kw.items() if k != 'v_rel'})
    s['v_rel'] = kw.get('v_rel', 1.0)
    return ta.classify(s)[0]

# Handlebar: little steering = road, even if it shakes a lot and goes slowly
assert level(steer=18, speed=15, roughness=2000) == 0
assert level(steer=18, speed=6, v_rel=0.4) == 0
# Trail at normal speed = 1, the same trail at low speed relative to the road speed = 2
assert level(steer=30, speed=14, v_rel=1.0) == 1
assert level(steer=30, speed=7, v_rel=0.5) == 2
# Lots of steering is enough for 2 even at normal speed
assert level(steer=50, speed=14, v_rel=1.0) == 2
# Steep still gives 2
assert level(steer=10, speed=14, grade=15) == 2

# Wrist: its own trail limit, and only the speed decides 1 vs 2
assert level(steer=40, speed=14, mount='wrist') == 0
assert level(steer=70, speed=14, mount='wrist', v_rel=1.0) == 1
assert level(steer=70, speed=8, mount='wrist', v_rel=0.55) == 2
assert level(steer=120, speed=14, mount='wrist', v_rel=1.0) == 1

# The reasons in plain text
lv, why = ta.classify(dict(sec(30, 7), v_rel=0.5))
assert lv == 2 and any('slow' in w for w in why), why

print('trailanalysis: all tests passed')
