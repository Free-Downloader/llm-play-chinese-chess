"""Configuration loading and defaults."""

from __future__ import annotations

import copy
import os

import yaml

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "config.yaml"
)

DEFAULTS: dict = {
    "game": {
        "delay_between_moves_ms": 500,
        "invalid_move_retries": 2,
        "request_retries": 2,
        "request_timeout_s": 120,
        "max_fullmoves": 200,
        "threefold_repetition": True,
    },
    "prompts": {
        "allow_resign": True,
        "system": (
            "You are an expert Xiangqi (Chinese Chess) player. You will be given "
            "the current position as a FEN string, told which side you play, and "
            "given the complete list of legal moves in coordinate notation (e.g. "
            '"b7e4" means the piece on b7 moves to e4; files are letters a-i from '
            "left to right as seen from Red's side, ranks are digits 0-9 from "
            "Black's back rank to Red's back rank). Your goal is to win the game. "
            "Analyze the position carefully, then choose the single best legal "
            "move for {side}."
        ),
    },
    "players": [],
}

DEFAULT_PLAYER: dict = {
    "name": "unnamed",
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "temperature": 0.3,
    "max_tokens": 1024,
    "system_prompt": "",
    "extra_headers": {},
    # Provider-specific parameters merged verbatim into the request JSON
    # body, e.g. reasoning/thinking level: {"reasoning_effort": "high"}.
    "extra_body": {},
}


class ConfigError(Exception):
    pass


def load_config(path: str | None = None) -> dict:
    """Load config.yaml and merge it over the built-in defaults."""
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.isfile(path):
        raise ConfigError(f"configuration file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        user_cfg = yaml.safe_load(fh) or {}
    cfg = copy.deepcopy(DEFAULTS)
    for section in ("game", "prompts"):
        cfg[section].update(user_cfg.get(section) or {})
    players = []
    for p in user_cfg.get("players") or []:
        profile = dict(DEFAULT_PLAYER)
        profile.update(p or {})
        players.append(profile)
    cfg["players"] = players
    return cfg


def resolve_api_key(profile: dict) -> str:
    """Return the API key for a profile.

    Priority: non-empty value in the config file, then environment variable
    <NAME>_API_KEY, then OPENAI_API_KEY.
    """
    key = (profile.get("api_key") or "").strip()
    if key:
        return key
    env_name = profile.get("name", "llm")
    env_name = env_name.upper().replace(" ", "_").replace("-", "_") + "_API_KEY"
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    return os.environ.get("OPENAI_API_KEY", "").strip()
