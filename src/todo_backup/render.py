from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


def render_markdown(snapshot: dict[str, Any]) -> str:
    todo_list = snapshot["list"]
    tasks = snapshot.get("tasks", [])
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
    ]

    for task in open_tasks:
        _append_task(lines, task)

    if completed_tasks:
        lines.append(f"> [!done]- Completed ({len(completed_tasks)})")
        for task in completed_tasks:
            quoted: list[str] = []
            _append_task(quoted, task)
            if quoted and not quoted[-1]:
                quoted.pop()
            for line in quoted:
                lines.append(f"> {line}" if line else ">")

    return "\n".join(lines).rstrip() + "\n"


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
    lines.append(f"- [{checked}] {task.get('title', '')}")
    body = task.get("body") or {}
    content = _body_content_for_markdown(body)
    if content:
        for body_line in content.splitlines():
            lines.append(f"  {body_line}")
    for checklist_item in task.get("checklistItems", []):
        item_checked = "x" if checklist_item.get("isChecked") else " "
        lines.append(f"  - [{item_checked}] {checklist_item.get('displayName', '')}")
    lines.append("")


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
