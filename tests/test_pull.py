from __future__ import annotations

import json
from pathlib import Path

from todo_backup.auth import StaticTokenProvider
from todo_backup.config import load_config
from todo_backup.graph import GRAPH_ROOT, GraphClient
from todo_backup.sync import pull_once


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.requests.append((url, headers))
        if url == f"{GRAPH_ROOT}/me/todo/lists":
            return {
                "value": [
                    {
                        "id": "list-1",
                        "displayName": "Inbox",
                    }
                ]
            }
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?"):
            return {
                "value": [
                    {
                        "id": "task-open",
                        "title": "Buy milk",
                        "status": "notStarted",
                        "body": {"contentType": "text", "content": "Remember oat milk."},
                        "importance": "normal",
                    },
                    {
                        "id": "task-done",
                        "title": "File receipt",
                        "status": "completed",
                        "body": {"contentType": "text", "content": "June expenses"},
                        "categories": ["admin"],
                    },
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=abc",
            }
        raise AssertionError(f"Unexpected URL: {url}")


def test_pull_writes_snapshot_markdown_and_state(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "out"
    config_path.write_text(json.dumps({"clientId": "client-1", "outputDir": str(output_dir)}), encoding="utf-8")
    config = load_config(config_path)
    transport = FakeTransport()

    pull_once(GraphClient(transport, StaticTokenProvider()), config.output_dir)

    snapshot = json.loads((output_dir / "snapshots" / "list-1.json").read_text(encoding="utf-8"))
    assert snapshot["list"] == {"id": "list-1", "displayName": "Inbox"}
    assert snapshot["tasks"][0]["importance"] == "normal"
    assert snapshot["tasks"][1]["categories"] == ["admin"]

    markdown = (output_dir / "lists" / "Inbox.md").read_text(encoding="utf-8")
    assert "todo-list: Inbox" in markdown
    assert "todo-list-id: list-1" in markdown
    assert "synced:" in markdown
    assert "# Inbox" in markdown
    assert "- [ ] Buy milk" in markdown
    assert "  Remember oat milk." in markdown
    assert "- [x] File receipt" in markdown
    assert "  June expenses" in markdown

    state = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
    assert state["schemaVersion"] == 1
    assert state["lists"]["list-1"]["name"] == "Inbox"
    assert state["lists"]["list-1"]["snapshotFile"] == "snapshots/list-1.json"
    assert state["lists"]["list-1"]["markdownFile"] == "lists/Inbox.md"
    assert state["lists"]["list-1"]["deltaLink"].endswith("$deltatoken=abc")
    assert state["lists"]["list-1"]["lastSynced"] == snapshot["synced"]

    assert transport.requests[0][1]["Authorization"] == "Bearer static-test-token"
