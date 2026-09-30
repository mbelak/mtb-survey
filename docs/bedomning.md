# Automatisk bedömning

Analysen ger varje 25 m-sektion en nivå från klockans sensorer och farten. Den skattar samma skala som
knapparna: 0 = grusväg eller asfalt, 1 = barnvänlig stig, 2 = stig som inte är barnvänlig.

```
python3 tools/trailanalysis.py aktivitet.fit [--mount arm|styre]
```
Analysen körs också automatiskt av `fitmap.py`. Spåret delas i sektioner om 25 m, och varje sektion
får nivån **lätt**, **kräver vana** eller **svårt för barn**, med skälen i klartext:

| Skäl | Mätvärde |
|---|---|
| brant | max lutning i sektionen |
| lång backe | sektionen ligger i en sammanhängande stigning, med minst 12 m upp över minst 150 m |
| gångfart i uppförsbacke | medianfart under 4 km/h där det lutar minst 5 % |
| ryckig fart, stopp | farten varierar mycket, eller sekunder under 2 km/h |
| kurvigt | riktningsändring per 100 m, mätt över 20 m-korda. **Av som standard**, eftersom den är grov (GPS-brus). Slå på med `USE_CURV = True` i `tools/trailanalysis.py`. |
| stig, mycket styrande, långsam på stig | `steer` från appen v0.3 och farten relativt dagens vägfart, se nedan |

På kartsidan växlar knappen **Automatisk / Din bedömning** färgläggningen av karta och höjdprofil.
Automatiskt läge är standard. Adressen `...html#manual` öppnar din egen bedömning direkt.

Sensorvärden och fart jämnas ut med en glidande median över `SMOOTH_N` sektioner (5 stycken, alltså 125 m)
innan nivån sätts. Utan utjämning är 25 m-värdena för brusiga.

**Kalibrering:** tabellen *Mätvärden per mtb:scale* visar medianen av varje mätvärde för varje
manuellt värde. Ett mätvärde som skiljer dina bedömningar åt ökar från rad till rad. Justera
`MOUNT_LIMITS` överst i `tools/trailanalysis.py` efter det. Ju fler turer med manuell bedömning, desto säkrare.

## Klockan på styret eller armen

Läget avgörs per sektion. Puls utan anslutet pulsband betyder att klockan satt på handleden,
eftersom den optiska pulsmätaren inte får kontakt på styret. Pulsavbrott eller pulsglimtar kortare än
en minut ändrar inte läget. Med pulsband antas styret. `--mount arm` eller `--mount styre` till
`fitmap.py` eller `trailanalysis.py` anger läget för hela passet.
På kartan är armsektioner streckade, och en rad under nivåtabellen säger hur mycket som mättes på armen.

**Styret rekommenderas.** Samma sträckor gav samma värden olika dagar, inom 10 %. På armen blir
skak och styrning 1,7 respektive 2,4 gånger högre, och de skiljer inte lätt stig från svår.

## Nivåerna (kalibrerade 2026-09-30)

Skalan: 0 = grusväg eller asfalt, 1 = barnvänlig stig, 2 = stig som inte är barnvänlig.
Facit är handbedömningen från turen 2026-09-25 (styre). Den överfördes via plats till turen 2026-09-30, där
samma loop kördes en gång på armen och en gång på styret.

| | Styret | Armen |
|---|---|---|
| Stig (1) | `steer` minst 24 °/s | `steer` minst 59 °/s (preliminärt) |
| Svår stig (2) | `steer · (v_rel)^-0,66` minst 47 | `v_rel` högst 0,62 |
| Båda | max lutning minst 14 % ger 2 | |

`v_rel` är farten delad med dagens vägfart, med lutningen utjämnad (fart ~ e^(−0,036 · lutning %)).
Dagens vägfart är medianen av den lutningsjusterade farten på de 35 % lugnaste sektionerna, alltså
de med lägst styrning, räknat inom varje läge. Har passet för lite lugn sträcka används 15 km/h.
Du saktar in på svåra stigar, och farten relativt dagens vägfart tål att tempot varierar mellan dagar.
Absolut fart gör inte det: en lugn tur fick 52 % svårt med en fast fartgräns.

Gränserna står i `MOUNT_LIMITS` och `SPEED_EXP` överst i `tools/trailanalysis.py`.
`roughness` visas men påverkar inte nivån. Den skilde inte 1 från 2, och skakiga grusvägar blev
felaktigt stig med den tidigare gränsen på 425 mG.

Balanserad träff, där varje nivå väger lika. Slumpen ger 0,33 för tre nivåer och 0,50 för 1 mot 2.

| Tur | Tre nivåer | 1 mot 2 | Väg mot stig |
|---|---|---|---|
| 25/9, styre (kalibrering) | 0,73 | 0,74 | 0,87 |
| 30/9, styre (annan dag) | 0,71 | 0,72 | 0,83 |
| 30/9, arm | 0,64 | 0,64 | 0,82 |

Med de tidigare gränserna (`steer` 26/36, `roughness` 425) gav turen 30/9 på styret 0,53 och 0,58.

Begränsningar: det finns bara en handbedömd tur, och testet gick på samma stigar. Armens stiggräns
kommer från samma tur som den testas på. Turen 2026-09-29, med lätta stigar och klockan på armen,
fick 100 % lätt. Armens värden var mycket lägre den dagen, så gränsen håller inte alla dagar.

## Vad som testades och valdes bort

Analysen gjordes 2026-09-30 mot samma facit. Den balanserade träffen mellan 1 och 2 mättes med AUC,
där 0,50 betyder ingen skillnad och 1,00 betyder perfekt åtskillnad.

**Fartreferens.** Inom en tur ger alla fartvarianter nästan samma åtskillnad. Skillnaden syns när en gräns
från en tur används på en annan. Kontrollen var en lugn tur med bara lätta stigar och en vägfart på
11,6 km/h, mot 15 till 17 km/h de andra dagarna.

| Fartreferens | Andel svårt på den lugna turen |
|---|---|
| Absolut fart | 52 % |
| Hela passets medianfart | 18 % |
| Glidande 20 minuter | 15 % |
| Dagens vägfart, lutningsjusterad (vald) | 13 % |

Hela passets medianfart och glidande fönster påverkas av hur mycket stig passet innehåller.
Ett fönster på 5 minuter försämrade också åtskillnaden mellan väg och stig.

**Skak.** Inget sätt att räkna skaket skilde 1 från 2 eller tillförde något utöver styrning och fart.
Testat: medel, 90:e percentilen, variation, stötarnas median och 90:e percentil, stöt delat med skak,
andel sekunder med stöt över 2000 till 6000 mG, glidande fönster från 25 m till 1 km och medel per
stigsegment. AUC för 1 mot 2 låg mellan 0,33 och 0,63, ofta omvänt på långa fönster. Per stigsegment
gav skaket 0,39, styrningen 0,81 och farten 0,72. Mellan väg och stig fungerar skaket, med 0,85 till 0,90,
men inte bättre än styrningen. Skaket mäter snarare ytans jämnhet och passar troligen OSM-taggen
`smoothness` bättre än `mtb:scale`.

**Skak per fart** skilde 1 från 2 (AUC cirka 0,75), men bara för att måttet i praktiken blir ett fartmått.
Inom samma nivå ökar skaket bara svagt med farten, ungefär som fart upphöjt till 0,19.

## Kalibrera om

Fler handbedömda turer gör gränserna säkrare, särskilt på stigar som inte ingick i kalibreringen.

1. Kör med klockan på styret och bedöm stigen med knapparna under turen.
2. Gör kartan med `python3 tools/fitmap.py tur.fit` och läs tabellen *Mätvärden per mtb:scale*.
3. Jämför styrning och fart per nivå, och justera `MOUNT_LIMITS` och `SPEED_EXP`.
4. Kör `python3 tools/test_trailanalysis.py`. Testerna använder gränsernas storleksordning,
   så en stor ändring kan kräva att testfallen justeras.
