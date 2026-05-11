#!/usr/bin/env python3
"""
search_by_date.py — Search the metadata JSON for MP4s and photos created on a specific date.

Usage:
    python search_by_date.py <metadata.json> [--date YYYY-MM-DD] [--type image|video|raw|all]

Defaults to searching for files created on 2024-03-16.

Date fields checked (in order of preference):
  Images/RAW : EXIF DateTimeOriginal → DateTime → file modified date
  Video      : encoded_date → tagged_date → file modified date
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import date, datetime


DEFAULT_DATE = "2024-03-16"

# EXIF date fields to check, in priority order
IMAGE_DATE_FIELDS = ["DateTimeOriginal", "DateTime", "DateTimeDigitized"]

# Video general-track fields to check, in priority order
VIDEO_DATE_FIELDS = ["encoded_date", "tagged_date", "recorded_date"]


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_exif_date(value: str) -> date | None:
    """Parse EXIF date strings like '2024:03:16 14:22:05'."""
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def parse_video_date(value: str) -> date | None:
    """Parse video date strings like 'UTC 2024-03-16 14:22:05' or ISO 8601."""
    cleaned = value.strip()
    # Strip leading timezone label (e.g. "UTC ")
    for prefix in ("UTC ", "utc "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y:%m:%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def parse_modified_date(value: str) -> date | None:
    """Parse ISO 8601 file-modified timestamp."""
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, AttributeError):
        return None


def get_file_date(record: dict) -> tuple[date | None, str]:
    """
    Return (date, source_field) for a metadata record.
    Tries the most-reliable date fields first, falls back to file mtime.
    """
    file_type = record.get("type", "")

    if file_type in ("image", "raw"):
        exif = record.get("exif", {})
        for field in IMAGE_DATE_FIELDS:
            if field in exif:
                d = parse_exif_date(str(exif[field]))
                if d:
                    return d, field

    elif file_type == "video":
        general = record.get("general", {})
        for field in VIDEO_DATE_FIELDS:
            if field in general:
                d = parse_video_date(str(general[field]))
                if d:
                    return d, field

    # Fallback: file system modified date
    modified = record.get("modified")
    if modified:
        d = parse_modified_date(modified)
        if d:
            return d, "file_modified"

    return None, "unknown"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

TYPE_FILTER_MAP = {
    "image": {"image"},
    "video": {"video"},
    "raw":   {"raw"},
    "all":   {"image", "video", "raw"},
}

MP4_AND_PHOTOS = {"image", "raw", "video"}   # used when --type is default


def matches_type(record: dict, allowed_types: set) -> bool:
    file_type = record.get("type", "")
    if file_type == "video":
        # Within video, only include mp4 for the default "mp4 + photos" use case
        # unless the user explicitly asked for all video
        return file_type in allowed_types
    return file_type in allowed_types


def is_mp4(record: dict) -> bool:
    return record.get("extension", "").lower() == ".mp4"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Search metadata JSON for files created on a specific date.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("metadata", help="Path to metadata JSON produced by extract_exif.py")
    parser.add_argument(
        "--date", default=DEFAULT_DATE,
        help=f"Date to search for in YYYY-MM-DD format (default: {DEFAULT_DATE})"
    )
    parser.add_argument(
        "--type", dest="file_type", default="mp4_and_photos",
        choices=["mp4_and_photos", "image", "video", "raw", "all"],
        help="File types to include (default: mp4_and_photos)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Optional: save results to a JSON file",
    )
    args = parser.parse_args()

    # Parse target date
    try:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print(f"Error: invalid date '{args.date}'. Use YYYY-MM-DD format.")
        sys.exit(1)

    # Load metadata
    metadata_path = Path(args.metadata)
    if not metadata_path.is_file():
        print(f"Error: '{metadata_path}' not found.")
        sys.exit(1)

    with open(metadata_path, encoding="utf-8") as f:
        data = json.load(f)

    all_files = data.get("files", [])
    print(f"Loaded {len(all_files)} records from {metadata_path.name}")
    print(f"Searching for: {target_date.strftime('%B %d, %Y')}  |  Type: {args.file_type}\n")

    # Filter
    matches = []
    for record in all_files:
        file_type = record.get("type", "")

        # Type filter
        if args.file_type == "mp4_and_photos":
            if file_type == "video" and not is_mp4(record):
                continue
            if file_type not in ("image", "raw", "video"):
                continue
        else:
            allowed = TYPE_FILTER_MAP.get(args.file_type, set())
            if file_type not in allowed:
                continue

        # Date filter
        file_date, source_field = get_file_date(record)
        if file_date == target_date:
            matches.append({
                "file": record["file"],
                "path": record["path"],
                "type": file_type,
                "extension": record.get("extension"),
                "size_bytes": record.get("size_bytes"),
                "date_matched": str(file_date),
                "date_source": source_field,
                # Extra fields by type
                **({"width": record.get("width"), "height": record.get("height")}
                   if file_type in ("image", "raw") else {}),
                **({"duration_seconds": record.get("duration_seconds")}
                   if file_type == "video" else {}),
            })

    # Results
    if not matches:
        print(f"No files found created on {target_date}.")
        return

    print(f"Found {len(matches)} file(s) created on {target_date}:\n")
    print(f"  {'File':<45} {'Type':<8} {'Date Source':<22} {'Size':>10}")
    print("  " + "-" * 90)
    for m in matches:
        size_kb = f"{m['size_bytes'] / 1024:.1f} KB" if m.get("size_bytes") else "—"
        print(f"  {m['file']:<45} {m['type']:<8} {m['date_source']:<22} {size_kb:>10}")

    # Optional JSON output
    if args.output:
        output_path = Path(args.output)
        payload = {
            "search_date": str(target_date),
            "source_metadata": str(metadata_path.resolve()),
            "match_count": len(matches),
            "files": matches,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
