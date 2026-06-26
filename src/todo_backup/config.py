from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from todo_backup.auth import default_token_cache_path


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "todo-backup" / "config.json"
DEFAULT_OUTPUT_DIR = Path.home() / "todo-backup-output"


@dataclass(frozen=True)
class Config:
    client_id: str
    output_dir: Path
    token_cache_path: Path


def load_config(path: Path | None = None) -> Config:
    config_path = path or DEFAULT_CONFIG_PATH
    data: dict[str, str] = {}
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))

    client_id = data.get("clientId") or data.get("client_id")
    if not client_id:
        raise ValueError(f"Missing clientId in config: {config_path}")

    output = data.get("outputDir") or data.get("output_dir")
    output_dir = Path(output).expanduser() if output else DEFAULT_OUTPUT_DIR
    token_cache = data.get("tokenCachePath") or data.get("token_cache_path")
    token_cache_path = Path(token_cache).expanduser() if token_cache else default_token_cache_path()
    return Config(client_id=client_id, output_dir=output_dir, token_cache_path=token_cache_path)
