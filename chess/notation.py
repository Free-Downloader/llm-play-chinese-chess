"""Chinese move notation (中国象棋记谱法), e.g. 马二进三 / 炮8平5.

Rules implemented:
  * piece name (帅将 仕士 相象 马 车 炮 兵卒);
  * start file label - Red uses Chinese numerals 一..九 numbered right-to-left
    from Red's view, Black uses Arabic 1..9 numbered left-to-right;
  * action: 进/退 (forward/backward) or 平 (sideways);
  * straight-moving pieces (K R C P) count steps after 进/退, and give the
    destination file after 平;
  * diagonal pieces (N B A) always give the destination file;
  * when two identical pieces stand on the same file, 前/后 replaces the
    start file label (前 = the one closer to the opponent).
"""

from __future__ import annotations

from .engine import RED, Board, Move, color_of

RED_NUMERALS = "一二三四五六七八九"

NOTATION_NAMES = {
    "K": "帅", "k": "将",
    "A": "仕", "a": "士",
    "B": "相", "b": "象",
    "N": "马", "n": "马",
    "R": "车", "r": "车",
    "C": "炮", "c": "炮",
    "P": "兵", "p": "卒",
}

# pieces whose 进/退 destination is a file label, not a step count
_DIAGONAL_TYPES = ("N", "B", "A")


def file_label(side: str, file_: int) -> str:
    if side == RED:
        return RED_NUMERALS[8 - file_]
    return str(file_ + 1)


def step_label(side: str, steps: int) -> str:
    if side == RED:
        return RED_NUMERALS[steps - 1]
    return str(steps)


def move_to_chinese(board: Board, move: Move) -> str:
    """Standard Chinese notation for `move` in the position `board`
    (before the move is played)."""
    piece = board.squares[move.fr]
    side = color_of(piece)
    name = NOTATION_NAMES[piece]
    ff, fr = move.fr
    tf, tr = move.to

    # 前/后 qualifier when two identical pieces share the start file.
    same_file = [sq for sq, p in board.squares.items()
                 if p == piece and sq != move.fr and sq[0] == ff]
    if len(same_file) == 1:
        other_rank = same_file[0][1]
        closer = fr < other_rank if side == RED else fr > other_rank
        head = ("前" if closer else "后") + name
    else:
        head = name + file_label(side, ff)

    if fr == tr:
        return f"{head}平{file_label(side, tf)}"
    forward = tr < fr if side == RED else tr > fr
    action = "进" if forward else "退"
    if piece.upper() in _DIAGONAL_TYPES:
        target = file_label(side, tf)
    else:
        target = step_label(side, abs(tr - fr))
    return f"{head}{action}{target}"
