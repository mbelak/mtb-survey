# FIT-filens fält

Appen spelar in en vanlig cykelaktivitet. Sporten är `cycling` och undersporten `mountain`.
Utöver Garmins vanliga fält skriver den fyra developer fields på **varje** record-meddelande, ett per sekund.

| Fält-id | Namn | Typ | Enhet | Innehåll |
|---|---|---|---|---|
| 0 | `mtb_scale` | uint8 | `grade` | Värdet på klockans skärm, 0 till 6. Ändras med UP och DOWN. |
| 1 | `roughness` | float32 | `mG` | Skakningar: RMS av accelerationens belopp kring sekundens medel. |
| 2 | `jolt` | float32 | `mG` | Största avvikelsen av accelerationens belopp under sekunden. |
| 3 | `steer` | float32 | `deg/s` | Styrkorrigeringar: RMS av vridhastigheten kring lodaxeln, efter att sekundens medel dragits bort. |

- Accelerometer och gyroskop läses 25 gånger per sekund. Värdena räknas per sekund.
- Lodaxeln tas från tyngdkraften, alltså accelerometerns medelvektor. Värdena beror därför inte på hur klockan är vriden.
- En jämn kurva ger inget `steer`. Bara snabba korrigeringar inom sekunden räknas.
- `steer` saknas om gyroskopet inte gick att starta.
- Sensorvärden äldre än 3 sekunder skrivs inte. Då saknas fältet på de records det gäller.
- Beräkningen finns i funktionen `motionMetrics()` i `source/MtbSurveyView.mc` och testas i `test/`.

## Övriga fält som analysen använder

| Fält | Meddelande | Används till |
|---|---|---|
| `position_lat`, `position_long` | record | spåret |
| `enhanced_altitude` | record | höjdprofil och lutning |
| `distance`, `enhanced_speed` | record | sträcka och fart |
| `heart_rate` | record | avgöra om klockan satt på handleden |
| `device_type` = 120 | device_info | ett anslutet pulsband, då säger pulsen inget om var klockan satt |
| `timer` stop och start | event | pauser, där spåret bryts |

## Läsa filen

`tools/fitdump.py` är en fristående avkodare utan beroenden. Den skriver ut varje record med dess
developer fields och avslutar med en summering:

```
python3 tools/fitdump.py aktivitet.fit
```

Från Python:

```python
from fitdump import parse
for kind, msg, dev in parse('aktivitet.fit'):
    if kind == 'record':
        print(msg['ts'], msg['lat'], msg['lon'], dev.get('mtb_scale'), dev.get('steer'))
```

`parse()` ger en lista av tupler `(typ, fält, developer_fields)`, där typ är `record`, `event`,
`device_info` eller `field_description`. Tidsstämpeln `ts` räknas i sekunder från FIT-epoken
1989-12-31 00:00 UTC.

Andra FIT-bibliotek, som Garmins FIT SDK eller Pythonpaketet `fitparse`, läser också fälten.
Garmin Connect visar dem däremot inte för sidladdade appar.
