"""OpenAI-compatible chat-completions client.

The HTTP call runs in a worker thread (see LLMWorker); this module only
contains the blocking request itself plus a signal-emitting QThread wrapper.
"""

from __future__ import annotations

import json

import requests

from config.settings import resolve_api_key


class LLMError(Exception):
    """Raised for any failure to obtain a usable model reply."""


def chat_completion(profile: dict, messages: list[dict], timeout: float) -> dict:
    """Call {base_url}/chat/completions and return the parsed JSON response.

    Returns a dict with keys:
      content     - the assistant message text
      request     - the exact request payload sent (for logging)
      response    - the raw response body text
      status_code - HTTP status code
    """
    base_url = (profile.get("base_url") or "").rstrip("/")
    if not base_url:
        raise LLMError(f"player {profile.get('name')!r} has no base_url configured")
    api_key = resolve_api_key(profile)
    payload = {
        "model": profile.get("model", ""),
        "messages": messages,
        "temperature": profile.get("temperature", 0.3),
        "max_tokens": profile.get("max_tokens", 1024),
    }
    # Provider-specific options (reasoning/thinking level etc.) override or
    # extend the standard parameters verbatim.
    extra_body = profile.get("extra_body") or {}
    payload.update(extra_body)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for key, value in (profile.get("extra_headers") or {}).items():
        headers[str(key)] = str(value)

    url = base_url + "/chat/completions"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise LLMError(f"request failed: {exc}") from exc

    result = {
        "request": {"url": url, "headers": _redact(headers), **payload},
        "response": resp.text,
        "status_code": resp.status_code,
    }
    if resp.status_code != 200:
        raise LLMError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    try:
        data = resp.json()
        message = data["choices"][0]["message"]
        content = message["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"malformed API response: {resp.text[:500]}") from exc
    if not isinstance(content, str) or not content.strip():
        # Reasoning models may burn the whole token budget on hidden
        # reasoning and leave the visible content empty - say so clearly.
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            raise LLMError(
                f"API returned an empty message (model produced "
                f"{len(reasoning)} chars of reasoning but no content; try "
                f"increasing max_tokens). Reasoning begins: "
                f"{reasoning[:120]!r}")
        raise LLMError("API returned an empty message (no content, no "
                       "reasoning returned either)")
    result["content"] = content
    # DeepSeek-style thinking mode returns the chain-of-thought separately.
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        result["reasoning_content"] = reasoning
    return result


def _redact(headers: dict) -> dict:
    redacted = dict(headers)
    if "Authorization" in redacted:
        redacted["Authorization"] = "Bearer ***"
    return redacted


def format_for_log(record: dict) -> str:
    """Pretty-print a request/response record for the console window."""
    request_part = json.dumps(record["request"], ensure_ascii=False, indent=2)
    try:
        response_part = json.dumps(
            json.loads(record["response"]), ensure_ascii=False, indent=2
        )
    except ValueError:
        response_part = record["response"]
    return (
        f"POST {record['request']['url']}\n"
        f"--- request body ---\n{request_part}\n"
        f"--- response (HTTP {record['status_code']}) ---\n{response_part}"
    )


# --------------------------------------------------------------------- Qt

from PySide6.QtCore import QThread, Signal  # noqa: E402


class LLMWorker(QThread):
    """Runs one chat-completion call off the GUI thread.

    finished_ok(record: dict)  - carries content/request/response/status_code
    failed(error: str)
    """

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, profile: dict, messages: list[dict], timeout: float,
                 parent=None):
        super().__init__(parent)
        self._profile = profile
        self._messages = messages
        self._timeout = timeout

    def run(self) -> None:
        try:
            record = chat_completion(self._profile, self._messages, self._timeout)
        except LLMError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - never let the thread die silently
            self.failed.emit(f"unexpected error: {exc}")
        else:
            self.finished_ok.emit(record)
