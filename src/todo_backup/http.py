from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen


class UrlLibTransport:
    def get(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
