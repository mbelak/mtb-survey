# Contributing

Bug reports, ideas and changes are welcome as issues and pull requests.

## The algorithm needs you

The automatic assessment is the least finished part of the project, and the place where help matters
most. It was tuned by hand on a single labelled ride. Ideas, criticism, better methods, labelled rides and
rides from other watches are all very welcome. [docs/research.md](docs/research.md) explains what has
been tried, what went wrong, and which directions look promising.

## Before you send a change

- Run `make test`. The Python tests only need Python 3.9 or later, without packages. The Node test needs Node.
- If you change the watch app: build with `make build` and run the unit tests with `make test-watch`.
  Please say whether the change has been tested on a real watch.
- If you change the limits in `tools/trailanalysis.py`: describe which manually assessed rides they were
  calibrated against and what accuracy they gave, as in [docs/assessment.md](docs/assessment.md).
  Fit on some rides and test on others; see [docs/research.md](docs/research.md#methods).
- If you add a watch to `manifest.xml`: check it with `python3 tools/devicecheck.py`, see
  [docs/devices.md](docs/devices.md), and say whether it was tried on a real device.

## Style

- The analysis tools only use the Python standard library. Keep it that way, so they run everywhere.
- Code, comments and documentation are in English. FIT file fields and OSM tags keep their original names.
- The map page must work under a strict Content Security Policy: no `style` attributes and no inline code
  in the web host version.

## Never commit

- The developer key (`developer_key`).
- Your own FIT files, generated maps and GeoJSON files. They contain GPS positions.
  `.gitignore` excludes them, but check with `git status` before you commit.
