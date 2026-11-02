"""Play Mini Chess from pixels: read the board and pieces directly from the picture.

No copied game state or engine move generator imported: reads all 64 squares from pixels
and uses a self-contained chess move generator and search.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from playfellow_coop.skills.base import Done

Frame = np.ndarray

SQUARE = 60
BOARD_TOP = 64
WIDTH, HEIGHT = 480, 544

VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}
KNIGHT = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))
KING = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
DIAGONAL = ((-1, -1), (-1, 1), (1, -1), (1, 1))
STRAIGHT = ((-1, 0), (1, 0), (0, -1), (0, 1))
CENTRE = [[0, 1, 2, 3, 3, 2, 1, 0][c] + [0, 1, 2, 3, 3, 2, 1, 0][r] for r in range(8) for c in range(8)]

_TEMPLATES: dict[str, np.ndarray] | None = None


def _get_templates() -> dict[str, np.ndarray]:
    global _TEMPLATES
    if _TEMPLATES is not None:
        return _TEMPLATES
    try:
        f = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        f = ImageFont.load_default(size=26)
    templates: dict[str, np.ndarray] = {}
    for ch in "PNBRQK":
        im = Image.new("L", (40, 40), 0)
        d = ImageDraw.Draw(im)
        box = d.textbbox((0, 0), ch, font=f)
        d.text(((40 - box[2]) / 2, (40 - box[3]) / 2 - 3), ch, fill=255, font=f)
        templates[ch] = np.asarray(im)
    _TEMPLATES = templates
    return _TEMPLATES


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look or None if not Mini Chess."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[:2] != (HEIGHT, WIDTH):
        return None
    if frame.std() < 5.0:
        return None
    if int(frame[0, 0, 0]) == 16 and int(frame[0, 0, 1]) == 16 and int(frame[0, 0, 2]) == 32:
        return "arena"
    return None


def read_board(frame: Frame) -> tuple[tuple[str, ...], int]:
    """Read the 64-square board tuple and the currently picked square (-1 if none) from pixels."""
    templates = _get_templates()
    detected: list[str] = []
    picked = -1
    for sq in range(64):
        r, c = divmod(sq, 8)
        cx, cy = c * SQUARE + SQUARE // 2, BOARD_TOP + r * SQUARE + SQUARE // 2

        # Check for picked highlight color (124, 92, 255) in square corner
        corner = frame[BOARD_TOP + r * SQUARE + 4, c * SQUARE + 4]
        if np.linalg.norm(corner.astype(float) - [124, 92, 255]) < 25:
            picked = sq

        # Sample piece circle above center
        sample = frame[cy - 16, cx]
        is_white = bool(np.linalg.norm(sample.astype(float) - [250, 250, 250]) < 30)
        is_black = bool(np.linalg.norm(sample.astype(float) - [30, 30, 40]) < 30)
        if not (is_white or is_black):
            detected.append(".")
            continue

        patch = frame[cy - 20 : cy + 20, cx - 20 : cx + 20]
        gray = patch.mean(axis=2)
        letter_norm = np.clip(250 - gray if is_white else gray - 30, 0, 255)
        best_ch, best_score = "P", -1e9
        for ch, tmpl in templates.items():
            score = float(np.sum(letter_norm * tmpl))
            if score > best_score:
                best_score = score
                best_ch = ch
        detected.append(best_ch if is_white else best_ch.lower())
    return tuple(detected), picked


# ---- Self-contained chess move generator and Negamax search ----

def _rays(board: tuple[str, ...], sq: int, steps: tuple, slide: bool):
    r, c = divmod(sq, 8)
    for dr, dc in steps:
        nr, nc = r + dr, c + dc
        while 0 <= nr < 8 and 0 <= nc < 8:
            yield nr * 8 + nc
            if not slide or board[nr * 8 + nc] != ".":
                break
            nr, nc = nr + dr, nc + dc


def _attacked(board: tuple[str, ...], sq: int, by_white: bool) -> bool:
    r, c = divmod(sq, 8)
    pawn_row = r + 1 if by_white else r - 1
    for dc in (-1, 1):
        if 0 <= pawn_row < 8 and 0 <= c + dc < 8:
            p = board[pawn_row * 8 + c + dc]
            if p == ("P" if by_white else "p"):
                return True
    for steps, slide, kinds in ((KNIGHT, False, "n"), (KING, False, "k"), (DIAGONAL, True, "bq"), (STRAIGHT, True, "rq")):
        for t in _rays(board, sq, steps, slide):
            p = board[t]
            if p != "." and p.isupper() == by_white and p.lower() in kinds:
                return True
    return False


def _moves(pos: tuple[tuple[str, ...], bool, str, int]) -> list[tuple[int, int]]:
    board, w, castling, ep = pos
    out = []
    for sq, p in enumerate(board):
        if p == "." or p.isupper() != w:
            continue
        kind = p.lower()
        r, c = divmod(sq, 8)
        if kind == "p":
            step = -8 if w else 8
            one = sq + step
            if 0 <= one < 64 and board[one] == ".":
                out.append((sq, one))
                if (r == 6 if w else r == 1) and board[one + step] == ".":
                    out.append((sq, one + step))
            for dc in (-1, 1):
                if 0 <= c + dc < 8:
                    t = one + dc
                    if 0 <= t < 64 and ((board[t] != "." and board[t].isupper() != w) or t == ep):
                        out.append((sq, t))
            continue
        steps, slide = {"n": (KNIGHT, False), "k": (KING, False), "b": (DIAGONAL, True), "r": (STRAIGHT, True),
                        "q": (DIAGONAL + STRAIGHT, True)}[kind]
        for t in _rays(board, sq, steps, slide):
            if board[t] == "." or board[t].isupper() != w:
                out.append((sq, t))
        if kind == "k":
            home = 60 if w else 4
            rights = "KQ" if w else "kq"
            if sq == home and not _attacked(board, home, not w):
                if rights[0] in castling and board[home + 1] == board[home + 2] == "." \
                        and not _attacked(board, home + 1, not w) and board[home + 3] == ("R" if w else "r"):
                    out.append((home, home + 2))
                if rights[1] in castling and board[home - 1] == board[home - 2] == board[home - 3] == "." \
                        and not _attacked(board, home - 1, not w) and board[home - 4] == ("R" if w else "r"):
                    out.append((home, home - 2))
    return out


def _make(pos: tuple[tuple[str, ...], bool, str, int], move: tuple[int, int]) -> tuple[tuple[str, ...], bool, str, int]:
    board, w, castling, ep = pos
    frm, to = move
    b = list(board)
    piece = b[frm]
    kind = piece.lower()
    b[frm] = "."
    if kind == "p" and to == ep:
        b[to + (8 if w else -8)] = "."
    if kind == "k" and abs(to - frm) == 2:
        rook_from, rook_to = (frm + 3, frm + 1) if to > frm else (frm - 4, frm - 1)
        b[rook_to], b[rook_from] = b[rook_from], "."
    if kind == "p" and (to < 8 or to >= 56):
        piece = "Q" if w else "q"
    b[to] = piece
    new_ep = (frm + to) // 2 if kind == "p" and abs(to - frm) == 16 else -1
    lost = {60: "KQ", 4: "kq", 63: "K", 56: "Q", 7: "k", 0: "q"}
    for sq in (frm, to):
        for right in lost.get(sq, ""):
            castling = castling.replace(right, "")
    return tuple(b), not w, castling, new_ep


def _in_check(pos: tuple[tuple[str, ...], bool, str, int], of_white: bool) -> bool:
    target = "K" if of_white else "k"
    if target not in pos[0]:
        return True
    return _attacked(pos[0], pos[0].index(target), not of_white)


def _legal(pos: tuple[tuple[str, ...], bool, str, int]) -> list[tuple[int, int]]:
    w = pos[1]
    return [m for m in _moves(pos) if not _in_check(_make(pos, m), w)]


def _evaluate(board: tuple[str, ...]) -> int:
    score = 0
    for sq, p in enumerate(board):
        if p != ".":
            v = VALUES[p.lower()] + (4 * CENTRE[sq] if p.lower() in "nbp" else 0)
            score += v if p.isupper() else -v
    return score


def _search(pos: tuple[tuple[str, ...], bool, str, int], depth: int, alpha: float = -1e9, beta: float = 1e9) -> float:
    board, w = pos[0], pos[1]
    if "K" not in board or "k" not in board:
        return -100000 if ("K" if w else "k") not in board else 100000
    if depth == 0:
        return _evaluate(board) if w else -_evaluate(board)
    best = -1e9
    ordered = sorted(_moves(pos), key=lambda m: VALUES.get(board[m[1]].lower(), 0) if board[m[1]] != "." else -1, reverse=True)
    for m in ordered:
        score = -_search(_make(pos, m), depth - 1, -beta, -alpha)
        if score > best:
            best = score
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    if best <= -99000 and not _in_check(pos, w):
        return 0
    return best


def _best_move(pos: tuple[tuple[str, ...], bool, str, int], depth: int = 3) -> tuple[int, int] | None:
    best, best_m = -1e9, None
    for m in _legal(pos):
        score = -_search(_make(pos, m), depth - 1, -1e9, -(best - 1))
        if score > best or best_m is None:
            best = score
            best_m = m
    return best_m


def square_click(sq: int) -> tuple[str, float, float]:
    """Return click coordinates on 0-1000 grid for square index sq."""
    row, col = divmod(sq, 8)
    px = col * SQUARE + SQUARE / 2
    py = BOARD_TOP + row * SQUARE + SQUARE / 2
    return ("click", px / WIDTH * 1000.0, py / HEIGHT * 1000.0)


class PlayChess:
    name = "play_chess"
    about = "Read the chess board from pixels and play moves against the bot to win or survive in Mini Chess."
    max_steps = 150

    def __init__(self, look: str | None = None):
        self.look = look
        self.detected_look: str | None = None
        self.reset()

    def reset(self) -> None:
        self.detected_look = None
        self.castling = "KQkq"
        self.last_board: tuple[str, ...] | None = None
        self.plan: tuple[int, int] | None = None

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> tuple[str, float, float] | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable mini_chess picture")
        self.detected_look = mode

        board, picked = read_board(frame)

        # Detect castling rights lost from previous board
        if self.last_board is not None:
            lost = {60: "KQ", 4: "kq", 63: "K", 56: "Q", 7: "k", 0: "q"}
            for sq in range(64):
                if board[sq] != self.last_board[sq]:
                    for right in lost.get(sq, ""):
                        self.castling = self.castling.replace(right, "")

        self.last_board = board

        # If a square is currently picked in the game, complete the move to target
        if picked >= 0 and self.plan is not None and self.plan[0] == picked:
            target = self.plan[1]
            self.plan = None
            return square_click(target)

        # Plan the next move
        pos = (board, True, self.castling, -1)
        move = _best_move(pos, depth=3)
        if move is None:
            raise Done("no legal moves available")

        self.plan = move
        return square_click(move[0])
