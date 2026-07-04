from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
from typing import Any

from todo_backup.graph import GraphClient
from todo_backup.render import render_markdown
from todo_backup.store import read_snapshot, read_state, read_state_or_empty, unique_markdown_file, write_pull_checkpoint, write_sync_output
from pathlib import Path


@dataclass(frozen=True)
class PullSummary:
    list_count: int
    task_count: int

    def line(self) -> str:
        return f"Backed up {self.list_count} lists and {self.task_count} tasks."


def pull_once(graph: GraphClient, output_dir: Path) -> PullSummary:
    state = read_state_or_empty(output_dir)
    synced = _utc_now()
    used_markdown_files = {
        Path(list_state["markdownFile"])
        for list_state in state["lists"].values()
        if "markdownFile" in list_state
    }
    todo_lists = graph.lists()
    task_count = 0
    for todo_list in todo_lists:
        existing = state["lists"].get(todo_list.id)
        if existing and existing.get("deltaLink") and not existing.get("pullNextLink"):
            continue

        if existing:
            snapshot_file = existing["snapshotFile"]
            markdown_file = existing["markdownFile"]
            snapshot = read_snapshot(output_dir, snapshot_file)
            url = existing.get("pullNextLink") or graph.task_delta_initial_url(todo_list.id)
        else:
            snapshot_file = (Path("snapshots") / f"{todo_list.id}.json").as_posix()
            markdown_file = unique_markdown_file(todo_list.display_name, used_markdown_files).as_posix()
            snapshot = {
                "schemaVersion": 1,
                "synced": synced,
                "list": {"id": todo_list.id, "displayName": todo_list.display_name},
                "tasks": [],
            }
            state["lists"][todo_list.id] = {
                "name": todo_list.display_name,
                "markdownFile": markdown_file,
                "snapshotFile": snapshot_file,
                "deltaLink": "",
                "lastSynced": synced,
                "pullNextLink": graph.task_delta_initial_url(todo_list.id),
            }
            url = state["lists"][todo_list.id]["pullNextLink"]

        list_state = state["lists"][todo_list.id]
        while url:
            tasks, next_link, delta_link = graph.task_delta_page(url)
            task_count += len(tasks)
            snapshot["tasks"].extend(tasks)
            snapshot["synced"] = synced
            list_state["lastSynced"] = synced
            if next_link:
                list_state["pullNextLink"] = next_link
                write_pull_checkpoint(output_dir, state, snapshot, snapshot_file)
                url = next_link
                continue
            if not delta_link:
                raise RuntimeError("Task delta response did not include @odata.deltaLink")
            list_state["deltaLink"] = delta_link
            list_state.pop("pullNextLink", None)
            write_pull_checkpoint(output_dir, state, snapshot, snapshot_file, render_markdown(snapshot), markdown_file)
            url = None

    summary = PullSummary(list_count=len(todo_lists), task_count=task_count)
    print(summary.line())
    return summary


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
            list_state["name"] = todo_list.display_name
            list_state["markdownFile"] = new_markdown_file
            if new_markdown_file != old_markdown_file:
                removed_files.append(old_markdown_file)

        tasks_delta, delta_link = graph.task_delta_url(list_state["deltaLink"])
        updated_tasks = _apply_task_delta(snapshot.get("tasks", []), tasks_delta)
        snapshot_changed = updated_tasks != snapshot.get("tasks", [])
        delta_changed = delta_link != list_state.get("deltaLink")

        # A rename and/or a task change re-renders the list exactly once.
        if renamed or snapshot_changed:
            snapshot = dict(snapshot)
            if snapshot_changed:
                snapshot["tasks"] = updated_tasks
            snapshot["synced"] = synced
            list_state["lastSynced"] = synced
            changed_outputs.append(
                (
                    snapshot,
                    render_markdown(snapshot),
                    list_state["snapshotFile"],
                    list_state["markdownFile"],
                )
            )
            state_changed = True

        if delta_changed:
            list_state["deltaLink"] = delta_link
            state_changed = True

    if changed_outputs or removed_files or state_changed:
        write_sync_output(output_dir, state, changed_outputs, removed_files)


def render_once(output_dir: Path) -> None:
    state = read_state(output_dir)
    outputs = []
    for list_state in state["lists"].values():
        snapshot = read_snapshot(output_dir, list_state["snapshotFile"])
        outputs.append((snapshot, render_markdown(snapshot), list_state["snapshotFile"], list_state["markdownFile"]))
    write_sync_output(output_dir, state, outputs)


def repull_once(graph: GraphClient, output_dir: Path) -> PullSummary:
    _validate_repull_target(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    return pull_once(graph, output_dir)


def _validate_repull_target(output_dir: Path) -> None:
    target = output_dir.expanduser().resolve()
    if target in {Path("/").resolve(), Path.home().resolve()}:
        raise ValueError(f"Refusing to delete unsafe outputDir: {output_dir}")


def _apply_task_delta(tasks: list[dict[str, Any]], delta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A dict keyed by task id preserves insertion order, so edits keep their
    # position, additions append, and removals drop out — all in O(n + m).
    updated: dict[str, dict[str, Any]] = {task["id"]: dict(task) for task in tasks}
    for task in delta:
        task_id = task["id"]
        if "@removed" in task:
            updated.pop(task_id, None)
        else:
            updated[task_id] = task
    return list(updated.values())


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def status_lines(output_dir: Path) -> list[str]:
    state = read_state_or_empty(output_dir)
    lines = []
    for list_id in sorted(state["lists"], key=lambda value: state["lists"][value]["name"]):
        list_state = state["lists"][list_id]
        snapshot = read_snapshot(output_dir, list_state["snapshotFile"])
        tasks = snapshot.get("tasks", [])
        completed = sum(1 for task in tasks if task.get("status") == "completed")
        open_count = len(tasks) - completed
        lines.append(f"{list_state['name']}\tlastSynced={list_state['lastSynced']}\topen={open_count}\tcompleted={completed}")
    return lines
