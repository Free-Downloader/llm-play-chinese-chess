"""Xiangqi (Chinese chess) rules engine with FEN support.

Coordinate system used throughout the program:
  * files 0..8  -> letters 'a'..'i', left to right as seen by Red
    (Red sits at the bottom of the board window).
  * ranks 0..9  -> top to bottom, rank 0 is Black's back rank,
    rank 9 is Red's back rank.

A square name is e.g. 'b7' (file 'b', rank 7); a move is 'b7b4'.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RED = "w"
BLACK = "b"

FILES = "abcdefghi"
RANKS = "0123456789"

INITIAL_FEN = (
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
)

PIECE_NAMES_EN = {
    "k": "King (General)",
    "a": "Advisor (Guard)",
    "b": "Elephant (Bishop)",
    "n": "Knight (Horse)",
    "r": "Rook (Chariot)",
    "c": "Cannon",
    "p": "Pawn (Soldier)",
}

PIECE_NAMES_ZH = {
    "k": "将帅",
    "a": "士仕",
    "b": "象相",
    "n": "马",
    "r": "车",
    "c": "炮",
    "p": "卒兵",
}


class IllegalMoveError(Exception):
    """Raised when a move is not legal in the current position."""


class FenError(Exception):
    """Raised when a FEN string is malformed."""


def color_of(piece: str) -> str:
    return RED if piece.isupper() else BLACK


def enemy(side: str) -> str:
    return BLACK if side == RED else RED


def side_name(side: str) -> str:
    return "Red" if side == RED else "Black"


def sq_name(sq: tuple[int, int]) -> str:
    return FILES[sq[0]] + str(sq[1])


def parse_sq(text: str) -> tuple[int, int]:
    text = text.strip().lower()
    if len(text) != 2 or text[0] not in FILES or text[1] not in RANKS:
        raise ValueError(f"invalid square name: {text!r}")
    return (FILES.index(text[0]), int(text[1]))


@dataclass(frozen=True)
class Move:
    fr: tuple[int, int]
    to: tuple[int, int]
    piece: str = ""
    captured: str = ""

    def uci(self) -> str:
        return sq_name(self.fr) + sq_name(self.to)

    @classmethod
    def from_uci(cls, text: str) -> "Move":
        text = text.strip().lower()
        if len(text) != 4:
            raise ValueError(f"invalid move notation: {text!r}")
        return cls(parse_sq(text[:2]), parse_sq(text[2:]))


def in_board(f: int, r: int) -> bool:
    return 0 <= f <= 8 and 0 <= r <= 9


def in_palace(sq: tuple[int, int], side: str) -> bool:
    f, r = sq
    if not (3 <= f <= 5):
        return False
    return 0 <= r <= 2 if side == BLACK else 7 <= r <= 9


_ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
_KNIGHT_JUMPS = (
    (1, 2, 0, 1), (-1, 2, 0, 1), (1, -2, 0, -1), (-1, -2, 0, -1),
    (2, 1, 1, 0), (2, -1, 1, 0), (-2, 1, -1, 0), (-2, -1, -1, 0),
)


class Board:
    """A mutable xiangqi position."""

    def __init__(self, fen: str = INITIAL_FEN):
        self.squares: dict[tuple[int, int], str] = {}
        self.side_to_move: str = RED
        self.halfmove_clock: int = 0
        self.fullmove: int = 1
        self._repetition: dict[tuple[str, str], int] = {}
        self.move_history: list[Move] = []
        self.set_fen(fen)

    # ------------------------------------------------------------------ FEN
    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        if len(parts) < 2:
            raise FenError(f"FEN needs at least board and side: {fen!r}")
        rows = parts[0].split("/")
        if len(rows) != 10:
            raise FenError(f"FEN board must have 10 rows: {fen!r}")
        squares: dict[tuple[int, int], str] = {}
        for rank, row in enumerate(rows):
            file_ = 0
            for ch in row:
                if ch.isdigit():
                    file_ += int(ch)
                elif ch.lower() in PIECE_NAMES_EN:
                    if file_ > 8:
                        raise FenError(f"too many files in row {rank}: {fen!r}")
                    squares[(file_, rank)] = ch
                    file_ += 1
                else:
                    raise FenError(f"invalid FEN character {ch!r} in {fen!r}")
            if file_ != 9:
                raise FenError(f"row {rank} must span 9 files: {fen!r}")
        if parts[1] not in ("w", "b"):
            raise FenError(f"invalid side to move: {fen!r}")
        self.squares = squares
        self.side_to_move = parts[1]
        self.halfmove_clock = int(parts[4]) if len(parts) > 4 and parts[4].lstrip("-").isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
        self.move_history = []
        self._repetition = {(self.board_key(), self.side_to_move): 1}

    def board_key(self) -> str:
        rows = []
        for rank in range(10):
            row = ""
            empties = 0
            for file_ in range(9):
                piece = self.squares.get((file_, rank))
                if piece is None:
                    empties += 1
                else:
                    if empties:
                        row += str(empties)
                        empties = 0
                    row += piece
            if empties:
                row += str(empties)
            rows.append(row)
        return "/".join(rows)

    def fen(self) -> str:
        return (
            f"{self.board_key()} {self.side_to_move} - - "
            f"{self.halfmove_clock} {self.fullmove}"
        )

    # ------------------------------------------------------------- queries
    def king_square(self, side: str) -> tuple[int, int] | None:
        target = "K" if side == RED else "k"
        for sq, piece in self.squares.items():
            if piece == target:
                return sq
        return None

    def kings_facing(self) -> bool:
        bk = self.king_square(BLACK)
        rk = self.king_square(RED)
        if bk is None or rk is None or bk[0] != rk[0]:
            return False
        for rank in range(bk[1] + 1, rk[1]):
            if (bk[0], rank) in self.squares:
                return False
        return True

    def _attacks(self, sq: tuple[int, int], by_side: str) -> bool:
        """Whether `by_side` attacks square `sq`."""
        f, r = sq
        # Rooks and cannons along ranks/files.  The first piece on a ray is a
        # screen for a possible cannon behind it, regardless of its colour.
        for df, dr in _ORTHOGONAL:
            nf, nr = f + df, r + dr
            first_piece = True
            while in_board(nf, nr):
                piece = self.squares.get((nf, nr))
                if piece is None:
                    nf += df
                    nr += dr
                    continue
                if first_piece:
                    if color_of(piece) == by_side and piece.lower() == "r":
                        return True
                    first_piece = False
                else:
                    if color_of(piece) == by_side and piece.lower() == "c":
                        return True
                    break
                nf += df
                nr += dr
        # Knights (hobbling horse: the leg lies next to the KNIGHT, on the
        # orthogonal square toward the target - not next to the target!).
        for df, dr in ((1, 2), (-1, 2), (1, -2), (-1, -2),
                       (2, 1), (2, -1), (-2, 1), (-2, -1)):
            nf, nr = f + df, r + dr  # would-be knight square
            piece = self.squares.get((nf, nr))
            if piece is None or piece.lower() != "n" \
                    or color_of(piece) != by_side:
                continue
            if abs(df) == 2:
                leg = (nf - df // 2, nr)
            else:
                leg = (nf, nr - dr // 2)
            if leg not in self.squares:
                return True
        # Pawns.
        fwd = -1 if by_side == RED else 1  # direction the pawn moves (toward enemy)
        src = (f, r - fwd)
        if in_board(*src) and self.squares.get(src, "").lower() == "p" \
                and color_of(self.squares[src]) == by_side:
            return True
        crossed_rank = 4 if by_side == RED else 5  # river: ranks 4/5 boundary
        for df in (1, -1):
            src = (f + df, r)
            crossed = r <= crossed_rank if by_side == RED else r >= crossed_rank
            if crossed and in_board(*src) and self.squares.get(src, "").lower() == "p" \
                    and color_of(self.squares[src]) == by_side:
                return True
        # King: adjacent palace steps plus the flying-general attack.
        king = self.king_square(by_side)
        if king is not None:
            if abs(king[0] - f) + abs(king[1] - r) == 1:
                return True
            if king[0] == f:
                step = 1 if r > king[1] else -1
                rank = king[1] + step
                while rank != r:
                    if (f, rank) in self.squares:
                        break
                    rank += step
                else:
                    return True
        return False

    def is_in_check(self, side: str) -> bool:
        king = self.king_square(side)
        if king is None:
            return False
        return self._attacks(king, enemy(side))

    # ------------------------------------------------------ move generation
    def _add_pawn_moves(self, sq, piece, moves):
        f, r = sq
        side = color_of(piece)
        fwd = -1 if side == RED else 1
        target = self.squares.get((f, r + fwd))
        if in_board(f, r + fwd) and (target is None or color_of(target) != side):
            moves.append(Move(sq, (f, r + fwd), piece, target or ""))
        crossed = r <= 4 if side == RED else r >= 5
        if crossed:
            for df in (1, -1):
                target = self.squares.get((f + df, r))
                if in_board(f + df, r) and (target is None or color_of(target) != side):
                    moves.append(Move(sq, (f + df, r), piece, target or ""))

    def pseudo_moves(self, side: str | None = None) -> list[Move]:
        if side is None:
            side = self.side_to_move
        moves: list[Move] = []
        for sq, piece in list(self.squares.items()):
            if color_of(piece) != side:
                continue
            f, r = sq
            ptype = piece.lower()
            if ptype == "p":
                self._add_pawn_moves(sq, piece, moves)
            elif ptype == "k":
                for df, dr in _ORTHOGONAL:
                    nf, nr = f + df, r + dr
                    if not (in_board(nf, nr) and in_palace((nf, nr), side)):
                        continue
                    target = self.squares.get((nf, nr))
                    if target is None or color_of(target) != side:
                        moves.append(Move(sq, (nf, nr), piece, target or ""))
                # Flying general: capture the enemy king down an open file.
                ek = self.king_square(enemy(side))
                if ek is not None and ek[0] == f:
                    blocked = any((f, rr) in self.squares
                                  for rr in range(min(r, ek[1]) + 1, max(r, ek[1])))
                    if not blocked:
                        moves.append(Move(sq, ek, piece, self.squares[ek]))
            elif ptype == "a":
                for df, dr in _DIAGONAL:
                    nf, nr = f + df, r + dr
                    if not (in_board(nf, nr) and in_palace((nf, nr), side)):
                        continue
                    target = self.squares.get((nf, nr))
                    if target is None or color_of(target) != side:
                        moves.append(Move(sq, (nf, nr), piece, target or ""))
            elif ptype == "b":
                for df, dr in _DIAGONAL:
                    nf, nr = f + 2 * df, r + 2 * dr
                    if not in_board(nf, nr):
                        continue
                    if side == RED and nr < 5 or side == BLACK and nr > 4:
                        continue  # elephants may not cross the river
                    eye = (f + df, r + dr)
                    if eye in self.squares:
                        continue
                    target = self.squares.get((nf, nr))
                    if target is None or color_of(target) != side:
                        moves.append(Move(sq, (nf, nr), piece, target or ""))
            elif ptype == "n":
                for df, dr, lf, lr in _KNIGHT_JUMPS:
                    nf, nr = f + df, r + dr
                    if not in_board(nf, nr):
                        continue
                    if (f + lf, r + lr) in self.squares:
                        continue
                    target = self.squares.get((nf, nr))
                    if target is None or color_of(target) != side:
                        moves.append(Move(sq, (nf, nr), piece, target or ""))
            elif ptype == "r":
                for df, dr in _ORTHOGONAL:
                    nf, nr = f + df, r + dr
                    while in_board(nf, nr):
                        target = self.squares.get((nf, nr))
                        if target is None:
                            moves.append(Move(sq, (nf, nr), piece, ""))
                        else:
                            if color_of(target) != side:
                                moves.append(Move(sq, (nf, nr), piece, target))
                            break
                        nf += df
                        nr += dr
            elif ptype == "c":
                for df, dr in _ORTHOGONAL:
                    nf, nr = f + df, r + dr
                    screen = False
                    while in_board(nf, nr):
                        target = self.squares.get((nf, nr))
                        if not screen:
                            if target is None:
                                moves.append(Move(sq, (nf, nr), piece, ""))
                            else:
                                screen = True
                        else:
                            if target is not None:
                                if color_of(target) != side:
                                    moves.append(Move(sq, (nf, nr), piece, target))
                                break
                        nf += df
                        nr += dr
        return moves

    def _apply_to(self, squares: dict, move: Move) -> None:
        piece = squares.pop(move.fr)
        squares[move.to] = piece

    def _is_legal_after(self, move: Move, side: str) -> bool:
        trial = dict(self.squares)
        self._apply_to(trial, move)
        probe = Board.__new__(Board)
        probe.squares = trial
        king = None
        target = "K" if side == RED else "k"
        for sq, piece in trial.items():
            if piece == target:
                king = sq
                break
        if king is None:
            return True  # edited position without a king: nothing to check
        if probe._attacks(king, enemy(side)):
            return False
        bk = probe.king_square(RED)
        rk = probe.king_square(BLACK)
        if bk and rk and bk[0] == rk[0] and not any(
            (bk[0], rr) in trial for rr in range(min(bk[1], rk[1]) + 1, max(bk[1], rk[1]))
        ):
            return False  # flying-general rule
        return True

    def legal_moves(self, side: str | None = None) -> list[Move]:
        if side is None:
            side = self.side_to_move
        return [m for m in self.pseudo_moves(side) if self._is_legal_after(m, side)]

    def legal_uci_set(self, side: str | None = None) -> set[str]:
        return {m.uci() for m in self.legal_moves(side)}

    # ------------------------------------------------------------- making
    def push(self, move: Move | str) -> Move:
        if isinstance(move, str):
            move = Move.from_uci(move)
        legal = {m.uci(): m for m in self.legal_moves()}
        key = move.uci()
        if key not in legal:
            raise IllegalMoveError(f"illegal move: {key}")
        move = legal[key]
        captured = self.squares.get(move.to, "")
        del self.squares[move.fr]
        self.squares[move.to] = move.piece
        self.move_history.append(move)
        if move.piece.lower() == "p" or captured:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1
        if self.side_to_move == BLACK:
            self.fullmove += 1
        self.side_to_move = enemy(self.side_to_move)
        rep_key = (self.board_key(), self.side_to_move)
        self._repetition[rep_key] = self._repetition.get(rep_key, 0) + 1
        return move

    def repetition_count(self) -> int:
        return self._repetition.get((self.board_key(), self.side_to_move), 0)

    # -------------------------------------------------------------- status
    def game_status(self, max_fullmoves: int = 0, threefold_draw: bool = True):
        """Return (state, winner).

        state in {"ongoing", "checkmate", "stalemate", "king_capture",
                  "repetition_draw", "move_limit_draw"}
        winner in {"w", "b", "draw", None}

        A missing king means it was captured (possible only in hand-edited
        positions, since legal play can never capture a king) - that side
        loses immediately.
        """
        red_king = self.king_square(RED)
        black_king = self.king_square(BLACK)
        if red_king is None and black_king is None:
            return "king_capture", "draw"
        if red_king is None:
            return "king_capture", BLACK
        if black_king is None:
            return "king_capture", RED
        moves = self.legal_moves()
        if not moves:
            if self.is_in_check(self.side_to_move):
                return "checkmate", enemy(self.side_to_move)
            # In xiangqi a stalemate loses for the side to move.
            return "stalemate", enemy(self.side_to_move)
        if threefold_draw and self.repetition_count() >= 3:
            return "repetition_draw", "draw"
        if max_fullmoves and self.fullmove > max_fullmoves:
            return "move_limit_draw", "draw"
        return "ongoing", None
