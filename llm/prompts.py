"""Prompt construction and answer parsing for the LLM players.

Everything sent to the models is in English and deliberately minimal:
system prompt + current FEN + "it is your turn" + the legal move list +
whether resigning is allowed.  The model must answer with exactly one move
(e.g. "b7e4") or the word "resign".

Models do not always obey that instruction: thinking models like to write a
long analysis first, quote the FEN back, echo the legal-move list and announce
their choice in the last sentence.  ``extract_move`` is therefore written to
recover the move the model actually decided on, and to never mistake quoted
prompt text for an answer.
"""

from __future__ import annotations

import re

from chess.engine import Board, side_name

RESIGN_TOKEN = "resign"

# One coordinate move, e.g. "b7e4".  The lookarounds are what stop the pattern
# from matching inside a longer run of characters: the FEN field "4C2c1" must
# not be read as the move "c2c1", which is exactly what used to happen.
_MOVE_PATTERN = r"(?<![0-9a-z])[a-i][0-9][a-i][0-9](?![0-9a-z])"

# Text that merely quotes the prompt back and must never be parsed as an
# answer: a FEN board field ("rnbakabnr/9/9/..." - its rank fields contain
# move-shaped substrings), the echoed "Legal moves: ..." list, and the
# instruction sentence with its "e.g. b7e4" example.
_QUOTED = (
    re.compile(r"[rnbakcpRNBAKCP1-9]+(?:/[rnbakcpRNBAKCP1-9]+){2,}"),
    re.compile(r"(?i)\blegal\s+moves?\b[^\n:]{0,12}:[^\n]*"),
    re.compile(r"(?i)\breply with exactly one legal move[^\n]*"),
)

# How models announce the move they picked, e.g.
#   "I will select `d9d1`.", "Answer: b0c2", "Conclusion: `h1e1` is the best
#   move.", "`i6i8` is the best move." (the last one is _BEST_RE below).
_ANNOUNCE = (
    r"final\s+answer|answer|my\s+(?:move|choice|pick)|best\s+move|"
    r"chosen\s+move|decision|conclusion|verdict|move\s+is|"
    r"i\s*(?:will|shall|would|'ll|\u2019ll)?\s*"
    r"(?:play|choose|select|pick|go\s+with|output|make\s+the\s+move)|"
    r"(?:let'?s|let\s+us)\s+(?:play|choose|select|pick|go\s+with)|"
    r"i'?m\s+going\s+with|going\s+with|i\s+decide\s+(?:on|to\s+play)"
)
_ANNOUNCED_RE = re.compile(
    rf"(?i)\b(?:{_ANNOUNCE})\b[^\n]{{0,25}}?(?P<move>{_MOVE_PATTERN})"
)
_BEST_RE = re.compile(
    rf"(?i)(?P<move>{_MOVE_PATTERN})[^\n]{{0,20}}?"
    rf"\b(?:is|seems\s+to\s+be)\b[^\n]{{0,20}}?"
    rf"\b(?:best|strongest|winning|chosen|correct|right|"
    rf"my\s+(?:move|choice|pick)|the\s+move)\b"
)

# A phrase like "if I play d9d1 ..." announces no decision at all.
_SPECULATIVE = re.compile(
    r"(?i)(?:\b(?:if|whether|unless|suppose|supposing|maybe|perhaps|not|"
    r"instead\s+of|rather\s+than|should|could|might|consider|considering|"
    r"evaluating|checking|testing)\b|n't\b)"
)

# "resign", possibly with markdown/punctuation, as the whole reply or as its
# final line - models wrap a resignation in a paragraph of prose.
_RESIGN_LINE = re.compile(
    r"(?i)^\s*(?:\**|`*|\"*)?(?:i\s+(?:would\s+like\s+to\s+|want\s+to\s+|"
    r"hereby\s+)?)?resign(?:\**|`*|\"*)?\s*[.!]?\s*$"
)


def build_messages(
    board: Board,
    side: str,
    legal_moves: list,
    system_prompt: str,
    allow_resign: bool,
) -> list[dict]:
    """Return the OpenAI-style messages list for the given position."""
    side_label = side_name(side)
    fen = board.fen()
    legal = sorted(m.uci() for m in legal_moves)
    system = system_prompt.format(side=side_label)

    lines = [
        f"Current position (FEN): {fen}",
        f"It is your turn to move. You play {side_label}.",
        "Legal moves: " + ", ".join(legal),
    ]
    if allow_resign:
        lines.append(
            f'If your position is hopeless you may resign by replying exactly '
            f'"{RESIGN_TOKEN}".'
        )
    lines.append(
        "Reply with exactly one legal move in coordinate notation (e.g. \"b7e4\")"
        + (" or resign." if allow_resign else ".")
    )
    user = "\n".join(lines)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_move(text: str, legal_moves=None) -> str | None:
    """Extract the move the model decided on from its reply.

    ``legal_moves`` (any iterable of coordinate moves) is optional but
    recommended: it lets the parser ignore move-shaped noise that is not a
    legal move in the current position.

    Order of preference:

    1. a resignation (the whole reply, or its last line, is "resign");
    2. the last move the reply explicitly announces as its choice
       ("I will play ...", "Answer: ...", "... is the best move");
    3. the last *legal* move mentioned anywhere in the reply - models reason
       towards their conclusion, so the last one is their choice;
    4. the last move-shaped token, even if illegal, so that the caller can
       report it back to the model when re-asking.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if _is_resignation(raw):
        return RESIGN_TOKEN

    cleaned = _mask_quoted_prompt_text(raw)
    declared = _declared_move(cleaned)
    if declared:
        return declared

    tokens = [m.group(0).lower()
              for m in re.finditer(_MOVE_PATTERN, cleaned, re.I)]
    if not tokens:
        return None
    if legal_moves is not None:
        legal = {str(move).lower() for move in legal_moves}
        for token in reversed(tokens):
            if token in legal:
                return token
    return tokens[-1]


def _is_resignation(text: str) -> bool:
    if _RESIGN_LINE.match(text):
        return True
    last_line = text.rstrip().splitlines()[-1] if text.rstrip() else ""
    return bool(_RESIGN_LINE.match(last_line))


def _mask_quoted_prompt_text(text: str) -> str:
    """Blank out FEN strings and echoed prompt lines, keeping the layout."""
    for pattern in _QUOTED:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _declared_move(text: str) -> str | None:
    """The move announced as the answer, if the reply announces one."""
    best = None  # (token start, token)
    for pattern in (_ANNOUNCED_RE, _BEST_RE):
        for match in pattern.finditer(text):
            move = match.group("move")
            start = match.start("move")
            if _SPECULATIVE.search(_current_line(text, start)[-40:]):
                continue  # "if I play d9d1 ..." is not a decision
            if best is None or start > best[0]:
                best = (start, move.lower())
    return best[1] if best else None


def _current_line(text: str, index: int) -> str:
    """The part of `text` before `index` that is on the same line."""
    return text[text.rfind("\n", 0, index) + 1:index]
