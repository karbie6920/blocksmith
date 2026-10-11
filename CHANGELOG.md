# Changelog

## 10.12
- Build: the first move no longer lowers the arm where it stands, and cubes travel 70 mm above the pick height (same as pick and sort). Fixes "Joint limits violated" at the start of a build.
- A rejected move now shows its target coordinates in the log.
- If the driver fails to load its parameter files at start ("Node not found"), the app loads them again.
- Code comments and docstrings translated to English.
- Modules renamed: `budowanie.py` → `build_tab.py`, `kolory.py` → `colours.py`, `jezyk.py` → `i18n.py`. An existing `kolory.json` is still read.

## 10.11
- English interface, switchable at runtime in the Start tab or with `--lang en`.

## 10.10
- Build tab: structures proposed by Ollama, plan repair, 3D preview, building with cube rotation.
- Robot reach shown on the camera image, adjustable reach limits.
- Camera address can be left empty to use the first camera found.

## 10.9
- First version of the desktop app: drivers started from the app, work area, colour teaching,
  guided camera-to-robot calibration, pick and sort by colour.
