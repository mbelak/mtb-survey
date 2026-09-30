# Klockappen: implementation

Hur appen i `source/` fungerar. För användning, se [README](../README.md).

## Kontinuerlig GPS
`Position.enableLocationEvents(Position.LOCATION_CONTINUOUS, ...)` anropas när vyn
visas och GPS hålls igång tills appen avslutas. Den stängs alltså inte av i paus.
Modulen heter `Toybox.Position`. Rättigheten i manifestet heter `Positioning`.

## `mtb_scale` som tillstånd
Värdet ligger i `_scale` i `MtbSurveyView`. UP och DOWN ändrar bara detta tillstånd.
Startvärdet är 1.

## Developer field på varje record
Fältet skapas med `Session.createField("mtb_scale", 0, DATA_TYPE_UINT8,
{ :mesgType => MESG_TYPE_RECORD, :units => "grade" })`.

`Field.setData()` lägger bara värdet i kö till nästa record som systemet skriver.
Därför skrivs `_scale` om till fältet:

1. en gång per sekund från en `Timer` (`onTick`),
2. vid varje positionshändelse (`onPosition`),
3. direkt vid UP/DOWN,
4. direkt vid start och vid återupptagning efter paus.

Skrivningen sker bara medan sessionen spelar in. Ett värde som ändras under paus
hamnar därför på första record efter återupptagning.

## Rörelsesensorer
Accelerometer och gyroskop läses 25 gånger per sekund via `Sensor.registerSensorDataListener`,
i paket om en sekund. Varje paket blir tre developer fields på record, float:

| Fält | Enhet | Vad |
|---|---|---|
| `roughness` | mG | RMS av accelerationens belopp kring sekundens medel. Skakningar från rötter och stenar. |
| `jolt` | mG | Största avvikelsen under sekunden. Enstaka hårda stötar. |
| `steer` | grader/s | RMS av vridhastigheten kring lodaxeln, efter att sekundens medel dragits bort. Små snabba styrkorrigeringar, inte jämna kurvor. |

Lodaxeln tas från accelerometerns medelvektor, alltså tyngdkraften. Därför beror värdena inte på
hur klockan sitter. **Sätt klockan på styret** för bäst signal. På handleden dämpar armen stötarna.
Kör helst med samma cykel varje gång, eftersom dämpning och däcktryck påverkar skakningarna.

Går gyroskopet inte att starta registreras bara accelerometern, och `steer` utelämnas.
Sensorvärden äldre än 3 s skrivs inte.

`Sensor.setEnabledSensors` slår på klockans puls och parkopplade ANT+-sensorer för kadens och fart.
Kadensen hamnar då i FIT-filens vanliga fält.

Beräkningen ligger i den rena funktionen `motionMetrics()` och är enhetstestad i `test/`.

## Avslut
`AppBase.onStop()` sparar en eventuell kvarvarande session och stänger av timer och GPS.
Spåret går alltså inte förlorat om appen avslutas på annan väg än BACK.

## Rättigheter i `manifest.xml`
| Rättighet | Används av |
|---|---|
| `Positioning` | `Toybox.Position` |
| `Fit` | `Toybox.ActivityRecording` |
| `FitContributor` | `Toybox.FitContributor`, `Session.createField` |
| `Sensor` | `Toybox.Sensor`: accelerometer, gyroskop, externa sensorer |

`minApiLevel` är 3.3.0, eftersom gyroskopet kräver det.
