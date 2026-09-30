#!/usr/bin/env python3
"""Automatisk bedömning av hur barnvänlig en stig är, från en FIT-fil.

Spåret delas i sektioner om SECTION_M meter. Varje sektion får mätvärden och
en nivå: 0 = lätt, 1 = kräver vana, 2 = svårt för barn, med skälen i klartext.

Mätvärden (alla valfria utom position/höjd):
  lutning      max |lutning| i sektionen (från fitmap.build_profile)
  lång backe   sektionen ligger i en sammanhängande stigning (long_climbs)
  fart         median av records-farten, km/h
  ryckighet    variationskoefficient för farten (std / medel)
  stopp        sekunder under 2 km/h
  kurvighet    summa riktningsändring, grader per 100 m
  roughness    skakningar från klockans accelerometer (appen v0.3), mG RMS (visas, styr inte nivån)
  steer        styrkorrigeringar från klockans gyroskop (appen v0.3), grader/s RMS
  v_rel        fart relativt dagens vägfart, lutningsjusterad
  mount        'arm' eller 'styre', var klockan satt
  kadens       från kadenssensor, om ansluten

Gränsvärdena nedan är kalibrerade mot en runda (se LIMITS). Jämför med
tabellen "Mätvärden per mtb:scale" i kartan och justera dem efter fler turer.

Användning:  python3 tools/trailanalysis.py aktivitet.fit [--mount arm|styre]

Utan --mount avgörs läget per sektion: puls utan pulsband = armen, annars styret.
"""
import math, os, statistics, sys
from bisect import bisect_left, bisect_right

SECTION_M = 25

# Långa backar: sammanhängande stigning där dippar under DIP_M inte bryter
LONG_DIP_M = 2.0
LONG_MIN_GAIN_M = 12
LONG_MIN_LEN_M = 150

# Gränser per nivå: (kräver vana, svårt för barn). None = används inte.
# Skalan: 0 = grusväg eller asfalt, 1 = barnvänlig stig, 2 = stig som inte är barnvänlig.
# Lutning, långa backar och stopp säger inget om underlaget och är avstängda;
# slå på dem igen vid behov. Styrning och fart hanteras per läge i MOUNT_LIMITS.
LIMITS = {
    'grade':     (None, 14.0),    # max |lutning| %
    'climb':     (None, None),    # höjdmeter i den långa backe sektionen ligger i
    'walk_kmh':  (None, None),    # medianfart under detta i uppförsbacke = troligen ledde cykeln
    'cv':        (None, None),    # ryckig fart
    'stop_s':    (None, None),    # sekunder stillastående
    'curv':      (120.0, 220.0),  # grader per 100 m
}

# Var klockan satt. Kalibrerat 2026-09-30 mot handbedömningen från turen 2026-09-25 (styre),
# överförd via plats till turen 2026-09-30 (samma loop, en gång på armen och en på styret).
#   trail_steer  steer (°/s) från vilken sektionen räknas som stig (nivå 1)
#   hard_score   styret: svår (2) om steer * (v_rel ** -SPEED_EXP) >= hard_score.
#                Låg fart relativt dagens vägfart förstärker alltså styrvärdet.
#   v_rel_hard   armen: svår (2) om farten är högst så här stor andel av vägfarten.
#                Armens styrning och skak skiljer inte lätt stig från svår.
# Styret: balanserad träff 0,71 (tre nivåer) på en annan dag än kalibreringen, mot 0,53
# med de tidigare gränserna. Roughness används inte: den skilde inte 1 från 2 och gav
# falska stigar på skakiga grusvägar. Armens stiggräns är preliminär (en tur).
SPEED_EXP = 0.66
MOUNT_LIMITS = {
    'styre': {'trail_steer': 24.0, 'hard_score': 47.0, 'v_rel_hard': None},
    'arm':   {'trail_steer': 59.0, 'hard_score': None, 'v_rel_hard': 0.62},
}
MOUNTS = tuple(MOUNT_LIMITS)

# Dagens vägfart: median av lutningsjusterad fart på de ROAD_Q lugnaste sektionerna
# (lägst steer, räknat inom varje läge). Fart relativt den tål att tempot varierar
# mellan dagar, vilket absolut fart inte gör.
ROAD_Q = 0.35
GRADE_K = -0.036                  # fart ~ exp(GRADE_K * lutning %), anpassad på väg
MIN_ROAD_SECS = 4
V_ROAD_DEFAULT = 15.0             # km/h, om passet har för lite lugn sträcka
HR_STRAP = 120                    # FIT antplus_device_type för pulsband
MOUNT_MIN_S = 60                  # kortare pulsavbrott eller pulsglimtar ändrar inte läget
# Sensorvärden och fart jämnas ut med en glidande median över så här många
# sektioner innan nivån sätts. 5 sektioner = 125 m. Utan utjämning är
# värdena för brusiga på 25 m.
SMOOTH_N = 5
LEVELS = ['lätt', 'kräver vana', 'svårt för barn']
# Kurvighet är grov (GPS-brus) och räknas inte in i nivån som standard.
# Kartsidan kan slå på den; både nivåer med och utan räknas ut.
USE_CURV = False


def long_climbs(prof):
    """Sammanhängande stigningar. prof-punkt: [d, alt, ...]."""
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
    """Var ett pulsband anslutet? Då kommer pulsen därifrån och säger inget om klockan."""
    return any(k == 'device_info' and m.get('device_type') == HR_STRAP for k, m, dev in rows)


def record_mounts(rows, force=None):
    """[(ts, 'arm'|'styre')] per record. Puls utan pulsband = klockan på handleden,
    eftersom den optiska pulsmätaren inte når någon hud på styret. Partier kortare
    än MOUNT_MIN_S slås ihop med grannarna, så enstaka avbrott inte byter läge."""
    recs = [(m['ts'], bool(m.get('hr'))) for k, m, dev in rows if k == 'record' and m.get('ts') is not None]
    if force or not recs or has_hr_strap(rows):
        return [(ts, force or 'styre') for ts, _ in recs]
    runs = []                                   # [flagga, första index, sista index]
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
        out += [(recs[i][0], 'arm' if f else 'styre') for i in range(a, b + 1)]
    return out


def _grade_factor(grade):
    return math.exp(GRADE_K * max(-15.0, min(15.0, grade or 0.0)))


def _quantile(v, q):
    v = sorted(v)
    x = q * (len(v) - 1)
    lo = int(x)
    return v[lo] if lo + 1 >= len(v) else v[lo] + (x - lo) * (v[lo + 1] - v[lo])


def road_speed(secs):
    """Dagens vägfart i km/h: median av lutningsjusterad fart på de lugnaste sektionerna."""
    road = []
    for mount in MOUNTS:
        ss = [s for s in secs if s.get('mount', 'styre') == mount and s.get('steer') is not None
              and s.get('speed') and s['speed'] > 2]
        if not ss:
            continue
        lim = _quantile([s['steer'] for s in ss], ROAD_Q)
        road += [s['speed'] / _grade_factor(s.get('avg_grade')) for s in ss if s['steer'] <= lim]
    return statistics.median(road) if len(road) >= MIN_ROAD_SECS else V_ROAD_DEFAULT


def sections(prof, rows, climbs, mount=None):
    """Delar profilen i sektioner och räknar mätvärden per sektion."""
    recs = sorted((m['ts'], m.get('speed'), dev.get('roughness'), dev.get('steer'), m.get('cad'))
                  for k, m, dev in rows if k == 'record' and m.get('ts') is not None)
    rts = [r[0] for r in recs]
    mounts = dict(record_mounts(rows, force=mount))
    # riktning över 20 m-korda, för kurvighet (kortare korda ger mest GPS-brus)
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
            'mount': max(set(ms), key=ms.count) if ms else (out[-1]['mount'] if out else (mount or 'styre')),
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
    """Glidande median över n sektioner, på plats. Råvärdet sparas som <key>_raw."""
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
    """Nivå 0-2 och skäl. Varje mätvärde som passerar en gräns höjer nivån."""
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

    check('grade', s['grade'], 'brant %.0f %%' % s['grade'])
    if s['avg_grade'] >= 3:
        check('climb', s['climb'], 'lång backe +%.0f m' % s['climb'])
    check('cv', s['cv'], 'ryckig fart')
    check('stop_s', s['stop_s'], 'stopp %d s' % s['stop_s'])
    if use_curv:
        check('curv', s['curv'], 'kurvigt')
    ml = MOUNT_LIMITS[s.get('mount') or 'styre']
    steer, v_rel = s.get('steer'), s.get('v_rel')
    if steer is not None and steer >= ml['trail_steer']:
        level = max(level, 1)
        rel = v_rel if v_rel else 1.0
        slow = rel < 0.85
        hard = ((ml['hard_score'] is not None and steer * rel ** -SPEED_EXP >= ml['hard_score']) or
                (ml['v_rel_hard'] is not None and v_rel is not None and v_rel <= ml['v_rel_hard']))
        if hard:
            level = 2
            why.append((2, 'långsam på stig' if slow else 'mycket styrande'))
        else:
            why.append((1, 'stig'))
    walk = LIMITS['walk_kmh'][1]
    if walk is not None and s['speed'] is not None and s['avg_grade'] >= 5 and s['speed'] < walk:
        level = 2; why.append((2, 'gångfart i uppförsbacke'))
    why.sort(key=lambda w: -w[0])
    return level, [w[1] for w in why]


def per_scale(secs):
    """Mätvärden sammanställda per manuellt mtb:scale-värde, för kalibrering."""
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
    """mount: None = avgör per sektion från pulsen, 'arm' eller 'styre' = hela passet."""
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
            sys.exit('--mount ska vara ' + ' eller '.join(MOUNTS))
    rows = parse(args[0])
    a = analyze(rows, build_profile(rows), mount=mount)
    print('Vägfart %.1f km/h. Klockan: %s' % (a['v_road'], ', '.join(
        '%s %.1f km' % (mm, m / 1000) for mm, m in a['mount_m'].items() if m)))
    for c in a['climbs']:
        print('lång backe %d  vid %.2f km  %4d m  +%.1f m  snitt %.1f %%' % (
            c['id'], c['start_d'] / 1000, c['length_m'], c['gain'], c['avg']))
    total = sum(s['length_m'] for s in a['sections'])
    for L, name in enumerate(LEVELS):
        m = sum(s['length_m'] for s in a['sections'] if s['level'] == L)
        print('%-15s %6.0f m  %3.0f %%' % (name, m, 100 * m / total if total else 0))
    print('\nPer mtb:scale (median):')
    for p in a['per_scale']:
        print('  scale %s  %5d m  fart %s km/h  cv %s  lutning %s %%  kurv %s  stopp/km %s  nivåer %s %%' % (
            p['scale'], p['length_m'], p['speed'], p['cv'], p['grade'], p['curv'], p['stops_per_km'], p['levels']))
    print('Sensorer:', ', '.join(k for k, v in a['has'].items() if v) or 'inga (appen v0.2)')


if __name__ == '__main__':
    main()
