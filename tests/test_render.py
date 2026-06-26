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

- [ ] Open task
  Open body
  - [x] Done step
  - [ ] Open step

- [ ] Another open task

> [!done]- Completed (1)
> - [x] Done task
>   Done body
"""
