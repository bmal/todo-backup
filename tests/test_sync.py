from __future__ import annotations

import json
from pathlib import Path

from todo_backup.auth import StaticTokenProvider
from todo_backup.graph import GRAPH_ROOT, GraphClient
from todo_backup.sync import pull_once, sync_once


class SyncFakeTransport:
    def __init__(self, sync_payload: dict) -> None:
        self.sync_payload = sync_payload
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.requests.append((url, headers))
        if url == f"{GRAPH_ROOT}/me/todo/lists":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?") and "deltatoken" not in url:
            return {
                "value": [
                    {
                        "id": "task-open",
                        "title": "Buy milk",
                        "status": "notStarted",
                        "body": {"contentType": "text", "content": "Remember oat milk."},
                    },
                    {
                        "id": "task-done",
                        "title": "File receipt",
                        "status": "completed",
                        "body": {"contentType": "text", "content": "June expenses"},
                    },
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=initial",
            }
        if url == "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=initial":
            return self.sync_payload
        raise AssertionError(f"Unexpected URL: {url}")


def test_sync_adds_task_and_advances_delta_link(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [
                {
                    "id": "task-added",
                    "title": "Call dentist",
                    "status": "notStarted",
                    "body": {"contentType": "text", "content": "Ask about Tuesday."},
                }
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=add",
        }
    )

    _pull_then_sync(output_dir, transport)

    snapshot = _read_json(output_dir / "snapshots" / "list-1.json")
    assert [task["id"] for task in snapshot["tasks"]] == ["task-open", "task-done", "task-added"]
    markdown = (output_dir / "lists" / "Inbox.md").read_text(encoding="utf-8")
    assert "- [ ] Call dentist" in markdown
    assert "  Ask about Tuesday." in markdown
    state = _read_json(output_dir / "state.json")
    assert state["lists"]["list-1"]["deltaLink"].endswith("$deltatoken=add")
    assert any(url.endswith("$deltatoken=initial") for url, _headers in transport.requests)


def test_sync_edits_task_in_snapshot_and_markdown(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [
                {
                    "id": "task-open",
                    "title": "Buy almond milk",
                    "status": "inProgress",
                    "body": {"contentType": "text", "content": "Use coupon."},
                }
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=edit",
        }
    )

    _pull_then_sync(output_dir, transport)

    snapshot = _read_json(output_dir / "snapshots" / "list-1.json")
    assert snapshot["tasks"][0]["title"] == "Buy almond milk"
    assert snapshot["tasks"][0]["body"]["content"] == "Use coupon."
    markdown = (output_dir / "lists" / "Inbox.md").read_text(encoding="utf-8")
    assert "- [ ] Buy almond milk" in markdown
    assert "  Use coupon." in markdown
    assert "Buy milk" not in markdown


def test_sync_completed_task_moves_to_folded_section(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [
                {
                    "id": "task-open",
                    "title": "Buy milk",
                    "status": "completed",
                    "body": {"contentType": "text", "content": "Remember oat milk."},
                }
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=complete",
        }
    )

    _pull_then_sync(output_dir, transport)

    markdown = (output_dir / "lists" / "Inbox.md").read_text(encoding="utf-8")
    assert "> [!done]- Completed (2)" in markdown
    assert "> - [x] Buy milk" in markdown
    assert "- [ ] Buy milk" not in markdown


def test_sync_removed_task_is_pruned(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [{"id": "task-open", "@removed": {"reason": "deleted"}}],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=removed",
        }
    )

    _pull_then_sync(output_dir, transport)

    snapshot = _read_json(output_dir / "snapshots" / "list-1.json")
    assert [task["id"] for task in snapshot["tasks"]] == ["task-done"]
    markdown = (output_dir / "lists" / "Inbox.md").read_text(encoding="utf-8")
    assert "Buy milk" not in markdown
    assert "> [!done]- Completed (1)" in markdown


def test_sync_noop_produces_no_content_changes(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=initial",
        }
    )
    pull_once(GraphClient(transport, StaticTokenProvider()), output_dir)
    before = _output_texts(output_dir)

    sync_once(GraphClient(transport, StaticTokenProvider()), output_dir)

    assert _output_texts(output_dir) == before


def _pull_then_sync(output_dir: Path, transport: SyncFakeTransport) -> None:
    graph = GraphClient(transport, StaticTokenProvider())
    pull_once(graph, output_dir)
    sync_once(graph, output_dir)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _output_texts(output_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(output_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    }
