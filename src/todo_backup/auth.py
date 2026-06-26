from __future__ import annotations


class StaticTokenProvider:
    def __init__(self, token: str = "static-test-token") -> None:
        self._token = token

    def access_token(self) -> str:
        return self._token
