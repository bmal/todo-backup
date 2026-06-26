from __future__ import annotations

from datetime import datetime, timezone

from todo_backup.graph import GraphClient
from todo_backup.render import render_markdown
from todo_backup.store import write_pull_output
from pathlib import Path


def pull_once(graph: GraphClient, output_dir: Path) -> None:
    todo_list = graph.first_list()
    tasks, delta_link = graph.task_delta(todo_list.id)
    synced = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    snapshot = {
        "schemaVersion": 1,
        "synced": synced,
        "list": {"id": todo_list.id, "displayName": todo_list.display_name},
        "tasks": tasks,
    }
    write_pull_output(output_dir, snapshot, render_markdown(snapshot), delta_link)
