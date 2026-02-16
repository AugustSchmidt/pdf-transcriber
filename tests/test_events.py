"""Tests for event system: typed events, parse_event, emit→discover round-trip, and job CM."""
import asyncio
import json
from pathlib import Path

import pytest

from pdf_transcriber.event_types import (
    JobStartedEvent,
    PageCompletedEvent,
    HeartbeatEvent,
    ErrorEvent,
    JobCompletedEvent,
)
from pdf_transcriber.events import (
    EventEmitter,
    ProgressTracker,
    parse_event,
    read_event_log_typed,
)
from pdf_transcriber.tui.discovery import discover_jobs


def _run(coro):
    """Run async coroutine synchronously (avoids pytest-asyncio dep)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_emitter(tmp_path: Path, job_id: str = "test-job") -> EventEmitter:
    """Create an EventEmitter writing to tmp_path (no symlink noise)."""
    output_dir = tmp_path / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return EventEmitter(job_id=job_id, output_dir=output_dir, central_dir=tmp_path / "telemetry")


# ---------------------------------------------------------------------------
# D1: Full success lifecycle
# ---------------------------------------------------------------------------


def test_full_success_lifecycle(tmp_path):
    """emit start → pages → completed → discover_jobs sees completed job."""
    emitter = _make_emitter(tmp_path)

    emitter.emit_job_started(
        pdf_path="/tmp/test.pdf",
        output_dir=str(tmp_path / "test-job"),
        total_pages=5,
        quality="balanced",
        mode="streaming",
        metadata={"title": "Test Paper"},
    )

    for page in range(1, 6):
        emitter.emit_page_completed(page_number=page, duration_ms=1000)

    emitter.emit_job_completed(total_pages=5, pages_completed=5, pages_failed=0)

    # discover_jobs scans the output directory
    jobs = discover_jobs(tmp_path, stale_threshold_seconds=120)
    assert len(jobs) == 1

    job = jobs[0]
    assert job.job_id == "test-job"
    assert job.completed_at is not None
    assert job.is_active is False
    assert job.pages_completed == 5
    assert job.total_pages == 5
    assert job.error_count == 0


# ---------------------------------------------------------------------------
# D2: Job with errors
# ---------------------------------------------------------------------------


def test_job_with_errors(tmp_path):
    """emit error + completed → discover sees error counts."""
    emitter = _make_emitter(tmp_path)

    emitter.emit_job_started(
        pdf_path="/tmp/test.pdf",
        output_dir=str(tmp_path / "test-job"),
        total_pages=10,
        quality="balanced",
        mode="streaming",
        metadata={},
    )

    for page in range(1, 9):
        emitter.emit_page_completed(page_number=page, duration_ms=800)

    emitter.emit_error(
        severity="error",
        error_type="ocr_fail",
        error_message="OCR failed on page 9",
        page_number=9,
    )
    emitter.emit_error(
        severity="warning",
        error_type="low_confidence",
        error_message="Low OCR confidence on page 10",
        page_number=10,
    )

    emitter.emit_job_completed(total_pages=10, pages_completed=8, pages_failed=2)

    jobs = discover_jobs(tmp_path, stale_threshold_seconds=120)
    assert len(jobs) == 1

    job = jobs[0]
    assert job.completed_at is not None
    assert job.is_active is False
    # job_completed event's counts override incremental counts
    # emitter tracks errors (1) and warnings (1) separately
    assert job.error_count == 1
    assert job.warning_count == 1


# ---------------------------------------------------------------------------
# D3: Stalled job detection
# ---------------------------------------------------------------------------


def test_stalled_job_detection(tmp_path):
    """emit start only (no completion) → discover sees active/stalled job."""
    emitter = _make_emitter(tmp_path)

    emitter.emit_job_started(
        pdf_path="/tmp/test.pdf",
        output_dir=str(tmp_path / "test-job"),
        total_pages=20,
        quality="fast",
        mode="streaming",
        metadata={},
    )

    emitter.emit_page_completed(page_number=1, duration_ms=500)

    # No job_completed, no heartbeat → should appear as active
    jobs = discover_jobs(tmp_path, stale_threshold_seconds=120)
    assert len(jobs) == 1

    job = jobs[0]
    assert job.completed_at is None
    assert job.is_active is True
    assert job.pages_completed == 1


# ---------------------------------------------------------------------------
# parse_event edge cases
# ---------------------------------------------------------------------------


def test_parse_event_unknown_type():
    """parse_event raises ValueError for unknown event_type."""
    with pytest.raises(ValueError, match="Unknown event_type"):
        parse_event({"event_type": "quantum_fluctuation", "timestamp": "now"})


def test_parse_event_missing_fields():
    """parse_event raises KeyError for missing required fields."""
    with pytest.raises(KeyError):
        parse_event({"event_type": "job_started"})  # missing all required fields


# ---------------------------------------------------------------------------
# Context manager tests (async)
# ---------------------------------------------------------------------------


def test_cm_success(tmp_path):
    """CM emits job_started + job_completed around successful body."""
    emitter = _make_emitter(tmp_path)

    async def _run_job():
        async with emitter.job(
            pdf_path="/tmp/test.pdf",
            output_dir=str(tmp_path / "test-job"),
            total_pages=3,
            quality="fast",
            mode="streaming",
            metadata={},
        ) as progress:
            progress.pages_completed = 3
            progress.pages_failed = 0

    _run(_run_job())

    # Read events back
    events = read_event_log_typed(emitter.central_log_path)
    event_types = [e.event_type for e in events]

    assert event_types == ["job_started", "job_completed"]

    # Verify job_completed has correct counts
    completed = events[-1]
    assert isinstance(completed, JobCompletedEvent)
    assert completed.pages_completed == 3
    assert completed.pages_failed == 0


def test_cm_exception(tmp_path):
    """CM emits error + job_completed even when body raises."""
    emitter = _make_emitter(tmp_path)

    async def _run_job():
        async with emitter.job(
            pdf_path="/tmp/test.pdf",
            output_dir=str(tmp_path / "test-job"),
            total_pages=10,
            quality="balanced",
            mode="streaming",
            metadata={},
        ) as progress:
            progress.pages_completed = 3
            progress.pages_failed = 1
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _run(_run_job())

    # Read events back
    events = read_event_log_typed(emitter.central_log_path)
    event_types = [e.event_type for e in events]

    # Should be: job_started, error (from CM), job_completed (from CM finally)
    assert event_types == ["job_started", "error", "job_completed"]

    # Verify error event
    error = events[1]
    assert isinstance(error, ErrorEvent)
    assert error.error_type == "transcription_failure"
    assert "boom" in error.error_message

    # Verify job_completed reflects progress at time of exception
    completed = events[2]
    assert isinstance(completed, JobCompletedEvent)
    assert completed.pages_completed == 3
    assert completed.pages_failed == 1


# ---------------------------------------------------------------------------
# from_dict round-trip
# ---------------------------------------------------------------------------


def test_from_dict_round_trip():
    """Event.to_dict() → Event.from_dict() preserves all fields."""
    events = [
        JobStartedEvent(
            timestamp="2026-02-15T12:00:00Z",
            job_id="roundtrip",
            pdf_path="/tmp/test.pdf",
            output_dir="/tmp/out",
            total_pages=42,
            quality="high-quality",
            mode="batch",
            metadata={"authors": ["Euler"]},
        ),
        PageCompletedEvent(
            timestamp="2026-02-15T12:01:00Z",
            job_id="roundtrip",
            page_number=7,
            duration_ms=1234,
            hallucination_detected=True,
            fallback_used="pymupdf",
            verification_error="math_symbol_mismatch",
        ),
        HeartbeatEvent(
            timestamp="2026-02-15T12:02:00Z",
            job_id="roundtrip",
            current_page=7,
            total_pages=42,
            pages_completed_since_last_heartbeat=3,
            cpu_percent=65.2,
            memory_mb=1024,
        ),
        ErrorEvent(
            timestamp="2026-02-15T12:03:00Z",
            job_id="roundtrip",
            severity="warning",
            error_type="low_confidence",
            error_message="Confidence below threshold",
            page_number=8,
        ),
        JobCompletedEvent(
            timestamp="2026-02-15T12:10:00Z",
            job_id="roundtrip",
            total_pages=42,
            pages_completed=40,
            pages_failed=2,
            total_duration_seconds=600.0,
            avg_velocity_pages_per_hour=240.0,
            error_count=1,
            warning_count=3,
        ),
    ]

    for event in events:
        d = event.to_dict()
        # Simulate JSON round-trip (catches non-serializable types)
        d = json.loads(json.dumps(d))
        restored = type(event).from_dict(d)
        assert restored == event, f"Round-trip failed for {type(event).__name__}: {restored} != {event}"
