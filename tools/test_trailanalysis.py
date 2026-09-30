"""python3 tools/test_trailanalysis.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trailanalysis as ta


def rec(ts, hr=None):
    return ('record', {'ts': ts, 'hr': hr, 'speed': 4.0, 'lat': 59.4, 'lon': 18.0, 'alt': 10, 'dist': ts * 4.0}, {})


# --- Var satt klockan? ---------------------------------------------------------
# Puls utan pulsband = handleden. Ingen puls = styret.
rows = [rec(t, 120) for t in range(300)] + [rec(t) for t in range(300, 600)]
m = ta.record_mounts(rows)
assert m[0] == (0, 'arm') and m[299] == (299, 'arm'), m[299]
assert m[300] == (300, 'styre') and m[-1] == (599, 'styre'), m[300]

# Korta pulsavbrott på handleden (under en minut) ändrar inte läget
rows = [rec(t, 120) for t in range(200)] + [rec(t) for t in range(200, 230)] + [rec(t, 120) for t in range(230, 400)]
assert {mm for _, mm in ta.record_mounts(rows)} == {'arm'}

# Med pulsband säger pulsen inget om var klockan satt: allt blir styre
strap = [('device_info', {'device_type': 120, 'source_type': 1}, {})]
assert ta.has_hr_strap(strap + rows)
assert not ta.has_hr_strap(rows)
assert {mm for _, mm in ta.record_mounts(strap + rows)} == {'styre'}

# Manuell överstyrning
assert {mm for _, mm in ta.record_mounts(rows, force='styre')} == {'styre'}
assert {mm for _, mm in ta.record_mounts([rec(t) for t in range(50)], force='arm')} == {'arm'}


# --- Dagens vägfart -------------------------------------------------------------
def sec(steer, speed, grade=0.0, mount='styre', roughness=300.0):
    return {'steer': steer, 'speed': speed, 'avg_grade': grade, 'mount': mount, 'roughness': roughness,
            'grade': abs(grade), 'climb': 0, 'cv': None, 'stop_s': 0, 'curv': 0}

# Vägfarten tas från de lugnaste sektionerna (lägst styrning), inte från stigen
secs = [sec(10, 16) for _ in range(12)] + [sec(40, 8) for _ in range(18)]
assert abs(ta.road_speed(secs) - 16) < 0.01, ta.road_speed(secs)
# Styrningen jämförs inom varje läge, så armens högre nivå stör inte
secs += [sec(50, 17, mount='arm') for _ in range(12)] + [sec(90, 9, mount='arm') for _ in range(18)]
assert 16 <= ta.road_speed(secs) <= 17, ta.road_speed(secs)
# Uppförsbacke justeras: 12 km/h i 5 % motsvarar ungefär 14 km/h på plan mark
up = [sec(10, 12, grade=5) for _ in range(12)] + [sec(40, 8) for _ in range(18)]
assert 13.5 < ta.road_speed(up) < 15, ta.road_speed(up)
# För få sektioner: reservvärdet används
assert ta.road_speed([sec(10, 30)]) == ta.V_ROAD_DEFAULT


# --- Nivåer ---------------------------------------------------------------------
def level(**kw):
    s = sec(**{k: v for k, v in kw.items() if k != 'v_rel'})
    s['v_rel'] = kw.get('v_rel', 1.0)
    return ta.classify(s)[0]

# Styret: lite styrning = väg, även om det skakar mycket och går långsamt
assert level(steer=18, speed=15, roughness=2000) == 0
assert level(steer=18, speed=6, v_rel=0.4) == 0
# Stig i normal fart = 1, samma stig i låg fart relativt vägfarten = 2
assert level(steer=30, speed=14, v_rel=1.0) == 1
assert level(steer=30, speed=7, v_rel=0.5) == 2
# Mycket styrning räcker för 2 även i vanlig fart
assert level(steer=50, speed=14, v_rel=1.0) == 2
# Brant ger fortfarande 2
assert level(steer=10, speed=14, grade=15) == 2

# Armen: egen gräns för stig, och bara farten avgör 1 mot 2
assert level(steer=40, speed=14, mount='arm') == 0
assert level(steer=70, speed=14, mount='arm', v_rel=1.0) == 1
assert level(steer=70, speed=8, mount='arm', v_rel=0.55) == 2
assert level(steer=120, speed=14, mount='arm', v_rel=1.0) == 1

# Skälen i klartext
lv, why = ta.classify(dict(sec(30, 7), v_rel=0.5))
assert lv == 2 and any('långsam' in w for w in why), why

print('trailanalysis: alla tester gick igenom')
