"""
Batch mover/uploader for ghavanin files.

Workflow per batch (size=20):
1) Move up to 20 files from data/ghavanin/** (excluding staging/archived) into
   data/ghavanin/New folder.
2) Call the RAG upload API with that staging folder.
3) Move the processed files into data/uploadwithscript/<batch_xxx>/.

Run:
    python scripts/batch_upload_ghavanin.py
"""

from __future__ import annotations

import time
from pathlib import Path
import shutil
import requests
import sys


BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_ROOT = BASE_DIR / "data" / "ghavanin"
STAGING_DIR = SOURCE_ROOT / "New folder"
ARCHIVE_ROOT = BASE_DIR / "data" / "uploadwithscript"
API_URL = "http://localhost:4000/rag/upload-folder-from-path"
BATCH_SIZE = 10
API_TIMEOUT = 900  # 15 minutes timeout
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds between retries

# Relative path expected by API (from project root)
API_FOLDER_PATH = "./data/ghavanin/New folder"


def ensure_dirs() -> None:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)


def iter_source_files():
    """
    Yield all files under SOURCE_ROOT except those already in staging/archived.
    """
    for path in SOURCE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if STAGING_DIR in path.parents:
            continue
        if ARCHIVE_ROOT in path.parents:
            continue
        yield path


def take_batch(batch_size: int):
    files = list(iter_source_files())
    return files[:batch_size]


def move_files(files, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    for f in files:
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
        shutil.move(str(f), target)
    return list(destination.iterdir())


def call_api(retry_count=0):
    """
    Call the upload API with retry logic and extended timeout.
    """
    try:
        print(
            f"  API call attempt {retry_count + 1}/{MAX_RETRIES} (timeout: {API_TIMEOUT}s)..."
        )
        start_time = time.time()

        resp = requests.post(
            API_URL,
            json={"folder_path": API_FOLDER_PATH, "recursive": True},
            timeout=API_TIMEOUT,
        )

        elapsed = time.time() - start_time
        print(f"  API call completed in {elapsed:.1f} seconds")

        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as e:
        if retry_count < MAX_RETRIES - 1:
            print(f"  Timeout occurred. Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
            return call_api(retry_count + 1)
        else:
            raise Exception(f"API timeout after {MAX_RETRIES} attempts: {e}")
    except requests.exceptions.RequestException as e:
        if retry_count < MAX_RETRIES - 1:
            print(f"  Request failed: {e}. Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
            return call_api(retry_count + 1)
        else:
            raise


def archive_all_from_staging():
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


def main():
    ensure_dirs()

    # Count total files first
    all_files = list(iter_source_files())
    total_files = len(all_files)
    print(f"Total files to process: {total_files}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Estimated batches: {(total_files + BATCH_SIZE - 1) // BATCH_SIZE}")
    print(f"API timeout: {API_TIMEOUT}s ({API_TIMEOUT // 60} minutes)")
    print("-" * 60)

    if total_files == 0:
        print("No files found to process.")
        return

    batch_num = 0
    processed_files = 0

    while True:
        batch_files = take_batch(BATCH_SIZE)
        if not batch_files:
            print("\n" + "=" * 60)
            print("All files processed successfully!")
            print(f"Total batches: {batch_num}")
            print(f"Total files processed: {processed_files}")
            break

        batch_num += 1
        print(f"\n{'=' * 60}")
        print(f"Batch {batch_num}: Processing {len(batch_files)} files")
        print(
            f"Progress: {processed_files}/{total_files} files ({processed_files * 100 // total_files if total_files > 0 else 0}%)"
        )
        print("-" * 60)

        # Show file names being processed
        print("Files in this batch:")
        for i, f in enumerate(batch_files[:5], 1):  # Show first 5
            print(f"  {i}. {f.name}")
        if len(batch_files) > 5:
            print(f"  ... and {len(batch_files) - 5} more files")

        print(f"\nMoving files to staging: {STAGING_DIR}")
        staged_files = move_files(batch_files, STAGING_DIR)
        print(f"✓ Moved {len(staged_files)} files to staging")

        print(f"\nCalling API: {API_URL}")
        try:
            result = call_api()
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

            processed_files += files_before_archive
            print(f"✓ Batch {batch_num} archived to: {archived_dir}")

        except Exception as exc:
            print(f"\n✗ API call failed for batch {batch_num}: {exc}")
            print(f"Files remain in staging folder: {STAGING_DIR}")
            print("You can:")
            print("  1. Check the API server status")
            print("  2. Manually retry the API call")
            print("  3. Reduce BATCH_SIZE if files are too large")
            print("\nStopping batch processing.")
            sys.exit(1)


if __name__ == "__main__":
    main()
