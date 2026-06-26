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

    def first_list(self) -> GraphList:
        payload = self._get(f"{GRAPH_ROOT}/me/todo/lists")
        lists = payload.get("value", [])
        if not lists:
            raise RuntimeError("No Microsoft To Do lists returned by Graph")
        first = lists[0]
        return GraphList(id=first["id"], display_name=first["displayName"])

    def task_delta(self, list_id: str) -> tuple[list[dict[str, Any]], str]:
        query = urlencode(
            {
                "$select": "id,title,status,body,createdDateTime,lastModifiedDateTime,dueDateTime,importance,categories,recurrence,reminderDateTime",
                "$expand": "checklistItems",
            }
        )
        url = f"{GRAPH_ROOT}/me/todo/lists/{list_id}/tasks/delta?{query}"
        payload = self._get(url)
        delta_link = payload.get("@odata.deltaLink")
        if not delta_link:
            raise RuntimeError("Task delta response did not include @odata.deltaLink")
        return list(payload.get("value", [])), delta_link

    def _get(self, url: str) -> dict[str, Any]:
        return self._transport.get(
            url,
            headers={
                "Authorization": f"Bearer {self._token_provider.access_token()}",
                "Accept": "application/json",
                "Prefer": "odata.maxpagesize=50",
            },
        )
