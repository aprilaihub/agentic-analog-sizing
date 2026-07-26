"""Unified command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable


def _dispatch(command: Callable[[], int | None], argv: list[str]) -> int:
    previous = sys.argv
    try:
        sys.argv = [previous[0], *argv]
        return int(command() or 0)
    finally:
        sys.argv = previous


def main(argv: list[str] | None = None) -> int:
    command_line = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="agentic-sizing")
    parser.add_argument("command", choices=("run", "tag", "extract-kb"))
    # Parse only the command name. Options after it belong to that command,
    # including ``--help``.
    args = parser.parse_args(command_line[:1])
    remainder = command_line[1:]
    if args.command == "run":
        from .workflow.runner import main as command
    elif args.command == "tag":
        from .tagging.__main__ import main as command
    else:
        from .kb.__main__ import main as command
    return _dispatch(command, remainder)


if __name__ == "__main__":
    raise SystemExit(main())
