from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from todo_backup.graph import Throttled


class UrlLibTransport:
    def get(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After", "1")
                raise Throttled(int(retry_after)) from exc
            raise
