from __future__ import annotations

import json
from pathlib import Path

import pytest

from todo_backup.auth import StaticTokenProvider
from todo_backup.cli import main
from todo_backup.config import load_config
from todo_backup.graph import GRAPH_ROOT, GraphClient, Throttled
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
                    },
                    {
                        "id": "list-2",
                        "displayName": "Projects",
                    }
                ]
            }
        if url == f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?page=2":
            return {
                "value": [
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
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?"):
            return {
                "value": [
                    {
                        "id": "task-open",
                        "title": "Buy milk",
                        "status": "notStarted",
                        "body": {"contentType": "text", "content": "Remember oat milk."},
                        "importance": "normal",
                        "dueDateTime": {"dateTime": "2026-07-01T10:00:00", "timeZone": "UTC"},
                        "reminderDateTime": {"dateTime": "2026-06-30T09:00:00", "timeZone": "UTC"},
                        "recurrence": {"pattern": {"type": "weekly"}, "range": {"type": "noEnd"}},
                        "checklistItems": [
                            {"id": "step-1", "displayName": "Check fridge", "isChecked": True},
                            {"id": "step-2", "displayName": "Buy carton", "isChecked": False},
                        ],
                    },
                ],
                "@odata.nextLink": f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?page=2",
            }
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-2/tasks/delta?"):
            return {
                "value": [
                    {
                        "id": "task-project",
                        "title": "Plan launch",
                        "status": "notStarted",
                        "body": {"contentType": "text", "content": "Draft milestones."},
                    }
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-2/tasks/delta?$deltatoken=def",
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
    assert [task["id"] for task in snapshot["tasks"]] == ["task-open", "task-done"]
    assert snapshot["tasks"][0]["importance"] == "normal"
    assert snapshot["tasks"][0]["dueDateTime"] == {"dateTime": "2026-07-01T10:00:00", "timeZone": "UTC"}
    assert snapshot["tasks"][0]["reminderDateTime"] == {"dateTime": "2026-06-30T09:00:00", "timeZone": "UTC"}
    assert snapshot["tasks"][0]["recurrence"] == {"pattern": {"type": "weekly"}, "range": {"type": "noEnd"}}
    assert snapshot["tasks"][1]["categories"] == ["admin"]
    projects_snapshot = json.loads((output_dir / "snapshots" / "list-2.json").read_text(encoding="utf-8"))
    assert projects_snapshot["list"] == {"id": "list-2", "displayName": "Projects"}
    assert projects_snapshot["tasks"][0]["title"] == "Plan launch"

    markdown = (output_dir / "lists" / "Inbox.md").read_text(encoding="utf-8")
    assert "todo-list: Inbox" in markdown
    assert "todo-list-id: list-1" in markdown
    assert "synced:" in markdown
    assert "# Inbox" in markdown
    assert "- [ ] Buy milk" in markdown
    assert "  Remember oat milk." in markdown
    assert "  - [x] Check fridge" in markdown
    assert "  - [ ] Buy carton" in markdown
    assert "> [!done]- Completed (1)" in markdown
    assert "> - [x] File receipt" in markdown
    assert ">   June expenses" in markdown
    assert markdown.index("- [ ] Buy milk") < markdown.index("> [!done]- Completed (1)")
    projects_markdown = (output_dir / "lists" / "Projects.md").read_text(encoding="utf-8")
    assert "todo-list: Projects" in projects_markdown
    assert "- [ ] Plan launch" in projects_markdown

    state = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
    assert state["schemaVersion"] == 1
    assert state["lists"]["list-1"]["name"] == "Inbox"
    assert state["lists"]["list-1"]["snapshotFile"] == "snapshots/list-1.json"
    assert state["lists"]["list-1"]["markdownFile"] == "lists/Inbox.md"
    assert state["lists"]["list-1"]["deltaLink"].endswith("$deltatoken=abc")
    assert state["lists"]["list-1"]["lastSynced"] == snapshot["synced"]
    assert state["lists"]["list-2"]["name"] == "Projects"
    assert state["lists"]["list-2"]["snapshotFile"] == "snapshots/list-2.json"
    assert state["lists"]["list-2"]["markdownFile"] == "lists/Projects.md"
    assert state["lists"]["list-2"]["deltaLink"].endswith("$deltatoken=def")

    assert transport.requests[0][1]["Authorization"] == "Bearer static-test-token"
    assert any(url == f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?page=2" for url, _headers in transport.requests)


def test_pull_retries_after_throttling(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = ThrottledTransport()

    pull_once(GraphClient(transport, StaticTokenProvider()), output_dir)

    snapshot = json.loads((output_dir / "snapshots" / "list-1.json").read_text(encoding="utf-8"))
    assert snapshot["tasks"][0]["title"] == "Buy milk"
    assert transport.task_attempts == 2


def test_pull_resumes_interrupted_initial_export_without_refetching_completed_page(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    transport = InterruptedTransport()

    try:
        pull_once(GraphClient(transport, StaticTokenProvider()), output_dir)
    except RuntimeError as exc:
        assert str(exc) == "boom"

    state = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
    assert state["lists"]["list-1"]["pullNextLink"] == f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?page=2"
    assert transport.initial_page_calls == 1

    transport.fail_on_second_page = False
    pull_once(GraphClient(transport, StaticTokenProvider()), output_dir)

    snapshot = json.loads((output_dir / "snapshots" / "list-1.json").read_text(encoding="utf-8"))
    assert [task["id"] for task in snapshot["tasks"]] == ["task-open", "task-done"]
    state = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
    assert "pullNextLink" not in state["lists"]["list-1"]
    assert state["lists"]["list-1"]["deltaLink"].endswith("$deltatoken=abc")
    assert transport.initial_page_calls == 1


def test_status_command_prints_last_sync_and_counts(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "out"
    config_path.write_text(json.dumps({"clientId": "client-1", "outputDir": str(output_dir)}), encoding="utf-8")
    pull_once(GraphClient(FakeTransport(), StaticTokenProvider()), output_dir)

    assert main(["--config", str(config_path), "status"]) == 0

    output = capsys.readouterr().out
    assert "Inbox\tlastSynced=" in output
    assert "\topen=1\tcompleted=1" in output
    assert "Projects\tlastSynced=" in output
    assert "\topen=1\tcompleted=0" in output


def test_graph_client_gives_up_after_max_throttle_retries() -> None:
    class AlwaysThrottled:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url: str, headers: dict[str, str]) -> dict:
            self.calls += 1
            raise Throttled(0)

    transport = AlwaysThrottled()
    graph = GraphClient(transport, StaticTokenProvider(), max_throttle_retries=3)

    with pytest.raises(Throttled):
        graph.lists()
    assert transport.calls == 4  # initial attempt plus three retries


def test_status_before_pull_is_graceful(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "out"
    config_path.write_text(json.dumps({"clientId": "client-1", "outputDir": str(output_dir)}), encoding="utf-8")

    assert main(["--config", str(config_path), "status"]) == 0
    assert capsys.readouterr().out == ""


def test_missing_client_id_reports_configuration_error(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"outputDir": str(tmp_path / "out")}), encoding="utf-8")

    assert main(["--config", str(config_path), "status"]) == 1
    assert "Configuration error" in capsys.readouterr().err


def test_html_body_renders_as_text_and_snapshot_preserves_original(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    pull_once(GraphClient(HtmlTransport(), StaticTokenProvider()), output_dir)

    snapshot = json.loads((output_dir / "snapshots" / "list-1.json").read_text(encoding="utf-8"))
    assert snapshot["tasks"][0]["body"] == {
        "contentType": "html",
        "content": "<p>Hello <strong>world</strong>.</p><p>Bring &amp; review.</p>",
    }
    markdown = (output_dir / "lists" / "Inbox.md").read_text(encoding="utf-8")
    assert "  Hello world." in markdown
    assert "  Bring & review." in markdown
    assert "<strong>" not in markdown


class ThrottledTransport:
    def __init__(self) -> None:
        self.task_attempts = 0

    def get(self, url: str, headers: dict[str, str]) -> dict:
        if url == f"{GRAPH_ROOT}/me/todo/lists":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?"):
            self.task_attempts += 1
            if self.task_attempts == 1:
                raise Throttled(0)
            return _single_task_payload()
        raise AssertionError(f"Unexpected URL: {url}")


class InterruptedTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.fail_on_second_page = True
        self.initial_page_calls = 0

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.requests.append((url, headers))
        if url == f"{GRAPH_ROOT}/me/todo/lists":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url == f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?page=2":
            if self.fail_on_second_page:
                raise RuntimeError("boom")
            return {
                "value": [
                    {
                        "id": "task-done",
                        "title": "File receipt",
                        "status": "completed",
                        "body": {"contentType": "text", "content": "June expenses"},
                    }
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=abc",
            }
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?"):
            self.initial_page_calls += 1
            return {
                "value": [
                    {
                        "id": "task-open",
                        "title": "Buy milk",
                        "status": "notStarted",
                        "body": {"contentType": "text", "content": "Remember oat milk."},
                    }
                ],
                "@odata.nextLink": f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?page=2",
            }
        raise AssertionError(f"Unexpected URL: {url}")


class HtmlTransport:
    def get(self, url: str, headers: dict[str, str]) -> dict:
        if url == f"{GRAPH_ROOT}/me/todo/lists":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta?"):
            return {
                "value": [
                    {
                        "id": "task-html",
                        "title": "Read note",
                        "status": "notStarted",
                        "body": {
                            "contentType": "html",
                            "content": "<p>Hello <strong>world</strong>.</p><p>Bring &amp; review.</p>",
                        },
                    }
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=html",
            }
        raise AssertionError(f"Unexpected URL: {url}")


def _single_task_payload() -> dict:
    return {
        "value": [
            {
                "id": "task-open",
                "title": "Buy milk",
                "status": "notStarted",
                "body": {"contentType": "text", "content": "Remember oat milk."},
            }
        ],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/todo/lists/list-1/tasks/delta?$deltatoken=abc",
    }
