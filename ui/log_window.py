"""Console-style window showing the API communication of one LLM player."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMainWindow, QPlainTextEdit


class LogWindow(QMainWindow):
    """Displays initialization info and every prompt/response exchange."""

    MAX_BLOCKS = 5000

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560)
        self._file = None
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.TypeWriter)
        self.text.setFont(font)
        self.text.setMaximumBlockCount(self.MAX_BLOCKS)
        self.setCentralWidget(self.text)

    def attach_file(self, file_object) -> None:
        """Also mirror every line written to this window into a file."""
        self._file = file_object

    # ------------------------------------------------------------------ API
    def append(self, line: str) -> None:
        self.text.appendPlainText(line)
        if self._file is not None:
            self._file.write(line + "\n")
            self._file.flush()

    def log_init(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        for line in text.splitlines():
            self.append(f"[{stamp}] {line}")
        self.append("")

    def log_request(self, header: str, body: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.append(f"[{stamp}] >>> {header}")
        for line in body.splitlines():
            self.append("    " + line)

    def log_response(self, body: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.append(f"[{stamp}] <<< RESPONSE")
        for line in body.splitlines():
            self.append("    " + line)
        self.append("")

    def log_info(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        for line in text.splitlines():
            self.append(f"[{stamp}] {line}")
        self.append("")

    def log_error(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        for line in text.splitlines():
            self.append(f"[{stamp}] !!! ERROR: {line}")
        self.append("")
