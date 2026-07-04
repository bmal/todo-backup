from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any


def empty_state() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "lists": {},
    }


def read_state_or_empty(output_dir: Path) -> dict[str, Any]:
    state_file = output_dir / "state.json"
    if not state_file.exists():
        return empty_state()
    return json.loads(state_file.read_text(encoding="utf-8"))


def read_state(output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / "state.json").read_text(encoding="utf-8"))


def read_snapshot(output_dir: Path, snapshot_file: str) -> dict[str, Any]:
    return json.loads((output_dir / snapshot_file).read_text(encoding="utf-8"))


def write_sync_output(
    output_dir: Path,
    state: dict[str, Any],
    changed_outputs: list[tuple[dict[str, Any], str, str, str]],
    removed_files: list[str] | None = None,
) -> None:
    for snapshot, markdown, snapshot_file, markdown_file in changed_outputs:
        _write_json_if_changed(output_dir / snapshot_file, snapshot)
        _write_text_if_changed(output_dir / markdown_file, markdown)
    for removed_file in removed_files or []:
        path = output_dir / removed_file
        if path.exists():
            path.unlink()
    _write_json_if_changed(output_dir / "state.json", state)


def write_pull_checkpoint(
    output_dir: Path,
    state: dict[str, Any],
    snapshot: dict[str, Any],
    snapshot_file: str,
    markdown: str | None = None,
    markdown_file: str | None = None,
) -> None:
    _write_json_if_changed(output_dir / snapshot_file, snapshot)
    if markdown is not None and markdown_file is not None:
        _write_text_if_changed(output_dir / markdown_file, markdown)
    _write_json_if_changed(output_dir / "state.json", state)


def make_repull_staging(output_dir: Path) -> Path:
    """Create an empty staging directory beside output_dir on the same filesystem.

    A fresh pull is built here and later swapped into place, so os.replace can
    move it atomically without crossing a filesystem boundary.
    """
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", suffix=".staging", dir=output_dir.parent))


def swap_repull_into_place(staging: Path, output_dir: Path) -> None:
    """Atomically replace output_dir with staging, discarding prior content only now.

    The previous backup is moved aside first and removed only after the new one
    is in place, so an interrupted swap can be restored and never leaves the
    output missing.
    """
    if not output_dir.exists():
        os.replace(staging, output_dir)
        return
    old = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", suffix=".old", dir=output_dir.parent))
    os.replace(output_dir, old)
    try:
        os.replace(staging, output_dir)
    except BaseException:
        os.replace(old, output_dir)
        raise
    shutil.rmtree(old, ignore_errors=True)


def unique_markdown_file(list_name: str, used: set[Path], list_directory: str = "") -> Path:
    stem = _slugify(list_name)
    directory = _markdown_directory(list_directory)
    markdown_file = directory / f"{stem}.md"
    suffix = 2
    while markdown_file in used:
        markdown_file = directory / f"{stem}-{suffix}.md"
        suffix += 1
    used.add(markdown_file)
    return markdown_file


def matches_markdown_file(list_name: str, markdown_file: str, list_directory: str = "") -> bool:
    path = Path(markdown_file)
    stem = _slugify(list_name)
    return path.parent == _markdown_directory(list_directory) and re.fullmatch(rf"{re.escape(stem)}(?:-\d+)?\.md", path.name)


def _markdown_directory(list_directory: str) -> Path:
    return Path("lists") / _slugify(list_directory) if list_directory else Path("lists")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return slug or "list"


def _write_json_if_changed(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    _write_text_if_changed(path, text)


def _write_text_if_changed(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    _write_text_atomic(path, text)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
