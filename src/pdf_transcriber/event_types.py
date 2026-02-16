"""Event dataclasses for PDF transcription telemetry.

Defines the JSONL event schema for transcription progress tracking.
Each event type corresponds to a specific phase of the transcription lifecycle.

Each event has:
- to_dict(): serialize to JSON-safe dict (for writing to JSONL)
- from_dict(): deserialize from raw dict (for reading from JSONL)
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal


# Event type literals
EventType = Literal[
    "job_started",
    "page_completed",
    "heartbeat",
    "error",
    "warning",
    "job_completed"
]


@dataclass
class JobStartedEvent:
    """Emitted once at transcription start."""
    timestamp: str
    job_id: str
    pdf_path: str
    output_dir: str
    total_pages: int
    quality: str
    mode: str
    metadata: dict[str, Any]
    event_type: EventType = "job_started"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobStartedEvent:
        """Create from raw event dict. Raises KeyError on missing required fields."""
        return cls(
            timestamp=data["timestamp"],
            job_id=data["job_id"],
            pdf_path=data["pdf_path"],
            output_dir=data["output_dir"],
            total_pages=data["total_pages"],
            quality=data["quality"],
            mode=data["mode"],
            metadata=data.get("metadata", {}),
            event_type=data.get("event_type", "job_started"),
        )


@dataclass
class PageCompletedEvent:
    """Emitted after each page is successfully transcribed."""
    timestamp: str
    job_id: str
    page_number: int
    duration_ms: int
    hallucination_detected: bool = False
    fallback_used: str | None = None  # "pymupdf" or None
    verification_error: str | None = None  # Error type if hallucination detected
    event_type: EventType = "page_completed"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageCompletedEvent:
        """Create from raw event dict. Raises KeyError on missing required fields."""
        return cls(
            timestamp=data["timestamp"],
            job_id=data["job_id"],
            page_number=data["page_number"],
            duration_ms=data["duration_ms"],
            hallucination_detected=data.get("hallucination_detected", False),
            fallback_used=data.get("fallback_used"),
            verification_error=data.get("verification_error"),
            event_type=data.get("event_type", "page_completed"),
        )


@dataclass
class HeartbeatEvent:
    """Emitted every 30 seconds while transcription is active."""
    timestamp: str
    job_id: str
    current_page: int
    total_pages: int
    pages_completed_since_last_heartbeat: int
    cpu_percent: float
    memory_mb: int
    event_type: EventType = "heartbeat"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeartbeatEvent:
        """Create from raw event dict. Raises KeyError on missing required fields."""
        return cls(
            timestamp=data["timestamp"],
            job_id=data["job_id"],
            current_page=data["current_page"],
            total_pages=data["total_pages"],
            pages_completed_since_last_heartbeat=data.get("pages_completed_since_last_heartbeat", 0),
            cpu_percent=data.get("cpu_percent", 0.0),
            memory_mb=data.get("memory_mb", 0),
            event_type=data.get("event_type", "heartbeat"),
        )


@dataclass
class ErrorEvent:
    """Emitted when problems occur."""
    timestamp: str
    job_id: str
    severity: Literal["error", "warning"]
    error_type: str
    error_message: str
    page_number: int | None = None
    event_type: EventType = "error"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ErrorEvent:
        """Create from raw event dict. Raises KeyError on missing required fields."""
        return cls(
            timestamp=data["timestamp"],
            job_id=data["job_id"],
            severity=data["severity"],
            error_type=data["error_type"],
            error_message=data["error_message"],
            page_number=data.get("page_number"),
            event_type=data.get("event_type", "error"),
        )


@dataclass
class JobCompletedEvent:
    """Emitted once at successful completion."""
    timestamp: str
    job_id: str
    total_pages: int
    pages_completed: int
    pages_failed: int
    total_duration_seconds: float
    avg_velocity_pages_per_hour: float
    error_count: int
    warning_count: int
    event_type: EventType = "job_completed"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobCompletedEvent:
        """Create from raw event dict. Raises KeyError on missing required fields."""
        return cls(
            timestamp=data["timestamp"],
            job_id=data["job_id"],
            total_pages=data["total_pages"],
            pages_completed=data["pages_completed"],
            pages_failed=data["pages_failed"],
            total_duration_seconds=data.get("total_duration_seconds", 0.0),
            avg_velocity_pages_per_hour=data.get("avg_velocity_pages_per_hour", 0.0),
            error_count=data.get("error_count", 0),
            warning_count=data.get("warning_count", 0),
            event_type=data.get("event_type", "job_completed"),
        )
