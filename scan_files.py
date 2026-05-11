#!/usr/bin/env python3
"""
scan_files.py
Recursively scans a directory, collects file metadata, and outputs a JSON report.

Usage:
    python scan_files.py [directory] [output.json]

Arguments:
    directory    Directory to scan (default: current directory)
    output.json  Output file path (default: scan_report.json)
"""

import os
import sys
import json
import hashlib
import datetime


def format_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def get_file_hash(filepath: str, algo: str = "md5") -> str:
    """Compute a file's hash (md5 by default). Returns empty string on error."""
    h = hashlib.new(algo)
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ""


def get_file_info(filepath: str) -> dict:
    """Collect metadata for a single file."""
    stat = os.stat(filepath)
    name = os.path.basename(filepath)
    _, ext = os.path.splitext(name)

    return {
        "path": os.path.abspath(filepath),
        "name": name,
        "extension": ext.lower() if ext else "(none)",
        "size_bytes": stat.st_size,
        "size_human": format_size(stat.st_size),
        "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "accessed": datetime.datetime.fromtimestamp(stat.st_atime).isoformat(),
        "is_symlink": os.path.islink(filepath),
        "md5": get_file_hash(filepath),
    }


def scan_directory(root: str) -> tuple[list[dict], list[str]]:
    """Walk a directory tree and collect file info. Returns (files, errors)."""
    files = []
    errors = []

    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            try:
                files.append(get_file_info(full_path))
            except Exception as e:
                errors.append({"path": full_path, "error": str(e)})

    return files, errors


def build_summary(files: list[dict]) -> dict:
    """Compute aggregate statistics across all scanned files."""
    if not files:
        return {}

    sizes = [f["size_bytes"] for f in files]
    ext_counts: dict[str, int] = {}
    ext_sizes: dict[str, int] = {}

    for f in files:
        ext = f["extension"]
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
        ext_sizes[ext] = ext_sizes.get(ext, 0) + f["size_bytes"]

    largest = max(files, key=lambda f: f["size_bytes"])
    smallest = min(files, key=lambda f: f["size_bytes"])

    return {
        "total_files": len(files),
        "total_size_bytes": sum(sizes),
        "total_size_human": format_size(sum(sizes)),
        "average_size_bytes": int(sum(sizes) / len(sizes)),
        "average_size_human": format_size(sum(sizes) / len(sizes)),
        "largest_file": {"path": largest["path"], "size_human": largest["size_human"]},
        "smallest_file": {"path": smallest["path"], "size_human": smallest["size_human"]},
        "extensions": {
            ext: {
                "count": ext_counts[ext],
                "total_size_human": format_size(ext_sizes[ext]),
                "total_size_bytes": ext_sizes[ext],
            }
            for ext in sorted(ext_counts, key=lambda e: ext_counts[e], reverse=True)
        },
    }


def main():
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    output_path = sys.argv[2] if len(sys.argv) > 2 else "scan_report.json"

    if not os.path.isdir(target_dir):
        print(f"Error: '{target_dir}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning: {os.path.abspath(target_dir)}")
    files, errors = scan_directory(target_dir)
    print(f"Found {len(files)} files. Building report...")

    files.sort(key=lambda f: f["size_bytes"], reverse=True)

    report = {
        "scanned_at": datetime.datetime.now().isoformat(),
        "scanned_directory": os.path.abspath(target_dir),
        "summary": build_summary(files),
        "files": files,
        "errors": errors,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to: {os.path.abspath(output_path)}")
    if errors:
        print(f"Warning: {len(errors)} file(s) could not be read (see 'errors' in report).")


if __name__ == "__main__":
    main()
