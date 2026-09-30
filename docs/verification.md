# What has been verified

Environment: Connect IQ SDK 9.2.0, device profile `epix2`, macOS. Python 3.9 and 3.14, Node 24.

## On the watch (Epix Gen 2, September 2026)

Three rides with version 0.3, 7 to 13 km long, decoded with `tools/fitdump.py`:

- Every record carried `mtb_scale`, position, `roughness`, `jolt` and `steer`. No record lacked any of them.
- Button presses show up in the FIT file in the right place. A quick UP, DOWN sequence gives the values 0, 1, 0
  within a couple of seconds, and it can be used as a marker along the track.
- The watch's heart rate is recorded on the wrist and is missing when the watch is on the handlebar.
  A connected ANT+ heart rate strap shows up as `device_info` with device type 120.
- The same stretches with the watch on the handlebar gave the same `steer` and `roughness` on different days, within 10 %.

**Not verified on the watch**
- Battery use with the sensors on.
- Cadence sensor over ANT+.

## Build and unit tests

- The app and the test variant build for `epix2` with `monkeyc` without errors.
  The only warning is that the launcher icon is 40x40 and is scaled to 60x60.
- The unit tests for `motionMetrics()` pass (4 of 4): a still watch, shaking with known RMS and peak,
  steering with the watch tilted 90 degrees, and that a smooth curve does not count as a correction.
- The Python tests (`test_trailanalysis.py`, `test_trailsegments.py`) and the Node test (`test_osmedit.js`) pass.

## In the simulator (versions 0.1 to 0.3)

- A self-running test variant started recording, changed the value, paused, changed the value during the pause,
  resumed, changed the value and saved. Results:
  - 41 records, one per second, and all 41 carried `mtb_scale`.
  - The value sequence was 1, then 3, then 4 after the pause, then 2. This matches the state.
  - The field description in the file is `mtb_scale`, unit `grade`, uint8, attached to record.
- A control experiment without the periodic writing gave only 5 records over the same time,
  and the value changed during the pause was not included after resuming.
  So the periodic writing is needed.
- The motion sensor listener is registered with both accelerometer and gyroscope, and the FIT file gets
  field descriptions for `roughness`, `jolt` and `steer`. The simulator sends no motion data,
  so the sensor values are empty (`NaN`) there. The real values are verified on the watch, see above.

## The automatic assessment

The limits are calibrated against a single manually assessed ride. See [the assessment](assessment.md) for accuracy
and limitations.
