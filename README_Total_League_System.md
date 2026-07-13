# Total League System

Source tree for LeaguePost, Neo_Phoenix, and the roster merge system.

## Layout

Total_League_System/
  LeaguePost/
    LeaguePost.py
    run_LeaguePost.bat
    LeaguePost.spec
    league_team_list.xlsx
  Neo_Phoenix/
  <roster merge system folder>/

## Run from source

Run LeaguePost\run_LeaguePost.bat.

LeaguePost.py looks for Neo_Phoenix and the roster system in the same parent folder when run from source.

## Build x64 EXE

Use LeaguePost\LeaguePost.spec in GitHub Actions or another x64 build environment.
If the EXE is placed at the Total_League_System root, keep Neo_Phoenix and the roster system beside it.
