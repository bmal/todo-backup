from __future__ import annotations

import argparse
import sys
from pathlib import Path

from todo_backup.auth import AuthError, DeviceCodeTokenProvider, init_device_code_auth
from todo_backup.config import DEFAULT_CONFIG_PATH, load_config
from todo_backup.graph import GraphClient
from todo_backup.http import UrlLibTransport
from todo_backup.sync import pull_once, status_lines, sync_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo-backup")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-auth")
    subparsers.add_parser("pull")
    subparsers.add_parser("sync")
    subparsers.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "init-auth":
            init_device_code_auth(config.client_id, config.token_cache_path)
            return 0
        if args.command == "pull":
            graph = GraphClient(UrlLibTransport(), DeviceCodeTokenProvider(config.client_id, config.token_cache_path))
            pull_once(graph, config.output_dir)
            return 0
        if args.command == "sync":
            graph = GraphClient(UrlLibTransport(), DeviceCodeTokenProvider(config.client_id, config.token_cache_path))
            sync_once(graph, config.output_dir)
            return 0
        if args.command == "status":
            for line in status_lines(config.output_dir):
                print(line)
            return 0
        raise AssertionError(f"Unhandled command: {args.command}")
    except AuthError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
