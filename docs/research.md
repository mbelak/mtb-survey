# Research notes: finding a model for trail difficulty

This document explains how the automatic assessment came to be: which data exist, what was tried,
what went wrong along the way, and what the next person should do. It is written so that anyone can
pick up the work. The current rules and their accuracy are summarized in [assessment.md](assessment.md).

> **The model is trained on far too little data.** All limits come from **one** hand-labelled ride by
> **one** rider on **one** bike in **one** forest. The test data are the same trails ridden on another
> day. The numbers below show that the approach is promising, not that it works in general.
> More labelled rides are the single most important next step. See [What data is needed](#what-data-is-needed).

**Ideas, criticism and contributions to the algorithm are very welcome.** The approach so far is a
first, hand-tuned attempt by one person. If you know signal processing, statistics, machine learning or
mountain biking, you can probably improve it. See [Contributing to the algorithm](#contributing-to-the-algorithm).

## The goal

The long-term aim is that riders just ride, and their trails are inventoried and mapped in
OpenStreetMap with a difficulty, so that routes can later be planned by difficulty. A person still
reviews each value before it is written, as OpenStreetMap's rules for automated edits require.
The step this document is about is the one in between:

Estimate, for every 25 m of a ride, how difficult the trail is, from what the watch records:
GPS, elevation, speed and the three motion values `roughness`, `jolt` and `steer`
(see [fit-fields.md](fit-fields.md)). The output should help decide `mtb:scale` for trails in
OpenStreetMap, or at least point out where OSM and the rider disagree.

The labels used so far are **not** OSM's `mtb:scale`. The rider used a simpler scale focused on
riding with children:

| Label | Meaning |
|---|---|
| 0 | gravel road or asphalt |
| 1 | child-friendly trail |
| 2 | trail that is not child-friendly |

## The data

| Ride | Length | Watch | Labels | Used for |
|---|---|---|---|---|
| A, 2026-09-25 | 13 km | handlebar, chest strap for heart rate | yes, with the buttons during the ride | calibration |
| W, 2026-09-29 | 7.6 km | wrist | no; the rider said afterwards it was only easy trails and gravel roads | sanity check |
| P, 2026-09-30 | 11.5 km | wrist for the first half, handlebar for the second | no, only markers | wrist versus handlebar, and testing |

Ride P was designed as an experiment: transport, the same loop of about 3.6 km twice, and transport
back. The rider marked the start and end of each loop with a quick UP then DOWN, which shows up in the
FIT file as the value sequence 0, 1, 0. The watch sat on the wrist for the first loop and on the
handlebar for the second. Ride A covered almost the same trails, so its labels could be transferred to
ride P by position (see [Methods](#methods)).

The rides are **not** in the repository, because they contain GPS positions near the rider's home.

## Timeline and what was learned

### 1. First calibration against ride A

The first limits were fitted by hand against ride A: `roughness` of at least 425 mG meant a trail,
`steer` of 26 and 36 °/s meant level 1 and 2, and a grade of 14 % meant level 2. This matched the labels
on 71 % of the distance, and 70 to 71 % within each level. Speed, grade, stops and curviness added
less than one percentage point and were switched off.

### 2. The wrist ride, and a wrong conclusion

Ride W was recorded on the wrist without labels. The automatic assessment called 88 % of it easy.
The roughness on the wrist was about half of the handlebar values on gravel, so the conclusion at the
time was that the arm damps the shaking.

**This was wrong.** It compared two different rides on different trails. The paired ride P later showed
the opposite. **Lesson: only compare sensor values on the same stretch of trail.**

### 3. Which half was on the wrist?

The heart rate answered it. The optical heart rate sensor only works against skin, so the heart rate is
present on the wrist and missing on the handlebar. In ride P, heart rate was present until a 57 second
stop at the loop change, and missing after it. This is now how the tools detect the mount automatically.
It fails when a chest strap is connected, which the FIT file reveals as a `device_info` message with
device type 120. Ride A had a chest strap, so its heart rate says nothing about the mount.

### 4. Wrist versus handlebar on the same loop

The two loops were matched by position in 250 m pieces. On the wrist, `roughness` was 1.66 times and
`steer` 2.37 times the handlebar value. All 15 pieces pointed the same way. The arm adds its own
movement instead of damping.

The handlebar was also repeatable between days. Ride A and ride P overlap on about 5.7 km:

| Same stretches, handlebar | roughness | steer | speed |
|---|---|---|---|
| 2026-09-25 | 663 mG | 29.1 °/s | 12.8 km/h |
| 2026-09-30 | 607 mG | 27.7 °/s | 12.0 km/h |

Whether the wrist is repeatable between days is **not known**. Rides W and P only overlap on about
450 m, and the speed there was 9.4 against 15.2 km/h.

### 5. The labeller drifts

When shown the result, the rider said that the whole loop, except the first trails, should be level 2.
But on 2026-09-25 the same rider had labelled the same loop as about 10 % level 0, 50 % level 1 and
40 % level 2. The existing limits reproduced the old labels reasonably well. The rider chose to keep the
old labels as ground truth.

**Lesson:** a human's scale moves over time, and the model can only be as consistent as its labels.
Write down what each level means, with examples, before labelling, and re-label a known stretch now
and then to check for drift.

### 6. A biased comparison, and how it was fixed

To compare wrist and handlebar, the handlebar's automatic level was first used as ground truth for the
wrist. That favours the handlebar, since the handlebar is then compared with itself. The comparison was
redone with the rider's own labels from ride A, transferred by position to both loops of ride P.

How well each value separates the levels, as AUC (0.5 means no separation, 1.0 means perfect):

| Mount and value | 0 against 1 | 1 against 2 |
|---|---|---|
| Handlebar, steer | 0.87 | 0.68 |
| Handlebar, roughness | 0.82 | 0.53 |
| Wrist, steer | 0.87 | 0.46 |
| Wrist, roughness | 0.87 | 0.40 |

Both mounts tell road from trail equally well. Only the handlebar's steering says anything about easy
against hard trail.

### 7. Speed carries the missing information

The rider slows down on hard trails. That is the strongest single signal for level 1 against 2, with an
AUC of about 0.72 to 0.80 depending on the ride, and it works the same on the wrist and the handlebar.

Within the same level, `roughness` barely grows with speed, roughly as speed to the power 0.19.
`steer` falls with speed, roughly as speed to the power −0.56, because slow riding needs more balance
corrections. So part of the steering signal is really speed.

Dividing roughness by speed also separated 1 from 2, with an AUC of about 0.76. That is not because it
corrects the shaking for speed. It works because the result is mostly a speed measure.

### 8. Which speed reference?

Speed only works across rides if it is relative to something. Ride W was a slow, easy ride: its road
speed was 11.6 km/h, against 15 to 17 km/h on the other days. A good reference must not call that ride
hard. Same method for every reference: speed alone, grade-adjusted, with the limit set so that ride A gets
its own share of level 2. Lower is better, since ride W had no hard trails.

| Speed reference | Share hard on ride W |
|---|---|
| Absolute speed | 32 % |
| Median speed of the whole ride | 19 % |
| 80th percentile of the ride's speed | 13 % |
| The day's road speed (chosen) | 10 % |

With the limits actually fitted for the rule, a fixed 10.9 km/h called 52 % of ride W hard,
against 13 % for 0.62 of the road speed. A sliding 20 minute window was only tested together with
steering, where it called 15 % hard, against 0 to 7 % for the road speed in the same setup.

- **Absolute speed** fails when the pace changes, for example when riding with children.
- **The ride's median and sliding windows** depend on how much trail the ride contains. On a long hard
  stretch the window's own reference drops and hides the difficulty. A 5 minute window also made road
  against trail worse.
- **The road speed of the day** is the median grade-adjusted speed on the calmest 35 % of the sections,
  meaning those with the least steering. It follows the day's pace but not the share of trail.
  Uphill slows everyone, so speed is adjusted with `speed ~ exp(−0.036 · grade %)`, fitted on road
  sections of ride A.

### 9. The current rule

For the handlebar, a logistic regression on log steer and log relative speed gave weights 0.85 and
−0.56. That was turned into a readable rule: `steer · v_rel^−0.66 ≥ 47` means level 2. A section is a
trail from 24 °/s of steer. For the wrist only relative speed is used for level 2, at most 0.62 of the
road speed, and 59 °/s of steer means trail. The wrist trail limit comes from the same ride it was
tested on.

Balanced accuracy, where each level weighs the same:

| Test | Three levels | 1 against 2 |
|---|---|---|
| Ride A, handlebar (calibration) | 0.73 | 0.74 |
| Ride P, handlebar (another day) | 0.71 | 0.72 |
| Ride P, wrist | 0.64 | 0.64 |
| Ride P, handlebar, old limits | 0.53 | 0.58 |

Part of the gain came from dropping the roughness limit. The gravel roads in ride P shook more than
425 mG and were called trail.

With the new rule, ride W came out 100 % easy. On the wrist that day, the steering was so low that no
section reached the wrist trail limit. So the wrist limit does not hold on every day.

### 10. Shaking does not help

Because the handlebar measures shaking well, many ways to use it were tried, both alone and on top of
steering and speed:

- mean, 90th percentile and variation of `roughness` per section
- median and 90th percentile of `jolt`, and `jolt` divided by `roughness`
- share of seconds with a jolt above 2000, 3000, 4000, 5000 or 6000 mG
- sliding windows from 25 m to 1 km, and the mean over whole trail segments between junctions

None of them separated 1 from 2. The AUC was between 0.33 and 0.63, often reversed on long windows.
Added to steering and speed, they changed the result by at most 0.02, which is within noise.
Over whole trail segments, steering reached 0.81, speed 0.72 and shaking 0.39.

Two likely reasons. First, the rider slows down on the hard parts, which removes shaking. Second,
child-friendliness is about steepness, narrow passages and technical steering more than about a rough
surface: a gravel road can shake a lot and still be easy. Shaking tells road from trail well
(AUC 0.85 to 0.90), but not better than steering. It probably describes the OSM tag `smoothness` better
than `mtb:scale`.

## How OpenStreetMap is used

- **Trail network.** The tools fetch paths and roads around the ride from Overpass and split them at
  junctions into trail segments. Each segment gets one value: the highest level that occurs over at least
  50 m in a row. This turns noisy 25 m sections into something that can be tagged. See
  [map-page.md](map-page.md).
- **Comparison.** Each ridden OSM way is compared with the `mtb:scale` already in OSM: missing, equal,
  lower or higher. This is where a rider finds trails to tag or check.
- **Not as ground truth, yet.** OSM's `mtb:scale` is a different scale from the one used here. It rates
  technical difficulty from 0 to 6, while the labels rate child-friendliness. It is also added by many
  people with different standards, and most trails have no value. On the loop in ride P most trails were
  tagged 2, some 3. The handlebar steering still rose with OSM's value: median 23, 28, 33 and 35 °/s
  for OSM levels 0 to 3. So OSM tags could serve as weak extra labels, or as an independent check,
  but only with the scale difference in mind.
- **Other tags.** `surface`, `smoothness` and `trail_visibility` are shown next to each way. They are
  candidates for new labels, for example testing whether shaking predicts `smoothness`.

## Methods

These choices matter for anyone repeating the analysis.

- **Sections.** The ride is resampled every 5 m and split into 25 m sections. Sensor values and speed are
  smoothed with a sliding median over 5 sections, which is 125 m, before a level is set.
- **Transferring labels by position.** A section on ride P gets the label of the nearest labelled point
  on ride A within 10 m. It needs at least 80 % agreement within the section, otherwise it is left out.
  This makes it possible to test on another day without labelling again, but only on the same trails.
- **Balanced accuracy** is the mean of the hit rate per level, so the most common level cannot dominate.
- **AUC** measures how well one value orders two levels, regardless of the limit.
- **Uncertainty.** Neighbouring sections are strongly correlated because of the smoothing. Confidence
  intervals were therefore computed with a block bootstrap over blocks of 10 sections, 250 m.
  They were typically ±0.1 on AUC and balanced accuracy. Differences of a few hundredths mean nothing.
- **Transfer test.** Limits are always fitted on one ride and tested on another. An AUC within one ride
  cannot show whether a reference such as relative speed works across days.
- **Checking the mount.** Heart rate without a chest strap means wrist. Shorter than 60 s gaps or blips
  are ignored.

The analysis scripts were one-off research code and are not in the repository. Everything they did is
described here and can be rebuilt on top of `tools/trailanalysis.py`, which already computes the
sections, the smoothing, the mount and the relative speed.

## Ideas for a better algorithm

The current rule is deliberately simple: two thresholds and one formula, readable by anyone. That was
the right choice for one labelled ride, since anything more flexible would just memorise that ride.
With more data, these are the directions that look most promising, and the reasoning behind each.

**Treat difficulty as a property of the trail, not of the second.** A trail does not change level every
25 m, but the sections do, because of noise. Today this is handled by smoothing over 125 m and, on the
map, by taking the highest level held for 50 m on a trail segment. A model that knows levels persist,
such as a hidden Markov model or a simple penalty on changes, could use the whole trail segment
between two junctions as evidence. The shaking analysis hints at this: over whole segments, steering
separated the levels better (AUC 0.81) than over 125 m (about 0.75).

**Model the rider, not only the trail.** Speed turned out to be the strongest signal, but speed is a
reaction of the rider. It depends on skill, fitness, company, the bike and the mood of the day. The road
speed of the day is a first normalisation. With several riders, a per-rider baseline for both speed and
steering, learned from their own road sections, is the natural next step. This is also why data from
many riders matters more than many rides by one rider.

**Use an ordinal model.** The levels are ordered, 0 < 1 < 2. An ordinal logistic regression on a handful
of features (log steer, log relative speed, grade) fits that structure, gives probabilities instead of
hard levels, and has few parameters. The current rule is roughly a hand-made version of it.
Probabilities would also let the map show how certain each level is.

**Features worth testing with more data.** They were not worth testing on one ride, because any gain
would be indistinguishable from noise:
- the frequency content of the gyroscope and accelerometer, not only the RMS per second. Rocks and roots
  may have a different signature than gravel. This needs a change in the watch app to record more than
  three numbers per second.
- stops and dismounts: short stops on a trail often mean a hard passage
- cadence, where a sensor exists: pedalling out of the saddle, or coasting on descents
- the grade profile over the last 100 to 200 m, not only the maximum in the section
- how the difficulty is distributed: one hard spot on an easy trail is different from a hard trail

**Combine with OpenStreetMap.** Where OSM already has `mtb:scale`, `surface`, `smoothness` or
`trail_visibility`, those are independent evidence. A model could use them as a prior and let the ride
confirm or question them. That needs a mapping between the child-friendly scale and OSM's scale, which
itself could be learned from rides on tagged trails.

**Beware of these traps.** Each of them happened during this work:
- comparing sensor values between different rides on different trails
- using the model's own output as ground truth for a comparison
- testing on the ride the limits were fitted on
- trusting small differences, when neighbouring sections are strongly correlated
- assuming that a labeller's scale stays the same over time

**Different watches.** The limits were set on one Epix Gen 2 mounted on one handlebar. Other watches may
have other sensors, and other mounts may shake differently. Rides from other devices would show whether
the limits need a per-device factor. See [devices.md](devices.md).

## Contributing to the algorithm

Every kind of contribution helps, and none is too small:

- **Ideas and criticism.** Open an issue if you see a flaw in the reasoning here, or know a better method.
  Arguments with a source or a small experiment behind them are the most useful.
- **Labelled rides.** See [What data is needed](#what-data-is-needed) and
  [How to contribute data](#how-to-contribute-data).
- **Code.** A proposal for a new rule or model should come with its evaluation: which labelled rides it
  was fitted on, which it was tested on, and the balanced accuracy and AUC as in the tables above.
  Fit on some rides and test on others. The limits live in `MOUNT_LIMITS` and `SPEED_EXP` in
  `tools/trailanalysis.py`, and the tests in `tools/test_trailanalysis.py` describe the expected behaviour.
- **An evaluation tool.** A script that takes a set of labelled FIT files and reports balanced accuracy,
  AUC with block bootstrap intervals, and leave-one-ride-out results would make every later change easier
  to judge. It does not exist yet, and it is probably the most valuable piece of code to add.
- **Other watches.** A ride on another device, labelled or not, tells whether the sensors behave the same.

## What data is needed

The current limits should be treated as a first guess. To trust them, and to learn a better model,
the project needs **many more labelled rides**. In order of importance:

1. **Handlebar rides on new trails, labelled with the buttons.** Different forests, surfaces and
   gradients. This is the only way to see whether the rule works outside the one forest it was tuned in.
   A rough target is ten rides and 100 km, with plenty of all three levels. That is a guess, not a
   calculation.
2. **Several riders and bikes.** Speed and steering depend on the rider, the bike, tyre pressure and
   suspension. Each rider may need their own road speed, and perhaps their own limits.
3. **The same trails ridden again.** Repeated rides show how repeatable the values and the labels are.
4. **Labelled wrist rides**, if the wrist mode should become usable. The wrist trail limit comes from a
   single ride and failed on another day.
5. **A written labelling guide** with examples of each level, used by everyone who labels. Consistent
   labels matter as much as more labels.

With enough data it becomes possible to:

- fit the limits, or a small ordinal or logistic model, with leave-one-ride-out cross-validation,
  instead of tuning by hand
- test other features that were not worth testing on one ride: cadence, stops, curviness and the
  history of the previous few hundred metres
- use OSM's `mtb:scale` as extra labels, and learn how the child-friendly scale maps to it
- test whether shaking predicts OSM's `smoothness`

## How to contribute data

Labelled FIT files are the most useful contribution. They contain your GPS positions, so think before
sharing them:

- Cut off the start and end of the ride, at least one or two kilometres, so that your home is not
  visible. The example map in `docs/example/` was made that way.
- Say which scale you used, where the watch sat, whether a chest strap was connected, and anything
  special about the ride, such as riding with children.
- Open an issue to agree on how to share the files before sending them.

## Open questions

- Does the handlebar rule hold on other trails, riders and bikes?
- Is the wrist repeatable between days at all, and can a per-ride normalisation fix it?
- Is 25 m sections with 125 m smoothing the right scale, or should the level be decided per trail
  segment from the start?
- How should the child-friendly scale map to OSM's `mtb:scale`?
- Can the watch app record the mount directly, so that heart rate is not needed?
