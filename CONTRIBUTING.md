# Contributing

Bug reports, ideas and changes are welcome as issues and pull requests.

## Before you send a change

- Run `make test`. The Python tests only need Python 3.9 or later, without packages. The Node test needs Node.
- If you change the watch app: build with `make build` and run the unit tests with `make test-watch`.
  Please say whether the change has been tested on a real watch.
- If you change the limits in `tools/trailanalysis.py`: describe which manually assessed rides they were
  calibrated against and what accuracy they gave, as in [docs/assessment.md](docs/assessment.md).

## Style

- The analysis tools only use the Python standard library. Keep it that way, so they run everywhere.
- Code, comments and documentation are in English. FIT file fields and OSM tags keep their original names.
- The map page must work under a strict Content Security Policy: no `style` attributes and no inline code
  in the web host version.

## Never commit

- The developer key (`developer_key`).
- Your own FIT files, generated maps and GeoJSON files. They contain GPS positions.
  `.gitignore` excludes them, but check with `git status` before you commit.
