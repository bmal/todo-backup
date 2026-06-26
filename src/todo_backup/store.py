from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def write_pull_output(output_dir: Path, snapshot: dict[str, Any], markdown: str, delta_link: str) -> None:
    list_id = snapshot["list"]["id"]
    list_name = snapshot["list"]["displayName"]
    snapshot_file = Path("snapshots") / f"{list_id}.json"
    markdown_file = Path("lists") / f"{_slugify(list_name)}.md"

    _write_json_atomic(output_dir / snapshot_file, snapshot)
    _write_text_atomic(output_dir / markdown_file, markdown)
    state = {
        "schemaVersion": 1,
        "lists": {
            list_id: {
                "name": list_name,
                "markdownFile": markdown_file.as_posix(),
                "snapshotFile": snapshot_file.as_posix(),
                "deltaLink": delta_link,
                "lastSynced": snapshot["synced"],
            }
        },
    }
    _write_json_atomic(output_dir / "state.json", state)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return slug or "list"


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    _write_text_atomic(path, text)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
