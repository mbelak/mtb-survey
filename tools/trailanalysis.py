#!/usr/bin/env python3
"""Automatic assessment of how child-friendly a trail is, from a FIT file.

The track is split into sections of SECTION_M meters. Each section gets metrics and
a level: 0 = easy, 1 = needs experience, 2 = hard for kids, with the reasons in plain text.

Metrics (all optional except position/altitude):
  grade        max |grade| in the section (from fitmap.build_profile)
  long climb   the section lies within a continuous climb (long_climbs)
  speed        median of the record speeds, km/h
  unevenness   coefficient of variation of the speed (std / mean)
  stops        seconds below 2 km/h
  twistiness   sum of heading changes, degrees per 100 m
  roughness    shake from the watch accelerometer (app v0.3), mG RMS (shown, does not set the level)
  steer        steering corrections from the watch gyroscope (app v0.3), degrees/s RMS
  v_rel        speed relative to the day's road speed, grade-adjusted
  mount        'wrist' or 'handlebar', where the watch was mounted
  cadence      from a cadence sensor, if connected

The limits below are calibrated against one loop (see LIMITS). Compare with
the "Metrics per mtb:scale" table on the map page and adjust them after more rides.

Usage:  python3 tools/trailanalysis.py activity.fit [--mount wrist|handlebar]

Without --mount the mount is decided per section: heart rate without a chest strap = wrist, otherwise handlebar.
"""
import math, os, statistics, sys
from bisect import bisect_left, bisect_right

SECTION_M = 25

# Long climbs: continuous climb where dips smaller than DIP_M do not break it
LONG_DIP_M = 2.0
LONG_MIN_GAIN_M = 12
LONG_MIN_LEN_M = 150

# Limits per level: (needs experience, hard for kids). None = not used.
# The scale: 0 = gravel road or asphalt, 1 = child-friendly trail, 2 = trail that is not child-friendly.
# Grade, long climbs and stops say nothing about the surface and are turned off;
# turn them back on if needed. Steering and speed are handled per mount in MOUNT_LIMITS.
LIMITS = {
    'grade':     (None, 14.0),    # max |grade| %
    'climb':     (None, None),    # elevation gain of the long climb the section lies in
    'walk_kmh':  (None, None),    # median speed below this uphill = probably walking the bike
    'cv':        (None, None),    # uneven speed
    'stop_s':    (None, None),    # seconds standing still
    'curv':      (120.0, 220.0),  # degrees per 100 m
}

# Where the watch was mounted. Calibrated 2026-09-30 against the manual assessment from the ride
# 2026-09-25 (handlebar), transferred by location to the ride 2026-09-30 (same loop, once on the
# wrist and once on the handlebar).
#   trail_steer  steer (deg/s) from which the section counts as trail (level 1)
#   hard_score   handlebar: hard (2) if steer * (v_rel ** -SPEED_EXP) >= hard_score.
#                Low speed relative to the day's road speed thus amplifies the steering value.
#   v_rel_hard   wrist: hard (2) if the speed is at most this share of the road speed.
#                Steering and shake on the wrist do not separate an easy trail from a hard one.
# Handlebar: balanced accuracy 0.71 (three levels) on a different day than the calibration, vs 0.53
# with the earlier limits. Roughness is not used: it did not separate 1 from 2 and gave
# false trails on bumpy gravel roads. The wrist trail limit is preliminary (one ride).
SPEED_EXP = 0.66
MOUNT_LIMITS = {
    'handlebar': {'trail_steer': 24.0, 'hard_score': 47.0, 'v_rel_hard': None},
    'wrist':     {'trail_steer': 59.0, 'hard_score': None, 'v_rel_hard': 0.62},
}
MOUNTS = tuple(MOUNT_LIMITS)

# The day's road speed: median of the grade-adjusted speed on the ROAD_Q calmest sections
# (lowest steer, counted within each mount). Speed relative to it tolerates the pace varying
# between days, which absolute speed does not.
ROAD_Q = 0.35
GRADE_K = -0.036                  # speed ~ exp(GRADE_K * grade %), fitted on road
MIN_ROAD_SECS = 4
V_ROAD_DEFAULT = 15.0             # km/h, if the ride has too little calm distance
HR_STRAP = 120                    # FIT antplus_device_type for a heart rate chest strap
MOUNT_MIN_S = 60                  # shorter heart rate dropouts or brief heart rate readings do not change the mount
# Sensor values and speed are smoothed with a moving median over this many
# sections before the level is set. 5 sections = 125 m. Without smoothing the
# values are too noisy over 25 m.
SMOOTH_N = 5
LEVELS = ['easy', 'needs experience', 'hard for kids']
# Twistiness is coarse (GPS noise) and is not counted in the level by default.
# The map page can turn it on; levels both with and without it are computed.
USE_CURV = False


def long_climbs(prof):
    """Continuous climbs. prof point: [d, alt, ...]."""
    out, s, p = [], 0, 0

    def close(s, p):
        gain = prof[p][1] - prof[s][1]
        length = prof[p][0] - prof[s][0]
        if gain >= LONG_MIN_GAIN_M and length >= LONG_MIN_LEN_M:
            out.append({'id': len(out) + 1, 'start_d': prof[s][0], 'end_d': prof[p][0],
                        'length_m': round(length), 'gain': round(gain, 1),
                        'avg': round(100 * gain / length, 1)})

    for i in range(1, len(prof)):
        a = prof[i][1]
        if a > prof[p][1]:
            p = i
        elif prof[p][1] - a > LONG_DIP_M or a < prof[s][1]:
            close(s, p)
            s = p = i
    if prof:
        close(s, p)
    return out


def _heading(a, b):
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = (math.cos(math.radians(a[0])) * math.sin(math.radians(b[0])) -
         math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1])))
    return math.degrees(math.atan2(y, x))


def _mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def has_hr_strap(rows):
    """Was a heart rate chest strap connected? Then the heart rate comes from it and says nothing about the watch."""
    return any(k == 'device_info' and m.get('device_type') == HR_STRAP for k, m, dev in rows)


def record_mounts(rows, force=None):
    """[(ts, 'wrist'|'handlebar')] per record. Heart rate without a chest strap = watch on the wrist,
    since the optical heart rate sensor touches no skin on the handlebar. Runs shorter
    than MOUNT_MIN_S are merged with their neighbors, so single dropouts do not change the mount."""
    recs = [(m['ts'], bool(m.get('hr'))) for k, m, dev in rows if k == 'record' and m.get('ts') is not None]
    if force or not recs or has_hr_strap(rows):
        return [(ts, force or 'handlebar') for ts, _ in recs]
    runs = []                                   # [flag, first index, last index]
    for i, (_, f) in enumerate(recs):
        if runs and runs[-1][0] == f:
            runs[-1][2] = i
        else:
            runs.append([f, i, i])

    def dur(r):
        return recs[r[2]][0] - recs[r[1]][0] + 1
    while len(runs) > 1:
        j = min(range(len(runs)), key=lambda i: dur(runs[i]))
        if dur(runs[j]) >= MOUNT_MIN_S:
            break
        runs[j][0] = not runs[j][0]
        merged = []
        for r in runs:
            if merged and merged[-1][0] == r[0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        runs = merged
    out = []
    for f, a, b in runs:
        out += [(recs[i][0], 'wrist' if f else 'handlebar') for i in range(a, b + 1)]
    return out


def _grade_factor(grade):
    return math.exp(GRADE_K * max(-15.0, min(15.0, grade or 0.0)))


def _quantile(v, q):
    v = sorted(v)
    x = q * (len(v) - 1)
    lo = int(x)
    return v[lo] if lo + 1 >= len(v) else v[lo] + (x - lo) * (v[lo + 1] - v[lo])


def road_speed(secs):
    """The day's road speed in km/h: median of the grade-adjusted speed on the calmest sections."""
    road = []
    for mount in MOUNTS:
        ss = [s for s in secs if s.get('mount', 'handlebar') == mount and s.get('steer') is not None
              and s.get('speed') and s['speed'] > 2]
        if not ss:
            continue
        lim = _quantile([s['steer'] for s in ss], ROAD_Q)
        road += [s['speed'] / _grade_factor(s.get('avg_grade')) for s in ss if s['steer'] <= lim]
    return statistics.median(road) if len(road) >= MIN_ROAD_SECS else V_ROAD_DEFAULT


def sections(prof, rows, climbs, mount=None):
    """Splits the profile into sections and computes metrics per section."""
    recs = sorted((m['ts'], m.get('speed'), dev.get('roughness'), dev.get('steer'), m.get('cad'))
                  for k, m, dev in rows if k == 'record' and m.get('ts') is not None)
    rts = [r[0] for r in recs]
    mounts = dict(record_mounts(rows, force=mount))
    # heading over a 20 m chord, for twistiness (a shorter chord gives mostly GPS noise)
    head = [_heading((prof[i][3], prof[i][4]), (prof[i + 4][3], prof[i + 4][4]))
            for i in range(len(prof) - 4)]
    turn = [0.0] + [abs((head[i] - head[i - 1] + 180) % 360 - 180) for i in range(1, len(head))]
    per = SECTION_M // 5
    out = []
    for k in range(0, len(prof) - 1, per):
        part = prof[k:k + per + 1]
        if len(part) < 2:
            break
        length = part[-1][0] - part[0][0]
        t0, t1 = part[0][6], part[-1][6]
        rs = recs[bisect_left(rts, t0):bisect_right(rts, t1)]
        sp = [r[1] * 3.6 for r in rs if r[1] is not None]
        mid = (part[0][0] + part[-1][0]) / 2
        climb = next((c for c in climbs if c['start_d'] <= mid <= c['end_d']), None)
        scales = [p[5] for p in part if p[5] is not None]
        ms = [mounts[r[0]] for r in rs if r[0] in mounts]
        sec = {
            'mount': max(set(ms), key=ms.count) if ms else (out[-1]['mount'] if out else (mount or 'handlebar')),
            'i': len(out), 'start_d': part[0][0], 'length_m': length,
            'coords': [[p[3], p[4]] for p in part],
            'grade': max(abs(p[2]) for p in part),
            'avg_grade': round(100 * (part[-1][1] - part[0][1]) / length, 1) if length else 0,
            'climb': climb['gain'] if climb else 0,
            'climb_id': climb['id'] if climb else None,
            'speed': round(statistics.median(sp), 1) if sp else None,
            'cv': round(statistics.pstdev(sp) / statistics.mean(sp), 2) if len(sp) > 2 and statistics.mean(sp) > 0 else None,
            'stop_s': sum(1 for v in sp if v < 2.0),
            'curv': round(100 * sum(turn[min(j, len(turn) - 1)] for j in range(k, k + per)) / length) if length else 0,
            'roughness': _mean([r[2] for r in rs]),
            'steer': _mean([r[3] for r in rs]),
            'cad': _mean([r[4] for r in rs]),
            'scale': max(set(scales), key=scales.count) if scales else None,
        }
        for key in ('roughness', 'steer', 'cad'):
            if sec[key] is not None:
                sec[key] = round(sec[key], 1)
        out.append(sec)
    smooth(out)
    v_road = road_speed(out)
    for sec in out:
        sec['v_rel'] = (round(sec['speed'] / (v_road * _grade_factor(sec['avg_grade'])), 3)
                        if sec['speed'] else None)
    for sec in out:
        lv0, why0 = classify(sec, use_curv=False)
        lv1, why1 = classify(sec, use_curv=True)
        sec['lv'], sec['whys'] = [lv0, lv1], [why0, why1]
        sec['level'], sec['why'] = (lv1, why1) if USE_CURV else (lv0, why0)
    return out


def smooth(secs, n=None, keys=('roughness', 'steer', 'speed')):
    """Moving median over n sections, in place. The raw value is kept as <key>_raw."""
    n = SMOOTH_N if n is None else n
    if n <= 1:
        return secs
    h = n // 2
    raw = [{k: s[k] for k in keys} for s in secs]
    for i, s in enumerate(secs):
        for k in keys:
            s[k + '_raw'] = raw[i][k]
            v = [r[k] for r in raw[max(0, i - h):i + h + 1] if r[k] is not None]
            s[k] = round(statistics.median(v), 1) if v else None
    return secs


def classify(s, use_curv=USE_CURV):
    """Level 0-2 and reasons. Each metric that passes a limit raises the level."""
    level, why = 0, []

    def check(key, value, text):
        nonlocal level
        if value is None:
            return
        lo, hi = LIMITS[key]
        if hi is not None and value >= hi:
            level = max(level, 2); why.append((2, text))
        elif lo is not None and value >= lo:
            level = max(level, 1); why.append((1, text))

    check('grade', s['grade'], 'steep %.0f %%' % s['grade'])
    if s['avg_grade'] >= 3:
        check('climb', s['climb'], 'long climb +%.0f m' % s['climb'])
    check('cv', s['cv'], 'uneven speed')
    check('stop_s', s['stop_s'], 'stopped %d s' % s['stop_s'])
    if use_curv:
        check('curv', s['curv'], 'twisty')
    ml = MOUNT_LIMITS[s.get('mount') or 'handlebar']
    steer, v_rel = s.get('steer'), s.get('v_rel')
    if steer is not None and steer >= ml['trail_steer']:
        level = max(level, 1)
        rel = v_rel if v_rel else 1.0
        slow = rel < 0.85
        hard = ((ml['hard_score'] is not None and steer * rel ** -SPEED_EXP >= ml['hard_score']) or
                (ml['v_rel_hard'] is not None and v_rel is not None and v_rel <= ml['v_rel_hard']))
        if hard:
            level = 2
            why.append((2, 'slow on trail' if slow else 'lots of steering'))
        else:
            why.append((1, 'trail'))
    walk = LIMITS['walk_kmh'][1]
    if walk is not None and s['speed'] is not None and s['avg_grade'] >= 5 and s['speed'] < walk:
        level = 2; why.append((2, 'walking pace uphill'))
    why.sort(key=lambda w: -w[0])
    return level, [w[1] for w in why]


def per_scale(secs):
    """Metrics summarized per manual mtb:scale value, for calibration."""
    out = []
    for sc in sorted({s['scale'] for s in secs if s['scale'] is not None}):
        ss = [s for s in secs if s['scale'] == sc]
        length = sum(s['length_m'] for s in ss)

        def med(key):
            v = [s[key] for s in ss if s[key] is not None]
            return round(statistics.median(v), 1) if v else None
        out.append({'scale': sc, 'length_m': round(length), 'n': len(ss),
                    'speed': med('speed'), 'cv': med('cv'), 'grade': med('grade'), 'curv': med('curv'),
                    'stops_per_km': round(1000 * sum(1 for s in ss if s['stop_s'] >= (LIMITS['stop_s'][0] or 4)) / length, 1) if length else 0,
                    'roughness': med('roughness'), 'steer': med('steer'),
                    'levels': [round(100 * sum(s['length_m'] for s in ss if s['level'] == L) / length) if length else 0
                               for L in range(3)],
                    'levels_v': [[round(100 * sum(s['length_m'] for s in ss if s['lv'][v] == L) / length) if length else 0
                                  for L in range(3)] for v in (0, 1)]})
    return out


def analyze(rows, prof, mount=None):
    """mount: None = decide per section from the heart rate, 'wrist' or 'handlebar' = the whole ride."""
    climbs = long_climbs(prof)
    secs = sections(prof, rows, climbs, mount=mount)
    return {'climbs': climbs, 'sections': secs, 'per_scale': per_scale(secs),
            'has': {k: any(s[k] is not None for s in secs) for k in ('roughness', 'steer', 'cad')},
            'limits': LIMITS, 'mount_limits': MOUNT_LIMITS, 'levels': LEVELS, 'section_m': SECTION_M,
            'use_curv': USE_CURV, 'smooth_n': SMOOTH_N, 'v_road': round(road_speed(secs), 1),
            'mount_m': {mm: round(sum(s['length_m'] for s in secs if s['mount'] == mm)) for mm in MOUNTS},
            'mount_forced': mount}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fitdump import parse
    from fitmap import build_profile
    args = sys.argv[1:]
    mount = None
    if '--mount' in args:
        i = args.index('--mount'); mount = args[i + 1]; del args[i:i + 2]
        if mount not in MOUNTS:
            sys.exit('--mount must be ' + ' or '.join(MOUNTS))
    rows = parse(args[0])
    a = analyze(rows, build_profile(rows), mount=mount)
    print('Road speed %.1f km/h. Watch: %s' % (a['v_road'], ', '.join(
        '%s %.1f km' % (mm, m / 1000) for mm, m in a['mount_m'].items() if m)))
    for c in a['climbs']:
        print('long climb %d  at %.2f km  %4d m  +%.1f m  avg %.1f %%' % (
            c['id'], c['start_d'] / 1000, c['length_m'], c['gain'], c['avg']))
    total = sum(s['length_m'] for s in a['sections'])
    for L, name in enumerate(LEVELS):
        m = sum(s['length_m'] for s in a['sections'] if s['level'] == L)
        print('%-17s %6.0f m  %3.0f %%' % (name, m, 100 * m / total if total else 0))
    print('\nPer mtb:scale (median):')
    for p in a['per_scale']:
        print('  scale %s  %5d m  speed %s km/h  cv %s  grade %s %%  curv %s  stops/km %s  levels %s %%' % (
            p['scale'], p['length_m'], p['speed'], p['cv'], p['grade'], p['curv'], p['stops_per_km'], p['levels']))
    print('Sensors:', ', '.join(k for k, v in a['has'].items() if v) or 'none (app v0.2)')


if __name__ == '__main__':
    main()
