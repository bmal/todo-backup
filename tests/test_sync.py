from __future__ import annotations

import json
from pathlib import Path

from todo_backup.auth import StaticTokenProvider
from todo_backup.graph import GRAPH_ROOT, GraphClient
from todo_backup.sync import pull_once, render_once, sync_once


class SyncFakeTransport:
    def __init__(
        self,
        sync_payload: dict,
        list_payloads: list[list[dict]] | None = None,
        initial_task_payloads: dict[str, dict] | None = None,
    ) -> None:
        self.sync_payload = sync_payload
        self.list_payloads = list_payloads or [[{"id": "list-1", "displayName": "Inbox"}]]
        self.initial_task_payloads = initial_task_payloads or {"list-1": _initial_list_1_payload()}
        self.list_calls = 0
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.requests.append((url, headers))
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            index = min(self.list_calls, len(self.list_payloads) - 1)
            self.list_calls += 1
            return {"value": self.list_payloads[index]}
        for list_id, payload in self.initial_task_payloads.items():
            if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/{list_id}/tasks/delta") and "deltatoken" not in url:
                return payload
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


def test_sync_discovers_new_list_and_pulls_it(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=unchanged",
        },
        list_payloads=[
            [{"id": "list-1", "displayName": "Inbox"}],
            [{"id": "list-1", "displayName": "Inbox"}, {"id": "list-2", "displayName": "Projects"}],
        ],
        initial_task_payloads={
            "list-1": _initial_list_1_payload(),
            "list-2": {
                "value": [
                    {
                        "id": "task-project",
                        "title": "Plan launch",
                        "status": "notStarted",
                        "body": {"contentType": "text", "content": "Draft milestones."},
                    }
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-2/tasks/delta?$deltatoken=new-list",
            },
        },
    )

    _pull_then_sync(output_dir, transport)

    snapshot = _read_json(output_dir / "snapshots" / "list-2.json")
    assert snapshot["list"] == {"id": "list-2", "displayName": "Projects"}
    assert snapshot["tasks"][0]["title"] == "Plan launch"
    markdown = (output_dir / "lists" / "Projects.md").read_text(encoding="utf-8")
    assert "todo-list: Projects" in markdown
    assert "- [ ] Plan launch" in markdown
    state = _read_json(output_dir / "state.json")
    assert state["lists"]["list-2"]["snapshotFile"] == "snapshots/list-2.json"
    assert state["lists"]["list-2"]["markdownFile"] == "lists/Projects.md"
    assert state["lists"]["list-2"]["deltaLink"].endswith("$deltatoken=new-list")
    assert state["lists"]["list-1"]["deltaLink"].endswith("$deltatoken=unchanged")


def test_sync_renames_list_file_and_frontmatter_preserving_tasks(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=renamed",
        },
        list_payloads=[
            [{"id": "list-1", "displayName": "Inbox"}],
            [{"id": "list-1", "displayName": "Personal"}],
        ],
    )

    _pull_then_sync(output_dir, transport)

    assert not (output_dir / "lists" / "Inbox.md").exists()
    markdown = (output_dir / "lists" / "Personal.md").read_text(encoding="utf-8")
    assert "todo-list: Personal" in markdown
    assert "# Personal" in markdown
    assert "- [ ] Buy milk" in markdown
    assert "> - [x] File receipt" in markdown
    snapshot = _read_json(output_dir / "snapshots" / "list-1.json")
    assert snapshot["list"] == {"id": "list-1", "displayName": "Personal"}
    assert [task["id"] for task in snapshot["tasks"]] == ["task-open", "task-done"]
    state = _read_json(output_dir / "state.json")
    assert state["lists"]["list-1"]["name"] == "Personal"
    assert state["lists"]["list-1"]["markdownFile"] == "lists/Personal.md"
    assert state["lists"]["list-1"]["deltaLink"].endswith("$deltatoken=renamed")


def test_sync_deletes_removed_list_files_and_state(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=unused",
        },
        list_payloads=[
            [{"id": "list-1", "displayName": "Inbox"}],
            [],
        ],
    )
    pull_once(GraphClient(transport, StaticTokenProvider()), output_dir)
    assert (output_dir / "snapshots" / "list-1.json").exists()
    assert (output_dir / "lists" / "Inbox.md").exists()

    sync_once(GraphClient(transport, StaticTokenProvider()), output_dir)

    assert not (output_dir / "snapshots" / "list-1.json").exists()
    assert not (output_dir / "lists" / "Inbox.md").exists()
    state = _read_json(output_dir / "state.json")
    assert state["lists"] == {}


def test_pull_writes_mapped_lists_under_configured_directories(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {"value": [], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/unused"},
        list_payloads=[[{"id": "list-1", "displayName": "Inbox"}]],
    )

    pull_once(GraphClient(transport, StaticTokenProvider()), output_dir, {"Inbox": "On hold"})

    assert not (output_dir / "lists" / "Inbox.md").exists()
    markdown = (output_dir / "lists" / "On hold" / "Inbox.md").read_text(encoding="utf-8")
    assert "todo-list: Inbox" in markdown
    state = _read_json(output_dir / "state.json")
    assert state["lists"]["list-1"]["markdownFile"] == "lists/On hold/Inbox.md"


def test_sync_moves_markdown_when_directory_mapping_changes(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {
            "value": [],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=unchanged",
        }
    )
    pull_once(GraphClient(transport, StaticTokenProvider()), output_dir)
    assert (output_dir / "lists" / "Inbox.md").exists()

    sync_once(GraphClient(transport, StaticTokenProvider()), output_dir, {"Inbox": "Archive"})

    assert not (output_dir / "lists" / "Inbox.md").exists()
    assert (output_dir / "lists" / "Archive" / "Inbox.md").exists()
    state = _read_json(output_dir / "state.json")
    assert state["lists"]["list-1"]["markdownFile"] == "lists/Archive/Inbox.md"


def test_render_moves_markdown_when_directory_mapping_changes(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    pull_once(GraphClient(SyncFakeTransport({"value": [], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/unused"}), StaticTokenProvider()), output_dir)

    render_once(output_dir, {"Inbox": "Later"})

    assert not (output_dir / "lists" / "Inbox.md").exists()
    assert (output_dir / "lists" / "Later" / "Inbox.md").exists()
    state = _read_json(output_dir / "state.json")
    assert state["lists"]["list-1"]["markdownFile"] == "lists/Later/Inbox.md"


def test_pull_strict_directory_mapping_rejects_unmapped_lists(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = SyncFakeTransport(
        {"value": [], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/unused"},
        list_payloads=[[{"id": "list-1", "displayName": "Inbox"}, {"id": "list-2", "displayName": "Projects"}]],
    )

    try:
        pull_once(GraphClient(transport, StaticTokenProvider()), output_dir, {"Inbox": "GTD"}, True)
    except ValueError as exc:
        assert "Unmapped Microsoft To Do lists: 'Projects'" in str(exc)
    else:
        raise AssertionError("Expected unmapped list error")

    assert not (output_dir / "state.json").exists()


def test_render_strict_directory_mapping_rejects_unmapped_lists(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    pull_once(
        GraphClient(
            SyncFakeTransport({"value": [], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/unused"}),
            StaticTokenProvider(),
        ),
        output_dir,
    )

    try:
        render_once(output_dir, {}, True)
    except ValueError as exc:
        assert "Unmapped Microsoft To Do lists: 'Inbox'" in str(exc)
    else:
        raise AssertionError("Expected unmapped list error")


def _initial_list_1_payload() -> dict:
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
