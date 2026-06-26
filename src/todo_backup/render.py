from __future__ import annotations

from typing import Any


def render_markdown(snapshot: dict[str, Any]) -> str:
    todo_list = snapshot["list"]
    tasks = snapshot.get("tasks", [])
    open_tasks = [task for task in tasks if task.get("status") != "completed"]
    completed_tasks = [task for task in tasks if task.get("status") == "completed"]
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

    for task in open_tasks:
        _append_task(lines, task)

    lines.append(f"> [!done]- Completed ({len(completed_tasks)})")
    for task in completed_tasks:
        quoted: list[str] = []
        _append_task(quoted, task)
        if quoted and not quoted[-1]:
            quoted.pop()
        for line in quoted:
            lines.append(f"> {line}" if line else ">")

    return "\n".join(lines).rstrip() + "\n"


def _append_task(lines: list[str], task: dict[str, Any]) -> None:
    checked = "x" if task.get("status") == "completed" else " "
    lines.append(f"- [{checked}] {task.get('title', '')}")
    body = task.get("body") or {}
    content = (body.get("content") or "").strip()
    if content:
        for body_line in content.splitlines():
            lines.append(f"  {body_line}")
    for checklist_item in task.get("checklistItems", []):
        item_checked = "x" if checklist_item.get("isChecked") else " "
        lines.append(f"  - [{item_checked}] {checklist_item.get('displayName', '')}")
    lines.append("")
