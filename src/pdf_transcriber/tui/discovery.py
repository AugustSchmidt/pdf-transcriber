"""Auto-discovery of transcription jobs from event logs."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import logging

from pdf_transcriber.events import read_event_log_typed
from pdf_transcriber.event_types import (
    JobStartedEvent,
    PageCompletedEvent,
    HeartbeatEvent,
    ErrorEvent,
    JobCompletedEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class JobInfo:
    """Information about a discovered transcription job."""
    job_id: str
    output_dir: Path
    event_log_path: Path
    is_active: bool
    is_stalled: bool

    # From job_started event
    pdf_path: str | None = None
    total_pages: int | None = None
    quality: str | None = None
    mode: str | None = None
    metadata: dict | None = None

    # Progress tracking
    current_page: int = 0
    pages_completed: int = 0

    # Timestamps
    started_at: datetime | None = None
    last_heartbeat: datetime | None = None
    completed_at: datetime | None = None

    # Statistics
    error_count: int = 0
    warning_count: int = 0

    # Resource metrics (from last heartbeat)
    cpu_percent: float = 0.0
    memory_mb: int = 0


def discover_jobs(
    output_dir: Path,
    stale_threshold_seconds: int = 120
) -> list[JobInfo]:
    """
    Discover all transcription jobs by scanning output directories.

    Looks for directories containing events.jsonl symlinks, then parses
    the event logs to build job state.

    Args:
        output_dir: Root output directory to scan
        stale_threshold_seconds: Seconds without heartbeat before job is stalled

    Returns:
        List of discovered jobs (active first, then recent completed)
    """
    jobs = []

    if not output_dir.exists():
        logger.debug(f"Output directory not found: {output_dir}")
        return jobs

    # Scan for directories with events.jsonl
    for job_dir in output_dir.iterdir():
        if not job_dir.is_dir():
            continue

        event_log = job_dir / "events.jsonl"
        if not event_log.exists() and not event_log.is_symlink():
            continue

        # Parse event log
        try:
            job_info = _parse_job_from_events(
                job_dir,
                event_log,
                stale_threshold_seconds
            )
            if job_info:
                jobs.append(job_info)
        except Exception as e:
            logger.warning(f"Failed to parse events for {job_dir.name}: {e}")

    # Sort: active first (by current_page desc), then completed (by completion time desc)
    jobs.sort(key=lambda j: (
        not j.is_active,  # Active jobs first
        -(j.current_page or 0) if j.is_active else 0,  # Active: sort by progress
        -(j.completed_at.timestamp() if j.completed_at else 0)  # Completed: sort by time
    ))

    return jobs


def _parse_job_from_events(
    job_dir: Path,
    event_log_path: Path,
    stale_threshold_seconds: int
) -> JobInfo | None:
    """
    Parse event log to extract job information.

    Args:
        job_dir: Output directory for this job
        event_log_path: Path to events.jsonl (may be symlink)
        stale_threshold_seconds: Threshold for stale detection

    Returns:
        JobInfo if events found, None otherwise
    """
    # Follow symlink if needed
    if event_log_path.is_symlink():
        event_log_path = event_log_path.resolve()

    # Read events as typed dataclasses
    events = read_event_log_typed(event_log_path)
    if not events:
        return None

    # Initialize job info
    job_info = JobInfo(
        job_id=job_dir.name,
        output_dir=job_dir,
        event_log_path=event_log_path,
        is_active=False,
        is_stalled=False
    )

    # Process events in order using isinstance dispatch
    for event in events:
        if isinstance(event, JobStartedEvent):
            job_info.pdf_path = event.pdf_path
            job_info.total_pages = event.total_pages
            job_info.quality = event.quality
            job_info.mode = event.mode
            job_info.metadata = event.metadata
            job_info.started_at = _parse_timestamp(event.timestamp)

        elif isinstance(event, PageCompletedEvent):
            job_info.pages_completed += 1
            if event.page_number > job_info.current_page:
                job_info.current_page = event.page_number

        elif isinstance(event, HeartbeatEvent):
            job_info.last_heartbeat = _parse_timestamp(event.timestamp)
            job_info.current_page = event.current_page
            job_info.cpu_percent = event.cpu_percent
            job_info.memory_mb = event.memory_mb

        elif isinstance(event, ErrorEvent):
            if event.severity == "error":
                job_info.error_count += 1
            else:
                job_info.warning_count += 1

        elif isinstance(event, JobCompletedEvent):
            job_info.completed_at = _parse_timestamp(event.timestamp)
            job_info.is_active = False
            job_info.error_count = event.error_count
            job_info.warning_count = event.warning_count

    # Determine if job is active or stalled
    if job_info.completed_at is None:
        # Self-healing heuristic: if the output .md file exists, infer
        # completion from its mtime (handles logs permanently missing
        # job_completed due to the earlier emit_job_completed bug)
        output_md = job_dir / f"{job_dir.name}.md"
        if output_md.exists():
            mtime = output_md.stat().st_mtime
            job_info.completed_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
            job_info.is_active = False
            logger.debug(
                f"Inferred completion for {job_dir.name} from output file mtime"
            )
        else:
            job_info.is_active = True

            # Check for stalled job (no heartbeat in threshold period)
            if job_info.last_heartbeat:
                now = datetime.now(timezone.utc)
                seconds_since_heartbeat = (now - job_info.last_heartbeat).total_seconds()
                if seconds_since_heartbeat > stale_threshold_seconds:
                    job_info.is_stalled = True

    return job_info


def _parse_timestamp(ts_str: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp string."""
    if not ts_str:
        return None

    try:
        # Handle both 'Z' and '+00:00' formats
        ts_str = ts_str.replace('Z', '+00:00')
        return datetime.fromisoformat(ts_str)
    except Exception as e:
        logger.debug(f"Failed to parse timestamp '{ts_str}': {e}")
        return None
