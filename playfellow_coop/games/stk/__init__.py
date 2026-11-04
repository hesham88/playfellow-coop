"""SuperTuxKart (open source, GPL, offline modes only): the pre-skill pack.

  io        the only way anything here touches Windows: find the game window, look at it, press keys on it. Keys go out only while
            the game window is in front, only keys on the allow-list, never the mouse; every held key comes back up.
  card      the controls card, read from the game's own input.xml (the bindings the player set), not guessed
  vision    fast local looks at a frame: which screen this is, the road ahead, the race position
  drive     the racing pre-skill: steer, throttle, drift, nitro, items, rescue, at 20-30 looks a second, no model in the loop
  menus     the menu pre-skill: keyboard-only routes through the game's menus, each step checked on screen
  brains    the models' part: read the help pages, choose the next step, confirm the result screen, talk in the widget

Online and Addons are never entered: they are refused by name in `menus` (offline, single-player and local split-screen only).
"""
