from __future__ import annotations

from datetime import datetime, timezone

from todo_backup.graph import GraphClient
from todo_backup.render import render_markdown
from todo_backup.store import write_pull_output
from pathlib import Path


def pull_once(graph: GraphClient, output_dir: Path) -> None:
    synced = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    outputs = []
    for todo_list in graph.lists():
        tasks, delta_link = graph.task_delta(todo_list.id)
        snapshot = {
            "schemaVersion": 1,
            "synced": synced,
            "list": {"id": todo_list.id, "displayName": todo_list.display_name},
            "tasks": tasks,
        }
        outputs.append((snapshot, render_markdown(snapshot), delta_link))
    write_pull_output(output_dir, outputs)
