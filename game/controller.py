"""The game controller: alternately asks the two LLM players for moves,
validates and plays them, detects the end of the game, and reports every
prompt/response to the log windows through Qt signals.
"""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QObject, QTimer, Signal

from chess.engine import BLACK, RED, Board, Move, side_name
from chess.notation import move_to_chinese
from config.settings import resolve_api_key
from llm.client import LLMWorker
from llm.prompts import RESIGN_TOKEN, build_messages, extract_move

KEY_FOR_SIDE = {RED: "red", BLACK: "black"}

RESULT_TEXT = {
    "checkmate": "将死",
    "stalemate": "困毙（无着可动判负）",
    "king_capture": "将/帅被吃",
    "repetition_draw": "三次重复和棋",
    "move_limit_draw": "达到步数上限，和棋",
}


class GameController(QObject):
    # (side_key, header, body) - an outgoing LLM request
    request_logged = Signal(str, str, str)
    # (side_key, body) - the raw API response
    response_logged = Signal(str, str)
    # (side_key, text) - informational line for the log window
    info_logged = Signal(str, str)
    # (side_key, text)
    error_logged = Signal(str, str)
    # (text, elapsed_seconds) - one line for the move list, plus how long the
    # model thought about this move (cumulative across retries)
    move_played = Signal(str, float)
    # (text) - emitted whenever a move request is sent (starts the timer)
    thinking_started = Signal(str)
    # (text) - current status line for the main window
    status_changed = Signal(str)
    # (reason, result_text) - game over
    game_over = Signal(str, str)

    def __init__(self, config: dict, board: Board, parent=None):
        super().__init__(parent)
        self._config = config
        self.board = board
        self._profiles: dict[str, dict] = {"red": None, "black": None}
        self._running = False
        self._generation = 0
        self._retries_left = 0
        self._error_retries_left = 0
        self._worker: LLMWorker | None = None
        self._last_invalid_reply: str | None = None
        self._think_start: float | None = None

    # ------------------------------------------------------------- public
    def set_profiles(self, red: dict, black: dict) -> None:
        self._profiles["red"] = red
        self._profiles["black"] = black

    def is_running(self) -> bool:
        return self._running

    def start(self) -> str | None:
        """Begin a game. Returns an error message or None on success."""
        if self._running:
            return "对局已在进行中"
        for key, side in (("red", RED), ("black", BLACK)):
            if not self._profiles.get(key):
                return f"请先为{'红方' if key == 'red' else '黑方'}选择选手"
        if self.board.king_square(RED) is None or self.board.king_square(BLACK) is None:
            return "局面中双方都必须有将/帅才能开始对弈"
        self._running = True
        self._generation += 1
        self._retries_left = 0
        self._error_retries_left = 0
        self._last_invalid_reply = None
        for key in ("red", "black"):
            self._log_init(key)
        self.status_changed.emit(
            f"对局开始：红方 = {self._profiles['red']['name']}，"
            f"黑方 = {self._profiles['black']['name']}，"
            f"{side_name(self.board.side_to_move)}先行"
        )
        QTimer.singleShot(0, self._step)
        return None

    def stop(self, reason: str = "用户停止了对局") -> None:
        if not self._running:
            return
        self._finish(reason, "对局中止")

    def test_connection(self, key: str) -> None:
        """Send a minimal request for one side and log the outcome."""
        profile = self._profiles.get(key)
        if not profile:
            self.error_logged.emit(key, "该方尚未选择选手配置")
            return
        messages = [{"role": "user", "content": "Reply with exactly: OK"}]
        self.request_logged.emit(
            key, "CONNECTION TEST - request",
            self._format_request(profile, messages),
        )
        self._start_worker(key, messages, is_test=True)

    # -------------------------------------------------------------- steps
    def _step(self) -> None:
        if not self._running:
            return
        game = self._config["game"]
        state, winner = self.board.game_status(
            max_fullmoves=game.get("max_fullmoves", 0),
            threefold_draw=game.get("threefold_repetition", True),
        )
        if state != "ongoing":
            if winner == "draw":
                self._finish(RESULT_TEXT[state], "和棋")
            else:
                self._finish(
                    f"{RESULT_TEXT[state]}，{side_name(winner)}获胜",
                    f"{side_name(winner)}胜",
                )
            return

        side = self.board.side_to_move
        key = KEY_FOR_SIDE[side]
        profile = self._profiles[key]
        legal = self.board.legal_moves()
        prompts_cfg = self._config["prompts"]
        system = profile.get("system_prompt") or prompts_cfg["system"]
        messages = build_messages(
            self.board, side, legal, system, prompts_cfg["allow_resign"]
        )
        if self._last_invalid_reply:
            messages[1]["content"] += (
                f'\nYour previous reply "{self._last_invalid_reply}" was not a '
                f"legal move. Answer again with exactly one legal move and "
                f"nothing else."
            )

        header = f"MOVE {len(self.board.move_history) + 1} - {side_name(side)} - request"
        self.request_logged.emit(key, header, self._format_request(profile, messages))
        if self._think_start is None:
            self._think_start = time.time()
        self.status_changed.emit(f"等待{side_name(side)}方 {profile['name']} 走棋……")
        self.thinking_started.emit(
            f"等待{side_name(side)}方 {profile['name']} 走棋")
        self._start_worker(key, messages, is_test=False)

    def _start_worker(self, key: str, messages: list[dict], is_test: bool) -> None:
        profile = self._profiles[key]
        timeout = float(self._config["game"].get("request_timeout_s", 120))
        self._generation += 1
        # Test requests use generation 0 so concurrent red/black tests do not
        # invalidate each other; they are always accepted when they arrive.
        generation = 0 if is_test else self._generation
        self._worker = LLMWorker(profile, messages, timeout, parent=self)
        self._worker.finished_ok.connect(
            lambda record, g=generation, k=key, t=is_test:
            self._on_reply(g, k, t, record))
        self._worker.failed.connect(
            lambda err, g=generation, k=key, t=is_test:
            self._on_error(g, k, t, err))
        self._worker.start()

    def _on_reply(self, generation: int, key: str, is_test: bool, record: dict) -> None:
        if generation != self._generation and generation != 0:
            return  # a newer request superseded this one
        try:
            body = json.dumps(json.loads(record["response"]), ensure_ascii=False,
                              indent=2)
        except ValueError:
            body = record["response"]
        self.response_logged.emit(key, body)

        if is_test:
            self.info_logged.emit(key, "Connection test succeeded.")
            self.status_changed.emit("连接测试成功")
            return
        if not self._running:
            return

        content = record["content"]
        reasoning = record.get("reasoning_content")
        if reasoning:
            self.info_logged.emit(key, "--- reasoning content (chain of thought) ---\n"
                                  + reasoning.strip())
        legal_set = self.board.legal_uci_set()
        token = extract_move(content, legal_set)
        self.info_logged.emit(key, f"Parsed answer: {token or '(none)'}")

        prompts_cfg = self._config["prompts"]
        if token == RESIGN_TOKEN and prompts_cfg["allow_resign"]:
            winner = "black" if key == "red" else "red"
            self._finish(f"{side_name(self.board.side_to_move)}方认输",
                         f"{'红方' if winner == 'red' else '黑方'}胜（认输）")
            return
        if token is not None and token in legal_set:
            self._retries_left = 0
            self._error_retries_left = 0
            self._last_invalid_reply = None
            text = move_to_chinese(self.board, Move.from_uci(token))
            played = self.board.push(token)
            elapsed = time.time() - self._think_start if self._think_start else 0.0
            self._think_start = None
            self._emit_move(played, text, elapsed)
            self._schedule_next()
            return

        # Illegal or unparseable answer: re-ask while retries remain.
        self._last_invalid_reply = content.strip()[:200]
        limit = int(self._config["game"].get("invalid_move_retries", 2))
        if self._retries_left < limit:
            self._retries_left += 1
            self.error_logged.emit(
                key,
                f'Illegal answer "{content.strip()[:120]}" '
                f"- re-asking ({self._retries_left}/{limit} used).",
            )
            self._schedule_next()
        else:
            winner = "black" if key == "red" else "red"
            self._finish(
                f"{side_name(self.board.side_to_move)}方连续返回非法着法或出错，对局终止",
                f"{'红方' if winner == 'red' else '黑方'}胜（对方出错）",
            )

    def _on_error(self, generation: int, key: str, is_test: bool, error: str) -> None:
        if generation != self._generation and generation != 0:
            return
        self.error_logged.emit(key, error)
        if is_test:
            self.status_changed.emit("连接测试失败，详见日志窗口")
            return
        if not self._running:
            return
        # Transport failures have their own budget: a flaky connection must
        # not eat the retries reserved for illegal answers (and vice versa).
        limit = int(self._config["game"].get("request_retries", 2))
        if self._error_retries_left < limit:
            self._error_retries_left += 1
            self.error_logged.emit(
                key, f"Retrying ({self._error_retries_left}/{limit} used).")
            self._schedule_next()
        else:
            winner = "black" if key == "red" else "red"
            self._finish(f"API 请求失败：{error}",
                         f"{'红方' if winner == 'red' else '黑方'}胜（对方出错）")

    # ------------------------------------------------------------ helpers
    def _schedule_next(self) -> None:
        if not self._running:
            return
        delay = int(self._config["game"].get("delay_between_moves_ms", 500))
        QTimer.singleShot(delay, self._step)

    def _emit_move(self, move, chinese: str, elapsed: float) -> None:
        number = (len(self.board.move_history) + 1) // 2
        side = "红" if move.piece.isupper() else "黑"
        self.move_played.emit(
            f"{number}. {side} {chinese} · 用时 {elapsed:.1f}s", elapsed)

    def _finish(self, reason: str, result_text: str) -> None:
        self._running = False
        self._think_start = None
        self._generation += 1  # invalidate any pending worker reply
        self.info_logged.emit("red", f"GAME OVER: {reason}")
        self.info_logged.emit("black", f"GAME OVER: {reason}")
        self.status_changed.emit(f"对局结束：{reason}")
        self.game_over.emit(reason, result_text)

    def _log_init(self, key: str) -> None:
        profile = self._profiles[key]
        key_source = "config file" if (profile.get("api_key") or "").strip() else \
            ("environment variable" if resolve_api_key(profile) else "NOT SET")
        side = "红方 (Red)" if key == "red" else "黑方 (Black)"
        self.info_logged.emit(
            key,
            "=== INITIALIZATION ===\n"
            f"Player:   {profile['name']} ({side})\n"
            f"Base URL: {profile['base_url']}\n"
            f"Model:    {profile['model']}\n"
            f"Params:   temperature={profile['temperature']}, "
            f"max_tokens={profile['max_tokens']}, "
            f"timeout={self._config['game'].get('request_timeout_s', 120)}s\n"
            f"API key:  {key_source}",
        )

    @staticmethod
    def _format_request(profile: dict, messages: list[dict]) -> str:
        url = (profile.get("base_url") or "").rstrip("/") + "/chat/completions"
        payload = {
            "model": profile.get("model"),
            "messages": messages,
            "temperature": profile.get("temperature"),
            "max_tokens": profile.get("max_tokens"),
        }
        payload.update(profile.get("extra_body") or {})
        return f"POST {url}\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


PIECE_ZH = {
    "K": "帅", "A": "仕", "B": "相", "N": "马", "R": "车", "C": "炮", "P": "兵",
    "k": "将", "a": "士", "b": "象", "n": "马", "r": "车", "c": "炮", "p": "卒",
}
