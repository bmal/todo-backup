from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from todo_backup.graph import GraphClient
from todo_backup.render import render_markdown
from todo_backup.store import read_snapshot, read_state, write_pull_output, write_sync_output
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


def sync_once(graph: GraphClient, output_dir: Path) -> None:
    state = read_state(output_dir)
    changed_outputs = []
    state_changed = False

    for list_id, list_state in state["lists"].items():
        tasks_delta, delta_link = graph.task_delta_url(list_state["deltaLink"])
        snapshot = read_snapshot(output_dir, list_state["snapshotFile"])
        updated_tasks = _apply_task_delta(snapshot.get("tasks", []), tasks_delta)
        snapshot_changed = updated_tasks != snapshot.get("tasks", [])
        delta_changed = delta_link != list_state.get("deltaLink")

        if snapshot_changed:
            snapshot = dict(snapshot)
            snapshot["tasks"] = updated_tasks
            snapshot["synced"] = _utc_now()
            changed_outputs.append(
                (
                    snapshot,
                    render_markdown(snapshot),
                    list_state["snapshotFile"],
                    list_state["markdownFile"],
                )
            )

        if snapshot_changed or delta_changed:
            if snapshot_changed:
                list_state["lastSynced"] = snapshot["synced"]
            list_state["deltaLink"] = delta_link
            state_changed = True

    if changed_outputs or state_changed:
        write_sync_output(output_dir, state, changed_outputs)


def _apply_task_delta(tasks: list[dict[str, Any]], delta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated = [dict(task) for task in tasks]
    positions = {task["id"]: index for index, task in enumerate(updated)}
    for task in delta:
        task_id = task["id"]
        if "@removed" in task:
            if task_id in positions:
                del updated[positions[task_id]]
                positions = {existing["id"]: index for index, existing in enumerate(updated)}
            continue
        if task_id in positions:
            updated[positions[task_id]] = task
        else:
            positions[task_id] = len(updated)
            updated.append(task)
    return updated


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
