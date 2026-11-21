"""Command line entry point for maintenance tasks.

Usage::

    python -m supermarket_comparison.cli cleanup --json
"""

from __future__ import annotations

import argparse
import json
import sys

from .storage import Repository
from .storage.cleanup import clean_database


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``supermarket_comparison`` CLI."""

    parser = argparse.ArgumentParser(
        prog="python -m supermarket_comparison.cli",
        description="Maintenance tasks for the price comparison service.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    cleanup = subparsers.add_parser(
        "cleanup",
        help=(
            "Remove placeholder brands and unverifiable catalogue images "
            "(runs automatically on startup, too)."
        ),
    )
    cleanup.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print the result as JSON.",
    )
    return parser


def _cleanup(args: argparse.Namespace) -> int:
    repository = Repository()
    try:
        result = clean_database(repository.db._conn)
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("Cleanup finished:")
            print(f"  Brands reset:            {result['brands_cleaned']}")
            print(f"  Unverified images cleared: {result['unverified_images_cleared']}")
            print(f"  Produce images cleared:   {result['produce_images_cleared']}")
        return 0
    except Exception as exc:
        if args.as_json:
            print(json.dumps({"status": "failed", "error": str(exc)}))
        else:
            print(f"Cleanup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        repository.close()


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and dispatch the requested command."""

    args = build_parser().parse_args(argv)
    if args.command == "cleanup":
        return _cleanup(args)
    return 2  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":
    raise SystemExit(main())