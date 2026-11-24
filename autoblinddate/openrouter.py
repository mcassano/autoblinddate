"""Minimal OpenRouter chat-completions client (stdlib only)."""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"

Message = dict[str, str]


class ChatClient(Protocol):
    def complete(self, model: str, messages: list[Message], *, temperature: float, max_tokens: int) -> str: ...


class OpenRouterError(RuntimeError):
    pass


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing values."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class OpenRouterClient:
    api_key: str
    timeout: float = 120.0
    max_retries: int = 4
    app_title: str = "autoblinddate"

    @classmethod
    def from_env(cls) -> "OpenRouterClient":
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set (put it in .env or the environment).")
        return cls(api_key=key)

    def complete(self, model: str, messages: list[Message], *, temperature: float = 0.9,
                 max_tokens: int = 400) -> str:
        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Ask reasoning models to keep their thinking out of the content field.
            "reasoning": {"exclude": True},
        }).encode()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": self.app_title,
        }
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                last_err = OpenRouterError(f"HTTP {e.code} from OpenRouter: {detail}")
                if e.code not in (408, 429, 500, 502, 503, 504):
                    raise last_err from e
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = OpenRouterError(f"Network error: {e}")
            else:
                if "error" in payload:
                    last_err = OpenRouterError(f"OpenRouter error: {payload['error']}")
                else:
                    try:
                        content = payload["choices"][0]["message"].get("content") or ""
                    except (KeyError, IndexError) as e:
                        raise OpenRouterError(f"Unexpected response shape: {str(payload)[:500]}") from e
                    if content.strip():
                        return content
                    last_err = OpenRouterError("Model returned empty content")
            if attempt < self.max_retries:
                time.sleep(min(30.0, (2 ** attempt) + random.random()))
        assert last_err is not None
        raise last_err
