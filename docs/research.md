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
| 0 | gravel road or asphalt, free of obstacles: no stones, no roots |
| 1 | a six-year-old can ride it without walking. Simpler roots and stones that can be ridden over or around, no big gradients |
| 2 | the child has to walk now and then: too stony, too rooty, rock slabs with small drops, or a nice trail with too steep a climb |
| 3 | an adult has to walk. Rare, and counted as 2 in the analysis |

Note that level 2 is decided by the worst spot on the trail ("has to walk somewhere"), not by its average.

## The data

| Ride | Length | Watch | Labels | Used for |
|---|---|---|---|---|
| A, 2026-09-25 | 13 km | handlebar, chest strap for heart rate | yes, with the buttons during the ride | calibration |
| W, 2026-09-29 | 7.6 km | wrist | no; the rider said afterwards it was only easy trails and gravel roads | sanity check |
| P, 2026-09-30 | 11.5 km | wrist for the first half, handlebar for the second | no, only markers | wrist versus handlebar, and testing |
| T, 2026-10-25 | 23.2 km | wrist, chest strap for heart rate | no | the calibration loop ridden six times in a row; wrist repeatability, and testing |
| N, 2026-10-31 | 18.2 km | handlebar, chest strap for heart rate | yes, with the buttons; **wet**: leaves, slippery roots and mud | testing on new trails (8.6 km) and on ride A's trails (9.6 km) |

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
- **The road speed of the day** was first the median grade-adjusted speed on the calmest 35 % of the sections,
  meaning those with the least steering. It follows the day's pace but not the share of trail.
  Uphill slows everyone, so speed is adjusted with `speed ~ exp(−0.036 · grade %)`, fitted on road
  sections of ride A. Ride T later showed that the calm sections do include slow trail when the ride is
  mostly trail, and the definition was changed, see [11](#11-the-wrist-is-not-repeatable-and-the-reference-dilutes).

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

### 11. The wrist is not repeatable, and the reference dilutes

Ride T, 2026-10-25, was the loop from rides A and P ridden six times in a row, with the watch on the
wrist and no labels. The labels from ride A were transferred by position and cover 20 of its 23 km, so
every labelled section of the loop is measured six times. Three things came out of it.

**The wrist is not repeatable between days.** On the same stretches, the wrist gave 1.6 times the
handlebar's `roughness` and 2.2 times its `steer` on 2026-09-30, but 1.05 and 1.6 times on 2026-10-25.
Within ride T the steering rose lap by lap, from 1.2 to 2.2 times the handlebar value of ride A, while
`roughness` only rose from 1.0 to 1.2 times and the speed stayed within 10 %:

| Lap | steer, T / A | roughness, T / A |
|---|---|---|
| 1 | 1.45 | 0.99 |
| 2 | 1.64 | 1.02 |
| 3 | 1.73 | 1.10 |
| 4 | 2.03 | 1.16 |
| 5 | 1.96 | 1.21 |
| 6 | 2.20 | 1.21 |

At standstill the watch read 2.4 °/s and about 20 mG all through the ride, the same as on the other
rides, so the sensors did not drift. The arm did. Fatigue, grip or the strap's tension are all
possible, and the data cannot tell them apart. The consequence is that no fixed steering limit can work
on the wrist: the wrist trail limit of 59 °/s called 100 % of ride W easy, and on ride T the gravel roads
alone averaged 43 °/s against 16 on the handlebar, so 27 % of them were called trail. Within each lap, `steer` still separated road from trail (AUC 0.72 to 0.86) but not
easy trail from hard (AUC 0.16 to 0.61, mostly reversed), while relative speed separated 1 from 2 in
every lap (AUC 0.64 to 0.93). This settles an open question from before: the wrist is not repeatable,
and only the speed is worth using there.

**The road speed reference dilutes on trail-heavy rides.** Ride T was 76 % trail by label. The calmest
35 % of its sections, by steering, therefore contained a lot of slow trail, and the reference came out
at 12.4 km/h where the gravel roads actually held 16.2. Everything then looked fast, and the wrist rule
found only 19 % of the hard sections. The reference was compared with the true road speed, the
grade-adjusted speed on the label-0 sections, on all rides:

| Reference | A | W | P hb | P wrist | T | worst error |
|---|---|---|---|---|---|---|
| True road speed (label 0) | 16.3 | 10.6 | 15.1 | 16.0 | 16.2 | |
| Median of the calmest 35 % (old) | 17.3 | 11.6 | 15.2 | 15.5 | 12.4 | −3.8 |
| 65th percentile of the calmest 50 % (new) | 17.6 | 12.1 | 16.1 | 16.5 | 14.7 | −1.6 |
| Calm below median and fast above median | 17.5 | 12.4 | 15.8 | 17.4 | 15.9 | +1.8 |
| 65th percentile of the calmest 35 % | 18.5 | 12.4 | 17.2 | 17.6 | 15.9 | +2.6 |

The new definition takes a high percentile of the speed within the calm half instead of its median, so
slow trail that slips into the calm half no longer pulls the reference down. With the limits unchanged,
balanced accuracy went from 0.72 to 0.75 on ride P handlebar, 0.63 to 0.64 on ride P wrist and 0.51 to
0.55 on ride T, stayed at 0.73 on ride A, and ride W stayed 100 % easy. The gains are within the ±0.1
uncertainty of a single ride, but they point the same way on every ride, and the reference now matches
the true road speed within 1.6 km/h everywhere. A ride with no road at all would still fool it.

**A trail limit relative to the day's steering does not transfer.** Because the steering level varied by
a factor 2.7 between rides, a trail limit relative to the ride's own calm steering looked attractive, and
on each ride the best absolute limit was indeed close to the ride's 35th percentile of `steer`. But
fitted on ride A and tested on the others, a relative limit was worse than the absolute one: 0.58 to
0.63 on ride P handlebar against 0.75, and it called 41 to 57 % of the easy ride W trail and 14 to 20 %
of it hard. The share of road in a ride moves the percentile too much. The absolute limits stay.

### 12. A second labelled ride: the rule holds, and the labels set the ceiling

Ride N was the second ride labelled with the buttons, with the watch on the handlebar. About half of it
followed ride A's trails and half was new. It was also wet, and the rider rated the trails harder that
day because of leaves, slippery roots and mud.

**The rule transfers.** Without any change to the limits, balanced accuracy was 0.72 (0.73 on A's trails,
0.67 on the new ones), against 0.73 on ride A. Limits fitted on ride N gave 0.76 on N but 0.72 on A, and
limits fitted on both rides gained at most 0.03, so nothing was changed. No extra feature helped when a
logistic model was trained on one ride and tested on another: grade, speed variation, `roughness`,
curviness, stops and 225 m of context all moved the result by ±0.02. Neither a steep-climb rule nor
`jolt` (90th percentile, share of hits above 2000 mG) separated 1 from 2; the missed level 2 sections
lie on almost flat ground. The labels came on time: shifting them by one 25 m section either way only
made the fit worse.

**The handlebar is repeatable.** On the same places, `steer` on ride N was 0.94 to 0.96 of ride A and
`roughness` 0.86 to 0.88, and `steer` did not drift during the ride, unlike the wrist on ride T.

**The labels set the ceiling.** On the same places, the rider gave the same label on both days for 69 %
of the sections (balanced 0.71) and 68 % of the OSM trail segments. The rule agreed with itself between
the days on 76 % of the sections and 80 % of the segments, and matched the labels at 0.73: about as
well as the rider matched themselves. Where both days' labels agree, the rule scores 0.82 to 0.88. Per
OSM trail segment it scored 0.77 on ride N, and per stretch the rider labelled as one piece, 0.80 to
0.83 from 75 m and 0.89 to 0.96 from 250 m.

**The wet day was harder, and the sensors saw it.** The labels on ride N were on average 0.2 levels
higher than ride A's on the same places, and this matched the conditions, not a drifting scale. Away
from button presses (more than 20 s), the road speed was the same as on ride A (14.1 against 14.4 km/h)
while trail was 20 to 40 % slower. But the road speed reference diluted on this trail-heavy ride
(11.3 km/h), which cancelled the effect: the rule moved 0.08 levels *easier*. With the road speed taken
as the median where `steer` is below the trail limit, it moved 0.06 harder and called 41 % hard, against
the labels' 34 %. Against ride A's dry labels on the same places, ride N's wet sensors separated 1 from
2 as well as ride A's own sensors did (AUC 0.79 and 0.71 for steering and slowness, against 0.78 and
0.72). The ordering of the trails does not depend on the weather; the level does.

**Button presses slow the rider, but only briefly.** The speed drops by about 15 % within ±4 s of a
press. Ride N had 9.3 presses per km, so 22 % of the time was within 5 s of one, but the total effect is
about 2 %, and the 125 m smoothing evens most of it out.

**Consequences.** The levels are meant for dry conditions, like OSM's `mtb:scale`, so labels from wet
rides are not used to set the limits. Rides are marked dry or wet, and `tools/trailmerge.py` combines
several rides per trail segment. Within one ride a segment gets the highest level that lasts 50 m, but
across rides that rule gets harsher with every pass: on the segments with three passes it gave 0.77,
0.70 and 0.66 for one, two and three passes. The median of the passes' levels, weighted by covered
metres, held at 0.74 to 0.77, and letting the dry passes decide gave 0.77 against 0.72 for all passes
equal. Only 53 segments had three passes, so this is a direction, not a measurement.

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

1. **Dry handlebar rides on new trails, labelled with the buttons.** Different forests, surfaces and
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
6. **Conditions for every ride.** Wet rides are useful for the combined map, but their labels describe
   wet trails and are not ground truth for the dry level.

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
- Say which scale you used, where the watch sat, whether a chest strap was connected, whether the
  trails were dry or wet, and anything special about the ride, such as riding with children.
- Open an issue to agree on how to share the files before sending them.

## Open questions

- Does the handlebar rule hold on other trails, riders and bikes?
- The wrist is not repeatable between days, and its steering drifts within a ride (see
  [11](#11-the-wrist-is-not-repeatable-and-the-reference-dilutes)). Is there any normalisation that
  makes it usable, or should the wrist mode only use speed?
- How should the road speed reference be found on a ride with no road at all, or one that is almost
  all trail? The median speed where `steer` is below the trail limit followed the wet ride better, but
  did not change the accuracy (see [12](#12-a-second-labelled-ride-the-rule-holds-and-the-labels-set-the-ceiling)).
- Level 2 is decided by the worst spot of a trail. Can short peaks, such as a sharp slowdown over 10 to
  25 m, find it better than a 125 m median?
- Is 25 m sections with 125 m smoothing the right scale, or should the level be decided per trail
  segment from the start?
- How should the child-friendly scale map to OSM's `mtb:scale`?
- Can the watch app record the mount directly, so that heart rate is not needed?
