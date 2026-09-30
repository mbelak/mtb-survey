# Automatic assessment

The analysis gives each 25 m section a level based on the watch sensors and the speed. It estimates the
same scale as the buttons: 0 = gravel road or asphalt, 1 = child-friendly trail, 2 = trail that is not child-friendly.

```
python3 tools/trailanalysis.py activity.fit [--mount wrist|handlebar]
```
`fitmap.py` also runs the analysis automatically. The track is split into 25 m sections, and each section
gets the level **easy**, **needs experience** or **hard for kids**, with the reasons in plain text:

| Reason | Measurement |
|---|---|
| steep | maximum grade in the section |
| long climb | the section is part of a continuous climb of at least 12 m up over at least 150 m |
| walking pace uphill | median speed below 4 km/h where the grade is at least 5 % |
| uneven speed, stopped | the speed varies a lot, or seconds below 2 km/h |
| twisty | change of direction per 100 m, measured over a 20 m chord. **Off by default**, because it is coarse (GPS noise). Turn it on with `USE_CURV = True` in `tools/trailanalysis.py`. |
| trail, lots of steering, slow on trail | `steer` from app v0.3 and the speed relative to the day's road speed, see below |

On the map page the **Automatic / Your assessment** button switches the coloring of the map and the
elevation profile. Automatic mode is the default. The address `...html#manual` opens your own assessment directly.

Sensor values and speed are smoothed with a moving median over `SMOOTH_N` sections (5 of them, that is 125 m)
before the level is set. Without smoothing, the 25 m values are too noisy.

**Calibration:** the table *Measurements per mtb:scale* shows the median of each measurement for each
manual value. A measurement that separates your assessments increases from row to row. Adjust
`MOUNT_LIMITS` at the top of `tools/trailanalysis.py` based on that. The more rides with a manual assessment, the more reliable.

## Watch on the handlebar or on the wrist

The mode is detected per section. Heart rate without a connected heart rate strap means that the watch was
on the wrist, since the optical heart rate sensor gets no contact on the handlebar. Heart rate dropouts, or
heart rate readings shorter than a minute, do not change the mode. With a heart rate strap, the handlebar is assumed.
`--mount wrist` or `--mount handlebar` to `fitmap.py` or `trailanalysis.py` sets the mode for the whole ride.
On the map, wrist sections are dashed, and a line below the level table says how much was measured on the wrist.

**The handlebar is recommended.** The same stretches gave the same values on different days, within 10 %. On the
wrist, shake and steering are 1.7 and 2.4 times higher respectively, and they do not separate an easy trail from a hard one.

## The levels (calibrated 2026-09-30)

The scale: 0 = gravel road or asphalt, 1 = child-friendly trail, 2 = trail that is not child-friendly.
The ground truth is the manual assessment from the ride on 2026-09-25 (handlebar). It was transferred by location to the
ride on 2026-09-30, where the same loop was ridden once with the watch on the wrist and once on the handlebar.

| | Handlebar | Wrist |
|---|---|---|
| Trail (1) | `steer` at least 24 °/s | `steer` at least 59 °/s (preliminary) |
| Hard trail (2) | `steer · (v_rel)^-0.66` at least 47 | `v_rel` at most 0.62 |
| Both | maximum grade of at least 14 % gives 2 | |

`v_rel` is the speed divided by the day's road speed, with the grade evened out (speed ~ e^(−0.036 · grade %)).
The day's road speed is the median of the grade-adjusted speed on the 35 % calmest sections, that is
the ones with the least steering, computed within each mode. If the ride has too little calm distance, 15 km/h is used.
You slow down on hard trails, and the speed relative to the day's road speed copes with the pace varying between days.
Absolute speed does not: a calm ride got 52 % hard with a fixed speed limit.

The limits are in `MOUNT_LIMITS` and `SPEED_EXP` at the top of `tools/trailanalysis.py`.
`roughness` is shown but does not affect the level. It did not separate 1 from 2, and rough gravel roads were
wrongly classed as trail with the earlier limit of 425 mG.

Balanced accuracy, where each level has equal weight. Chance gives 0.33 for three levels and 0.50 for 1 vs 2.

| Ride | Three levels | 1 vs 2 | Road vs trail |
|---|---|---|---|
| 25 Sep, handlebar (calibration) | 0.73 | 0.74 | 0.87 |
| 30 Sep, handlebar (another day) | 0.71 | 0.72 | 0.83 |
| 30 Sep, wrist | 0.64 | 0.64 | 0.82 |

With the earlier limits (`steer` 26/36, `roughness` 425), the ride on 30 Sep with the watch on the handlebar gave 0.53 and 0.58.

Limitations: there is only one manually assessed ride, and the test was on the same trails. The wrist trail limit
comes from the same ride it is tested on. The ride on 2026-09-29, with easy trails and the watch on the wrist,
got 100 % easy. The wrist values were much lower that day, so the limit does not hold every day.

## What was tested and rejected

The analysis was done on 2026-09-30 against the same ground truth. The separation between 1 and 2 was measured with AUC,
where 0.50 means no difference and 1.00 means perfect separation.

**Speed reference.** Within one ride, all speed variants give almost the same separation. The difference shows when a limit
from one ride is used on another. The check was a calm ride with only easy trails and a road speed of
11.6 km/h, against 15 to 17 km/h on the other days.

| Speed reference | Share hard on the calm ride |
|---|---|
| Absolute speed | 52 % |
| Median speed of the whole ride | 18 % |
| Moving 20 minutes | 15 % |
| The day's road speed, grade-adjusted (chosen) | 13 % |

The median speed of the whole ride and moving windows are affected by how much trail the ride contains.
A 5-minute window also made the separation between road and trail worse.

**Shake.** No way of computing the shake separated 1 from 2 or added anything beyond steering and speed.
Tested: mean, 90th percentile, variation, median and 90th percentile of the jolts, jolt divided by shake,
share of seconds with a jolt above 2000 to 6000 mG, moving windows from 25 m to 1 km, and the mean per
trail segment. The AUC for 1 vs 2 was between 0.33 and 0.63, often reversed for long windows. Per trail segment,
shake gave 0.39, steering 0.81 and speed 0.72. Between road and trail the shake works, with 0.85 to 0.90,
but not better than the steering. Shake rather measures how smooth the surface is, and probably fits the OSM tag
`smoothness` better than `mtb:scale`.

**Shake per speed** separated 1 from 2 (AUC about 0.75), but only because the measure in practice becomes a speed measure.
Within the same level, the shake only increases weakly with speed, roughly as speed to the power of 0.19.

## Recalibrate

More manually assessed rides make the limits more reliable, especially on trails that were not part of the calibration.

1. Ride with the watch on the handlebar and assess the trail with the buttons during the ride.
2. Make the map with `python3 tools/fitmap.py ride.fit` and read the table *Measurements per mtb:scale*.
3. Compare steering and speed per level, and adjust `MOUNT_LIMITS` and `SPEED_EXP`.
4. Run `python3 tools/test_trailanalysis.py`. The tests use the order of magnitude of the limits,
   so a large change may require adjusting the test cases.
