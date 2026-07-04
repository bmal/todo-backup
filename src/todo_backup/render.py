from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


def render_markdown(snapshot: dict[str, Any]) -> str:
    todo_list = snapshot["list"]
    tasks = _dedup_recurring(snapshot.get("tasks", []))
    open_tasks = [task for task in tasks if task.get("status") != "completed"]
    completed_tasks = [task for task in tasks if task.get("status") == "completed"]
    lines = [
        "---",
        f"todo-list: {_yaml_scalar(todo_list['displayName'])}",
        f"todo-list-id: {todo_list['id']}",
        f"synced: {snapshot['synced']}",
        "---",
        "",
        f"# {todo_list['displayName']}",
        "",
        f"## To do ({len(open_tasks)})",
        "",
    ]

    for task in open_tasks:
        _append_task(lines, task)

    if completed_tasks:
        if not open_tasks:
            lines.pop()
            lines.pop()
        lines.append(f"> [!done]- Completed ({len(completed_tasks)})")
        for task in completed_tasks:
            quoted: list[str] = []
            _append_task(quoted, task)
            if quoted and not quoted[-1]:
                quoted.pop()
            for line in quoted:
                lines.append(f"> {line}" if line else ">")

    return "\n".join(lines).rstrip() + "\n"


def _dedup_recurring(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For recurring tasks, keep only the most recently modified instance per title."""
    best: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not task.get("recurrence"):
            continue
        key = task.get("title", "")
        if key not in best or task.get("lastModifiedDateTime", "") > best[key].get("lastModifiedDateTime", ""):
            best[key] = task
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for task in tasks:
        if not task.get("recurrence"):
            result.append(task)
        else:
            key = task.get("title", "")
            if best.get(key) is task and key not in seen:
                seen.add(key)
                result.append(task)
    return result


def _recurrence_label(recurrence: dict[str, Any]) -> str:
    pattern_type = (recurrence.get("pattern") or {}).get("type", "")
    labels: dict[str, str] = {
        "daily": "daily",
        "weekly": "weekly",
        "absoluteMonthly": "monthly",
        "relativeMonthly": "monthly",
        "absoluteYearly": "yearly",
        "relativeYearly": "yearly",
    }
    return labels.get(pattern_type, pattern_type) or "recurring"


def _yaml_scalar(value: str) -> str:
    """Emit a frontmatter value as a plain scalar, double-quoting only when a
    plain scalar would be ambiguous or invalid YAML (e.g. a name with a colon)."""
    needs_quote = (
        value == ""
        or value != value.strip()
        or value[0] in "!&*?|>@%#\"'[]{},`-:"
        or ": " in value
        or value.endswith(":")
        or " #" in value
        or "\n" in value
        or "\t" in value
    )
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _append_task(lines: list[str], task: dict[str, Any]) -> None:
    checked = "x" if task.get("status") == "completed" else " "
    task_id = task.get("id")
    if task_id:
        lines.append(f"<!-- todo-task-id: {task_id} -->")
    lines.append(f"- [{checked}] {task.get('title', '')}")
    metadata = _task_metadata(task)
    if metadata:
        lines.append(f"  _{'; '.join(metadata)}_")
    recurrence = task.get("recurrence")
    if recurrence:
        lines.append(f"  recurrence: {_recurrence_label(recurrence)}")
    body = task.get("body") or {}
    content = _body_content_for_markdown(body)
    if content:
        for body_line in content.splitlines():
            lines.append(f"  {body_line}")
    for checklist_item in task.get("checklistItems", []):
        item_checked = "x" if checklist_item.get("isChecked") else " "
        item_id = checklist_item.get("id")
        if item_id:
            lines.append(f"  <!-- todo-checklist-item-id: {item_id} -->")
        lines.append(f"  - [{item_checked}] {checklist_item.get('displayName', '')}")
    lines.append("")


def _task_metadata(task: dict[str, Any]) -> list[str]:
    metadata: list[str] = []
    due = _date_time_label(task.get("dueDateTime"))
    if due:
        metadata.append(f"due: {due}")
    reminder = _date_time_label(task.get("reminderDateTime"))
    if reminder:
        metadata.append(f"reminder: {reminder}")
    categories = task.get("categories") or []
    if categories:
        metadata.append("categories: " + ", ".join(str(category) for category in categories))
    return metadata


def _date_time_label(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    date_time = value.get("dateTime")
    if not date_time:
        return ""
    timezone = value.get("timeZone")
    return f"{date_time} {timezone}" if timezone else str(date_time)


def _body_content_for_markdown(body: dict[str, Any]) -> str:
    content = body.get("content") or ""
    if body.get("contentType") == "html":
        return _html_to_text(content).strip()
    return content.strip()


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li"}:
            self._line_break()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li"}:
            self._line_break()

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def _line_break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")


def _html_to_text(value: str) -> str:
    parser = _PlainTextHTMLParser()
    parser.feed(value)
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
