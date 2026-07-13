# Neo_Phoenix

NeoPhoenix runtime-only folder generated from Phoenix_V3_5.

## Start
- User: run_neo_phoenix.bat
- Developer: run_neo_phoenix_dev.bat

The default GUI is `customtkinter` based, starts maximized, and uses 18 point UI fonts.

## Build EXE
- Install runtime dependencies: `py -3 -m pip install -r requirements.txt`
- Install build dependency: `py -3 -m pip install -r requirements_build.txt`
- Run: `build_neo_exe.bat`

The build embeds `Phoenix.ico` and creates:
- `dist/NeoPhoenix.exe`
- `dist/NeoPhoenix_Developer.exe`

## Included
- Neo GUI entry point
- shared GUI base
- src runtime modules
- regression_cases GoldData
- empty runtime folders: games, html_cache, reports, urls, input

## Excluded
Phoenix legacy launchers, build scripts, docs, tests, old reports, frozen backups, and pycache files.
