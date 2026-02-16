"""Velocity and ETA calculation for transcription jobs."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

from pdf_transcriber.events import read_event_log_typed
from pdf_transcriber.event_types import (
    JobStartedEvent,
    PageCompletedEvent,
    HeartbeatEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class JobMetrics:
    """Calculated metrics for a transcription job."""
    # Progress
    current_page: int
    total_pages: int
    pages_completed: int
    progress_percent: float

    # Velocity (rolling window)
    velocity_pages_per_hour: float
    window_size: int  # Actual pages used for calculation

    # Time estimates
    elapsed_time: timedelta | None
    eta_hours: float | None
    completion_time: datetime | None

    # Resource usage (from last heartbeat)
    cpu_percent: float
    memory_mb: int


def calculate_metrics(
    event_log_path: Path,
    window_size: int = 50,
    min_pages_for_velocity: int = 5
) -> JobMetrics | None:
    """
    Calculate job metrics from event log.

    Uses a rolling window approach for velocity calculation to balance
    responsiveness and stability.

    Args:
        event_log_path: Path to events.jsonl file
        window_size: Number of recent pages to use for velocity (default: 50)
        min_pages_for_velocity: Minimum pages needed for stable velocity (default: 5)

    Returns:
        JobMetrics if sufficient data available, None otherwise
    """
    # Read event log as typed events
    events = read_event_log_typed(event_log_path)
    if not events:
        return None

    # Extract key information
    total_pages = None
    current_page = 0
    started_at = None
    cpu_percent = 0.0
    memory_mb = 0

    # Collect page completion events
    page_events: list[tuple[datetime, int]] = []

    for event in events:
        if isinstance(event, JobStartedEvent):
            total_pages = event.total_pages
            started_at = _parse_timestamp(event.timestamp)

        elif isinstance(event, PageCompletedEvent):
            ts = _parse_timestamp(event.timestamp)
            if ts and event.page_number is not None:
                page_events.append((ts, event.page_number))

        elif isinstance(event, HeartbeatEvent):
            current_page = event.current_page
            cpu_percent = event.cpu_percent
            memory_mb = event.memory_mb

    if total_pages is None or not page_events:
        return None

    # Calculate progress
    pages_completed = len(page_events)
    progress_percent = (current_page / total_pages * 100) if total_pages > 0 else 0.0

    # Calculate elapsed time
    elapsed = None
    if started_at:
        now = datetime.now(timezone.utc)
        elapsed = now - started_at

    # Calculate velocity using rolling window
    velocity, actual_window_size = _calculate_rolling_velocity(
        page_events,
        window_size,
        min_pages_for_velocity
    )

    # Calculate ETA
    eta_hours = None
    completion_time = None

    if velocity > 0 and total_pages > current_page:
        remaining_pages = total_pages - current_page
        eta_hours = remaining_pages / velocity
        completion_time = datetime.now(timezone.utc) + timedelta(hours=eta_hours)

    return JobMetrics(
        current_page=current_page,
        total_pages=total_pages,
        pages_completed=pages_completed,
        progress_percent=round(progress_percent, 1),
        velocity_pages_per_hour=round(velocity, 1),
        window_size=actual_window_size,
        elapsed_time=elapsed,
        eta_hours=eta_hours,
        completion_time=completion_time,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb
    )


def _calculate_rolling_velocity(
    page_events: list[tuple[datetime, int]],
    window_size: int,
    min_pages: int
) -> tuple[float, int]:
    """
    Calculate velocity using a rolling window of recent pages.

    Args:
        page_events: List of (timestamp, page_number) tuples
        window_size: Target number of pages for window
        min_pages: Minimum pages required for calculation

    Returns:
        Tuple of (velocity_pages_per_hour, actual_window_size)
    """
    if len(page_events) < min_pages:
        return 0.0, 0

    # Sort by timestamp (should already be sorted from log)
    page_events = sorted(page_events, key=lambda x: x[0])

    # Take last N pages
    window = page_events[-window_size:]
    actual_size = len(window)

    if actual_size < min_pages:
        return 0.0, 0

    # Calculate time span
    first_ts = window[0][0]
    last_ts = window[-1][0]
    time_span = (last_ts - first_ts).total_seconds()

    if time_span <= 0:
        # All pages completed at same time (unlikely but possible)
        return 0.0, actual_size

    # Calculate velocity (pages per hour)
    pages_in_window = len(window)
    hours = time_span / 3600.0
    velocity = pages_in_window / hours

    return velocity, actual_size


def format_elapsed_time(td: timedelta | None) -> str:
    """Format elapsed time as human-readable string."""
    if td is None:
        return "Unknown"

    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def format_eta(eta_hours: float | None) -> str:
    """Format ETA as human-readable string."""
    if eta_hours is None or eta_hours <= 0:
        return "Unknown"

    if eta_hours < 1:
        minutes = int(eta_hours * 60)
        return f"~{minutes}m"
    else:
        return f"~{eta_hours:.1f}h"


def format_completion_time(dt: datetime | None) -> str:
    """Format completion time as human-readable string."""
    if dt is None:
        return "Unknown"

    # Convert to local time
    local_dt = dt.astimezone()
    return local_dt.strftime("%H:%M")


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
