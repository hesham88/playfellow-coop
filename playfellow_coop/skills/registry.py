"""Which skills exist for which game (the controls-card name of the game)."""
from __future__ import annotations

from playfellow_coop.skills.grid_chase import ChaseFood
from playfellow_coop.skills.box_pusher import PushBoxes
from playfellow_coop.skills.lane_runner import RunLanes
from playfellow_coop.skills.paddle_track import TrackPaddle
from playfellow_coop.skills.tile_merge import SlideMerge

SKILLS = {"snake": ChaseFood, "slide_2048": SlideMerge, "lane_dash": RunLanes, "box_push": PushBoxes, "brick_breaker": TrackPaddle}


def skill_for_game(game_key: str):
    """A fresh skill object for an arena game key (snake, box_push, ...); KeyError when the game has none."""
    return SKILLS[game_key]()
