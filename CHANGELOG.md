# Ändringar

## Oreleasat

Analysverktygen:
- Två lägen för var klockan satt, styret eller armen. Läget avgörs per sektion från pulsen,
  eller anges med `--mount arm|styre`. Armsektioner streckas på kartan.
- Ny bedömning: stig avgörs av styrningen, svår stig av styrningen och farten relativt dagens vägfart.
  Gränserna är kalibrerade om, se [docs/bedomning.md](docs/bedomning.md).
- `roughness` påverkar inte längre nivån.
- `tools/fitdump.py` läser `device_info`, så att anslutna pulsband syns.
- Enhetstester i `tools/test_trailanalysis.py`.

Projektet:
- Dokumentationen är uppdelad i README och `docs/`. Makefile med `build`, `package` och `test`, och GitHub Actions för testerna.

## 0.3

Klockappen:
- Rörelsesensorer: developer fields `roughness`, `jolt` och `steer` på varje record.
- Puls och ANT+-kadens och fart aktiveras via `Sensor.setEnabledSensors`.
- Levande sensorvärden på skärmen under inspelning.
- Enhetstester för `motionMetrics()` i `test/`.

Analysverktygen:
- `tools/fitdump.py` läser höjd, sträcka, fart, puls och kadens, och tolkar `NaN` som saknat värde.
- `tools/fitmap.py` visar höjdprofil, branta backar och automatisk bedömning.
- `tools/trailanalysis.py`: automatisk bedömning per 25 m-sektion.
- `tools/trailsegments.py`: stigsegment mellan korsningar från OpenStreetMap, jämförelse med
  OSM:s `mtb:scale` och skrivning av taggen till OSM från kartsidan.

## 0.2

- Explicit kontinuerlig GPS via `Toybox.Position`.
- GPS-status på skärmen.
- `mtb_scale` skrivs i takt med records i stället för bara vid knapptryck.
- Vibration även vid start, paus, återuppta och spara.
- Status `PAUSED`, färgkodning och layout relativ till skärmstorleken.
- Säker avslutning i `onStop()`.
- `tools/fitdump.py` för att granska FIT-filer.
- `tools/fitmap.py` för färgkodad karta och GeoJSON.

## 0.1

- Första versionen: `mtb_scale` som developer field, ändrat med UP och DOWN och skrivet vid knapptryck.
