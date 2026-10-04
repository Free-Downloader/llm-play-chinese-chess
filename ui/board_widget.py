"""The xiangqi board widget: paints checkerboard.jpg + piece sprites and
translates mouse clicks into board-square signals.

Pixel geometry was measured from Art_Assets/checkerboard.jpg (933x993).
Logical coordinates: file 0..8 left->right (Red's view), rank 0..9 top->bottom
(rank 0 = Black's back rank).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Art_Assets"
)

BOARD_IMG = os.path.join(ASSETS_DIR, "checkerboard.jpg")
ARROW_IMG = os.path.join(ASSETS_DIR, "arrow-right.png")
BOARD_W, BOARD_H = 933, 993

GRID_X = [99, 194, 285, 376, 466, 557, 647, 738, 829]
GRID_Y = [92, 187, 277, 368, 458, 566, 656, 747, 837, 928]

# piece char -> sprite file name (r* = red, b* = black)
SPRITE_NAMES = {
    "K": "rk", "A": "ra", "B": "rb", "N": "rn", "R": "rr", "C": "rc", "P": "rp",
    "k": "bk", "a": "ba", "b": "bb", "n": "bn", "r": "br", "c": "bc", "p": "bp",
}


class BoardWidget(QWidget):
    square_clicked = Signal(int, int, object)  # file, rank, mouse button

    def __init__(self, parent=None):
        super().__init__(parent)
        self._board = None
        self._board_pixmap = QPixmap(BOARD_IMG)
        self._arrow_pixmap = QPixmap(ARROW_IMG)
        self._piece_pixmaps = {
            ch: QPixmap(os.path.join(ASSETS_DIR, name + ".png"))
            for ch, name in SPRITE_NAMES.items()
        }
        self._flipped = False
        self._selected: tuple[int, int] | None = None
        self._last_move: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._legal_hints: set[tuple[int, int]] = set()
        self._check_square: tuple[int, int] | None = None
        self._place_piece: str | None = None  # edit mode: piece letter to place
        self.setMinimumSize(480, 512)

    # -------------------------------------------------------------- state
    def set_board(self, board) -> None:
        self._board = board
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        self._flipped = flipped
        self.update()

    def set_selected(self, sq) -> None:
        self._selected = sq
        self.update()

    def set_last_move(self, move) -> None:
        if move is None:
            self._last_move = None
        else:
            self._last_move = (move.fr, move.to)
        self.update()

    def set_legal_hints(self, squares) -> None:
        self._legal_hints = set(squares or ())
        self.update()

    def set_check_square(self, sq) -> None:
        self._check_square = sq
        self.update()

    def set_place_piece(self, piece: str | None) -> None:
        """Edit mode: the piece letter that the next board click will place."""
        self._place_piece = piece
        self.update()

    # ---------------------------------------------------------- transform
    def _display_square(self, file_: int, rank: int) -> tuple[int, int]:
        """Logical -> display orientation (180-degree rotation when flipped)."""
        if self._flipped:
            return 8 - file_, 9 - rank
        return file_, rank

    def _layout(self):
        """Return (target_rect, scale, offset_x, offset_y) mapping image pixels
        to widget pixels with a uniform scale, centered."""
        w, h = self.width(), self.height()
        scale = min(w / BOARD_W, h / BOARD_H)
        drawn_w, drawn_h = BOARD_W * scale, BOARD_H * scale
        ox = (w - drawn_w) / 2
        oy = (h - drawn_h) / 2
        return QRectF(ox, oy, drawn_w, drawn_h), scale, ox, oy

    def _square_center(self, file_: int, rank: int) -> tuple[float, float]:
        df, dr = self._display_square(file_, rank)
        _, scale, ox, oy = self._layout()
        x = ox + GRID_X[df] * scale
        y = oy + GRID_Y[dr] * scale
        return x, y

    def square_at(self, pos) -> tuple[int, int] | None:
        """Map a widget position to the nearest grid intersection."""
        _, scale, ox, oy = self._layout()
        best, best_d = None, 0.45 * 91 * scale
        for rank in range(10):
            for file_ in range(9):
                x, y = self._square_center(file_, rank)
                d = ((pos.x() - x) ** 2 + (pos.y() - y) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = (file_, rank), d
        return best

    # -------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        target, scale, ox, oy = self._layout()
        painter.drawPixmap(target, self._board_pixmap, QRectF(0, 0, BOARD_W, BOARD_H))

        if self._last_move:
            for sq in self._last_move:
                self._fill_square(painter, sq, QColor(255, 213, 79, 110))
        if self._check_square:
            self._fill_square(painter, self._check_square, QColor(244, 67, 54, 130))
        if self._selected:
            self._fill_square(painter, self._selected, QColor(129, 199, 132, 140))

        if self._board:
            piece_size = 88 * scale
            for (file_, rank), piece in self._board.squares.items():
                x, y = self._square_center(file_, rank)
                pixmap = self._piece_pixmaps.get(piece)
                if pixmap:
                    painter.drawPixmap(
                        QRectF(x - piece_size / 2, y - piece_size / 2,
                               piece_size, piece_size), pixmap,
                        QRectF(0, 0, pixmap.width(), pixmap.height()))

        if self._last_move:
            self._draw_arrow(painter, self._last_move[0], self._last_move[1])

        for sq in self._legal_hints:
            x, y = self._square_center(*sq)
            radius = 8 * scale
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(66, 66, 66, 160))
            painter.drawEllipse(QRectF(x - radius, y - radius,
                                       2 * radius, 2 * radius))
        painter.end()

    def _draw_arrow(self, painter: QPainter,
                    fr: tuple[int, int], to: tuple[int, int]) -> None:
        """Draw the green arrow from the source square to the destination."""
        import math

        _, scale, _, _ = self._layout()
        x1, y1 = self._square_center(*fr)
        x2, y2 = self._square_center(*to)
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 2 or self._arrow_pixmap.isNull():
            return
        ux, uy = dx / length, dy / length
        # start just outside the source piece, end at the destination centre
        piece_r = 44 * scale
        sx, sy = x1 + ux * piece_r * 0.6, y1 + uy * piece_r * 0.6
        ex, ey = x2 - ux * piece_r * 0.1, y2 - uy * piece_r * 0.1
        arrow_len = math.hypot(ex - sx, ey - sy)
        if arrow_len < 4:
            return
        angle = math.degrees(math.atan2(ey - sy, ex - sx))
        scaled = self._arrow_pixmap.scaled(
            int(arrow_len), int(arrow_len),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        rotated = scaled.transformed(QTransform().rotate(angle))
        painter.setOpacity(0.72)
        painter.drawPixmap(
            QRectF((sx + ex) / 2 - rotated.width() / 2,
                   (sy + ey) / 2 - rotated.height() / 2,
                   rotated.width(), rotated.height()),
            rotated,
            QRectF(0, 0, rotated.width(), rotated.height()))
        painter.setOpacity(1.0)

    def _fill_square(self, painter: QPainter, sq, color: QColor) -> None:
        _, scale, _, _ = self._layout()
        x, y = self._square_center(*sq)
        size = 88 * scale
        painter.fillRect(QRectF(x - size / 2, y - size / 2, size, size), color)

    # ----------------------------------------------------------- keyboard
    def mousePressEvent(self, event) -> None:  # noqa: N802
        sq = self.square_at(event.position())
        if sq is not None:
            self.square_clicked.emit(sq[0], sq[1], event.button())
        super().mousePressEvent(event)
