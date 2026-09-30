# Changelog

## Unreleased

Analysis tools:
- Two modes for where the watch was mounted, on the handlebar or on the wrist. The mode is detected per
  section from the heart rate, or set with `--mount wrist|handlebar`. Wrist sections are dashed on the map.
- New assessment: trail is decided by the steering, hard trail by the steering and the speed relative to
  the day's road speed. The limits are recalibrated, see [docs/assessment.md](docs/assessment.md).
- `roughness` no longer affects the level.
- `tools/fitdump.py` reads `device_info`, so connected heart rate straps are visible.
- Unit tests in `tools/test_trailanalysis.py`.

Project:
- The documentation is split into the README and `docs/`. A Makefile with `build`, `package` and `test`, and GitHub Actions for the tests.
- Screenshots of the watch and the map, and an example map in `docs/example/`.
- MIT license.
- Research notes in `docs/research.md`: how the model was found, ideas for a better algorithm, and what data is needed.
- 58 devices in `manifest.xml` instead of only the Epix Gen 2, after checking Garmin's device definitions.
  `tools/devicecheck.py` checks which watches can run the app. See `docs/devices.md`.

## 0.3

Watch app:
- Motion sensors: developer fields `roughness`, `jolt` and `steer` on every record.
- Heart rate and ANT+ cadence and speed are enabled via `Sensor.setEnabledSensors`.
- Live sensor values on the screen while recording.
- Unit tests for `motionMetrics()` in `test/`.

Analysis tools:
- `tools/fitdump.py` reads altitude, distance, speed, heart rate and cadence, and treats `NaN` as a missing value.
- `tools/fitmap.py` shows an elevation profile, steep slopes and the automatic assessment.
- `tools/trailanalysis.py`: automatic assessment per 25 m section.
- `tools/trailsegments.py`: trail segments between junctions from OpenStreetMap, comparison with
  the OSM `mtb:scale` and writing the tag to OSM from the map page.

## 0.2

- Explicit continuous GPS via `Toybox.Position`.
- GPS status on the screen.
- `mtb_scale` is written in step with the records instead of only on button presses.
- Vibration also on start, pause, resume and save.
- `PAUSED` status, color coding and a layout relative to the screen size.
- Safe shutdown in `onStop()`.
- `tools/fitdump.py` for inspecting FIT files.
- `tools/fitmap.py` for a color-coded map and GeoJSON.

## 0.1

- First version: `mtb_scale` as a developer field, changed with UP and DOWN and written on button presses.
