#!/usr/bin/env python3
"""
media_hasher.py — Calculate SHA-256 hashes for media files in a directory.

Usage:
    python media_hasher.py <source_directory> [options]

Options:
    -o, --output FILE       Output JSON file path (default: media_hashes.json)
    -a, --algorithm ALG     Hash algorithm: sha256, sha1, md5 (default: sha256)
    -u, --update            Update existing JSON file instead of overwriting
    -v, --verbose           Print each file as it's processed
    --no-recurse            Don't recurse into subdirectories
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Recognized media extensions
MEDIA_EXTENSIONS = {
    # Images
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".heic",
    ".heif",
    ".raw",
    ".cr2",
    ".cr3",
    ".nef",
    ".orf",
    ".arw",
    ".dng",
    ".rw2",
    ".pef",
    ".srw",
    ".x3f",
    ".svg",
    ".ico",
    ".avif",
    # Videos
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".3g2",
    ".ogv",
    ".ts",
    ".mts",
    ".m2ts",
    ".vob",
    ".f4v",
    ".rm",
    ".rmvb",
    ".divx",
    # Audio (optional bonus)
    ".mp3",
    ".wav",
    ".aac",
    ".flac",
    ".ogg",
    ".m4a",
    ".wma",
    ".aiff",
    ".aif",
    ".opus",
}


def compute_hash(
    file_path: Path, algorithm: str = "sha256", chunk_size: int = 1 << 20
) -> str:
    """Compute the hash of a file using the specified algorithm."""
    h = hashlib.new(algorithm)
    with file_path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def collect_media_files(source_dir: Path, recurse: bool = True):
    """Yield all media file paths under source_dir."""
    pattern = "**/*" if recurse else "*"
    for entry in source_dir.glob(pattern):
        if entry.is_file() and entry.suffix.lower() in MEDIA_EXTENSIONS:
            yield entry


def load_existing(output_path: Path) -> dict:
    """Load an existing JSON file, returning an empty structure on failure."""
    try:
        with output_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def build_record(file_path: Path, algorithm: str, verbose: bool) -> Optional[dict]:
    """Hash a single file and return its record dict, or None on error."""
    try:
        stat = file_path.stat()
        digest = compute_hash(file_path, algorithm)
        record = {
            "hash": digest,
            "algorithm": algorithm,
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "scanned": datetime.now(tz=timezone.utc).isoformat(),
        }
        if verbose:
            print(f"  [{digest[:12]}…] {file_path}")
        return record
    except (OSError, PermissionError) as exc:
        print(f"  WARNING: could not process {file_path}: {exc}", file=sys.stderr)
        return None


def find_duplicates(records: dict) -> dict[str, list[str]]:
    """Return a mapping of hash → [paths] for any hash that appears more than once."""
    from collections import defaultdict

    seen: dict[str, list[str]] = defaultdict(list)
    for path, info in records.items():
        seen[info["hash"]].append(path)
    return {h: paths for h, paths in seen.items() if len(paths) > 1}


def main():
    parser = argparse.ArgumentParser(
        description="Hash media files and store results in a JSON file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("source", help="Directory to scan for media files")
    parser.add_argument(
        "-o",
        "--output",
        default="media_hashes.json",
        help="Output JSON file (default: media_hashes.json)",
    )
    parser.add_argument(
        "-a",
        "--algorithm",
        default="sha256",
        choices=["sha256", "sha1", "md5"],
        help="Hash algorithm (default: sha256)",
    )
    parser.add_argument(
        "-u",
        "--update",
        action="store_true",
        help="Merge into existing JSON instead of overwriting",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print each file as it is processed",
    )
    parser.add_argument(
        "--no-recurse",
        action="store_true",
        help="Only scan top-level of source directory",
    )
    args = parser.parse_args()

    source_dir = Path(args.source).resolve()
    if not source_dir.is_dir():
        sys.exit(f"Error: '{source_dir}' is not a valid directory.")

    output_path = Path(args.output)

    # Load existing data if updating
    records: dict = load_existing(output_path) if args.update else {}

    print(f"Scanning: {source_dir}")
    print(f"Algorithm: {args.algorithm.upper()}")
    print(f"Output:    {output_path}")
    print(f"Recursive: {not args.no_recurse}")
    print()

    processed = skipped = errors = 0

    for file_path in collect_media_files(source_dir, recurse=not args.no_recurse):
        key = str(file_path)

        # Skip if already hashed and not updating individual files
        if args.update and key in records:
            skipped += 1
            if args.verbose:
                print(f"  [SKIP] {file_path}")
            continue

        record = build_record(file_path, args.algorithm, args.verbose)
        if record:
            records[key] = record
            processed += 1
        else:
            errors += 1

    # Build output structure
    output = {
        "meta": {
            "source_directory": str(source_dir),
            "algorithm": args.algorithm,
            "generated": datetime.now(tz=timezone.utc).isoformat(),
            "total_files": len(records),
        },
        "files": records,
    }

    # Detect duplicates and include summary
    dupes = find_duplicates(records)
    output["meta"]["duplicate_groups"] = len(dupes)
    if dupes:
        output["duplicates"] = dupes

    # Write JSON
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Summary
    print()
    print("─" * 50)
    print(f"Processed : {processed}")
    print(f"Skipped   : {skipped}  (already in JSON)")
    print(f"Errors    : {errors}")
    print(f"Total kept: {len(records)}")
    if dupes:
        print(f"Duplicate groups found: {len(dupes)}")
        for digest, paths in dupes.items():
            print(f"  {digest[:16]}… ({len(paths)} copies)")
            for p in paths:
                print(f"    {p}")
    print(f"\nSaved → {output_path}")


if __name__ == "__main__":
    main()
