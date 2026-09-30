# The watch app: implementation

How the app in `source/` works. For usage, see the [README](../README.md).

## Continuous GPS
`Position.enableLocationEvents(Position.LOCATION_CONTINUOUS, ...)` is called when the view
is shown, and GPS stays on until the app exits. So it is not turned off during a pause.
The module is called `Toybox.Position`. The permission in the manifest is called `Positioning`.

## `mtb_scale` as state
The value is kept in `_scale` in `MtbSurveyView`. UP and DOWN only change this state.
The initial value is 1.

## Developer field on every record
The field is created with `Session.createField("mtb_scale", 0, DATA_TYPE_UINT8,
{ :mesgType => MESG_TYPE_RECORD, :units => "grade" })`.

`Field.setData()` only queues the value for the next record the system writes.
That is why `_scale` is written to the field again:

1. once per second from a `Timer` (`onTick`),
2. on every position event (`onPosition`),
3. immediately on UP/DOWN,
4. immediately on start and on resume after a pause.

Writing only happens while the session is recording. A value changed during a pause
therefore ends up on the first record after resuming.

## Motion sensors
The accelerometer and gyroscope are read 25 times per second via `Sensor.registerSensorDataListener`,
in batches of one second. Each batch becomes three float developer fields on the record:

| Field | Unit | What |
|---|---|---|
| `roughness` | mG | RMS of the acceleration magnitude around the mean for the second. Shaking from roots and rocks. |
| `jolt` | mG | Largest deviation during the second. Single hard jolts. |
| `steer` | degrees/s | RMS of the rotation rate around the vertical axis, after subtracting the mean for the second. Small quick steering corrections, not smooth curves. |

The vertical axis is taken from the accelerometer's mean vector, that is gravity. So the values do not depend on
how the watch is mounted. **Put the watch on the handlebar** for the best signal. On the wrist, the arm damps the jolts.
Preferably ride the same bike every time, since suspension and tire pressure affect the shaking.

If the gyroscope cannot be started, only the accelerometer is registered, and `steer` is left out.
Sensor values older than 3 s are not written.

`Sensor.setEnabledSensors` turns on the watch's heart rate sensor and paired ANT+ cadence and speed sensors.
The cadence then ends up in the standard fields of the FIT file.

The calculation is in the pure function `motionMetrics()` and is unit tested in `test/`.

## Shutdown
`AppBase.onStop()` saves any remaining session and turns off the timer and GPS.
So the track is not lost if the app exits some other way than through BACK.

## Permissions in `manifest.xml`
| Permission | Used by |
|---|---|
| `Positioning` | `Toybox.Position` |
| `Fit` | `Toybox.ActivityRecording` |
| `FitContributor` | `Toybox.FitContributor`, `Session.createField` |
| `Sensor` | `Toybox.Sensor`: accelerometer, gyroscope, external sensors |

`minApiLevel` is 3.3.0, because the gyroscope requires it.
