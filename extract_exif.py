#!/usr/bin/env python3
"""
extract_exif.py — Extract metadata from images, RAW files, and videos. Save to JSON.

Supported formats:
  Images : .jpg .jpeg .png .tiff .tif .webp .heic
  RAW    : .sr2 .dng .cr2 .cr3 .nef .arw .raf .orf .rw2
  Video  : .mp4 .mov .mpg .mpeg .m4p .m4v .3gp .avi .mkv .wmv

Usage:
    python extract_exif.py <directory> [output.json] [-r] [--indent N]

Dependencies:
    pip install Pillow exifread pymediainfo
    (LibMediaInfo must also be installed on your system)

System dependency for video metadata:
    macOS  : brew install libmediainfo
    Ubuntu : sudo apt install libmediainfo-dev
    Windows: download from https://mediaarea.net/en/MediaInfo
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
PILLOW_OK = True

import exifread
EXIFREAD_OK = True

from pymediainfo import MediaInfo
MEDIAINFO_OK = True

# ---------------------------------------------------------------------------
# File type sets
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic"}
RAW_EXTENSIONS   = {".sr2", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mpg", ".mpeg", ".m4p", ".m4v", ".3gp", ".avi", ".mkv", ".wmv"}
ALL_EXTENSIONS   = IMAGE_EXTENSIONS | RAW_EXTENSIONS | VIDEO_EXTENSIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_serializable(value):
    """Recursively convert EXIF/media values to JSON-safe types."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return value.hex()
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            return float(value)
        except Exception:
            return str(value)
    if isinstance(value, (tuple, list)):
        return [make_serializable(v) for v in value]
    if isinstance(value, dict):
        return {k: make_serializable(v) for k, v in value.items()}
    return value


def get_gps_info(gps_data: dict) -> dict:
    """Convert raw GPS IFD data to a readable dict with decimal coordinates."""
    gps = {GPSTAGS.get(k, str(k)): make_serializable(v) for k, v in gps_data.items()}

    def dms_to_decimal(dms, ref):
        degrees, minutes, seconds = dms
        decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return round(decimal, 7)

    coords = {}
    try:
        if "GPSLatitude" in gps and "GPSLatitudeRef" in gps:
            coords["latitude"] = dms_to_decimal(gps["GPSLatitude"], gps["GPSLatitudeRef"])
        if "GPSLongitude" in gps and "GPSLongitudeRef" in gps:
            coords["longitude"] = dms_to_decimal(gps["GPSLongitude"], gps["GPSLongitudeRef"])
        if "GPSAltitude" in gps:
            coords["altitude_m"] = round(float(gps["GPSAltitude"]), 2)
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    gps.update(coords)
    return gps


def file_base(path: Path) -> dict:
    """Shared file-level metadata for every record."""
    stat = path.stat()
    return {
        "file": path.name,
        "path": str(path.resolve()),
        "extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "type": None,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

def extract_image_exif(path: Path) -> dict:
    """Pillow-based extractor for standard image formats."""
    record = file_base(path)
    record.update({"type": "image", "format": None, "mode": None,
                   "width": None, "height": None, "exif": {}, "gps": {}})
    if not PILLOW_OK:
        record["error"] = "Pillow not installed"
        return record
    try:
        with Image.open(path) as img:
            record["format"] = img.format
            record["mode"]   = img.mode
            record["width"], record["height"] = img.size
            raw_exif = img._getexif()
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    tag_name = TAGS.get(tag_id, str(tag_id))
                    if tag_name == "GPSInfo":
                        record["gps"] = get_gps_info(value)
                    else:
                        record["exif"][tag_name] = make_serializable(value)
    except Exception as exc:
        record["error"] = str(exc)
    return record


def extract_raw_exif(path: Path) -> dict:
    """exifread-based extractor for RAW camera formats."""
    record = file_base(path)
    record.update({"type": "raw", "exif": {}, "gps": {}})
    if not EXIFREAD_OK:
        record["error"] = "exifread not installed (pip install exifread)"
        return record
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
        for key, value in tags.items():
            parts = key.split(" ", 1)
            tag_name = parts[1] if len(parts) == 2 else key
            str_val = str(value)
            if key.startswith("GPS"):
                record["gps"][tag_name] = str_val
            else:
                record["exif"][tag_name] = str_val
    except Exception as exc:
        record["error"] = str(exc)
    return record


def extract_video_metadata(path: Path) -> dict:
    """pymediainfo-based extractor for video/audio formats."""
    record = file_base(path)
    record.update({
        "type": "video",
        "duration_seconds": None,
        "video_tracks": [],
        "audio_tracks": [],
        "general": {},
        "note": "m4p files are DRM-protected; metadata may be limited."
                if path.suffix.lower() == ".m4p" else None,
    })
    if not MEDIAINFO_OK:
        record["error"] = "pymediainfo not installed (pip install pymediainfo)"
        return record

    GENERAL_KEYS = {
        "format", "format_version", "codec_id", "file_size", "duration",
        "overall_bit_rate", "frame_rate", "encoded_date", "tagged_date",
        "com_apple_quicktime_location_iso6709",
        "xyz", "title", "album", "performer", "track_name",
        "recorded_date", "copyright", "comment", "description",
    }
    VIDEO_KEYS = {
        "format", "codec_id", "duration", "bit_rate", "width", "height",
        "frame_rate", "color_space", "chroma_subsampling", "bit_depth",
        "scan_type", "rotation",
    }
    AUDIO_KEYS = {
        "format", "codec_id", "duration", "bit_rate", "channel_s",
        "sampling_rate", "language",
    }

    def _pick(track, keys):
        return {k: getattr(track, k) for k in keys
                if getattr(track, k, None) is not None}

    try:
        mi = MediaInfo.parse(path)
        for track in mi.tracks:
            if track.track_type == "General":
                record["general"] = _pick(track, GENERAL_KEYS)
                if track.duration:
                    record["duration_seconds"] = round(float(track.duration) / 1000, 3)
            elif track.track_type == "Video":
                record["video_tracks"].append(_pick(track, VIDEO_KEYS))
            elif track.track_type == "Audio":
                record["audio_tracks"].append(_pick(track, AUDIO_KEYS))
    except Exception as exc:
        record["error"] = str(exc)
    return record


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def extract_metadata(path: Path) -> dict:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return extract_image_exif(path)
    if ext in RAW_EXTENSIONS:
        return extract_raw_exif(path)
    if ext in VIDEO_EXTENSIONS:
        return extract_video_metadata(path)
    return {**file_base(path), "type": "unsupported",
            "error": f"Extension '{ext}' not handled"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_directory(directory: Path, recursive: bool = False) -> list:
    glob = directory.rglob("*") if recursive else directory.glob("*")
    files = sorted(p for p in glob
                   if p.is_file() and p.suffix.lower() in ALL_EXTENSIONS)
    if not files:
        print(f"No supported files found in: {directory}")
        return []

    results = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name}")
        results.append(extract_metadata(path))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract metadata from images, RAW files, and videos. Output to JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("directory", help="Directory to scan")
    parser.add_argument("output", nargs="?", default="metadata.json",
                        help="Output JSON file (default: metadata.json)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Search subdirectories recursively")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indentation level (default: 2)")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"Error: '{directory}' is not a valid directory.")
        sys.exit(1)

    print(f"Scanning: {directory.resolve()}\n")
    records = process_directory(directory, recursive=args.recursive)

    type_counts: dict = {}
    for r in records:
        t = r.get("type", "unsupported")
        type_counts[t] = type_counts.get(t, 0) + 1

    payload = {
        "generated": datetime.now().isoformat(),
        "source_directory": str(directory.resolve()),
        "total_files": len(records),
        "counts_by_type": type_counts,
        "files": records,
    }

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=args.indent, ensure_ascii=False)

    print(f"\nDone. {len(records)} file(s) → {output_path.resolve()}")
    for t, n in type_counts.items():
        print(f"  {t.capitalize()}: {n}")


if __name__ == "__main__":
    main()
