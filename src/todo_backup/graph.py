from __future__ import annotations

from dataclasses import dataclass
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


class GraphClient:
    def __init__(self, transport: Transport, token_provider: TokenProvider) -> None:
        self._transport = transport
        self._token_provider = token_provider

    def lists(self) -> list[GraphList]:
        values: list[dict[str, Any]] = []
        url = f"{GRAPH_ROOT}/me/todo/lists"
        while url:
            payload = self._get(url)
            values.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
        if not values:
            raise RuntimeError("No Microsoft To Do lists returned by Graph")
        return [GraphList(id=value["id"], display_name=value["displayName"]) for value in values]

    def task_delta(self, list_id: str) -> tuple[list[dict[str, Any]], str]:
        query = urlencode(
            {
                "$select": "id,title,status,body,createdDateTime,lastModifiedDateTime,dueDateTime,importance,categories,recurrence,reminderDateTime",
                "$expand": "checklistItems",
            }
        )
        url = f"{GRAPH_ROOT}/me/todo/lists/{list_id}/tasks/delta?{query}"
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
        return self._transport.get(
            url,
            headers={
                "Authorization": f"Bearer {self._token_provider.access_token()}",
                "Accept": "application/json",
                "Prefer": "odata.maxpagesize=50",
            },
        )
