"""
Optimized batch mover/uploader for ghavanin files.

Improvements over batch_upload_ghavanin.py:
- Progress tracking with resume capability
- Better error handling and recovery
- Configurable settings via command-line arguments
- Enhanced logging with timestamps
- Checkpoint system to resume from failures
- Better file size estimation and reporting

Workflow per batch:
1) Move up to BATCH_SIZE files from data/ghavanin/** (excluding staging/archived) into
   data/ghavanin/New folder.
2) Call the RAG upload API with that staging folder.
3) Move the processed files into data/uploadwithscript/<batch_xxx>/.

Run:
    python scripts/optimized_batch_upload.py
    python scripts/optimized_batch_upload.py --batch-size 20
    python scripts/optimized_batch_upload.py --resume
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
import shutil
import requests
import sys


BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_ROOT = BASE_DIR / "data" / "ghavanin"
STAGING_DIR = SOURCE_ROOT / "New folder"
ARCHIVE_ROOT = BASE_DIR / "data" / "uploadwithscript"
PROGRESS_FILE = BASE_DIR / "scripts" / "upload_progress.json"

# Default settings
DEFAULT_BATCH_SIZE = 10
DEFAULT_API_URL = "http://localhost:4000/rag/upload-folder-from-path"
DEFAULT_API_TIMEOUT = 900  # 15 minutes
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 5  # seconds

# Relative path expected by API (from project root)
API_FOLDER_PATH = "./data/ghavanin/New folder"


def load_progress() -> dict:
    """Load progress from JSON file if it exists."""
    default_progress = {
        "processed_files": [],
        "total_files": 0,
        "batches_completed": 0,
        "last_update": None,
    }

    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)

                # Handle migration from old format
                if "last_batch_num" in loaded and "batches_completed" not in loaded:
                    # Old format detected - migrate it
                    default_progress["batches_completed"] = loaded.get(
                        "last_batch_num", 0
                    )
                    default_progress["total_files"] = loaded.get("total_processed", 0)
                    # Old format had file names, not full paths - we'll need to handle this
                    if "processed_files" in loaded:
                        default_progress["processed_files"] = loaded["processed_files"]
                    if "start_time" in loaded:
                        default_progress["last_update"] = loaded["start_time"]
                else:
                    # New format - merge with defaults to ensure all keys exist
                    default_progress.update(loaded)

                return default_progress
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load progress file: {e}")

    return default_progress


def save_progress(progress: dict) -> None:
    """Save progress to JSON file."""
    progress["last_update"] = datetime.now().isoformat()
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"Warning: Could not save progress file: {e}")


def ensure_dirs() -> None:
    """Ensure all required directories exist."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)


def iter_source_files(processed_files: set[str] | None = None):
    """
    Yield all files under SOURCE_ROOT except those already in staging/archived.
    Optionally skip files that have already been processed.
    Handles both full paths (new format) and file names (old format).
    """
    if processed_files is None:
        processed_files = set()

    for path in SOURCE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if STAGING_DIR in path.parents:
            continue
        if ARCHIVE_ROOT in path.parents:
            continue
        # Skip already processed files - check both full path and file name
        # (old format had just names, new format has full paths)
        if str(path) in processed_files or path.name in processed_files:
            continue
        yield path


def get_file_size_mb(path: Path) -> float:
    """Get file size in MB."""
    try:
        return path.stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


def take_batch(files: list[Path], batch_size: int) -> list[Path]:
    """Take the next batch of files."""
    return files[:batch_size]


def move_files(files: list[Path], destination: Path) -> list[Path]:
    """Move files to destination directory, handling duplicates."""
    # Ensure destination exists and is accessible
    try:
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True)

        # Test if destination is writable
        test_file = destination / ".test_write"
        try:
            test_file.touch()
            test_file.unlink()
        except (OSError, PermissionError) as e:
            raise Exception(
                f"Destination directory is not writable: {destination} - {e}"
            )
    except Exception as e:
        print(f"  ✗ Cannot access destination directory {destination}: {e}")
        raise

    moved_files = []

    for f in files:
        # Resolve paths to absolute paths to avoid issues
        try:
            source_path = f.resolve()
        except (OSError, ValueError) as e:
            print(f"  ⚠ Warning: Cannot resolve source path {f}: {e}")
            continue

        # Check if source file exists
        if not source_path.exists():
            print(f"  ⚠ Warning: Source file does not exist, skipping: {source_path}")
            continue

        if not source_path.is_file():
            print(f"  ⚠ Warning: Source is not a file, skipping: {source_path}")
            continue

        target = destination / f.name
        # If duplicate names appear, append a counter
        if target.exists():
            stem, suffix = f.stem, f.suffix
            counter = 1
            while True:
                alt = destination / f"{stem}_{counter}{suffix}"
                if not alt.exists():
                    target = alt
                    break
                counter += 1

        try:
            # Ensure target directory exists
            target.parent.mkdir(parents=True, exist_ok=True)

            # Resolve target to absolute path
            target = target.resolve()

            # Check path lengths (Windows has 260 char limit, but can be extended)
            source_str = str(source_path)
            target_str = str(target)

            if len(source_str) > 260 or len(target_str) > 260:
                print(
                    f"  ⚠ Warning: Long path detected (source: {len(source_str)}, target: {len(target_str)} chars)"
                )

            # Try to move the file
            try:
                shutil.move(source_str, target_str)
            except (FileNotFoundError, OSError) as move_error:
                # Fallback: try copy + delete (sometimes works better on Windows)
                print(f"  ⚠ Move failed, trying copy+delete for {f.name}: {move_error}")
                try:
                    shutil.copy2(source_str, target_str)
                    # Verify copy was successful before deleting source
                    if (
                        target.exists()
                        and target.stat().st_size == source_path.stat().st_size
                    ):
                        source_path.unlink()
                    else:
                        raise Exception(
                            "Copy verification failed - file sizes don't match"
                        )
                except Exception as copy_error:
                    print(f"  ✗ Copy+delete also failed for {f.name}: {copy_error}")
                    raise move_error from copy_error

            moved_files.append(target)
        except FileNotFoundError as e:
            print(f"  ✗ FileNotFoundError moving {f.name}: {e}")
            print(f"    Source exists: {source_path.exists()}")
            print(f"    Source path: {source_path}")
            print(
                f"    Source absolute: {source_path.resolve() if source_path.exists() else 'N/A'}"
            )
            print(f"    Target parent exists: {target.parent.exists()}")
            print(f"    Target path: {target}")
            raise
        except (OSError, shutil.Error) as e:
            print(f"  ✗ Error moving file {f.name}: {e}")
            print(f"    Source path: {source_path}")
            print(
                f"    Source absolute: {source_path.resolve() if source_path.exists() else 'N/A'}"
            )
            print(f"    Target path: {target}")
            print(f"    Error type: {type(e).__name__}")
            print(f"    Error code: {e.winerror if hasattr(e, 'winerror') else 'N/A'}")
            raise

    return moved_files


def call_api(
    api_url: str,
    api_timeout: int,
    max_retries: int,
    retry_delay: int,
    retry_count: int = 0,
) -> dict:
    """
    Call the upload API with retry logic and extended timeout.
    """
    try:
        print(
            f"  API call attempt {retry_count + 1}/{max_retries} (timeout: {api_timeout}s)..."
        )
        start_time = time.time()

        resp = requests.post(
            api_url,
            json={"folder_path": API_FOLDER_PATH, "recursive": True},
            timeout=api_timeout,
        )

        elapsed = time.time() - start_time
        print(f"  API call completed in {elapsed:.1f} seconds")

        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as e:
        if retry_count < max_retries - 1:
            print(f"  Timeout occurred. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
            return call_api(
                api_url, api_timeout, max_retries, retry_delay, retry_count + 1
            )
        else:
            raise Exception(f"API timeout after {max_retries} attempts: {e}")
    except requests.exceptions.RequestException as e:
        if retry_count < max_retries - 1:
            print(f"  Request failed: {e}. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
            return call_api(
                api_url, api_timeout, max_retries, retry_delay, retry_count + 1
            )
        else:
            raise


def archive_all_from_staging() -> Path:
    """
    Move ALL files from STAGING_DIR to archive directory.
    This ensures New folder is completely emptied after successful API call.
    """
    ts = time.strftime("batch_%Y%m%d_%H%M%S")
    dest_dir = ARCHIVE_ROOT / ts
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Get all files in staging directory (including subdirectories if recursive)
    all_staged_files = []
    for path in STAGING_DIR.rglob("*"):
        if path.is_file():
            all_staged_files.append(path)

    if not all_staged_files:
        print("  No files found in staging folder to archive.")
        return dest_dir

    print(f"  Archiving {len(all_staged_files)} files from staging folder...")
    for f in all_staged_files:
        # Preserve relative path structure if files are in subdirectories
        relative_path = f.relative_to(STAGING_DIR)
        target = dest_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), target)

    # Remove empty subdirectories from staging
    for path in sorted(STAGING_DIR.rglob("*"), reverse=True):
        if path.is_dir() and path != STAGING_DIR:
            try:
                path.rmdir()  # Only removes if empty
            except OSError:
                pass  # Directory not empty, skip

    return dest_dir


def format_time(seconds: float) -> str:
    """Format seconds into a human-readable time string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def main():
    parser = argparse.ArgumentParser(
        description="Optimized batch uploader for ghavanin files"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of files to process per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=DEFAULT_API_URL,
        help=f"API endpoint URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--api-timeout",
        type=int,
        default=DEFAULT_API_TIMEOUT,
        help=f"API timeout in seconds (default: {DEFAULT_API_TIMEOUT})",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Maximum number of retries for failed API calls (default: {DEFAULT_MAX_RETRIES})",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=DEFAULT_RETRY_DELAY,
        help=f"Delay between retries in seconds (default: {DEFAULT_RETRY_DELAY})",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint (skip already processed files)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset progress and start from beginning",
    )

    args = parser.parse_args()

    # Load or reset progress
    if args.reset:
        progress = {
            "processed_files": [],
            "total_files": 0,
            "batches_completed": 0,
            "last_update": None,
        }
        print("Progress reset. Starting from beginning.")
    else:
        progress = load_progress()
        if args.resume and progress["processed_files"]:
            print(
                f"Resuming: {len(progress['processed_files'])} files already processed."
            )
        else:
            progress["processed_files"] = []

    ensure_dirs()

    # Get all files to process
    processed_set = set(progress["processed_files"]) if args.resume else set()
    all_files = list(iter_source_files(processed_set))
    total_files = len(all_files)

    if total_files == 0:
        print("No files found to process.")
        if processed_set:
            print(f"All {len(processed_set)} files have already been processed.")
        return

    # Update total if this is a fresh start
    if not args.resume or progress["total_files"] == 0:
        progress["total_files"] = total_files + len(processed_set)

    print("=" * 70)
    print("OPTIMIZED BATCH UPLOAD SCRIPT")
    print("=" * 70)
    print(f"Total files to process: {total_files}")
    if processed_set:
        print(f"Already processed: {len(processed_set)}")
        print(f"Total files (including processed): {progress['total_files']}")
    print(f"Batch size: {args.batch_size}")
    print(
        f"Estimated batches: {(total_files + args.batch_size - 1) // args.batch_size}"
    )
    print(f"API URL: {args.api_url}")
    print(f"API timeout: {args.api_timeout}s ({args.api_timeout // 60} minutes)")
    print(f"Max retries: {args.max_retries}")
    print("-" * 70)

    batch_num = progress.get("batches_completed", 0)
    processed_count = len(processed_set)
    start_time = time.time()

    while True:
        batch_files = take_batch(all_files, args.batch_size)
        if not batch_files:
            elapsed = time.time() - start_time
            print("\n" + "=" * 70)
            print("All files processed successfully!")
            print(f"Total batches: {batch_num}")
            print(f"Total files processed: {processed_count}")
            print(f"Total time: {format_time(elapsed)}")
            print("=" * 70)

            # Clear progress on successful completion
            if PROGRESS_FILE.exists():
                PROGRESS_FILE.unlink()
                print("Progress file cleared.")
            break

        batch_num += 1
        print(f"\n{'=' * 70}")
        print(f"Batch {batch_num}: Processing {len(batch_files)} files")
        print(
            f"Progress: {processed_count}/{progress['total_files']} files "
            f"({processed_count * 100 // progress['total_files'] if progress['total_files'] > 0 else 0}%)"
        )

        # Calculate and display batch size info
        batch_size_mb = sum(get_file_size_mb(f) for f in batch_files)
        print(f"Batch size: {batch_size_mb:.2f} MB")
        print("-" * 70)

        # Filter out files that don't exist or are invalid
        existing_files = []
        for f in batch_files:
            if f.exists() and f.is_file():
                existing_files.append(f)
            else:
                print(f"  ⚠ Warning: File invalid or missing, skipping: {f.name}")

        if len(existing_files) < len(batch_files):
            missing_count = len(batch_files) - len(existing_files)
            print(
                f"  ⚠ Warning: {missing_count} file(s) invalid or missing, skipping them"
            )
            batch_files = existing_files

        if not batch_files:
            print("  No valid files in this batch, skipping...")
            # Remove from all_files list
            all_files = all_files[args.batch_size :]
            continue

        # Show file names being processed
        print("Files in this batch:")
        for i, f in enumerate(batch_files[:5], 1):  # Show first 5
            size_mb = get_file_size_mb(f)
            print(f"  {i}. {f.name} ({size_mb:.2f} MB)")
        if len(batch_files) > 5:
            print(f"  ... and {len(batch_files) - 5} more files")

        print(f"\nMoving files to staging: {STAGING_DIR}")
        try:
            staged_files = move_files(batch_files, STAGING_DIR)
            print(f"✓ Moved {len(staged_files)} files to staging")
        except Exception as e:
            print(f"\n✗ Failed to move files to staging: {e}")
            print("Stopping batch processing.")
            sys.exit(1)

        print(f"\nCalling API: {args.api_url}")
        try:
            result = call_api(
                args.api_url,
                args.api_timeout,
                args.max_retries,
                args.retry_delay,
            )
            print(f"\n✓ API Success!")
            print(f"  Files processed: {result.get('files_processed', 'N/A')}")
            print(f"  Chunks added: {result.get('chunks_added', 'N/A')}")

            # Count files before archiving
            files_before_archive = sum(1 for p in STAGING_DIR.rglob("*") if p.is_file())

            print(f"\nArchiving all files from staging folder (batch {batch_num})...")
            archived_dir = archive_all_from_staging()

            # Verify staging folder is empty
            remaining_files = list(STAGING_DIR.rglob("*"))
            remaining_files = [p for p in remaining_files if p.is_file()]

            if remaining_files:
                print(
                    f"⚠ Warning: {len(remaining_files)} files still remain in staging folder!"
                )
            else:
                print(
                    f"✓ All {files_before_archive} files archived. Staging folder is now empty."
                )

            # Update progress - only track files that were successfully moved
            # Use the number of staged files as the actual count
            files_actually_processed = len(staged_files)
            for f in batch_files[:files_actually_processed]:
                progress["processed_files"].append(str(f))
            processed_count += files_actually_processed
            progress["batches_completed"] = batch_num
            save_progress(progress)

            # Remove processed files from the list
            all_files = all_files[len(batch_files) :]

            print(f"✓ Batch {batch_num} archived to: {archived_dir}")

            # Estimate remaining time
            if processed_count > 0:
                elapsed = time.time() - start_time
                avg_time_per_file = elapsed / processed_count
                remaining_files_count = progress["total_files"] - processed_count
                estimated_remaining = avg_time_per_file * remaining_files_count
                print(f"  Estimated time remaining: {format_time(estimated_remaining)}")

        except Exception as exc:
            print(f"\n✗ API call failed for batch {batch_num}: {exc}")
            print(f"Files remain in staging folder: {STAGING_DIR}")
            print("You can:")
            print("  1. Check the API server status")
            print("  2. Manually retry the API call")
            print("  3. Reduce batch size with --batch-size")
            print("  4. Resume later with --resume flag")
            print(
                f"\nProgress saved. Run with --resume to continue from batch {batch_num}."
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
