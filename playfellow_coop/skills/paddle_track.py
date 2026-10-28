"""Keep a paddle under the ball (the brick-breaker skill): launch, follow the ball's predicted landing spot, and aim shots at the bricks that are left."""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Done, Frame
from playfellow_coop.skills.pixels import centre_of, mask_of

W, TOP = 480, 64
PADDLE, BALL = (124, 92, 255), (255, 255, 255)
BRICK_1, BRICK_2 = (34, 228, 255), (255, 61, 203)
BALL_R, PADDLE_W = 6, 80
PADDLE_STEP = 12


def landing_x(x: float, y: float, vx: float, vy: float, paddle_y: float) -> float:
    """Where a ball at (x, y) moving (vx, vy) reaches the paddle's height, bouncing off the side walls (bricks are ignored)."""
    if vy <= 0.5:
        return x
    t = (paddle_y - BALL_R - y) / vy
    raw = x + vx * t
    low, high = BALL_R, W - BALL_R
    span = high - low
    folded = (raw - low) % (2 * span)
    return low + (folded if folded <= span else 2 * span - folded)


class TrackPaddle:
    name = "track_paddle"
    about = "Launch the ball and keep the paddle under it, aiming at the remaining bricks, until every brick is gone."
    max_steps = 15000
    realtime = True

    def reset(self) -> None:
        self.previous = None
        self.rally = 0

    def next_key(self, frame: Frame) -> str | None:
        paddle = centre_of(mask_of(frame, PADDLE, 16, TOP))
        if paddle is None:
            raise Done("no paddle in the picture")
        ball = centre_of(mask_of(frame, BALL, 12, TOP))
        if ball is None:
            return None
        bricks = mask_of(frame, BRICK_1, 16, TOP) | mask_of(frame, BRICK_2, 16, TOP)
        if not bricks.any():
            raise Done("no bricks left")
        paddle_x = paddle[0]
        paddle_y = TOP + 372  # the paddle's row: the one thing about this game's layout the skill uses besides colours
        previous, self.previous = self.previous, ball
        if previous is None:
            return None
        vx, vy = ball[0] - previous[0], ball[1] - previous[1]
        on_paddle = abs(ball[1] - (paddle_y - BALL_R - 1)) < 3 and abs(ball[0] - paddle_x) < 3 and abs(vx) < 0.5 and abs(vy) < 0.5
        if on_paddle:
            return "space"  # served and waiting: launch
        aim_at = float(np.nonzero(bricks)[1].mean())
        landing = landing_x(ball[0], ball[1], vx, vy, paddle_y) if vy > 0 else ball[0]
        # hit the ball with a part of the paddle that sends it toward the bricks that are left (the edges send it sideways)
        offset = max(-0.6, min(0.6, (aim_at - landing) / 220.0)) if vy > 0 else 0.0
        want = landing - offset * (PADDLE_W / 2)
        gap = want - paddle_x
        if abs(gap) <= PADDLE_STEP / 2:
            return None
        return "right" if gap > 0 else "left"
