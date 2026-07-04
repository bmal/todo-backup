from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from todo_backup.graph import GraphApiError, Throttled


class UrlLibTransport:
    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout

    def get(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After", "1")
                raise Throttled(int(retry_after)) from exc
            body = exc.read().decode("utf-8", errors="replace")
            raise GraphApiError(f"Microsoft Graph returned HTTP {exc.code} for {url}: {_error_message(body)}") from exc


def _error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or "No response body"
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code")
        if message:
            return str(message)
    return body.strip() or "No response body"
