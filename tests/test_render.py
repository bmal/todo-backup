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
                },
                {
                    "id": "task-2",
                    "title": "Done task",
                    "status": "completed",
                    "body": {"contentType": "text", "content": "Done body"},
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

- [x] Done task
  Done body
"""
