# Vad som har verifierats

Miljö: Connect IQ SDK 9.2.0, enhetsprofil `epix2`, macOS. Python 3.9 och 3.14, Node 24.

## På klockan (Epix Gen 2, september 2026)

Tre turer med version 0.3, på 7 till 13 km, avkodade med `tools/fitdump.py`:

- Varje record bar `mtb_scale`, position, `roughness`, `jolt` och `steer`. Inget record saknade något av dem.
- Knapptryck syns i FIT-filen på rätt ställe. En snabb följd UP, DOWN ger värdesekvensen 0, 1, 0
  inom ett par sekunder, och den går att använda som markering längs spåret.
- Pulsen från klockan registreras på handleden och saknas när klockan sitter på styret.
  Ett anslutet ANT+-pulsband syns som `device_info` med enhetstyp 120.
- Samma sträckor med klockan på styret gav samma `steer` och `roughness` olika dagar, inom 10 %.

**Inte verifierat på klockan**
- Batteriåtgång med sensorerna på.
- Kadenssensor över ANT+.

## Bygge och enhetstester

- Appen och testvarianten byggs för `epix2` med `monkeyc` utan fel.
  Enda varningen gäller att startikonen är 40x40 och skalas till 60x60.
- Enhetstesterna för `motionMetrics()` går igenom (4 av 4): stilla klocka, skakningar med känd RMS och topp,
  styrning när klockan är lutad 90 grader, och att en jämn kurva inte räknas som korrigering.
- Python-testerna (`test_trailanalysis.py`, `test_trailsegments.py`) och Node-testet (`test_osmedit.js`) går igenom.

## I simulatorn (version 0.1 till 0.3)

- En självkörande testvariant startade inspelning, bytte värde, pausade, bytte värde under paus,
  återupptog, bytte värde och sparade. Resultat:
  - 41 records, ett per sekund, och alla 41 bar `mtb_scale`.
  - Värdesekvensen blev 1, sedan 3, sedan 4 efter pausen, sedan 2. Det stämmer med tillståndet.
  - Fältbeskrivningen i filen är `mtb_scale`, enhet `grade`, uint8, kopplad till record.
- Ett kontrollexperiment utan den periodiska skrivningen gav bara 5 records på samma tid,
  och värdet som ändrades under paus kom inte med efter återupptagning.
  Den periodiska skrivningen behövs alltså.
- Lyssnaren för rörelsesensorer registreras med både accelerometer och gyroskop, och FIT-filen får
  fältbeskrivningar för `roughness`, `jolt` och `steer`. Simulatorn skickar ingen rörelsedata,
  så sensorvärdena blir tomma (`NaN`) där. De verkliga värdena är verifierade på klockan, se ovan.

## Den automatiska bedömningen

Gränserna är kalibrerade mot en enda handbedömd tur. Se [bedömningen](bedomning.md) för träffsäkerhet
och begränsningar.
