"""Which skills exist for which game (the controls-card name of the game)."""
from __future__ import annotations

from playfellow_coop.skills.boss_duel import BeatBoss
from playfellow_coop.skills.box_pusher import PushBoxes
from playfellow_coop.skills.cave_jumper import UnlockCaves
from playfellow_coop.skills.chess_bot import PlayChess
from playfellow_coop.skills.grid_chase import ChaseFood
from playfellow_coop.skills.kingdom_builder import BuildKingdom
from playfellow_coop.skills.lane_runner import RunLanes
from playfellow_coop.skills.maze_runner import EscapeMaze
from playfellow_coop.skills.paddle_track import TrackPaddle
from playfellow_coop.skills.quest_hero import BattleHero
from playfellow_coop.skills.ray_walker import ClearRayMaze
from playfellow_coop.skills.ring_fighter import FightBot
from playfellow_coop.skills.tile_merge import SlideMerge
from playfellow_coop.skills.track_racer import DriveRacer

SKILLS = {
    "snake": ChaseFood,
    "slide_2048": SlideMerge,
    "lane_dash": RunLanes,
    "box_push": PushBoxes,
    "brick_breaker": TrackPaddle,
    "maze_chase": EscapeMaze,
    "key_caves": UnlockCaves,
    "action_quest": BeatBoss,
    "ray_maze": ClearRayMaze,
    "turn_quest": BattleHero,
    "tiny_kingdom": BuildKingdom,
    "mini_chess": PlayChess,
    "top_racer": DriveRacer,
    "mini_fighter": FightBot,
}


def skill_for_game(game_key: str):
    """A fresh skill object for an arena game key (snake, box_push, ...); KeyError when the game has none."""
    return SKILLS[game_key]()
