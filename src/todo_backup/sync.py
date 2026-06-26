from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from todo_backup.graph import GraphClient
from todo_backup.render import render_markdown
from todo_backup.store import read_snapshot, read_state, unique_markdown_file, write_pull_output, write_sync_output
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
    current_lists = {todo_list.id: todo_list for todo_list in graph.lists()}
    changed_outputs = []
    removed_files: list[str] = []
    state_changed = False
    synced = _utc_now()

    used_markdown_files = {
        Path(list_state["markdownFile"])
        for list_id, list_state in state["lists"].items()
        if list_id in current_lists and list_state["name"] == current_lists[list_id].display_name
    }

    for list_id in list(state["lists"]):
        if list_id in current_lists:
            continue
        list_state = state["lists"].pop(list_id)
        removed_files.extend([list_state["snapshotFile"], list_state["markdownFile"]])
        state_changed = True

    for list_id, todo_list in current_lists.items():
        if list_id not in state["lists"]:
            tasks, delta_link = graph.task_delta(list_id)
            snapshot = {
                "schemaVersion": 1,
                "synced": synced,
                "list": {"id": list_id, "displayName": todo_list.display_name},
                "tasks": tasks,
            }
            snapshot_file = (Path("snapshots") / f"{list_id}.json").as_posix()
            markdown_file = unique_markdown_file(todo_list.display_name, used_markdown_files).as_posix()
            state["lists"][list_id] = {
                "name": todo_list.display_name,
                "markdownFile": markdown_file,
                "snapshotFile": snapshot_file,
                "deltaLink": delta_link,
                "lastSynced": synced,
            }
            changed_outputs.append((snapshot, render_markdown(snapshot), snapshot_file, markdown_file))
            state_changed = True
            continue

        list_state = state["lists"][list_id]
        snapshot = read_snapshot(output_dir, list_state["snapshotFile"])
        renamed = list_state["name"] != todo_list.display_name
        if renamed:
            old_markdown_file = list_state["markdownFile"]
            new_markdown_file = unique_markdown_file(todo_list.display_name, used_markdown_files).as_posix()
            snapshot = dict(snapshot)
            snapshot["list"] = {**snapshot["list"], "displayName": todo_list.display_name}
            snapshot["synced"] = synced
            list_state["name"] = todo_list.display_name
            list_state["markdownFile"] = new_markdown_file
            list_state["lastSynced"] = synced
            if new_markdown_file != old_markdown_file:
                removed_files.append(old_markdown_file)
            changed_outputs.append(
                (
                    snapshot,
                    render_markdown(snapshot),
                    list_state["snapshotFile"],
                    new_markdown_file,
                )
            )
            state_changed = True

        tasks_delta, delta_link = graph.task_delta_url(list_state["deltaLink"])
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

    if changed_outputs or removed_files or state_changed:
        write_sync_output(output_dir, state, changed_outputs, removed_files)


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
