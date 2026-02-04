"""Resume-capable state management for PDF transcription jobs."""
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json
import logging
import shutil

logger = logging.getLogger(__name__)


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

    def has_existing_job(self) -> bool:
        """Check if a resumable job exists."""
        return self.state_file.exists()

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
        state = self.load_state()
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
        state = self.load_state()
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

        Returns:
            List of page numbers (1-indexed) that haven't been completed or failed
        """
        state = self.load_state()
        if state is None:
            return []

        all_done = set(state.completed_pages) | set(state.failed_pages)
        pending = [
            page_num
            for page_num in range(1, state.total_pages + 1)
            if page_num not in all_done
        ]

        return pending

    def get_failed_pages(self) -> list[int]:
        """Get list of failed pages for retry."""
        state = self.load_state()
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
        state = self.load_state()
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
        state = self.load_state()
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

    def get_progress_summary(self) -> dict:
        """
        Get summary of current progress.

        Returns:
            Dictionary with progress metrics
        """
        state = self.load_state()
        if state is None:
            return {
                "active": False,
                "completed": 0,
                "failed": 0,
                "pending": 0,
                "total": 0,
                "completion_percentage": 0.0
            }

        pending = self.get_pending_pages()
        completed_count = len(state.completed_pages)

        return {
            "active": True,
            "completed": completed_count,
            "failed": len(state.failed_pages),
            "pending": len(pending),
            "total": state.total_pages,
            "completion_percentage": (completed_count / state.total_pages * 100)
                                     if state.total_pages > 0 else 0.0,
            "started_at": state.started_at,
            "last_updated": state.last_updated
        }

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
