"""Tests for cleanup module."""
import json
from pathlib import Path
import pytest
import tempfile

from pdf_transcriber.cleanup import (
    cleanup_telemetry,
    check_job_completed,
    find_symlink_for_central_log,
    _normalize_job_id,
)


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for testing."""
    central_dir = tmp_path / "telemetry"
    central_dir.mkdir()

    output_base = tmp_path / "transcriptions"
    output_base.mkdir()

    return central_dir, output_base


def create_event_log(
    central_dir: Path,
    job_id: str,
    output_dir: str,
    include_completion: bool = True,
    total_pages: int = 10,
    pages_completed: int = 10
):
    """Helper to create a test event log."""
    log_path = central_dir / f"{job_id}.jsonl"

    events = [
        {
            "timestamp": "2026-02-14T19:01:00.768453Z",
            "event_type": "job_started",
            "job_id": job_id,
            "pdf_path": f"/tmp/test/{job_id}.pdf",
            "output_dir": output_dir,
            "total_pages": total_pages,
            "quality": "balanced",
            "mode": "streaming",
            "metadata": {"title": "Test Paper"}
        },
        {
            "timestamp": "2026-02-14T19:01:30.123456Z",
            "event_type": "page_completed",
            "job_id": job_id,
            "page_number": 1,
            "duration_ms": 1500
        }
    ]

    if include_completion:
        events.append({
            "timestamp": "2026-02-14T19:10:00.000000Z",
            "event_type": "job_completed",
            "job_id": job_id,
            "total_pages": total_pages,
            "pages_completed": pages_completed,
            "pages_failed": 0,
            "total_duration_seconds": 540.0,
            "avg_velocity_pages_per_hour": 66.7,
            "error_count": 0,
            "warning_count": 0
        })

    with open(log_path, 'w') as f:
        for event in events:
            f.write(json.dumps(event) + '\n')

    return log_path


def create_output_file(output_dir: Path, filename: str = "test.md"):
    """Helper to create a test output file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / filename
    output_file.write_text("# Test Output\n\nTranscribed content here.")
    return output_file


def create_symlink(output_dir: Path, central_log: Path):
    """Helper to create a symlink."""
    output_dir.mkdir(parents=True, exist_ok=True)
    symlink_path = output_dir / "events.jsonl"
    symlink_path.symlink_to(central_log)
    return symlink_path


def test_normalize_job_id():
    """Test job ID normalization."""
    assert _normalize_job_id("Rising Sea - Vakil (pub)") == "rising-sea-vakil-pub"
    assert _normalize_job_id("Test_Paper") == "test-paper"
    assert _normalize_job_id("multiple---hyphens") == "multiple-hyphens"
    assert _normalize_job_id("  spaces  ") == "spaces"


def test_check_job_completed(temp_dirs):
    """Test checking if a job is completed."""
    central_dir, output_base = temp_dirs
    output_dir = str(output_base / "test-job")

    # Create log with completion
    log_path = create_event_log(central_dir, "test-job", output_dir, include_completion=True)
    has_completion, extracted_output = check_job_completed(log_path)

    assert has_completion is True
    assert extracted_output == output_dir

    # Create log without completion
    log_path2 = create_event_log(central_dir, "incomplete-job", output_dir, include_completion=False)
    has_completion2, extracted_output2 = check_job_completed(log_path2)

    assert has_completion2 is False
    assert extracted_output2 == output_dir


def test_find_symlink_for_central_log(temp_dirs):
    """Test finding symlink for a central log."""
    central_dir, output_base = temp_dirs
    output_dir = output_base / "test-job"
    central_log = central_dir / "test-job.jsonl"
    central_log.touch()

    # Create symlink
    symlink = create_symlink(output_dir, central_log)

    # Find it (resolve both for comparison due to /tmp -> /private/tmp on macOS)
    found_symlink = find_symlink_for_central_log(central_log, str(output_dir))
    assert found_symlink is not None
    assert found_symlink.resolve() == symlink.resolve()
    assert found_symlink.is_symlink()

    # Test with non-existent directory
    found_none = find_symlink_for_central_log(central_log, str(output_base / "nonexistent"))
    assert found_none is None


def test_cleanup_completed_job_with_output(temp_dirs):
    """Test cleanup deletes logs for completed jobs with output."""
    central_dir, output_base = temp_dirs
    output_dir = output_base / "test-job"

    # Create event log
    log_path = create_event_log(central_dir, "test-job", str(output_dir), include_completion=True)

    # Create output file
    create_output_file(output_dir, "test-job.md")

    # Create symlink
    create_symlink(output_dir, log_path)

    # Run cleanup (not dry-run)
    result = cleanup_telemetry(central_dir=central_dir, dry_run=False)

    assert result.total_logs_found == 1
    assert result.logs_deleted == 1
    assert result.logs_kept == 0
    assert not log_path.exists()
    assert len(result.errors) == 0


def test_cleanup_dry_run(temp_dirs):
    """Test cleanup dry-run doesn't delete files."""
    central_dir, output_base = temp_dirs
    output_dir = output_base / "test-job"

    # Create event log and output
    log_path = create_event_log(central_dir, "test-job", str(output_dir), include_completion=True)
    create_output_file(output_dir, "test-job.md")
    create_symlink(output_dir, log_path)

    # Run cleanup in dry-run mode
    result = cleanup_telemetry(central_dir=central_dir, dry_run=True)

    assert result.total_logs_found == 1
    assert result.logs_deleted == 1  # Would be deleted
    assert result.logs_kept == 0
    assert log_path.exists()  # Still exists in dry-run


def test_cleanup_keeps_incomplete_jobs(temp_dirs):
    """Test cleanup keeps logs for incomplete jobs."""
    central_dir, output_base = temp_dirs
    output_dir = output_base / "incomplete-job"

    # Create event log WITHOUT completion
    log_path = create_event_log(central_dir, "incomplete-job", str(output_dir), include_completion=False)

    # Run cleanup
    result = cleanup_telemetry(central_dir=central_dir, dry_run=False)

    assert result.total_logs_found == 1
    assert result.logs_deleted == 0
    assert result.logs_kept == 1
    assert log_path.exists()


def test_cleanup_keeps_completed_without_output(temp_dirs):
    """Test cleanup keeps logs for completed jobs without output file."""
    central_dir, output_base = temp_dirs
    output_dir = output_base / "test-job"

    # Create event log with completion but NO output file
    log_path = create_event_log(central_dir, "test-job", str(output_dir), include_completion=True)

    # Don't create output file
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run cleanup
    result = cleanup_telemetry(central_dir=central_dir, dry_run=False)

    assert result.total_logs_found == 1
    assert result.logs_deleted == 0
    assert result.logs_kept == 1
    assert log_path.exists()


def test_cleanup_handles_corrupted_log(temp_dirs):
    """Test cleanup handles corrupted event logs gracefully."""
    central_dir, output_base = temp_dirs

    # Create corrupted log
    corrupted_log = central_dir / "corrupted.jsonl"
    corrupted_log.write_text("not valid json\n{incomplete")

    # Run cleanup
    result = cleanup_telemetry(central_dir=central_dir, dry_run=False)

    assert result.total_logs_found == 1
    assert result.logs_deleted == 0
    assert result.logs_kept == 1
    assert corrupted_log.exists()


def test_cleanup_multiple_jobs(temp_dirs):
    """Test cleanup with multiple jobs in different states."""
    central_dir, output_base = temp_dirs

    # Job 1: Completed with output (should delete)
    output_dir1 = output_base / "job1"
    log1 = create_event_log(central_dir, "job1", str(output_dir1), include_completion=True)
    create_output_file(output_dir1, "job1.md")
    create_symlink(output_dir1, log1)

    # Job 2: Completed without output (should keep)
    output_dir2 = output_base / "job2"
    log2 = create_event_log(central_dir, "job2", str(output_dir2), include_completion=True)
    output_dir2.mkdir(parents=True, exist_ok=True)

    # Job 3: Incomplete (should keep)
    output_dir3 = output_base / "job3"
    log3 = create_event_log(central_dir, "job3", str(output_dir3), include_completion=False)

    # Run cleanup
    result = cleanup_telemetry(central_dir=central_dir, dry_run=False)

    assert result.total_logs_found == 3
    assert result.logs_deleted == 1
    assert result.logs_kept == 2
    assert not log1.exists()  # Deleted
    assert log2.exists()  # Kept
    assert log3.exists()  # Kept


def test_cleanup_ignores_original_md(temp_dirs):
    """Test cleanup doesn't consider .original.md as final output."""
    central_dir, output_base = temp_dirs
    output_dir = output_base / "test-job"

    # Create event log
    log_path = create_event_log(central_dir, "test-job", str(output_dir), include_completion=True)

    # Create only .original.md file (not final output)
    create_output_file(output_dir, "test-job.original.md")

    # Run cleanup
    result = cleanup_telemetry(central_dir=central_dir, dry_run=False)

    assert result.total_logs_found == 1
    assert result.logs_deleted == 0
    assert result.logs_kept == 1
    assert log_path.exists()


def test_cleanup_nonexistent_directory(tmp_path):
    """Test cleanup handles nonexistent telemetry directory."""
    nonexistent = tmp_path / "does-not-exist"

    result = cleanup_telemetry(central_dir=nonexistent, dry_run=False)

    assert result.total_logs_found == 0
    assert result.logs_deleted == 0
    assert result.logs_kept == 0
