# Supported watches

The app is built and ridden on the **Epix Gen 2**. It is not tied to that watch: it builds for every
Garmin device the Connect IQ SDK knows about, and `manifest.xml` lists all devices that meet its
hardware needs. **Only the Epix Gen 2 has been used on real rides.** The other devices are supported
on paper, from Garmin's own device definitions. Reports from other watches are very welcome.

## What the app needs

| Need | Why | Without it |
|---|---|---|
| Connect IQ API level 3.3 or later | the gyroscope API | the app does not run |
| Device apps allowed | the app is a device app, not a data field | the app does not run |
| Accelerometer at 25 Hz or more | `roughness` and `jolt` | the app does not run properly |
| UP and DOWN buttons, plus START and BACK | setting the difficulty; the app has no touch input | the difficulty cannot be set |
| Gyroscope | `steer`, the main signal of the automatic assessment | recording and your own assessment work, but the automatic assessment does not |

Heart rate is only used to tell whether the watch sat on the wrist. Devices without an optical heart
rate sensor, such as the Edge bike computers, are simply treated as mounted on the handlebar.

## Support levels

- **full**: everything works.
- **record-only**: the app records the ride and your difficulty values, and the map shows your own
  assessment. The automatic assessment needs `steer`, so it does not work.
- **no**: the app cannot be used, usually because the device has no UP and DOWN buttons.

## Devices checked

Checked with `tools/devicecheck.py` against the device definitions in Connect IQ SDK 9.2.0,
2026-09-30. All 67 devices also compile. The 58 devices marked full or record-only are listed in
`manifest.xml`.

| Device id | Name | API | Screen | Support | Why |
|---|---|---|---|---|---|
| `d2mach1` | D2™ Mach 1 | 5.2.0 | round-416x416 | full | – |
| `d2mach2` | D2™ Mach 2 | 5.2.0 | round-454x454 | full | – |
| `d2mach2pro` | D2™ Mach 2 Pro | 6.0.0 | round-454x454 | full | – |
| `edge540` | Edge® 540 / 540 Solar | 6.0.0 | rectangle-246x322 | full | – |
| `edge550` | Edge® 550 | 6.0.0 | rectangle-420x600 | full | – |
| `edge840` | Edge® 840 / 840 Solar | 6.0.0 | rectangle-246x322 | full | – |
| `edge850` | Edge® 850 | 6.0.0 | rectangle-420x600 | full | – |
| `enduro3` | Enduro™ 3 | 6.0.2 | round-280x280 | full | – |
| `epix2` | epix™ (Gen 2) / quatix® 7 Sapphire | 5.2.0 | round-416x416 | full | – |
| `epix2pro42mm` | epix™ Pro (Gen 2) 42mm | 5.2.0 | round-390x390 | full | – |
| `epix2pro47mm` | epix™ Pro (Gen 2) 47mm / quatix® 7 Pro | 5.2.0 | round-416x416 | full | – |
| `epix2pro51mm` | epix™ Pro (Gen 2) 51mm / D2™ Mach 1 Pro / tactix® 7 – AMOLED Edition | 5.2.0 | round-454x454 | full | – |
| `fenix7` | fēnix® 7 / quatix® 7 | 5.2.0 | round-260x260 | full | – |
| `fenix7pro` | fēnix® 7 Pro | 5.2.0 | round-260x260 | full | – |
| `fenix7pronowifi` | fēnix® 7 Pro - Solar Edition (no Wi-Fi) | 5.2.0 | round-260x260 | full | – |
| `fenix7s` | fēnix® 7S | 5.2.0 | round-240x240 | full | – |
| `fenix7spro` | fēnix® 7S Pro | 5.2.0 | round-240x240 | full | – |
| `fenix7x` | fēnix® 7X / tactix® 7 / quatix® 7X Solar / Enduro™ 2 | 5.2.0 | round-280x280 | full | – |
| `fenix7xpro` | fēnix® 7X Pro | 5.2.0 | round-280x280 | full | – |
| `fenix7xpronowifi` | fēnix® 7X Pro - Solar Edition (no Wi-Fi) | 5.2.0 | round-280x280 | full | – |
| `fenix843mm` | fēnix® 8 43mm | 6.0.2 | round-416x416 | full | – |
| `fenix847mm` | fēnix® 8 47mm / 51mm / tactix® 8 47mm / 51mm / quatix® 8 47mm / 51mm | 6.0.2 | round-454x454 | full | – |
| `fenix8pro47mm` | fēnix® 8 Pro 47mm / 51mm / MicroLED / quatix® 8 Pro 47mm / 51mm | 6.0.2 | round-454x454 | full | – |
| `fenix8solar47mm` | fēnix® 8 Solar 47mm | 6.0.2 | round-260x260 | full | – |
| `fenix8solar51mm` | fēnix® 8 Solar 51mm / tactix® 8 Solar 51mm | 6.0.2 | round-280x280 | full | – |
| `fenix943mm` | fēnix® 9 43mm | 6.0.3 | round-416x416 | full | – |
| `fenix947mm` | fēnix® 9 47mm / 51mm | 6.0.3 | round-454x454 | full | – |
| `fenix9pro43mm` | fēnix® 9 Pro 43mm | 6.0.3 | round-416x416 | full | – |
| `fenix9pro47mm` | fēnix® 9 Pro 47mm | 6.0.3 | round-454x454 | full | – |
| `fenix9pro51mm` | fēnix® 9 Pro 51mm | 6.0.3 | round-466x466 | full | – |
| `fenix9prosolar47mm` | fēnix® 9 Pro Solar 47mm | 6.0.3 | round-260x260 | full | – |
| `fenix9prosolar51mm` | fēnix® 9 Pro Solar 51mm | 6.0.3 | round-280x280 | full | – |
| `fenixe` | fēnix® E | 6.0.2 | round-416x416 | full | – |
| `fr255` | Forerunner® 255 | 5.2.0 | round-260x260 | full | – |
| `fr255m` | Forerunner® 255 Music | 5.2.0 | round-260x260 | full | – |
| `fr255s` | Forerunner® 255s | 5.2.0 | round-218x218 | full | – |
| `fr255sm` | Forerunner® 255s Music | 5.2.0 | round-218x218 | full | – |
| `fr265` | Forerunner® 265 | 5.2.0 | round-416x416 | full | – |
| `fr265s` | Forerunner® 265s | 5.2.0 | round-360x360 | full | – |
| `fr57042mm` | Forerunner® 570 42mm | 6.0.2 | round-390x390 | full | – |
| `fr57047mm` | Forerunner® 570 47mm | 6.0.2 | round-454x454 | full | – |
| `fr955` | Forerunner® 955 / Solar | 5.2.0 | round-260x260 | full | – |
| `fr965` | Forerunner® 965 | 5.2.0 | round-454x454 | full | – |
| `fr970` | Forerunner® 970 | 6.0.2 | round-454x454 | full | – |
| `instinct3amoled45mm` | Instinct® 3 AMOLED 45mm | 6.0.2 | round-390x390 | full | – |
| `instinct3amoled50mm` | Instinct® 3 AMOLED 50mm | 6.0.2 | round-416x416 | full | – |
| `instinct3solar45mm` | Instinct® 3 Solar 45mm / 50mm | 6.0.2 | semioctagon-176x176 | full | – |
| `instinctcrossoveramoled` | Instinct® Crossover AMOLED | 6.0.2 | round-390x390 | full | – |
| `marq2` | MARQ® (Gen 2) Athlete / Adventurer / Captain / Golfer / Carbon Edition / Commander - Carbon Edition | 5.2.0 | round-390x390 | full | – |
| `marq2aviator` | MARQ® (Gen 2) Aviator | 5.2.0 | round-390x390 | full | – |
| `edgemtb` | Edge® MTB | 6.0.0 | rectangle-240x320 | record-only | no gyroscope |
| `fr165` | Forerunner® 165 | 5.2.0 | round-390x390 | record-only | no gyroscope |
| `fr165m` | Forerunner® 165 Music | 5.2.0 | round-390x390 | record-only | no gyroscope |
| `fr170` | Forerunner® 170 | 6.0.0 | round-390x390 | record-only | no gyroscope |
| `fr170m` | Forerunner® 170 Music | 6.0.0 | round-390x390 | record-only | no gyroscope |
| `fr70` | Forerunner® 70 | 6.0.0 | round-390x390 | record-only | no gyroscope |
| `instincte40mm` | Instinct® E 40mm | 6.0.2 | semioctagon-166x166 | record-only | no gyroscope |
| `instincte45mm` | Instinct® E 45mm | 6.0.2 | semioctagon-176x176 | record-only | no gyroscope |
| `edge1040` | Edge® 1040 / 1040 Solar | 6.0.0 | rectangle-282x470 | no | no UP/DOWN buttons |
| `edge1050` | Edge® 1050 | 6.0.0 | rectangle-480x800 | no | no UP/DOWN buttons |
| `venu3` | Venu® 3 | 5.2.0 | round-454x454 | no | no UP/DOWN buttons |
| `venu3s` | Venu® 3S | 5.2.0 | round-390x390 | no | no UP/DOWN buttons |
| `venu441mm` | Venu® 4 41mm | 6.0.2 | round-390x390 | no | no UP/DOWN buttons |
| `venu445mm` | Venu® 4 45mm / D2™ Air X15 | 6.0.2 | round-454x454 | no | no UP/DOWN buttons |
| `venux1` | Venu® X1 | 6.0.2 | rectangle-448x486 | no | no UP/DOWN buttons |
| `vivoactive5` | vívoactive® 5 | 5.2.0 | round-390x390 | no | no UP/DOWN buttons, no gyroscope |
| `vivoactive6` | vívoactive® 6 | 6.0.2 | round-390x390 | no | no UP/DOWN buttons |

## Things to know

- **Screen layout** is only checked on the Epix Gen 2, 416 × 416 pixels. The layout uses percentages
  of the screen, but on small screens (218 to 260 pixels) and on the Instinct's non-round screens the
  texts may be cramped.
- **Edge bike computers** with buttons (540, 550, 840, 850) should suit the app well, since they sit on
  the handlebar anyway. That they have a gyroscope comes from the SDK definitions and is not verified.
  The Edge MTB has no gyroscope according to the SDK.
- **Touch-only watches** such as the Venu and vívoactive series could be supported by adding touch
  input, for example tapping the upper or lower half of the screen. That would be a welcome contribution.
- **Devices not in the list** were not downloaded to the SDK used for the check. Older watches such as
  the fēnix 6, Forerunner 245, 745 and 945, Venu 2 and Instinct 2 may or may not qualify. Many older
  models lack a gyroscope.
- **The limits of the automatic assessment** were calibrated on one Epix Gen 2. Other watches may
  measure `steer` and `roughness` slightly differently. See [research.md](research.md).

## Check your own device

1. Open the Connect IQ SDK Manager and download the device.
2. Run:
   ```
   python3 tools/devicecheck.py
   ```
   It lists every downloaded device with its support level and the reasons.
3. If it says full or record-only and the device is missing from `manifest.xml`, add it as
   `<iq:product id="..."/>`, build with `make build DEVICE=<id>`, and please report how it works.
