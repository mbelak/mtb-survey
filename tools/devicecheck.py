#!/usr/bin/env python3
"""Which Garmin devices can run MTB Survey? Reads the device definitions of the Connect IQ SDK.

The app needs:
  - Connect IQ API level 3.3 or later (for the gyroscope), and device apps allowed
  - an accelerometer that can sample at 25 Hz or more
  - a gyroscope, otherwise there is no `steer` and the automatic assessment does not work
  - UP and DOWN buttons to set the difficulty; the app does not support touch input

Only devices downloaded with the SDK Manager are checked. Download more there to check them too.

Usage:  python3 tools/devicecheck.py [devices_dir] [--markdown]
Default devices_dir: ~/Library/Application Support/Garmin/ConnectIQ/Devices (macOS)
                     or ~/AppData/Roaming/Garmin/ConnectIQ/Devices (Windows)
"""
import json, os, sys

MIN_API = (3, 3, 0)
SAMPLE_HZ = 25                          # same as SAMPLE_HZ in source/MtbSurveyView.mc
KEYS = ('up', 'down', 'enter', 'esc')   # keys handled by source/MtbSurveyDelegate.mc


def _ver(v):
    return tuple(int(x) for x in str(v).split('.')[:3])


def check(compiler, simulator):
    """Support level for one device, from its compiler.json and simulator.json.
    Returns {'support': 'full' | 'record-only' | 'no', 'reasons': [...], 'api': 'x.y.z', ...}."""
    apis = [p.get('connectIQVersion') for p in compiler.get('partNumbers', []) if p.get('connectIQVersion')]
    api = max(apis, key=_ver) if apis else '0.0.0'
    apps = {a.get('type') if isinstance(a, dict) else a for a in compiler.get('appTypes', [])}
    keys = {k.get('id') for k in simulator.get('keys', [])}
    rates = simulator.get('sensorSampleRate') or {}
    accel, gyro = rates.get('maxAccelRate', 0) or 0, rates.get('maxGyroRate', 0) or 0

    blocking, degrading = [], []
    if _ver(api) < MIN_API:
        blocking.append('API level %s is below 3.3' % api)
    if 'watchApp' not in apps:
        blocking.append('device apps not allowed')
    if accel < SAMPLE_HZ:
        blocking.append('accelerometer below %d Hz' % SAMPLE_HZ)
    if not {'up', 'down'} <= keys:
        blocking.append('no UP/DOWN buttons')
    elif not set(KEYS) <= keys:
        blocking.append('missing buttons: ' + ', '.join(sorted(set(KEYS) - keys)))
    if gyro <= 0:
        degrading.append('no gyroscope')
    support = 'no' if blocking else ('record-only' if degrading else 'full')
    return {'support': support, 'reasons': blocking + degrading, 'api': api,
            'name': compiler.get('displayName', ''), 'screen': compiler.get('deviceFamily', '')}


def default_dir():
    home = os.path.expanduser('~')
    for d in (os.path.join(home, 'Library', 'Application Support', 'Garmin', 'ConnectIQ', 'Devices'),
              os.path.join(home, 'AppData', 'Roaming', 'Garmin', 'ConnectIQ', 'Devices')):
        if os.path.isdir(d):
            return d
    return None


def scan(devices_dir):
    out = []
    for dev in sorted(os.listdir(devices_dir)):
        try:
            with open(os.path.join(devices_dir, dev, 'compiler.json')) as f:
                c = json.load(f)
            with open(os.path.join(devices_dir, dev, 'simulator.json')) as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        out.append(dict(check(c, s), id=dev))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    d = args[0] if args else default_dir()
    if not d or not os.path.isdir(d):
        sys.exit('Device directory not found. Pass it as the first argument.\n\n' + __doc__)
    rows = scan(d)
    order = {'full': 0, 'record-only': 1, 'no': 2}
    rows.sort(key=lambda r: (order[r['support']], r['id']))
    if '--markdown' in sys.argv:
        print('| Device id | Name | API | Screen | Support | Why |\n|---|---|---|---|---|---|')
        for r in rows:
            print('| `%s` | %s | %s | %s | %s | %s |' % (r['id'], r['name'], r['api'], r['screen'],
                                                     r['support'], ', '.join(r['reasons']) or '–'))
    else:
        for r in rows:
            print('%-24s %-12s %-7s %-22s %s' % (r['id'], r['support'], r['api'], r['screen'], ', '.join(r['reasons'])))
    n = {k: sum(r['support'] == k for r in rows) for k in order}
    print('\n%d devices: %d full, %d record-only, %d not supported' % (len(rows), n['full'], n['record-only'], n['no']),
          file=sys.stderr)


if __name__ == '__main__':
    main()
