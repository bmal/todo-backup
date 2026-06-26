from __future__ import annotations

import argparse
from pathlib import Path

from todo_backup.auth import StaticTokenProvider
from todo_backup.config import DEFAULT_CONFIG_PATH, load_config
from todo_backup.graph import GraphClient
from todo_backup.http import UrlLibTransport
from todo_backup.sync import pull_once, sync_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo-backup")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("pull")
    subparsers.add_parser("sync")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.command == "pull":
        graph = GraphClient(UrlLibTransport(), StaticTokenProvider())
        pull_once(graph, config.output_dir)
        return 0
    if args.command == "sync":
        graph = GraphClient(UrlLibTransport(), StaticTokenProvider())
        sync_once(graph, config.output_dir)
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
