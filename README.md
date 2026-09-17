# Rhino Surface Mapper

Rhino Surface Mapper is a Python desktop application for mapping and navigating surface activity in *Elite Dangerous*. It reads the game's `Status.json` telemetry and provides a live surface map, search routes, markers, radar coverage, and optional steering assistance.

## Features

- Live SRV position, heading, and fuel telemetry from `Status.json`.
- Surface maps with route tracks, search routes, deposits, rigs, named markers, and radar coverage; maps can be saved and reopened as JSON files.
- Map library for browsing saved maps, with favorite and protection flags and a mining-only mode for protected maps.
- Navigation to map targets and a separate transparent navigation overlay.
- Radar pulse visualization and optional steering assistance using game telemetry and configured input controls.
- Configurable settings, including Windows, Dark, and Light interface themes, map and overlay appearance, and radar and navigation parameters.

The application does not detect obstacles. Radar input observation does not confirm that the game successfully fired a pulse. Steering assistance is optional and its behavior depends on valid game telemetry and input conditions.

## Requirements

- Python 3.13 is the current development baseline.
- Runtime dependencies are listed in [`requirements.txt`](requirements.txt), including PyQt6 and Requests.
- Development and test dependencies are listed in [`requirements-dev.txt`](requirements-dev.txt).
- For live game integration, an Elite Dangerous `Status.json` file. The application uses the standard Saved Games location by default and allows selecting another file in its settings.

Windows-specific game input integrations are present in the project. The repository does not currently document a supported-platform matrix.

## Development setup

From the repository root in PowerShell, create or activate the existing project `.venv`, then install development dependencies and launch the application:

```powershell
.\.venv\Scripts\Activate.ps1
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe rhino_surface_mapper.py
```

## Tests

Run the verified pytest workflow from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest tests -ra
```

Some Qt tests skip when PyQt6 is unavailable. Automated tests do not replace validation in the game, across monitor setups, or across Windows display scales. See [`TODO.md`](TODO.md) for recorded work and validation still pending.

## Project structure

- `rhino_surface_mapper.py` — application entry point.
- Core mapping and interface modules implement telemetry, navigation, maps, radar, overlay, and settings.
- `elite_dangerous/market/` — reusable market-data domain services.
- `assets/` — SVG interface and map resources.
- `tests/` — automated tests.

For detailed engineering notes and repository guidance, see [`PROJECT_NOTES.md`](PROJECT_NOTES.md) and [`AGENTS.md`](AGENTS.md).

## Development status

The project is under active development. Core mapping, navigation, radar, settings, map-library, and market-data components are present, but the project notes and task list record manual validation and additional work that remain. The automated test suite covers selected behavior; it does not establish that every feature has been validated in every game or display setup.

## Historical record

The first preserved compiled Beta dates from 11 September 2026, before the project adopted Git. It used Python 3.13, PyQt6, and PyInstaller. That Beta already included surface telemetry and mapping, deposits and markers, circular search routes, a navigation overlay, radar support, steering assistance, map persistence, and configurable settings.

The original source snapshot and compiled executable are retained privately as historical artifacts and are not public distribution assets. No preserved intermediate snapshots are available between that Beta and the start of Git history. Git history begins on 16 September 2026 with commit [`546a856`](https://github.com/pbgaspar/rhino-surface-mapper/commit/546a856) (`Baseline before repository cleanup`). No original semantic version number has been established for the Beta.

## License

No license has been selected for Rhino Surface Mapper. Until one is added, do not assume that the project may be reused, modified, or redistributed. Third-party components have their own licenses.
