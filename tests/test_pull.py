from __future__ import annotations

import json
from pathlib import Path

import pytest

from todo_backup.auth import StaticTokenProvider
from todo_backup.cli import main
from todo_backup.config import load_config
from todo_backup.graph import GRAPH_ROOT, GraphClient, Throttled
from todo_backup.sync import pull_once, repull_once


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.requests.append((url, headers))
        # The plain collection endpoint truncates (only list-1, no nextLink);
        # relying on it would silently drop list-2. The delta endpoint returns
        # the full set across two nextLink pages.
        if url == f"{GRAPH_ROOT}/me/todo/lists":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            return {
                "value": [{"id": "list-1", "displayName": "Inbox"}],
                "@odata.nextLink": f"{GRAPH_ROOT}/me/todo/lists/delta?page=2",
            }
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta?page=2":
            return {
                "value": [{"id": "list-2", "displayName": "Projects"}],
                "@odata.deltaLink": f"{GRAPH_ROOT}/me/todo/lists/delta?$deltatoken=lists",
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
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta"):
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
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-2/tasks/delta"):
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


def test_config_loads_list_directory_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "out"
    config_path.write_text(
        json.dumps(
            {
                "clientId": "client-1",
                "outputDir": str(output_dir),
                "listDirectories": {"Inbox": "Archive", "Projects": "On hold"},
                "requireListDirectories": True,
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.list_directories == {"Inbox": "Archive", "Projects": "On hold"}
    assert config.require_list_directories is True


def test_config_rejects_invalid_list_directory_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"clientId": "client-1", "listDirectories": ["Inbox"]}), encoding="utf-8")

    with pytest.raises(ValueError, match="listDirectories"):
        load_config(config_path)


def test_config_rejects_invalid_require_list_directories(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"clientId": "client-1", "requireListDirectories": "yes"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="requireListDirectories"):
        load_config(config_path)


class TruncatingListsTransport:
    """Plain /me/todo/lists truncates; /me/todo/lists/delta returns everything."""

    def __init__(self) -> None:
        self.plain_list_calls = 0

    def get(self, url: str, headers: dict[str, str]) -> dict:
        if url == f"{GRAPH_ROOT}/me/todo/lists":
            self.plain_list_calls += 1
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            return {
                "value": [{"id": "list-1", "displayName": "Inbox"}],
                "@odata.nextLink": f"{GRAPH_ROOT}/me/todo/lists/delta?page=2",
            }
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta?page=2":
            return {
                "value": [{"id": "list-2", "displayName": "Projects"}],
                "@odata.nextLink": f"{GRAPH_ROOT}/me/todo/lists/delta?page=3",
            }
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta?page=3":
            return {
                "value": [{"id": "list-3", "displayName": "Errands"}],
                "@odata.deltaLink": f"{GRAPH_ROOT}/me/todo/lists/delta?$deltatoken=done",
            }
        raise AssertionError(f"Unexpected URL: {url}")


def test_lists_enumerates_full_set_via_delta_not_truncating_endpoint() -> None:
    transport = TruncatingListsTransport()

    lists = GraphClient(transport, StaticTokenProvider()).lists()

    assert [todo_list.id for todo_list in lists] == ["list-1", "list-2", "list-3"]
    # The truncating collection endpoint must never be consulted.
    assert transport.plain_list_calls == 0


class RemovedAndDuplicateListsTransport:
    def get(self, url: str, headers: dict[str, str]) -> dict:
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            return {
                "value": [
                    {"id": "list-1", "displayName": "Inbox"},
                    {"id": "list-1", "displayName": "Inbox"},
                    {"id": "list-2", "displayName": "Projects"},
                    {"id": "list-2", "@removed": {"reason": "deleted"}},
                    {"id": "list-3", "displayName": "Errands"},
                ],
            }
        raise AssertionError(f"Unexpected URL: {url}")


def test_lists_dedupes_by_id_and_skips_removed() -> None:
    lists = GraphClient(RemovedAndDuplicateListsTransport(), StaticTokenProvider()).lists()

    assert [(todo_list.id, todo_list.display_name) for todo_list in lists] == [
        ("list-1", "Inbox"),
        ("list-3", "Errands"),
    ]


class MissingDisplayNameTransport:
    def get(self, url: str, headers: dict[str, str]) -> dict:
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            return {"value": [{"id": "list-1"}]}
        raise AssertionError(f"Unexpected URL: {url}")


def test_lists_tolerates_entry_without_display_name() -> None:
    # A malformed delta entry lacking displayName must not crash enumeration.
    lists = GraphClient(MissingDisplayNameTransport(), StaticTokenProvider()).lists()

    assert [(todo_list.id, todo_list.display_name) for todo_list in lists] == [("list-1", "")]


def test_pull_prints_completion_summary(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "out"

    summary = pull_once(GraphClient(FakeTransport(), StaticTokenProvider()), output_dir)

    assert summary.list_count == 2
    assert summary.task_count == 3
    assert "Backed up 2 lists and 3 tasks." in capsys.readouterr().out


def test_repull_prints_completion_summary(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "out"

    summary = repull_once(GraphClient(FakeTransport(), StaticTokenProvider()), output_dir)

    assert (summary.list_count, summary.task_count) == (2, 3)
    assert "Backed up 2 lists and 3 tasks." in capsys.readouterr().out


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


def test_repull_requires_confirmation(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"clientId": "client-1", "outputDir": str(tmp_path / "out")}), encoding="utf-8")

    assert main(["--config", str(config_path), "repull"]) == 1
    assert "without --yes" in capsys.readouterr().err


def test_repull_deletes_output_before_fresh_pull(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    stale_file = output_dir / "stale.txt"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("stale", encoding="utf-8")

    repull_once(GraphClient(FakeTransport(), StaticTokenProvider()), output_dir)

    assert not stale_file.exists()
    assert (output_dir / "state.json").exists()


def test_repull_refuses_home_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe outputDir"):
        repull_once(GraphClient(FakeTransport(), StaticTokenProvider()), Path.home())


def test_repull_failure_leaves_previous_backup_intact(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    # Establish a complete prior backup, then interrupt a repull partway through.
    pull_once(GraphClient(FakeTransport(), StaticTokenProvider()), output_dir)
    before = _output_texts(output_dir)
    assert before

    with pytest.raises(RuntimeError, match="network died"):
        repull_once(GraphClient(FailingPullTransport(), StaticTokenProvider()), output_dir)

    # Prior backup is untouched and no stray staging directories are left behind.
    assert _output_texts(output_dir) == before
    assert [path for path in output_dir.parent.iterdir() if path != output_dir] == []


class FailingPullTransport:
    def get(self, url: str, headers: dict[str, str]) -> dict:
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        raise RuntimeError("network died")


def _output_texts(output_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(output_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    }


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
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta"):
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
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
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
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta"):
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
        if url == f"{GRAPH_ROOT}/me/todo/lists/delta":
            return {"value": [{"id": "list-1", "displayName": "Inbox"}]}
        if url.startswith(f"{GRAPH_ROOT}/me/todo/lists/list-1/tasks/delta"):
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
