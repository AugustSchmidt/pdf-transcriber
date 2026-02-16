"""Resume-capable state management for PDF transcription jobs."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json
import logging
import shutil

from pdf_transcriber.events import (
    read_event_log,
    read_event_log_typed,
    get_last_completed_page,
    validate_completed_pages,
)
from pdf_transcriber.event_types import JobStartedEvent, ErrorEvent

logger = logging.getLogger(__name__)


@dataclass
class ProgressSummary:
    """Typed progress summary returned by StateManager.get_progress_summary()."""
    active: bool
    completed: int
    failed: int
    pending: int
    total: int
    completion_percentage: float
    started_at: str | None = None
    last_updated: str | None = None


@dataclass
class TranscriptionState:
    """State for a transcription job."""

    pdf_source: str
    total_pages: int
    completed_pages: list[int]
    failed_pages: list[int]
    output_format: str
    quality: str
    started_at: str
    last_updated: str
    version: int = 1

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptionState":
        """Create from dictionary."""
        return cls(**data)


class StateManager:
    """
    Manages transcription progress and resume capability.

    Creates a .pdf-progress/ directory with:
    - state.json: Lightweight state (~500 bytes)
    - page_NNN.md: Individual completed pages (for assembly)
    """

    def __init__(self, output_dir: Path, paper_name: str):
        """
        Initialize state manager.

        Args:
            output_dir: Base output directory
            paper_name: Name of the paper (used for subdirectory)
        """
        self.output_dir = Path(output_dir)
        self.paper_name = paper_name
        self.progress_dir = self.output_dir / paper_name / ".pdf-progress"
        self.state_file = self.progress_dir / "state.json"
        self.events_log = self.output_dir / paper_name / "events.jsonl"

    def has_existing_job(self) -> bool:
        """Check if a resumable job exists."""
        # Check both new event log and old state.json for backward compatibility
        return self.events_log.exists() or self.state_file.exists()

    def load_state_from_events(self) -> TranscriptionState | None:
        """
        Load state by replaying event log.

        This is the new event-driven resume approach. Falls back to
        load_state() for backward compatibility.

        Returns:
            TranscriptionState reconstructed from events, None if no events
        """
        # Try event log first
        if not self.events_log.exists():
            # Fall back to old state.json
            return self.load_state()

        try:
            # Read raw events for validate_completed_pages (operates on raw dicts)
            raw_events = read_event_log(self.events_log)
            if not raw_events:
                return self.load_state()

            # Read typed events for structured access
            typed_events = read_event_log_typed(self.events_log)
            if not typed_events:
                return self.load_state()

            # Find job_started event
            job_started = None
            for event in typed_events:
                if isinstance(event, JobStartedEvent):
                    job_started = event
                    break

            if not job_started:
                logger.warning("No job_started event found, falling back to state.json")
                return self.load_state()

            # Collect completed and failed pages
            all_completed, validated = validate_completed_pages(raw_events, validation_count=10)

            failed_pages: list[int] = []
            for event in typed_events:
                if isinstance(event, ErrorEvent) and event.severity == "error":
                    if event.page_number and event.page_number not in failed_pages:
                        failed_pages.append(event.page_number)

            # Reconstruct state — last timestamp from raw events (guaranteed non-empty)
            last_ts = raw_events[-1].get("timestamp", job_started.timestamp)
            state = TranscriptionState(
                pdf_source=job_started.pdf_path,
                total_pages=job_started.total_pages,
                completed_pages=all_completed,
                failed_pages=failed_pages,
                output_format="markdown",  # hardcoded for now
                quality=job_started.quality,
                started_at=job_started.timestamp,
                last_updated=last_ts,
            )

            logger.info(
                f"Loaded state from events: {len(state.completed_pages)}/{state.total_pages} "
                f"pages complete"
            )
            return state

        except Exception as e:
            logger.error(f"Failed to load state from events: {e}")
            return self.load_state()

    def load_state(self) -> TranscriptionState | None:
        """
        Load existing state for resume.

        Returns:
            TranscriptionState if exists, None otherwise
        """
        if not self.state_file.exists():
            return None

        try:
            data = json.loads(self.state_file.read_text())
            state = TranscriptionState.from_dict(data)
            logger.info(
                f"Loaded state: {len(state.completed_pages)}/{state.total_pages} pages complete"
            )
            return state
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.error(f"Corrupt state file: {e}")
            return None

    def create_job(
        self,
        pdf_source: str,
        total_pages: int,
        output_format: str,
        quality: str
    ) -> TranscriptionState:
        """
        Initialize new transcription job.

        Args:
            pdf_source: Path to source PDF
            total_pages: Total number of pages
            output_format: "markdown" or "latex"
            quality: Quality preset name

        Returns:
            New TranscriptionState
        """
        self.progress_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.utcnow().isoformat() + "Z"
        state = TranscriptionState(
            pdf_source=pdf_source,
            total_pages=total_pages,
            completed_pages=[],
            failed_pages=[],
            output_format=output_format,
            quality=quality,
            started_at=now,
            last_updated=now
        )

        self._save_state(state)
        logger.info(
            f"Created new job: {total_pages} pages, "
            f"format={output_format}, quality={quality}"
        )
        return state

    def mark_page_complete(self, page_num: int, content: str) -> None:
        """
        Save completed page and update state.

        Args:
            page_num: 1-indexed page number
            content: Transcribed content for this page
        """
        # Try event-based state first
        state = self.load_state_from_events()
        if state is None:
            raise RuntimeError("No active job. Call create_job() first.")

        # Don't add duplicates
        if page_num not in state.completed_pages:
            state.completed_pages.append(page_num)
            state.completed_pages.sort()  # Keep sorted for assembly

        state.last_updated = datetime.utcnow().isoformat() + "Z"

        # Save page content to temp file
        page_file = self.progress_dir / f"page_{page_num:03d}.md"
        page_file.write_text(content, encoding="utf-8")

        self._save_state(state)
        logger.info(
            f"Page {page_num} complete ({len(state.completed_pages)}/{state.total_pages})"
        )

    def mark_page_failed(self, page_num: int, error: str) -> None:
        """
        Record page failure for later retry.

        Args:
            page_num: 1-indexed page number
            error: Error message
        """
        state = self.load_state_from_events()
        if state is None:
            raise RuntimeError("No active job.")

        if page_num not in state.failed_pages:
            state.failed_pages.append(page_num)

        state.last_updated = datetime.utcnow().isoformat() + "Z"
        self._save_state(state)

        logger.warning(f"Page {page_num} failed: {error}")

    def get_pending_pages(self) -> list[int]:
        """
        Get pages that still need processing.

        On resume, previously failed pages are included so they get
        retried. Only successfully completed pages are skipped.

        Returns:
            List of page numbers (1-indexed) that haven't been completed
        """
        state = self.load_state_from_events()
        if state is None:
            return []

        completed = set(state.completed_pages)
        pending = [
            page_num
            for page_num in range(1, state.total_pages + 1)
            if page_num not in completed
        ]

        return pending

    def get_failed_pages(self) -> list[int]:
        """Get list of failed pages for retry."""
        state = self.load_state_from_events()
        if state is None:
            return []
        return state.failed_pages.copy()

    def get_next_chunk(self, chunk_size: int) -> list[int]:
        """
        Get the next batch of pending pages for chunk-based processing.

        Args:
            chunk_size: Maximum number of pages to return (0 = all pending)

        Returns:
            List of 1-indexed page numbers to process next.
            Returns empty list if no pages remaining.
        """
        pending = self.get_pending_pages()
        if not pending:
            return []

        # Sort to ensure consistent ordering
        pending.sort()

        if chunk_size <= 0:
            # No chunking - return all pending pages
            return pending

        # Return first chunk_size pages
        return pending[:chunk_size]

    def update_chunk_progress(self, last_page: int) -> None:
        """
        Update state timestamp after successful chunk completion.

        This provides a checkpoint for crash recovery - we know all pages
        up to and including those in the completed chunk are saved.

        Args:
            last_page: Last page number in the completed chunk
        """
        state = self.load_state_from_events()
        if state is None:
            return

        state.last_updated = datetime.utcnow().isoformat() + "Z"
        self._save_state(state)
        logger.info(f"Chunk complete (through page {last_page})")

    def assemble_output(self, include_page_markers: bool = True) -> str:
        """
        Combine all completed pages into final output.

        Args:
            include_page_markers: If True, add page number comments between pages

        Returns:
            Combined content from all completed pages
        """
        state = self.load_state_from_events()
        if state is None or not state.completed_pages:
            return ""

        pages = []
        for page_num in sorted(state.completed_pages):
            page_file = self.progress_dir / f"page_{page_num:03d}.md"
            if page_file.exists():
                content = page_file.read_text(encoding="utf-8")

                if include_page_markers:
                    marker = (
                        f"<!-- Page {page_num} -->"
                        if state.output_format == "markdown"
                        else f"% Page {page_num}"
                    )
                    pages.append(f"{marker}\n\n{content}")
                else:
                    pages.append(content)

        separator = "\n\n---\n\n"
        return separator.join(pages)

    def get_progress_summary(self) -> ProgressSummary:
        """
        Get summary of current progress.

        Returns:
            ProgressSummary with progress metrics
        """
        state = self.load_state_from_events()
        if state is None:
            return ProgressSummary(
                active=False,
                completed=0,
                failed=0,
                pending=0,
                total=0,
                completion_percentage=0.0,
            )

        pending = self.get_pending_pages()
        completed_count = len(state.completed_pages)

        return ProgressSummary(
            active=True,
            completed=completed_count,
            failed=len(state.failed_pages),
            pending=len(pending),
            total=state.total_pages,
            completion_percentage=(completed_count / state.total_pages * 100)
                                  if state.total_pages > 0 else 0.0,
            started_at=state.started_at,
            last_updated=state.last_updated,
        )

    def cleanup(self) -> None:
        """Remove progress directory after successful completion."""
        if self.progress_dir.exists():
            try:
                shutil.rmtree(self.progress_dir)
                logger.info(f"Cleaned up progress directory: {self.progress_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup progress directory: {e}")

    def _save_state(self, state: TranscriptionState) -> None:
        """Save state to JSON file."""
        try:
            self.state_file.write_text(
                json.dumps(state.to_dict(), indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            raise
