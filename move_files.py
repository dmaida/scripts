#!/usr/bin/env python3
"""
move_files.py — Move files listed in a JSON paths file to a destination directory.

Usage:
    python move_files.py <paths.json> <destination> [--dry-run] [--conflict skip|rename|overwrite]

Arguments:
    paths.json   JSON file with a "files" array of absolute paths (as produced by analyze_metadata.py)
    destination  Directory to move files into

Options:
    --dry-run              Print what would happen without moving anything
    --conflict             How to handle filename collisions (default: rename)
                             skip      — leave the source file in place
                             rename    — append _2, _3, … to avoid collision
                             overwrite — replace the existing destination file
"""

import json
import sys
import argparse
import shutil
from pathlib import Path


def resolve_dest(dest_dir: Path, src: Path, conflict: str) -> Path | None:
    """Return the destination path, handling conflicts per policy."""
    candidate = dest_dir / src.name

    if not candidate.exists():
        return candidate

    if conflict == "overwrite":
        return candidate

    if conflict == "skip":
        return None

    # rename: append _2, _3, …
    stem, suffix = src.stem, src.suffix
    counter = 2
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def main():
    parser = argparse.ArgumentParser(
        description="Move files listed in a JSON paths file to a destination directory."
    )
    parser.add_argument("input", help="JSON file containing a 'files' array of paths")
    parser.add_argument("destination", help="Directory to move files into")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without moving")
    parser.add_argument(
        "--conflict",
        choices=["skip", "rename", "overwrite"],
        default="rename",
        help="Collision handling strategy (default: rename)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    dest_dir = Path(args.destination)

    if not input_path.exists():
        print(f"Error: '{input_path}' not found.")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    files = data.get("files", [])
    if not files:
        print("No files listed in the JSON.")
        sys.exit(0)

    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    moved = skipped = missing = errors = 0

    for raw_path in files:
        src = Path(raw_path)

        if not src.exists():
            print(f"  MISSING   {src}")
            missing += 1
            continue

        dest = resolve_dest(dest_dir, src, args.conflict)

        if dest is None:
            print(f"  SKIP      {src.name}  (collision)")
            skipped += 1
            continue

        tag = "DRY-RUN" if args.dry_run else "MOVE"
        print(f"  {tag:<7}  {src.name}  →  {dest.name}")

        if not args.dry_run:
            try:
                shutil.move(str(src), dest)
                moved += 1
            except Exception as exc:
                print(f"  ERROR     {src.name}: {exc}")
                errors += 1
        else:
            moved += 1

    label = "Would move" if args.dry_run else "Moved"
    print(f"\n{label}: {moved}  |  Skipped: {skipped}  |  Missing: {missing}  |  Errors: {errors}")
    print(f"Destination: {dest_dir.resolve()}")


if __name__ == "__main__":
    main()
