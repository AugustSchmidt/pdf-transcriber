"""Event-driven telemetry for PDF transcription jobs.

This module provides JSONL-based event logging for transcription progress,
replacing the old .pdf-progress/ directory approach.

Events are the source of truth for resume-on-failure and monitoring.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Union
import json
import logging
import threading
import time

try:
    import psutil
except ImportError:
    psutil = None

from pdf_transcriber.event_types import (  # noqa: F401
    EventType,
    JobStartedEvent,
    PageCompletedEvent,
    HeartbeatEvent,
    ErrorEvent,
    JobCompletedEvent,
)

# Union of all typed event dataclasses
Event = Union[JobStartedEvent, PageCompletedEvent, HeartbeatEvent, ErrorEvent, JobCompletedEvent]

_EVENT_TYPE_MAP: dict[str, type] = {
    "job_started": JobStartedEvent,
    "page_completed": PageCompletedEvent,
    "heartbeat": HeartbeatEvent,
    "error": ErrorEvent,
    "job_completed": JobCompletedEvent,
}


def parse_event(raw: dict[str, Any]) -> Event:
    """Route a raw event dict to the correct typed dataclass.

    Args:
        raw: Parsed JSON dict from an event log line.

    Returns:
        Typed event dataclass instance.

    Raises:
        ValueError: Unknown event_type.
        KeyError: Missing required field in the raw dict.
    """
    event_type = raw.get("event_type")
    cls = _EVENT_TYPE_MAP.get(event_type)  # type: ignore[arg-type]
    if cls is None:
        raise ValueError(f"Unknown event_type: {event_type!r}")
    return cls.from_dict(raw)

logger = logging.getLogger(__name__)


class EventEmitter:
    """
    Handles event emission to JSONL log files.

    Uses hybrid storage: central cache directory with symlinks in output directories.
    """

    def __init__(
        self,
        job_id: str,
        output_dir: Path,
        central_dir: Path | None = None
    ):
        """
        Initialize event emitter.

        Args:
            job_id: Unique job identifier (derived from output directory name)
            output_dir: Output directory for this transcription
            central_dir: Central telemetry directory (default: ~/.cache/pdf-transcriber/telemetry)
        """
        self.job_id = job_id
        self.output_dir = Path(output_dir)

        # Central telemetry directory
        if central_dir is None:
            central_dir = Path.home() / ".cache" / "pdf-transcriber" / "telemetry"
        self.central_dir = Path(central_dir)
        self.central_dir.mkdir(parents=True, exist_ok=True)

        # Event log paths
        self.central_log_path = self.central_dir / f"{job_id}.jsonl"
        self.symlink_path = self.output_dir / "events.jsonl"

        # Create symlink in output directory
        self._create_symlink()

        # Heartbeat thread state
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop_event = threading.Event()
        self._heartbeat_interval = 30  # seconds
        self._current_page = 0
        self._pages_at_last_heartbeat = 0
        self._process = psutil.Process() if psutil else None

        # Statistics
        self._error_count = 0
        self._warning_count = 0
        self._start_time: float | None = None

    def _create_symlink(self) -> None:
        """Create symlink from output_dir to central log."""
        try:
            # Remove existing symlink/file if present
            if self.symlink_path.exists() or self.symlink_path.is_symlink():
                self.symlink_path.unlink()

            # Create symlink
            self.symlink_path.symlink_to(self.central_log_path)
            logger.debug(f"Created symlink: {self.symlink_path} -> {self.central_log_path}")
        except Exception as e:
            logger.warning(f"Failed to create symlink (will write directly): {e}")
            # Fallback: if symlink fails, we'll just write to central location

    def _write_event(self, event: JobStartedEvent | PageCompletedEvent | HeartbeatEvent | ErrorEvent | JobCompletedEvent) -> None:
        """
        Write event to JSONL log (append mode).

        Args:
            event: Event to write
        """
        try:
            event_json = json.dumps(event.to_dict())
            with open(self.central_log_path, 'a', encoding='utf-8') as f:
                f.write(event_json + '\n')
        except Exception as e:
            logger.error(f"Failed to write event: {e}")

    def _utc_timestamp(self) -> str:
        """Get current UTC timestamp in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def emit_job_started(
        self,
        pdf_path: str,
        output_dir: str,
        total_pages: int,
        quality: str,
        mode: str,
        metadata: dict[str, Any]
    ) -> None:
        """Emit job_started event."""
        self._start_time = time.time()

        event = JobStartedEvent(
            timestamp=self._utc_timestamp(),
            event_type="job_started",
            job_id=self.job_id,
            pdf_path=pdf_path,
            output_dir=output_dir,
            total_pages=total_pages,
            quality=quality,
            mode=mode,
            metadata=metadata
        )
        self._write_event(event)
        logger.info(f"Event: job_started ({total_pages} pages)")

    def emit_page_completed(
        self,
        page_number: int,
        duration_ms: int,
        hallucination_detected: bool = False,
        fallback_used: str | None = None,
        verification_error: str | None = None
    ) -> None:
        """Emit page_completed event."""
        self._current_page = page_number

        event = PageCompletedEvent(
            timestamp=self._utc_timestamp(),
            event_type="page_completed",
            job_id=self.job_id,
            page_number=page_number,
            duration_ms=duration_ms,
            hallucination_detected=hallucination_detected,
            fallback_used=fallback_used,
            verification_error=verification_error
        )
        self._write_event(event)

        # Enhanced logging for fallback cases
        if fallback_used:
            logger.info(
                f"Event: page_completed (page {page_number}, {duration_ms}ms, "
                f"fallback={fallback_used}, error={verification_error})"
            )
        else:
            logger.debug(f"Event: page_completed (page {page_number}, {duration_ms}ms)")

    def emit_heartbeat(self, current_page: int, total_pages: int) -> None:
        """
        Emit heartbeat event with resource metrics.

        Args:
            current_page: Current page being processed
            total_pages: Total pages in document
        """
        # Calculate pages since last heartbeat
        pages_since_last = current_page - self._pages_at_last_heartbeat
        self._pages_at_last_heartbeat = current_page

        # Get resource metrics
        cpu_percent = 0.0
        memory_mb = 0

        if self._process and psutil:
            try:
                cpu_percent = self._process.cpu_percent(interval=0.1)
                memory_mb = int(self._process.memory_info().rss / (1024 * 1024))
            except Exception as e:
                logger.debug(f"Failed to get process metrics: {e}")

        event = HeartbeatEvent(
            timestamp=self._utc_timestamp(),
            event_type="heartbeat",
            job_id=self.job_id,
            current_page=current_page,
            total_pages=total_pages,
            pages_completed_since_last_heartbeat=pages_since_last,
            cpu_percent=round(cpu_percent, 1),
            memory_mb=memory_mb
        )
        self._write_event(event)
        logger.debug(
            f"Event: heartbeat (page {current_page}/{total_pages}, "
            f"CPU {cpu_percent:.1f}%, MEM {memory_mb}MB)"
        )

    def emit_error(
        self,
        severity: Literal["error", "warning"],
        error_type: str,
        error_message: str,
        page_number: int | None = None
    ) -> None:
        """
        Emit error/warning event.

        Args:
            severity: "error" or "warning"
            error_type: Error type identifier (e.g., "ocr_fail", "timeout")
            error_message: Human-readable error message
            page_number: Optional page number where error occurred
        """
        if severity == "error":
            self._error_count += 1
        else:
            self._warning_count += 1

        event = ErrorEvent(
            timestamp=self._utc_timestamp(),
            event_type="error",  # Note: using "error" for both errors and warnings
            job_id=self.job_id,
            severity=severity,
            error_type=error_type,
            page_number=page_number,
            error_message=error_message
        )
        self._write_event(event)
        logger.info(f"Event: {severity} ({error_type}: {error_message})")

    def emit_job_completed(
        self,
        total_pages: int,
        pages_completed: int,
        pages_failed: int
    ) -> None:
        """Emit job_completed event."""
        # Calculate duration
        duration_seconds = 0.0
        if self._start_time:
            duration_seconds = time.time() - self._start_time

        # Calculate velocity
        avg_velocity = 0.0
        if duration_seconds > 0:
            avg_velocity = (pages_completed / duration_seconds) * 3600  # pages per hour

        event = JobCompletedEvent(
            timestamp=self._utc_timestamp(),
            event_type="job_completed",
            job_id=self.job_id,
            total_pages=total_pages,
            pages_completed=pages_completed,
            pages_failed=pages_failed,
            total_duration_seconds=round(duration_seconds, 2),
            avg_velocity_pages_per_hour=round(avg_velocity, 1),
            error_count=self._error_count,
            warning_count=self._warning_count
        )
        self._write_event(event)
        logger.info(
            f"Event: job_completed ({pages_completed}/{total_pages} pages, "
            f"{duration_seconds:.1f}s, {avg_velocity:.1f} pg/hr)"
        )

    def start_heartbeat(self, total_pages: int) -> None:
        """
        Start background heartbeat thread.

        Args:
            total_pages: Total pages in document (for heartbeat events)
        """
        if self._heartbeat_thread is not None:
            logger.warning("Heartbeat thread already running")
            return

        self._heartbeat_stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(total_pages,),
            daemon=True
        )
        self._heartbeat_thread.start()
        logger.info(f"Started heartbeat thread (interval: {self._heartbeat_interval}s)")

    def stop_heartbeat(self) -> None:
        """Stop background heartbeat thread."""
        if self._heartbeat_thread is None:
            return

        self._heartbeat_stop_event.set()
        self._heartbeat_thread.join(timeout=2.0)
        self._heartbeat_thread = None
        logger.info("Stopped heartbeat thread")

    def _heartbeat_loop(self, total_pages: int) -> None:
        """
        Heartbeat thread main loop.

        Args:
            total_pages: Total pages in document
        """
        while not self._heartbeat_stop_event.wait(self._heartbeat_interval):
            self.emit_heartbeat(self._current_page, total_pages)

    def update_current_page(self, page_number: int) -> None:
        """
        Update current page number for heartbeat tracking.

        Args:
            page_number: Current page number
        """
        self._current_page = page_number

    @asynccontextmanager
    async def job(
        self,
        pdf_path: str,
        output_dir: str,
        total_pages: int,
        quality: str,
        mode: str,
        metadata: dict[str, Any],
    ) -> AsyncIterator[ProgressTracker]:
        """Async context manager for a complete job lifecycle.

        Emits job_started on entry, guarantees job_completed + stop_heartbeat
        on exit — even if the body raises an exception.

        Usage::

            async with emitter.job(...) as progress:
                # transcription work...
                progress.pages_completed = summary.completed
                progress.pages_failed = summary.failed

        Args:
            pdf_path: Path to source PDF
            output_dir: Output directory for this job
            total_pages: Total pages in document
            quality: Quality preset name
            mode: Processing mode
            metadata: Job metadata dict
        """
        self.emit_job_started(
            pdf_path=pdf_path,
            output_dir=output_dir,
            total_pages=total_pages,
            quality=quality,
            mode=mode,
            metadata=metadata,
        )
        progress = ProgressTracker(total_pages=total_pages)
        try:
            yield progress
        except BaseException as exc:
            # Emit error for unexpected exceptions (not SystemExit from clean shutdown)
            if not isinstance(exc, (SystemExit, KeyboardInterrupt)):
                self.emit_error(
                    severity="error",
                    error_type="transcription_failure",
                    error_message=str(exc),
                )
            raise
        finally:
            self.emit_job_completed(
                total_pages=progress.total_pages,
                pages_completed=progress.pages_completed,
                pages_failed=progress.pages_failed,
            )
            self.stop_heartbeat()


@dataclass
class ProgressTracker:
    """Mutable progress state shared between the job CM and callers.

    The caller updates these fields during transcription; the CM reads
    them in __aexit__ to populate the job_completed event.
    """
    total_pages: int
    pages_completed: int = 0
    pages_failed: int = 0


def read_event_log(log_path: Path) -> list[dict[str, Any]]:
    """
    Read and parse event log.

    Args:
        log_path: Path to events.jsonl file

    Returns:
        List of event dictionaries (parsed JSON)
    """
    events = []

    if not log_path.exists():
        return events

    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping malformed event at line {line_num}: {e}")
    except Exception as e:
        logger.error(f"Failed to read event log: {e}")

    return events


def read_event_log_typed(log_path: Path) -> list[Event]:
    """Read event log and return typed event dataclass instances.

    Like read_event_log(), but deserializes each line into the appropriate
    typed dataclass. Skips malformed entries and unknown event types.

    Args:
        log_path: Path to events.jsonl file

    Returns:
        List of typed event instances
    """
    typed_events: list[Event] = []
    for raw in read_event_log(log_path):
        try:
            typed_events.append(parse_event(raw))
        except (ValueError, KeyError) as e:
            logger.warning(f"Skipping unparseable event: {e}")
    return typed_events


def get_last_completed_page(events: list[dict[str, Any]]) -> int:
    """
    Find the last completed page from event log.

    Args:
        events: List of event dictionaries

    Returns:
        Last completed page number (0 if none)
    """
    completed_pages = [
        event['page_number']
        for event in events
        if event.get('event_type') == 'page_completed'
    ]

    return max(completed_pages) if completed_pages else 0


def validate_completed_pages(
    events: list[dict[str, Any]],
    validation_count: int = 10
) -> tuple[list[int], list[int]]:
    """
    Validate last N completed pages from event log.

    This provides corruption detection - if recent pages are missing,
    we can scan backward to find the last verified page.

    Args:
        events: List of event dictionaries
        validation_count: Number of recent pages to validate

    Returns:
        Tuple of (all_completed_pages, validated_pages)
    """
    completed_pages = sorted([
        event['page_number']
        for event in events
        if event.get('event_type') == 'page_completed'
    ])

    if not completed_pages:
        return [], []

    # Take last N pages for validation
    pages_to_validate = completed_pages[-validation_count:]

    # Assume all are valid for now (Phase 1)
    # Phase 2 would check if page files exist or verify in final output
    validated_pages = pages_to_validate

    return completed_pages, validated_pages
