from __future__ import annotations

from todo_backup.render import render_markdown


def test_render_markdown_from_snapshot() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-26T08:30:00Z",
            "list": {"id": "list-1", "displayName": "Inbox"},
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Open task",
                    "status": "notStarted",
                    "body": {"contentType": "text", "content": "Open body"},
                    "checklistItems": [
                        {"id": "step-1", "displayName": "Done step", "isChecked": True},
                        {"id": "step-2", "displayName": "Open step", "isChecked": False},
                    ],
                },
                {
                    "id": "task-2",
                    "title": "Done task",
                    "status": "completed",
                    "body": {"contentType": "text", "content": "Done body"},
                },
                {
                    "id": "task-3",
                    "title": "Another open task",
                    "status": "inProgress",
                    "body": {"contentType": "text", "content": ""},
                },
            ],
        }
    )

    assert markdown == """---
todo-list: Inbox
todo-list-id: list-1
synced: 2026-06-26T08:30:00Z
---

# Inbox

## To do (2)

<!-- todo-task-id: task-1 -->
- [ ] Open task
  Open body
  <!-- todo-checklist-item-id: step-1 -->
  - [x] Done step
  <!-- todo-checklist-item-id: step-2 -->
  - [ ] Open step

<!-- todo-task-id: task-3 -->
- [ ] Another open task

> [!done]- Completed (1)
> <!-- todo-task-id: task-2 -->
> - [x] Done task
>   Done body
"""


def test_render_omits_completed_callout_when_no_completed_tasks() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-26T08:30:00Z",
            "list": {"id": "list-1", "displayName": "Inbox"},
            "tasks": [
                {"id": "task-1", "title": "Only open task", "status": "notStarted"},
            ],
        }
    )

    assert "- [ ] Only open task" in markdown
    assert "## To do (1)" in markdown
    assert "[!done]" not in markdown


def test_render_completed_only_list_omits_empty_to_do_section() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-26T08:30:00Z",
            "list": {"id": "list-1", "displayName": "Inbox"},
            "tasks": [
                {"id": "task-1", "title": "Done task", "status": "completed"},
            ],
        }
    )

    assert "## To do" not in markdown
    assert "> [!done]- Completed (1)" in markdown


def test_render_includes_task_metadata() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-26T08:30:00Z",
            "list": {"id": "list-1", "displayName": "Inbox"},
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Timed task",
                    "status": "notStarted",
                    "dueDateTime": {"dateTime": "2026-07-01T10:00:00", "timeZone": "UTC"},
                    "reminderDateTime": {"dateTime": "2026-06-30T09:00:00", "timeZone": "UTC"},
                    "categories": ["home", "urgent"],
                },
            ],
        }
    )

    assert "<!-- todo-task-id: task-1 -->" in markdown
    assert "  _due: 2026-07-01T10:00:00 UTC; reminder: 2026-06-30T09:00:00 UTC; categories: home, urgent_" in markdown


def test_render_quotes_frontmatter_name_with_yaml_metacharacters() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-26T08:30:00Z",
            "list": {"id": "list-1", "displayName": "Work: Q3 #goals"},
            "tasks": [],
        }
    )

    assert 'todo-list: "Work: Q3 #goals"' in markdown
    assert "# Work: Q3 #goals" in markdown


def test_render_recurring_task_shows_recurrence_label() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-28T08:00:00Z",
            "list": {"id": "list-1", "displayName": "Inbox"},
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Weekly review",
                    "status": "notStarted",
                    "recurrence": {"pattern": {"type": "weekly"}, "range": {"type": "noEnd"}},
                }
            ],
        }
    )

    assert "- [ ] Weekly review" in markdown
    assert "  recurrence: weekly" in markdown


def test_render_deduplicates_recurring_tasks_keeping_most_recent() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-28T08:00:00Z",
            "list": {"id": "list-1", "displayName": "Inbox"},
            "tasks": [
                {
                    "id": "task-old",
                    "title": "Weekly review",
                    "status": "completed",
                    "lastModifiedDateTime": "2026-06-14T10:00:00Z",
                    "recurrence": {"pattern": {"type": "weekly"}, "range": {"type": "noEnd"}},
                },
                {
                    "id": "task-new",
                    "title": "Weekly review",
                    "status": "completed",
                    "lastModifiedDateTime": "2026-06-21T10:00:00Z",
                    "recurrence": {"pattern": {"type": "weekly"}, "range": {"type": "noEnd"}},
                },
            ],
        }
    )

    assert markdown.count("Weekly review") == 1


def test_render_html_body_as_plain_text() -> None:
    markdown = render_markdown(
        {
            "schemaVersion": 1,
            "synced": "2026-06-26T08:30:00Z",
            "list": {"id": "list-1", "displayName": "Inbox"},
            "tasks": [
                {
                    "id": "task-1",
                    "title": "HTML task",
                    "status": "notStarted",
                    "body": {"contentType": "html", "content": "<p>Hello <em>there</em>.</p><p>Use &amp; keep.</p>"},
                }
            ],
        }
    )

    assert "  Hello there." in markdown
    assert "  Use & keep." in markdown
    assert "<em>" not in markdown
