from __future__ import annotations

from typing import Any


def render_markdown(snapshot: dict[str, Any]) -> str:
    todo_list = snapshot["list"]
    tasks = snapshot.get("tasks", [])
    lines = [
        "---",
        f"todo-list: {todo_list['displayName']}",
        f"todo-list-id: {todo_list['id']}",
        f"synced: {snapshot['synced']}",
        "---",
        "",
        f"# {todo_list['displayName']}",
        "",
    ]

    for task in tasks:
        checked = "x" if task.get("status") == "completed" else " "
        lines.append(f"- [{checked}] {task.get('title', '')}")
        body = task.get("body") or {}
        content = (body.get("content") or "").strip()
        if content:
            for body_line in content.splitlines():
                lines.append(f"  {body_line}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
