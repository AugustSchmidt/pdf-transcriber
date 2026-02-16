"""Cleanup utility for PDF transcription telemetry.

Safely removes event logs for completed jobs when final output exists.
Never deletes logs for active or incomplete jobs.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import logging
import sys

from pdf_transcriber.events import read_event_log_typed
from pdf_transcriber.event_types import JobStartedEvent, JobCompletedEvent

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    """Result of cleanup operation."""
    total_logs_found: int
    logs_deleted: int
    logs_kept: int
    deleted_files: list[str]
    kept_files: list[str]
    errors: list[str]


def find_output_path(job_id: str, output_dir: str | None = None) -> Path | None:
    """
    Find the final transcription output file for a job.

    Args:
        job_id: Job identifier (e.g., "rising-sea-vakil-pub")
        output_dir: Base output directory to search in

    Returns:
        Path to final output file if it exists, None otherwise
    """
    if output_dir is None:
        # Try to infer from events or use default
        # For now, we'll rely on the job_started event to tell us
        return None

    output_base = Path(output_dir).expanduser()
    if not output_base.exists():
        return None

    # The job_id is typically the slugified directory name
    # Look for directories matching the job_id pattern
    # The final output is typically {directory_name}/{paper_name}.md

    # Strategy: scan subdirectories for .md files that match
    for subdir in output_base.iterdir():
        if not subdir.is_dir():
            continue

        # Check if this looks like our job directory
        # Look for a .md file (not .original.md)
        for md_file in subdir.glob("*.md"):
            if not md_file.name.endswith(".original.md"):
                # Found a candidate - check if the subdir name relates to job_id
                # Job IDs are slugified directory names, so they should match
                if _normalize_job_id(subdir.name) == job_id:
                    return md_file

    return None


def _normalize_job_id(name: str) -> str:
    """
    Normalize a directory name to match job_id format.

    Job IDs are created by slugifying directory names in the events module.
    This tries to reverse that process for matching.
    """
    # Simple normalization: lowercase, replace spaces/special chars with hyphens
    normalized = name.lower()
    # Remove parentheses and other special characters
    for char in "()[]{}\"'":
        normalized = normalized.replace(char, "")
    # Replace spaces and underscores with hyphens
    normalized = normalized.replace(" ", "-")
    normalized = normalized.replace("_", "-")
    # Remove consecutive hyphens
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    normalized = normalized.strip("-")
    return normalized


def check_job_completed(log_path: Path) -> tuple[bool, str | None]:
    """
    Check if a job has a job_completed event and extract output path.

    Args:
        log_path: Path to events.jsonl file

    Returns:
        Tuple of (has_completion_event, output_dir_from_job_started)
    """
    try:
        events = read_event_log_typed(log_path)

        # Find job_completed event
        has_completion = any(
            isinstance(event, JobCompletedEvent) for event in events
        )

        # Extract output_dir from job_started event
        output_dir = None
        for event in events:
            if isinstance(event, JobStartedEvent):
                output_dir = event.output_dir
                break

        return has_completion, output_dir

    except Exception as e:
        logger.warning(f"Failed to parse event log {log_path}: {e}")
        return False, None


def find_symlink_for_central_log(central_log: Path, output_dir: str | None) -> Path | None:
    """
    Find the symlink that points to a central log file.

    Args:
        central_log: Path to central telemetry log
        output_dir: Directory where symlinks might be (from job_started event)

    Returns:
        Path to symlink if found, None otherwise
    """
    if output_dir is None:
        return None

    output_path = Path(output_dir).expanduser()
    if not output_path.exists():
        return None

    symlink_path = output_path / "events.jsonl"

    # Check if symlink exists and points to our central log
    if symlink_path.is_symlink():
        try:
            # Resolve both paths to handle symlinks like /tmp -> /private/tmp on macOS
            target = symlink_path.resolve()
            central_resolved = central_log.resolve()
            if target == central_resolved:
                return symlink_path
        except Exception:
            pass

    return None


def cleanup_telemetry(
    central_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = False
) -> CleanupResult:
    """
    Clean up telemetry files for completed jobs.

    Scans central telemetry directory and deletes event logs when:
    1. Job has a job_completed event
    2. Final transcription output exists

    Args:
        central_dir: Central telemetry directory (default: ~/.cache/pdf-transcriber/telemetry)
        dry_run: If True, show what would be deleted without deleting
        verbose: If True, print detailed reasoning for each decision

    Returns:
        CleanupResult with statistics and file lists
    """
    # Default central directory
    if central_dir is None:
        central_dir = Path.home() / ".cache" / "pdf-transcriber" / "telemetry"

    central_dir = Path(central_dir).expanduser()

    result = CleanupResult(
        total_logs_found=0,
        logs_deleted=0,
        logs_kept=0,
        deleted_files=[],
        kept_files=[],
        errors=[]
    )

    # Check if telemetry directory exists
    if not central_dir.exists():
        if verbose:
            print(f"Telemetry directory does not exist: {central_dir}")
        return result

    # Find all event logs
    event_logs = list(central_dir.glob("*.jsonl"))
    result.total_logs_found = len(event_logs)

    if verbose:
        print(f"Found {len(event_logs)} event log(s) in {central_dir}")
        print()

    for log_path in event_logs:
        job_id = log_path.stem

        try:
            # Check if job is completed
            has_completion, output_dir = check_job_completed(log_path)

            if not has_completion:
                if verbose:
                    print(f"KEEP: {log_path.name}")
                    print(f"  Reason: No job_completed event (active or failed job)")
                    print()
                result.logs_kept += 1
                result.kept_files.append(str(log_path))
                continue

            # Job is marked complete - check if output exists
            if output_dir is None:
                if verbose:
                    print(f"KEEP: {log_path.name}")
                    print(f"  Reason: Cannot determine output directory")
                    print()
                result.logs_kept += 1
                result.kept_files.append(str(log_path))
                continue

            # Look for final output file
            output_path = Path(output_dir).expanduser()
            final_output = None

            # Find .md file in output directory (not .original.md)
            if output_path.exists() and output_path.is_dir():
                for md_file in output_path.glob("*.md"):
                    if not md_file.name.endswith(".original.md"):
                        final_output = md_file
                        break

            if final_output is None or not final_output.exists():
                if verbose:
                    print(f"KEEP: {log_path.name}")
                    print(f"  Reason: Final output not found in {output_path}")
                    print()
                result.logs_kept += 1
                result.kept_files.append(str(log_path))
                continue

            # All conditions met - safe to delete
            if verbose:
                print(f"DELETE: {log_path.name}")
                print(f"  Reason: Job completed and output exists at {final_output}")

            # Find and delete symlink
            symlink = find_symlink_for_central_log(log_path, output_dir)

            if not dry_run:
                # Delete central log
                log_path.unlink()
                if verbose:
                    print(f"  Deleted: {log_path}")

                # Delete symlink if found (use is_symlink() to catch broken symlinks)
                if symlink and (symlink.is_symlink() or symlink.exists()):
                    symlink.unlink()
                    if verbose:
                        print(f"  Deleted symlink: {symlink}")
            else:
                if verbose:
                    print(f"  Would delete: {log_path}")
                    if symlink:
                        print(f"  Would delete symlink: {symlink}")

            if verbose:
                print()

            result.logs_deleted += 1
            result.deleted_files.append(str(log_path))

        except Exception as e:
            error_msg = f"Error processing {log_path.name}: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            result.logs_kept += 1
            result.kept_files.append(str(log_path))

            if verbose:
                print(f"ERROR: {log_path.name}")
                print(f"  {e}")
                print()

    return result


def print_summary(result: CleanupResult, dry_run: bool = False) -> None:
    """
    Print cleanup summary.

    Args:
        result: CleanupResult from cleanup operation
        dry_run: Whether this was a dry run
    """
    print("=" * 60)
    print("Cleanup Summary")
    print("=" * 60)

    if dry_run:
        print("Mode: DRY RUN (no files deleted)")
    else:
        print("Mode: LIVE (files deleted)")

    print()
    print(f"Total event logs found: {result.total_logs_found}")
    print(f"Logs deleted: {result.logs_deleted}")
    print(f"Logs kept: {result.logs_kept}")

    if result.errors:
        print(f"Errors: {len(result.errors)}")
        print()
        print("Errors encountered:")
        for error in result.errors:
            print(f"  - {error}")

    print()

    if result.logs_deleted == 0:
        print("No logs were eligible for deletion.")
    else:
        verb = "Would be deleted" if dry_run else "Deleted"
        print(f"{verb}: {result.logs_deleted} event log(s)")


def main():
    """CLI entry point for cleanup utility."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pdf-transcriber-cleanup",
        description="Clean up telemetry files for completed PDF transcription jobs"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed reasoning for each file"
    )

    parser.add_argument(
        "--telemetry-dir",
        type=Path,
        help="Central telemetry directory (default: ~/.cache/pdf-transcriber/telemetry)"
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s"
    )

    # Run cleanup
    try:
        result = cleanup_telemetry(
            central_dir=args.telemetry_dir,
            dry_run=args.dry_run,
            verbose=args.verbose
        )

        # Print summary
        if not args.verbose:
            # Always show summary if not in verbose mode
            print_summary(result, dry_run=args.dry_run)
        else:
            # In verbose mode, just print final stats
            print("=" * 60)
            print(f"Deleted: {result.logs_deleted}, Kept: {result.logs_kept}, Errors: {len(result.errors)}")

        # Exit with error code if there were errors
        if result.errors:
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
