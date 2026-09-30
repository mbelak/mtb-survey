"""python3 tools/test_devicecheck.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devicecheck as dc


def device(api='5.2.0', app=True, accel=100, gyro=100, keys=('up', 'down', 'enter', 'esc')):
    compiler = {'displayName': 'Test', 'deviceFamily': 'round-416x416',
                'appTypes': [{'type': 'watchApp'}] if app else [{'type': 'datafield'}],
                'partNumbers': [{'connectIQVersion': '3.2.0'}, {'connectIQVersion': api}]}
    simulator = {'keys': [{'id': k} for k in keys],
                 'sensorSampleRate': {'maxAccelRate': accel, 'maxGyroRate': gyro}}
    return compiler, simulator


# Everything the app needs: full support
assert dc.check(*device())['support'] == 'full'
# No gyroscope: the app records, but there is no steer, so no automatic assessment
r = dc.check(*device(gyro=0))
assert r['support'] == 'record-only' and 'no gyroscope' in r['reasons'], r
# Touch-only watch without UP/DOWN: the difficulty cannot be set
r = dc.check(*device(keys=('enter', 'esc')))
assert r['support'] == 'no' and 'no UP/DOWN buttons' in r['reasons'], r
# API level below 3.3 on every part number: not supported
r = dc.check(*device(api='3.2.0'))
assert r['support'] == 'no' and any('API' in x for x in r['reasons']), r
# The highest API level over all part numbers counts
assert dc.check(*device(api='3.3.0'))['support'] == 'full'
# Device apps not allowed (only data fields etc.)
assert dc.check(*device(app=False))['support'] == 'no'
# Accelerometer slower than the app's 25 Hz
assert dc.check(*device(accel=10))['support'] == 'no'

print('devicecheck: all tests passed')
