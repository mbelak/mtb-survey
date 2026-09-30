# FIT file fields

The app records a normal cycling activity. The sport is `cycling` and the sub sport `mountain`.
In addition to Garmin's standard fields, it writes four developer fields on **every** record message, one per second.

| Field id | Name | Type | Unit | Contents |
|---|---|---|---|---|
| 0 | `mtb_scale` | uint8 | `grade` | The value on the watch screen, 0 to 6. Changed with UP and DOWN. |
| 1 | `roughness` | float32 | `mG` | Shaking: RMS of the acceleration magnitude around the mean for the second. |
| 2 | `jolt` | float32 | `mG` | Largest deviation of the acceleration magnitude during the second. |
| 3 | `steer` | float32 | `deg/s` | Steering corrections: RMS of the rotation rate around the vertical axis, after subtracting the mean for the second. |

- The accelerometer and gyroscope are read 25 times per second. The values are computed per second.
- The vertical axis is taken from gravity, that is the accelerometer's mean vector. The values therefore do not depend on how the watch is rotated.
- A smooth curve gives no `steer`. Only quick corrections within the second count.
- `steer` is missing if the gyroscope could not be started.
- Sensor values older than 3 seconds are not written. The field is then missing on the affected records.
- The calculation is in the function `motionMetrics()` in `source/MtbSurveyView.mc` and is tested in `test/`.

## Other fields the analysis uses

| Field | Message | Used for |
|---|---|---|
| `position_lat`, `position_long` | record | the track |
| `enhanced_altitude` | record | elevation profile and grade |
| `distance`, `enhanced_speed` | record | distance and speed |
| `heart_rate` | record | detecting whether the watch was on the wrist |
| `device_type` = 120 | device_info | a connected heart rate strap, in which case the heart rate says nothing about where the watch was |
| `timer` stop and start | event | pauses, where the track is broken |

## Reading the file

`tools/fitdump.py` is a standalone decoder without dependencies. It prints each record with its
developer fields and ends with a summary:

```
python3 tools/fitdump.py activity.fit
```

From Python:

```python
from fitdump import parse
for kind, msg, dev in parse('activity.fit'):
    if kind == 'record':
        print(msg['ts'], msg['lat'], msg['lon'], dev.get('mtb_scale'), dev.get('steer'))
```

`parse()` returns a list of tuples `(kind, fields, developer_fields)`, where kind is `record`, `event`,
`device_info` or `field_description`. The timestamp `ts` is in seconds from the FIT epoch
1989-12-31 00:00 UTC.

Other FIT libraries, such as Garmin's FIT SDK or the Python package `fitparse`, also read the fields.
Garmin Connect, however, does not show them for sideloaded apps.
