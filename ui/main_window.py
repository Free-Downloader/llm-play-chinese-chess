"""Main window: the xiangqi board, the game controls and the move list."""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from chess.engine import INITIAL_FEN, Board
from game.controller import PIECE_ZH, GameController
from ui.board_widget import ASSETS_DIR, SPRITE_NAMES, BoardWidget

PALETTE_PIECES = ["K", "A", "B", "N", "R", "C", "P",
                  "k", "a", "b", "n", "r", "c", "p"]


class MainWindow(QWidget):
    def __init__(self, config: dict, controller: GameController,
                 log_windows: dict[str, object], session_logger=None):
        super().__init__()
        self._config = config
        self.controller = controller
        self.log_windows = log_windows  # {"red": LogWindow, "black": LogWindow}
        self.session_logger = session_logger
        self.board = controller.board
        self._edit_selected: tuple[int, int] | None = None
        self._place_piece: str | None = None
        self._think_base = ""
        self._think_since: float | None = None
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(1000)
        self._think_timer.timeout.connect(self._on_think_tick)

        self.setWindowTitle("LLM 中国象棋对弈")
        self._build_ui()
        self._wire_controller()
        self._refresh_board()
        self._update_status("请配置双方选手并点击“开始对弈”")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        # board
        self.board_widget = BoardWidget(self)
        self.board_widget.set_board(self.board)
        self.board_widget.square_clicked.connect(self._on_square_clicked)
        root.addWidget(self.board_widget, stretch=1)

        # side panel
        panel_widget = QWidget()
        panel_widget.setMinimumWidth(340)
        panel_widget.setMaximumWidth(420)
        panel = QVBoxLayout(panel_widget)
        panel.setSpacing(8)
        root.addWidget(panel_widget)

        # -- game control group
        control_box = QGroupBox("对局控制")
        control_form = QVBoxLayout(control_box)

        profiles = self._config.get("players", [])
        names = [p["name"] for p in profiles]

        row_red = QHBoxLayout()
        row_red.addWidget(QLabel("红方："))
        self.combo_red = QComboBox()
        self.combo_red.addItems(names)
        if len(names) > 0:
            self.combo_red.setCurrentIndex(0)
        row_red.addWidget(self.combo_red, stretch=1)
        control_form.addLayout(row_red)

        row_black = QHBoxLayout()
        row_black.addWidget(QLabel("黑方："))
        self.combo_black = QComboBox()
        self.combo_black.addItems(names)
        if len(names) > 1:
            self.combo_black.setCurrentIndex(1)
        elif len(names) > 0:
            self.combo_black.setCurrentIndex(0)
        row_black.addWidget(self.combo_black, stretch=1)
        control_form.addLayout(row_black)

        self.button_start = QPushButton("开始对弈")
        self.button_start.clicked.connect(self._on_start)
        control_form.addWidget(self.button_start)

        self.button_stop = QPushButton("停止")
        self.button_stop.setEnabled(False)
        self.button_stop.clicked.connect(self._on_stop)
        control_form.addWidget(self.button_stop)

        self.button_test = QPushButton("测试双方 API 连接")
        self.button_test.clicked.connect(self._on_test)
        control_form.addWidget(self.button_test)

        self.check_edit = QCheckBox("编辑局面")
        self.check_edit.toggled.connect(self._on_edit_toggled)
        control_form.addWidget(self.check_edit)

        self.check_flip = QCheckBox("翻转棋盘")
        self.check_flip.toggled.connect(
            lambda on: self.board_widget.set_flipped(on))
        control_form.addWidget(self.check_flip)

        row_board = QHBoxLayout()
        self.button_reset = QPushButton("重置为初始局面")
        self.button_reset.clicked.connect(self._on_reset)
        row_board.addWidget(self.button_reset)
        self.button_clear = QPushButton("清空棋盘")
        self.button_clear.clicked.connect(self._on_clear)
        row_board.addWidget(self.button_clear)
        control_form.addLayout(row_board)

        panel.addWidget(control_box)

        # -- edit palette
        self.palette_box = QGroupBox("棋子面板（编辑局面：左键放置/走子，右键删除）")
        palette_grid = QGridLayout(self.palette_box)
        self.palette_buttons: dict[str, QPushButton] = {}
        for i, ch in enumerate(PALETTE_PIECES):
            btn = QPushButton()
            btn.setIcon(QIcon(QPixmap(
                f"{ASSETS_DIR}/{SPRITE_NAMES[ch]}.png")))
            btn.setIconSize(QSize(40, 40))
            btn.setFixedSize(52, 52)
            btn.setToolTip(PIECE_ZH[ch])
            btn.clicked.connect(lambda _=False, c=ch: self._on_palette(c))
            palette_grid.addWidget(btn, i // 7, i % 7)
            self.palette_buttons[ch] = btn
        self.palette_box.setVisible(False)
        panel.addWidget(self.palette_box)

        # -- info group
        info_box = QGroupBox("对局信息")
        info_layout = QVBoxLayout(info_box)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        info_layout.addWidget(self.status_label)
        self.fen_label = QLabel()
        self.fen_label.setWordWrap(True)
        font = self.fen_label.font()
        font.setPointSize(8)
        self.fen_label.setFont(font)
        info_layout.addWidget(self.fen_label)
        self.move_list = QPlainTextEdit()
        self.move_list.setReadOnly(True)
        self.move_list.setMaximumBlockCount(1000)
        info_layout.addWidget(self.move_list)
        panel.addWidget(info_box, stretch=1)

        self._sync_profile_selection()

    def _wire_controller(self) -> None:
        c = self.controller
        c.request_logged.connect(self._on_request_logged)
        c.response_logged.connect(self._on_response_logged)
        c.info_logged.connect(self._on_info_logged)
        c.error_logged.connect(self._on_error_logged)
        c.move_played.connect(self._on_move_played)
        c.thinking_started.connect(self._on_thinking_started)
        c.status_changed.connect(self._update_status)
        c.game_over.connect(self._on_game_over)

    # ------------------------------------------------------- thinking timer
    def _on_thinking_started(self, text: str) -> None:
        self._think_base = text
        self._think_since = time.time()
        self._think_timer.start()
        self.status_label.setText(text)

    def _on_think_tick(self) -> None:
        if self._think_since is None:
            return
        elapsed = int(time.time() - self._think_since)
        self.status_label.setText(f"{self._think_base} · 已思考 {elapsed}s")

    def _stop_think_timer(self) -> None:
        self._think_timer.stop()
        self._think_since = None

    # ------------------------------------------------------- controller io
    def _on_request_logged(self, key: str, header: str, body: str) -> None:
        self.log_windows[key].log_request(header, body)

    def _on_response_logged(self, key: str, body: str) -> None:
        self.log_windows[key].log_response(body)

    def _on_info_logged(self, key: str, text: str) -> None:
        self.log_windows[key].log_info(text)

    def _on_error_logged(self, key: str, text: str) -> None:
        self.log_windows[key].log_error(text)

    def _on_move_played(self, text: str, _elapsed: float) -> None:
        self._stop_think_timer()
        self.move_list.appendPlainText(text)
        if self.session_logger is not None:
            self.session_logger.log_move(text)
        self._refresh_board()

    def _on_game_over(self, reason: str, _result: str) -> None:
        self._stop_think_timer()
        line = f"*** {reason} ***"
        self.move_list.appendPlainText(line)
        if self.session_logger is not None:
            self.session_logger.log_move(line)
        self._set_running_ui(False)
        self._refresh_board()

    def _update_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.fen_label.setText(f"FEN: {self.board.fen()}")

    # ------------------------------------------------------------ buttons
    def _sync_profile_selection(self) -> None:
        profiles = self._config.get("players", [])
        if not profiles:
            return
        red = profiles[min(self.combo_red.currentIndex(), len(profiles) - 1)]
        black = profiles[min(self.combo_black.currentIndex(), len(profiles) - 1)]
        self.controller.set_profiles(red, black)

    def _on_start(self) -> None:
        self._sync_profile_selection()
        error = self.controller.start()
        if error:
            QMessageBox.warning(self, "无法开始", error)
            return
        self.move_list.clear()
        self.board_widget.set_last_move(None)
        self._set_running_ui(True)
        self._refresh_board()

    def _on_stop(self) -> None:
        self.controller.stop()

    def _on_test(self) -> None:
        self._sync_profile_selection()
        self._update_status("正在测试双方 API 连接……")
        self.controller.test_connection("red")
        self.controller.test_connection("black")

    def _set_running_ui(self, running: bool) -> None:
        self.button_start.setEnabled(not running)
        self.button_stop.setEnabled(running)
        self.button_test.setEnabled(not running)
        self.check_edit.setEnabled(not running)
        self.combo_red.setEnabled(not running)
        self.combo_black.setEnabled(not running)
        self.button_reset.setEnabled(not running)
        self.button_clear.setEnabled(not running)

    def _on_reset(self) -> None:
        self._set_board(Board(INITIAL_FEN))
        self.move_list.clear()
        self._update_status("局面已重置为初始局面")

    def _on_clear(self) -> None:
        self._set_board(Board("9/9/9/9/9/9/9/9/9/9 w - - 0 1"))
        self.move_list.clear()
        self._update_status("棋盘已清空，请编辑局面")

    # -------------------------------------------------------------- edit
    def _on_edit_toggled(self, on: bool) -> None:
        self.palette_box.setVisible(on)
        if not on:
            self._edit_selected = None
            self._place_piece = None
            self.board_widget.set_selected(None)
            self.board_widget.set_legal_hints(())
            self.board_widget.set_place_piece(None)

    def _on_palette(self, ch: str) -> None:
        if self._place_piece == ch:
            self._place_piece = None
        else:
            self._place_piece = ch
        self.board_widget.set_place_piece(self._place_piece)

    def _on_square_clicked(self, file_: int, rank: int, button) -> None:
        if not self.check_edit.isChecked() or self.controller.is_running():
            return
        sq = (file_, rank)
        if button == Qt.MouseButton.RightButton:
            self.board.squares.pop(sq, None)
            self._edit_selected = None
            self.board_widget.set_selected(None)
            self._commit_edit()
            return
        if button != Qt.MouseButton.LeftButton:
            return
        if self._place_piece is not None:
            self.board.squares[sq] = self._place_piece
            self._commit_edit()
            return
        if self._edit_selected is None:
            if sq in self.board.squares:
                self._edit_selected = sq
                self.board_widget.set_selected(sq)
                self.board_widget.set_legal_hints(self._edit_targets(sq))
        elif self._edit_selected == sq:
            self._edit_selected = None
            self.board_widget.set_selected(None)
            self.board_widget.set_legal_hints(())
        else:
            self.board.squares[sq] = self.board.squares.pop(self._edit_selected)
            self._edit_selected = None
            self.board_widget.set_selected(None)
            self.board_widget.set_legal_hints(())
            self._commit_edit()

    def _edit_targets(self, sq: tuple[int, int]) -> set[tuple[int, int]]:
        piece = self.board.squares.get(sq)
        if piece is None:
            return set()
        return {m.to for m in self.board.pseudo_moves()
                if m.fr == sq and m.piece == piece}

    def _commit_edit(self) -> None:
        """Reset the board object so history/repetition state stays coherent."""
        fen = self.board.fen()
        self._set_board(Board(fen))

    def _set_board(self, board: Board) -> None:
        self.board = board
        self.controller.board = board
        self.board_widget.set_board(board)
        self.board_widget.set_last_move(None)
        self.board_widget.set_check_square(None)
        self.board_widget.set_legal_hints(())
        self.board_widget.set_selected(None)
        self._refresh_board()

    def _refresh_board(self) -> None:
        self.board_widget.update()
        if self.board.move_history:
            self.board_widget.set_last_move(self.board.move_history[-1])
        in_check = self.board.is_in_check(self.board.side_to_move)
        king = self.board.king_square(self.board.side_to_move)
        self.board_widget.set_check_square(king if in_check else None)
        self.fen_label.setText(f"FEN: {self.board.fen()}")
