#!/usr/bin/env python3
"""
organize_files.py
Organizes files in a directory into subfolders by extension.
Usage: python organize_files.py <directory> [--output <dest>] [--dry-run] [--recursive]
"""

import sys
import shutil
import argparse
from pathlib import Path


def organize(directory: str, output: str = None, dry_run: bool = False, recursive: bool = False) -> None:
    source = Path(directory).resolve()
    target = Path(output).resolve() if output else source

    if not source.exists():
        print(f"Error: '{source}' does not exist.")
        sys.exit(1)
    if not source.is_dir():
        print(f"Error: '{source}' is not a directory.")
        sys.exit(1)

    if dry_run:
        print("Dry run — no files will be moved.\n")

    if output:
        print(f"  Source:      {source}")
        print(f"  Destination: {target}\n")

    moved = 0
    skipped = 0

    # Collect files: recursively or top-level only
    files = source.rglob("*") if recursive else source.iterdir()

    for item in list(files):
        if item.is_dir():
            skipped += 1
            continue

        # Skip files that are already inside the target directory
        try:
            item.relative_to(target)
            skipped += 1
            continue
        except ValueError:
            pass

        ext = item.suffix.lstrip(".").lower()
        folder_name = ext if ext else "no_extension"
        dest_folder = target / folder_name

        dest_path = dest_folder / item.name
        # Avoid overwriting: append a counter if the filename already exists
        counter = 1
        while dest_path.exists():
            dest_path = dest_folder / f"{item.stem}_{counter}{item.suffix}"
            counter += 1

        if dry_run:
            print(f"  [dry run] Would move: {item.relative_to(source)} → {dest_folder}/")
        else:
            dest_folder.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(dest_path))
            print(f"  Moved: {item.relative_to(source)} → {dest_folder}/")

        moved += 1

    action = "would be moved" if dry_run else "moved"
    print(f"\nDone. {moved} file(s) {action}, {skipped} item(s) skipped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organize files in a directory into subfolders by extension."
    )
    parser.add_argument("directory", help="Path to the source directory to organize")
    parser.add_argument(
        "--output", "-o",
        help="Destination directory for organized folders (defaults to source directory)",
        default=None,
    )
    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Recursively organize files in all subdirectories",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would happen without moving any files",
    )
    args = parser.parse_args()
    organize(args.directory, output=args.output, dry_run=args.dry_run, recursive=args.recursive)


if __name__ == "__main__":
    main()
