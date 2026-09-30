# Bidra

Buggrapporter, idéer och ändringar är välkomna som issues och pull requests.

## Innan du skickar en ändring

- Kör `make test`. Python-testerna kräver bara Python 3.9 eller senare, utan paket. Node-testet kräver Node.
- Ändrar du klockappen: bygg med `make build` och kör enhetstesterna med `make test-watch`.
  Beskriv gärna om ändringen är provad på en riktig klocka.
- Ändrar du gränserna i `tools/trailanalysis.py`: beskriv vilka handbedömda turer de kalibrerades mot
  och vilken träffsäkerhet de gav, som i [docs/bedomning.md](docs/bedomning.md).

## Stil

- Analysverktygen använder bara Pythons standardbibliotek. Håll det så, så att de går att köra överallt.
- Kod, kommentarer och dokumentation är på svenska. Fält i FIT-filen och OSM-taggar behåller sina engelska namn.
- Kartsidan ska fungera under en strikt Content Security Policy: inga `style`-attribut och ingen inbäddad kod
  i webbhotellsversionen.

## Checka aldrig in

- Utvecklarnyckeln (`developer_key`).
- Egna FIT-filer, genererade kartor och GeoJSON-filer. De innehåller GPS-positioner.
  `.gitignore` utesluter dem, men kontrollera med `git status` innan du checkar in.
