# MTB Survey för Garmin Epix Gen 2

MTB Survey kartlägger hur svåra stigar är, medan du cyklar dem. Du anger svårigheten med klockans
knappar, och klockan mäter samtidigt skakningar och styrrörelser. Efteråt blir turen en karta där
stigarna är färgade efter din bedömning och efter en automatisk bedömning. Därifrån kan du skriva
taggen `mtb:scale` direkt till OpenStreetMap.

Projektet består av två delar:

- **Klockappen** i `source/`. En Connect IQ-app som spelar in en vanlig cykelaktivitet och skriver
  svårigheten och sensorvärdena i FIT-filen, varje sekund.
- **Analysverktygen** i `tools/`. Python-skript utan externa paket som läser FIT-filen, bedömer stigarna
  och gör kartan.

```
klockan ──FIT-fil──▶ fitmap.py ──▶ karta (HTML) och GeoJSON ──▶ mtb:scale i OpenStreetMap
                        │
                        ├─ trailanalysis.py   automatisk bedömning per 25 m
                        └─ trailsegments.py   stigar mellan korsningar, från OpenStreetMap
```

## Krav

| För | Behövs |
|---|---|
| Klockappen | Garmin Epix Gen 2 och [Connect IQ SDK](https://developer.garmin.com/connect-iq/sdk/) 9.2 eller senare, med en egen utvecklarnyckel |
| Analysverktygen | Python 3.9 eller senare. Inga paket behövs. |
| Kartan | En webbläsare med internet, för kartbilderna |
| Stigsegment | Internet första gången, för OpenStreetMaps Overpass-API. Svaret sparas sedan lokalt. |
| Testerna av OSM-skrivningen | Node 18 eller senare |

Appen är bara byggd och provad för Epix Gen 2 (`epix2`). Andra klockor med gyroskop och
API-nivå 3.3 bör fungera om de läggs till i `manifest.xml`, men det är inte provat.

## Installera på klockan

Det finns två sätt: via Connect IQ Store eller genom att kopiera appen direkt till klockan över USB.

**Appen finns inte öppet i Connect IQ Store.** Den ligger just nu som testapp på upphovspersonens
eget utvecklarkonto. Då kan bara den personen ladda ner den. Vill du installera den via butiken
måste du ladda upp den själv till ett eget utvecklarkonto. Enklast är att kopiera den över USB.

### Bygga

1. Installera [Connect IQ SDK](https://developer.garmin.com/connect-iq/sdk/) och skapa en utvecklarnyckel
   enligt Garmins anvisning, om du inte har en. Lägg den som `developer_key` i projektets rot.
   Filen ignoreras av git.
2. Bygg appen:
   ```
   make build
   ```
   Det motsvarar `monkeyc -f monkey.jungle -d epix2 -o bin/mtbsurveyepixgen2.prg -y developer_key -r`.
   Ligger SDK:n inte i `PATH`, ange sökvägen: `make build MONKEYC="/sökväg/till/sdk/bin/monkeyc"`.
   I VS Code går det också med *Monkey C: Build for Device* och epix (Gen 2).

### Alternativ 1: kopiera över USB (sideload)

1. Anslut klockan med USB.
2. Kopiera `bin/mtbsurveyepixgen2.prg` till mappen `GARMIN/APPS/` på klockan.
3. Koppla från. Appen finns sedan bland klockans appar.

Appen uppdateras inte automatiskt. Kopiera en ny `.prg` för att uppdatera.

### Alternativ 2: via Connect IQ Store

1. Bygg paketet för butiken:
   ```
   make package
   ```
   Det ger `bin/mtbsurvey.iq`, alltså `monkeyc -e -f monkey.jungle -o bin/mtbsurvey.iq -y developer_key -r`.
   Laddar du upp under ett eget konto: byt först appens id i `manifest.xml`. Id:t måste vara unikt
   i butiken, och det nuvarande används redan av originalappen. Ett nytt id går att skapa med
   `uuidgen | tr -d '-' | tr 'A-Z' 'a-z'`.
2. Logga in i Garmins utvecklarportal för Connect IQ och ladda upp `bin/mtbsurvey.iq` som en ny app.
   Välj att publicera den som testapp (beta) om bara du ska kunna ladda ner den.
3. Installera appen från Connect IQ-appen i telefonen, med samma Garmin-konto.

En testapp syns bara för kontot som laddade upp den. Ska andra kunna installera appen från butiken
måste den publiceras öppet och granskas av Garmin.

### Efter installationen

Ställ gärna in registrering varje sekund i klockans systeminställningar, för tätast möjliga spår.

Efter en tur ligger FIT-filen i `GARMIN/Activity/` på klockan. Den går också att ladda ner från
Garmin Connect som *Exportera original*.

## Använda i fält

| Knapp | Funktion | Vibration |
|---|---|---|
| START | Starta, pausa och återuppta inspelningen | lång vid start och återuppta, kort vid paus |
| UP | Höj svårigheten ett steg, högst 6 | kort |
| DOWN | Sänk svårigheten ett steg, lägst 0 | kort |
| BACK | Stoppa, spara aktiviteten och avsluta, utan bekräftelse | längst |

Skärmen visar GPS-status, aktuell svårighet med stora siffror, inspelningsstatus och längst ner
de senaste sensorvärdena, `RGH` för skak och `STR` för styrning. Står det `NO MOTION DATA` kommer
inga rörelsedata. Vänta på grön `GPS OK` innan du startar, annars saknar början av spåret position.
Svårigheten börjar på 1.

**Sätt klockan på styret.** Den automatiska bedömningen är mest träffsäker där, och värdena
håller sig lika från dag till dag. På handleden fungerar den sämre, se [bedömningen](docs/bedomning.md).

**Vilken skala du använder bestämmer du själv.** Appen sparar bara siffran. Skriver du till
OpenStreetMap ska den följa [`mtb:scale`](https://wiki.openstreetmap.org/wiki/Key:mtb:scale).
Den automatiska bedömningen är kalibrerad för en enklare skala med tre nivåer:
0 = grusväg eller asfalt, 1 = barnvänlig stig, 2 = stig som inte är barnvänlig.

**Markera platser.** Ett snabbt UP följt av DOWN syns som en kort topp i FIT-filen.
Det går att använda för att markera till exempel början och slutet på en slinga.

## Analysera en tur

Alla kommandon körs från projektets rot.

**Karta**, det vanligaste:
```
python3 tools/fitmap.py tur.fit [utmapp]
```
Skriver en fristående HTML-karta och GeoJSON-filer bredvid FIT-filen, eller i `utmapp`.
Kartan visar spåret färgat efter din bedömning eller den automatiska, en höjdprofil, branta backar,
stigsegment mellan korsningar och en jämförelse med `mtb:scale` i OpenStreetMap.
Se [kartsidan](docs/kartsidan.md).

| Flagga | Betydelse |
|---|---|
| `--site mapp` | Skriver också en mapp för webbhotell, som fungerar under en strikt Content Security Policy |
| `--no-osm` | Hoppar över stigsegmenten, alltså ingen fråga till OpenStreetMap |
| `--mount arm` eller `--mount styre` | Anger var klockan satt. Annars avgörs det från pulsen. |
| `--osm-client-id ID` | Slår på skrivning av `mtb:scale` till OpenStreetMap från kartsidan |
| `--osm-api URL` | Annan OSM-server, till exempel testservern |

**Automatisk bedömning** i terminalen:
```
python3 tools/trailanalysis.py tur.fit [--mount arm|styre]
```

**Avkoda FIT-filen**, för att granska den:
```
python3 tools/fitdump.py tur.fit
```
Sista raden summerar hur många records som har position, svårighet och sensorvärden.

## Dokumentation

| Dokument | Innehåll |
|---|---|
| [docs/kartsidan.md](docs/kartsidan.md) | Kartan, stigsegmenten, jämförelsen med OSM och skrivning till OSM |
| [docs/bedomning.md](docs/bedomning.md) | Hur den automatiska bedömningen fungerar, hur den kalibrerades och hur träffsäker den är |
| [docs/fit-falt.md](docs/fit-falt.md) | Fälten appen skriver i FIT-filen, och hur de läses |
| [docs/implementation.md](docs/implementation.md) | Hur klockappen fungerar inuti |
| [docs/verifiering.md](docs/verifiering.md) | Vad som är provat på klockan, i simulatorn och med tester |
| [CHANGELOG.md](CHANGELOG.md) | Ändringar per version |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Hur du bidrar |

## Projektstruktur

```
manifest.xml, monkey.jungle   Connect IQ-projektet
source/                       klockappen (Monkey C)
test/                         enhetstester för sensorberäkningen (Monkey C)
resources/                    appens namn och ikon
tools/
  fitdump.py                  FIT-avkodare utan beroenden
  fitmap.py                   karta, höjdprofil och webbhotellsmapp
  trailanalysis.py            automatisk bedömning; gränserna står överst
  trailsegments.py            stigsegment och jämförelse med OpenStreetMap
  osmedit.js                  taggbyte i OSM-way-XML, används av kartsidan
  leaflet/                    Leaflet 1.9.4 för webbhotellsmappen
  test_*.py, test_osmedit.js  tester
docs/                         dokumentation
```

## Tester

```
make test          # Python- och Node-tester för analysverktygen
make test-watch    # klockappens enhetstester i Connect IQ-simulatorn (starta simulatorn först)
```

Python- och Node-testerna körs också av GitHub Actions vid varje push.

## Integritet

FIT-filer, kartor och GeoJSON-filer innehåller dina GPS-positioner, och ofta startar turen hemma.
Dela dem bara med dem som får se var du har varit. `.gitignore` utesluter dem från git.
Skriver du till OpenStreetMap blir bara taggen `mtb:scale` på stigen publik, inte ditt spår.

## Kända begränsningar

- Garmin Connect visar inte developer fields från sidladdade appar. Värdena finns ändå i FIT-filen.
- BACK sparar och avslutar direkt, utan bekräftelse.
- Den automatiska bedömningen är kalibrerad mot en enda handbedömd tur. Den är inte provad på andra
  cyklister, cyklar eller stigtyper.
- Med klockan på handleden är gränsen mellan väg och stig preliminär och håller inte alla dagar.

## Licens

Ingen licens är vald ännu. Leaflet i `tools/leaflet/` har sin egen licens, BSD 2-Clause.
