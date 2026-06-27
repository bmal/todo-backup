from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Protocol
from urllib.parse import urlencode


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str]) -> dict[str, Any]: ...


class TokenProvider(Protocol):
    def access_token(self) -> str: ...


@dataclass(frozen=True)
class GraphList:
    id: str
    display_name: str


class Throttled(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Microsoft Graph throttled the request; retry after {retry_after} seconds")
        self.retry_after = retry_after


class GraphClient:
    def __init__(
        self,
        transport: Transport,
        token_provider: TokenProvider,
        *,
        max_throttle_retries: int = 8,
    ) -> None:
        self._transport = transport
        self._token_provider = token_provider
        self._max_throttle_retries = max_throttle_retries

    def lists(self) -> list[GraphList]:
        values: list[dict[str, Any]] = []
        url = f"{GRAPH_ROOT}/me/todo/lists"
        while url:
            payload = self._get(url)
            values.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
        return [GraphList(id=value["id"], display_name=value["displayName"]) for value in values]

    def task_delta(self, list_id: str) -> tuple[list[dict[str, Any]], str]:
        return self.task_delta_url(self.task_delta_initial_url(list_id))

    def task_delta_initial_url(self, list_id: str) -> str:
        query = urlencode(
            {
                "$select": "id,title,status,body,createdDateTime,lastModifiedDateTime,completedDateTime,startDateTime,dueDateTime,isReminderOn,importance,categories,recurrence,reminderDateTime",
                "$expand": "checklistItems",
            }
        )
        return f"{GRAPH_ROOT}/me/todo/lists/{list_id}/tasks/delta?{query}"

    def task_delta_page(self, url: str) -> tuple[list[dict[str, Any]], str | None, str | None]:
        payload = self._get(url)
        return payload.get("value", []), payload.get("@odata.nextLink"), payload.get("@odata.deltaLink")

    def task_delta_url(self, delta_url: str) -> tuple[list[dict[str, Any]], str]:
        url = delta_url
        values: list[dict[str, Any]] = []
        delta_link = ""
        while url:
            payload = self._get(url)
            values.extend(payload.get("value", []))
            delta_link = payload.get("@odata.deltaLink", "")
            url = payload.get("@odata.nextLink")
        if not delta_link:
            raise RuntimeError("Task delta response did not include @odata.deltaLink")
        return values, delta_link

    def _get(self, url: str) -> dict[str, Any]:
        attempts = 0
        while True:
            try:
                return self._transport.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._token_provider.access_token()}",
                        "Accept": "application/json",
                        "Prefer": "odata.maxpagesize=50",
                    },
                )
            except Throttled as exc:
                attempts += 1
                if attempts > self._max_throttle_retries:
                    raise
                time.sleep(exc.retry_after)
