"""Live TUI dashboard for monitoring PDF transcription jobs."""
from datetime import datetime, timezone
from pathlib import Path
import logging
import sys

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from pdf_transcriber.tui.discovery import discover_jobs, JobInfo
from pdf_transcriber.tui.metrics import (
    calculate_metrics,
    format_elapsed_time,
    format_eta,
    format_completion_time
)
from pdf_transcriber.events import read_event_log_typed
from pdf_transcriber.event_types import (
    ErrorEvent,
    PageCompletedEvent,
    HeartbeatEvent,
    JobStartedEvent,
    JobCompletedEvent,
)

logger = logging.getLogger(__name__)


class DashboardView:
    """Main dashboard view for monitoring jobs."""

    def __init__(
        self,
        output_dir: Path,
        refresh_interval: int = 5,
        recent_limit: int = 50,
        stale_threshold: int = 120
    ):
        """
        Initialize dashboard.

        Args:
            output_dir: Root output directory to scan for jobs
            refresh_interval: Seconds between refreshes
            recent_limit: Maximum recent completed jobs to show
            stale_threshold: Seconds without heartbeat before job is stalled
        """
        self.output_dir = output_dir
        self.refresh_interval = refresh_interval
        self.recent_limit = recent_limit
        self.stale_threshold = stale_threshold

        self.console = Console()
        self.selected_index = 0
        self.viewing_detail = False
        self.jobs: list[JobInfo] = []

    def render(self) -> Layout:
        """Render the current view."""
        # Discover jobs
        self.jobs = discover_jobs(self.output_dir, self.stale_threshold)

        if self.viewing_detail and self.jobs and self.selected_index < len(self.jobs):
            return self._render_detail_view(self.jobs[self.selected_index])
        else:
            return self._render_dashboard_view()

    def _render_dashboard_view(self) -> Layout:
        """Render main dashboard view."""
        layout = Layout()

        # Header
        now = datetime.now().strftime("%H:%M:%S")
        header = Panel(
            Text(f"PDF Transcription Monitor                  Updated: {now}", justify="left"),
            style="bold #5f8787"  # Muted teal
        )

        # Active jobs
        active_jobs = [j for j in self.jobs if j.is_active]
        recent_jobs = [j for j in self.jobs if not j.is_active][:self.recent_limit]

        if not active_jobs and not recent_jobs:
            # Empty state
            content = self._render_empty_state()
        else:
            # Active jobs section
            active_section = self._render_active_jobs(active_jobs)

            # Recent jobs section
            recent_section = self._render_recent_jobs(recent_jobs)

            # Combine sections
            content = Table.grid(padding=(0, 0))
            content.add_column()
            content.add_row(active_section)
            if recent_jobs:
                content.add_row("")  # Spacer
                content.add_row(recent_section)

        # Footer
        footer = Panel(
            "j/k:navigate │ Enter:details │ r:refresh │ q:quit",
            style="dim"
        )

        # Combine layout
        layout.split_column(
            Layout(header, size=3),
            Layout(Panel(content)),
            Layout(footer, size=3)
        )

        return layout

    def _render_active_jobs(self, jobs: list[JobInfo]) -> Table:
        """Render active jobs section."""
        table = Table.grid(padding=(0, 0))  # Remove horizontal padding
        table.add_column(style="bold")

        if not jobs:
            return table

        table.add_row(Text("Active Jobs", style="bold #ddeecc"))  # Pale mint
        table.add_row("")  # Spacer

        for i, job in enumerate(jobs):
            # Highlight selected
            is_selected = i == self.selected_index and not self.viewing_detail
            prefix = "> " if is_selected else "  "

            # Job name with stalled indicator
            job_name = Text(prefix + job.job_id)
            if job.is_stalled:
                job_name.append(" [STALLED]", style="bold #5f8787")  # Muted teal warning

            table.add_row(job_name)

            # Progress bar
            metrics = calculate_metrics(job.event_log_path)
            if metrics:
                progress_bar = self._create_progress_bar(
                    metrics.current_page,
                    metrics.total_pages,
                    metrics.progress_percent
                )
                # Add as Text object with indent
                row = Text("  ")
                row.append_text(progress_bar)
                table.add_row(row)

                # Stats line
                error_text = f"{metrics.current_page}/{metrics.total_pages} pages"
                stats_parts = [
                    f"{metrics.velocity_pages_per_hour:.1f} pg/hr",
                    f"ETA: {format_eta(metrics.eta_hours)}",
                    f"Elapsed: {format_elapsed_time(metrics.elapsed_time)}"
                ]

                if job.error_count > 0:
                    stats_parts.append(f"{job.error_count} errors")
                elif job.warning_count > 0:
                    stats_parts.append(f"{job.warning_count} warnings")
                else:
                    stats_parts.append("0 errors")

                stats = " | ".join(stats_parts)  # Use regular pipe instead of box-drawing character
                table.add_row(f"  {error_text}")
                table.add_row(f"  {stats}")

                # Last heartbeat for stalled jobs
                if job.is_stalled and job.last_heartbeat:
                    now = datetime.now(timezone.utc)
                    seconds_ago = (now - job.last_heartbeat).total_seconds()
                    minutes_ago = int(seconds_ago / 60)
                    table.add_row(
                        Text(f"  Last heartbeat: {minutes_ago}m {int(seconds_ago % 60)}s ago",
                             style="dim #888888")  # Dim gray
                    )

            table.add_row("")  # Spacer between jobs

        return table

    def _render_recent_jobs(self, jobs: list[JobInfo]) -> Table:
        """Render recent completed jobs section."""
        table = Table.grid(padding=(0, 0))  # Remove horizontal padding
        table.add_column()

        if not jobs:
            return table

        table.add_row(Text(f"Recent (last {self.recent_limit} completed)", style="bold #5f8787"))  # Muted teal
        table.add_row("")  # Spacer

        for job in jobs[:5]:  # Show top 5 recent
            # Calculate time since completion
            time_ago = "unknown"
            if job.completed_at:
                now = datetime.now(timezone.utc)
                delta = now - job.completed_at
                hours = delta.total_seconds() / 3600

                if hours < 1:
                    minutes = int(delta.total_seconds() / 60)
                    time_ago = f"{minutes}m ago"
                elif hours < 24:
                    time_ago = f"{int(hours)}h ago"
                else:
                    days = int(hours / 24)
                    time_ago = f"{days}d ago"

            # Format line
            error_info = ""
            if job.error_count > 0:
                error_info = f", {job.error_count} errors"
            elif job.warning_count > 0:
                error_info = f", {job.warning_count} warnings"

            pages_info = f"{job.total_pages or 0} pages" if job.total_pages else "unknown pages"

            line = f"  ✓ {job.job_id} (completed {time_ago}, {pages_info}{error_info})"
            table.add_row(Text(line, style="dim #99bbaa"))  # Dim desaturated teal

        return table

    def _render_empty_state(self) -> Table:
        """Render empty state when no jobs found."""
        table = Table.grid(padding=(1, 0))
        table.add_column(justify="center")

        table.add_row("")
        table.add_row(Text("No active transcriptions", style="bold #99bbaa"))  # Desaturated teal
        table.add_row("")
        table.add_row("To start a transcription:")
        table.add_row("  pdf-transcriber path/to/file.pdf")
        table.add_row("")
        table.add_row("Or use the MCP tool:")
        table.add_row("  mcp__pdf-transcriber__transcribe_pdf")
        table.add_row("")

        return table

    def _render_detail_view(self, job: JobInfo) -> Layout:
        """Render detail view for a specific job."""
        layout = Layout()

        # Header
        now = datetime.now().strftime("%H:%M:%S")
        status = "[STALLED]" if job.is_stalled else ("[ACTIVE]" if job.is_active else "[COMPLETED]")
        header = Panel(
            Text(f"{job.job_id} {status}                  Updated: {now}", justify="left"),
            style="bold #5f8787"  # Muted teal
        )

        # Content sections
        content = Table.grid(padding=(0, 1))
        content.add_column()

        # Progress section
        metrics = calculate_metrics(job.event_log_path)
        if metrics:
            content.add_row(Text("Progress", style="bold"))
            progress_bar = self._create_progress_bar(
                metrics.current_page,
                metrics.total_pages,
                metrics.progress_percent
            )
            content.add_row(f"  {progress_bar}")
            content.add_row("")

            # Metrics section
            content.add_row(Text("Metrics", style="bold"))
            content.add_row(f"  Velocity (50-page window): {metrics.velocity_pages_per_hour:.1f} pages/hour")
            content.add_row(f"  ETA: {format_eta(metrics.eta_hours)} (completion around {format_completion_time(metrics.completion_time)})")
            content.add_row(f"  Elapsed: {format_elapsed_time(metrics.elapsed_time)}")
            content.add_row(f"  CPU: {metrics.cpu_percent:.1f}% │ Memory: {metrics.memory_mb/1024:.1f} GB")
            content.add_row("")

        # Metadata section
        if job.metadata:
            content.add_row(Text("Metadata", style="bold"))
            if title := job.metadata.get("title"):
                content.add_row(f"  Title: {title}")
            if authors := job.metadata.get("authors"):
                authors_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
                content.add_row(f"  Authors: {authors_str}")
            content.add_row(f"  Quality: {job.quality} │ Mode: {job.mode}")
            content.add_row("")

        # Errors section
        content.add_row(Text(f"Errors ({job.error_count})", style="bold"))
        if job.error_count > 0 or job.warning_count > 0:
            # Read error events from log
            all_events = read_event_log_typed(job.event_log_path)
            error_events = [e for e in all_events if isinstance(e, ErrorEvent)][-5:]  # Last 5

            if error_events:
                for err in error_events:
                    style = "#5f8787" if err.severity == "error" else "#99bbaa"
                    page_info = f"page {err.page_number}" if err.page_number else "general"
                    content.add_row(Text(
                        f"  [{err.severity}] {err.error_type} ({page_info}): {err.error_message}",
                        style=style
                    ))
            else:
                content.add_row(Text(f"  {job.warning_count} warnings", style="#99bbaa"))
        else:
            content.add_row("  No errors")
        content.add_row("")

        # Recent events section
        content.add_row(Text("Recent Events", style="bold"))
        all_events = read_event_log_typed(job.event_log_path)
        recent_events = all_events[-10:]  # Last 10 events

        for event in reversed(recent_events):  # Most recent first
            timestamp = event.timestamp
            time_str = timestamp.split("T")[1][:8] if "T" in timestamp else timestamp

            if isinstance(event, PageCompletedEvent):
                duration = event.duration_ms / 1000
                content.add_row(f"  {time_str} │ page_completed │ page {event.page_number}, {duration:.1f}s")

            elif isinstance(event, HeartbeatEvent):
                pages_since = event.pages_completed_since_last_heartbeat
                content.add_row(f"  {time_str} │ heartbeat      │ page {event.current_page}, velocity {pages_since} pg/30s")

            elif isinstance(event, (JobStartedEvent, JobCompletedEvent)):
                content.add_row(f"  {time_str} │ {event.event_type:14} │")

        # Footer
        footer = Panel(
            "Esc:back │ r:refresh │ q:quit",
            style="dim"
        )

        # Combine layout
        layout.split_column(
            Layout(header, size=3),
            Layout(Panel(content)),
            Layout(footer, size=3)
        )

        return layout

    def _create_progress_bar(self, current: int, total: int, percent: float) -> Text:
        """Create a text-based progress bar as a Text object (don't render to string)."""
        # Build progress bar manually using Rich styling
        bar_width = 30
        filled = int(bar_width * percent / 100)
        empty = bar_width - filled

        # Build as a single Text object
        result = Text()
        result.append(f"{percent:>4.1f}%", style="#5f8787")
        result.append(" ")
        result.append("━" * filled, style="#5f8787")
        result.append("━" * empty, style="dim")
        result.append(" ")
        result.append(f"({current}/{total} pages)")

        return result

    def handle_key(self, key: str) -> bool:
        """
        Handle keyboard input.

        Args:
            key: Key pressed

        Returns:
            True to continue, False to quit
        """
        if key in ("q", "Q"):
            return False

        elif key in ("r", "R"):
            # Force refresh (will happen on next render)
            pass

        elif key in ("j", "J", "down"):
            if not self.viewing_detail:
                active_count = len([j for j in self.jobs if j.is_active])
                if active_count > 0:
                    self.selected_index = (self.selected_index + 1) % active_count

        elif key in ("k", "K", "up"):
            if not self.viewing_detail:
                active_count = len([j for j in self.jobs if j.is_active])
                if active_count > 0:
                    self.selected_index = (self.selected_index - 1) % active_count

        elif key == "enter":
            if not self.viewing_detail and self.jobs:
                active_jobs = [j for j in self.jobs if j.is_active]
                if self.selected_index < len(active_jobs):
                    self.viewing_detail = True

        elif key == "escape":
            if self.viewing_detail:
                self.viewing_detail = False

        return True


def run_dashboard(
    output_dir: Path | None = None,
    refresh_interval: int = 5,
    recent_limit: int = 50,
    stale_threshold: int = 120
):
    """
    Run the live TUI dashboard.

    Args:
        output_dir: Root output directory to scan (default: from config)
        refresh_interval: Seconds between refreshes
        recent_limit: Maximum recent completed jobs to show
        stale_threshold: Seconds without heartbeat before job is stalled
    """
    # Load config if output_dir not provided
    if output_dir is None:
        from pdf_transcriber.config import Config
        config = Config.load()
        output_dir = config.output_dir

    # Create dashboard
    dashboard = DashboardView(
        output_dir,
        refresh_interval,
        recent_limit,
        stale_threshold
    )

    # Run live display with keyboard handling
    try:
        with Live(
            dashboard.render(),
            refresh_per_second=1.0 / refresh_interval,
            console=dashboard.console,
            screen=True
        ) as live:
            import sys
            import tty
            import termios

            # Set up terminal for raw key input
            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())

                while True:
                    # Update display
                    live.update(dashboard.render())

                    # Check for key input (non-blocking)
                    import select
                    if select.select([sys.stdin], [], [], refresh_interval)[0]:
                        key = sys.stdin.read(1)

                        # Handle special keys
                        if key == '\x1b':  # ESC or arrow key
                            next_chars = sys.stdin.read(2)
                            if next_chars == '[A':
                                key = 'up'
                            elif next_chars == '[B':
                                key = 'down'
                            else:
                                key = 'escape'
                        elif key == '\r' or key == '\n':
                            key = 'enter'

                        # Handle key
                        if not dashboard.handle_key(key):
                            break

            finally:
                # Restore terminal settings
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    except KeyboardInterrupt:
        pass
