"""Entry point: opens the board window and the two LLM API console windows.

Usage:
    python main.py [--config path/to/config.yaml]
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from chess.engine import Board
from config.settings import ConfigError, load_config
from game.controller import GameController
from game.session_log import SessionLogger, new_session_dir
from ui.log_window import LogWindow
from ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM Play Chinese Chess")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("LLM Play Chinese Chess")

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        QMessageBox.critical(None, "配置错误", str(exc))
        return 1

    if not config.get("players"):
        QMessageBox.critical(None, "配置错误",
                             "配置文件中没有任何选手（players 列表为空）")
        return 1

    board = Board()
    controller = GameController(config, board)

    session_dir = new_session_dir()
    session_logger = SessionLogger(session_dir)

    log_red = LogWindow("API 通信日志 - 红方 (Red)")
    log_black = LogWindow("API 通信日志 - 黑方 (Black)")
    session_logger.attach_log_window("red", log_red)
    session_logger.attach_log_window("black", log_black)
    log_windows = {"red": log_red, "black": log_black}

    window = MainWindow(config, controller, log_windows,
                        session_logger=session_logger)
    window.resize(1180, 760)
    window.show()
    log_red.show()
    log_black.show()

    # Show initialization information in both console windows right away.
    init_text = (
        "LLM Play Chinese Chess - API console\n"
        "Initialization done. Waiting for game start.\n"
        "Every prompt sent to the model and every raw response "
        "will be printed here.\n"
        f"Session log directory: {session_dir}"
    )
    log_red.log_init(init_text)
    log_black.log_init(init_text)
    session_logger.log_move(
        "LLM Play Chinese Chess - 对局记谱\n"
        f"红方: {config['players'][0]['name']}  "
        f"黑方: {config['players'][1]['name'] if len(config['players']) > 1 else config['players'][0]['name']}"
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
