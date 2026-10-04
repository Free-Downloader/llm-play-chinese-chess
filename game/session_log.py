"""Session logging to disk.

Each program run creates a directory  logs/session_YYYYMMDD_HHMMSS/  with:
  red_api.log    - everything shown in the Red API console window
  black_api.log  - everything shown in the Black API console window
  moves.txt      - the move list in Chinese notation plus the game result
"""

from __future__ import annotations

import os
from datetime import datetime

LOGS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)


def new_session_dir() -> str:
    name = "session_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOGS_ROOT, name)
    os.makedirs(path, exist_ok=True)
    return path


class SessionLogger:
    """Mirrors the two API log windows and the move list to files."""

    def __init__(self, directory: str):
        self.directory = directory
        self._files: dict[str, object] = {}

    # ------------------------------------------------------------------ api
    def attach_log_window(self, key: str, window) -> None:
        """Mirror everything appended to `window` into <key>_api.log."""
        window.attach_file(self._get(f"{key}_api.log"))

    def log_api(self, key: str, text: str) -> None:
        fh = self._get(f"{key}_api.log")
        for line in text.splitlines():
            fh.write(line + "\n")
        fh.flush()

    def log_move(self, text: str) -> None:
        fh = self._get("moves.txt")
        fh.write(text + "\n")
        fh.flush()

    def _get(self, name: str):
        if name not in self._files:
            self._files[name] = open(
                os.path.join(self.directory, name), "a", encoding="utf-8")
        return self._files[name]

    def close(self) -> None:
        for fh in self._files.values():
            fh.close()
        self._files.clear()
