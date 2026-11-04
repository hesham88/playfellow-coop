"""Endless Sky 0.11.4 (open source, GPL, offline, single-player): the pre-skill pack.

  card      the controls, read from the game's own keys.txt
  save      reads the pilot's plain-text save (read-only): credits, place, missions, jobs; the record of what happened
  hud       fast looks at a frame: shields, hull, energy, heat, radar contacts, target, from positions and colours in the game's interface file
  screen    which screen is up, from a local text reader plus the HUD brightness
  flight    the fighting and flying decisions: pure logic, no Windows, one tick at a time
  session   the hands and eyes put together: pilot creation, shipyard, jobs, map routes, jumps, landing, combat
  play      one recorded run with the widget on the game window
  catalogue the full skill catalogue for the game and its genre, with the honest status of each skill

The buddy sees the screen and presses keys, only while the game is in front. It never changes a save, a data file or a plugin.
"""
