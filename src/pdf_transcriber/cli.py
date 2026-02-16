"""CLI for pdf-transcriber.

Provides direct terminal access to transcription functionality without MCP.
"""
import argparse
import asyncio
import sys
from pathlib import Path

from pdf_transcriber import __version__
from pdf_transcriber.config import Config


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="pdf-transcriber-cli",
        description="Convert math-heavy PDFs to Markdown using Marker OCR"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # transcribe command
    t = subparsers.add_parser("transcribe", help="Transcribe a PDF to Markdown")
    t.add_argument("pdf_path", type=Path, help="Path to PDF file")
    t.add_argument("-o", "--output", type=Path, help="Output directory")
    t.add_argument(
        "-q", "--quality",
        choices=["fast", "balanced", "high-quality"],
        default="balanced",
        help="Quality preset (default: balanced)"
    )
    t.add_argument(
        "--no-llm", action="store_true",
        help="Disable LLM enhancement (faster, less accurate)"
    )
    t.add_argument(
        "--no-lint", action="store_true",
        help="Skip post-transcription linting"
    )
    t.add_argument(
        "--no-resume", action="store_true",
        help="Don't resume from previous progress"
    )

    # check command
    subparsers.add_parser("check", help="Health check (config, paths, Ollama)")

    # install-skill command
    s = subparsers.add_parser("install-skill", help="Install Claude Code skill")
    s.add_argument(
        "--force", action="store_true",
        help="Overwrite existing skill"
    )

    # cleanup command
    c = subparsers.add_parser("cleanup", help="Clean up telemetry for completed jobs")
    c.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting"
    )
    c.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed reasoning for each file"
    )
    c.add_argument(
        "--telemetry-dir",
        type=Path,
        help="Central telemetry directory (default: ~/.cache/pdf-transcriber/telemetry)"
    )

    # tui command
    tui = subparsers.add_parser("tui", help="Launch TUI dashboard for monitoring jobs")
    tui.add_argument(
        "-o", "--output", type=Path,
        help="Output directory to monitor (default: from config)"
    )
    tui.add_argument(
        "--refresh", type=int, default=5,
        help="Refresh interval in seconds (default: 5)"
    )
    tui.add_argument(
        "--recent-limit", type=int, default=50,
        help="Maximum recent completed jobs to show (default: 50)"
    )
    tui.add_argument(
        "--stale-threshold", type=int, default=120,
        help="Seconds without heartbeat before job is stalled (default: 120)"
    )

    args = parser.parse_args()

    if args.command == "transcribe":
        asyncio.run(transcribe_command(args))
    elif args.command == "check":
        check_command()
    elif args.command == "install-skill":
        install_skill_command(args)
    elif args.command == "cleanup":
        cleanup_command(args)
    elif args.command == "tui":
        tui_command(args)


async def transcribe_command(args):
    """Execute the transcribe command."""
    import os

    # Apply CLI overrides to environment
    if args.no_llm:
        os.environ["PDF_TRANSCRIBER_USE_LLM"] = "false"

    # Load config after env overrides
    config = Config.load()

    # Validate PDF exists
    pdf_path = args.pdf_path.expanduser().resolve()
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    # Import transcription components
    from pdf_transcriber.core.pdf_processor import PDFProcessor
    from pdf_transcriber.core.engine_cache import get_transcription_engine
    from pdf_transcriber.core.state_manager import StateManager
    from pdf_transcriber.core.metadata_parser import (
        create_initial_metadata,
        generate_frontmatter
    )
    from pdf_transcriber.core.linter import engine as lint_engine

    # Determine output location
    paper_name = pdf_path.stem
    out_dir = args.output.expanduser() if args.output else config.output_dir
    paper_dir = out_dir / paper_name
    paper_dir.mkdir(parents=True, exist_ok=True)

    dpi = config.get_dpi(args.quality)

    print(f"Transcribing: {pdf_path.name}")
    print(f"  Quality: {args.quality} ({dpi} DPI)")
    print(f"  Output: {paper_dir}")
    print(f"  LLM: {'enabled' if config.use_llm else 'disabled'}")
    print()

    # Initialize state manager
    state_mgr = StateManager(out_dir, paper_name)

    # Check for existing job
    resume = not args.no_resume
    state = None
    if resume and state_mgr.has_existing_job():
        state = state_mgr.load_state()
        if state:
            print(f"Resuming: {len(state.completed_pages)}/{state.total_pages} pages done")

    if not state:
        try:
            with PDFProcessor(str(pdf_path), dpi) as proc:
                total_pages = proc.total_pages
        except Exception as e:
            print(f"Error: Failed to open PDF: {e}", file=sys.stderr)
            sys.exit(1)

        state = state_mgr.create_job(str(pdf_path), total_pages, "markdown", args.quality)
        print(f"Processing {total_pages} pages...")

    # Get transcription engine
    engine = get_transcription_engine(
        use_gpu=config.use_gpu,
        batch_size=config.marker_batch_size,
        langs=config.marker_langs,
        use_llm=config.use_llm,
        llm_service=config.llm_service,
        ollama_base_url=config.ollama_base_url,
        ollama_model=config.ollama_model,
        openai_base_url=config.openai_base_url,
        openai_api_key=config.openai_api_key,
        openai_model=config.openai_model,
        disable_table_extraction=config.disable_table_extraction
    )

    # Determine chunk size
    if state.total_pages > config.auto_chunk_threshold:
        chunk_size = config.chunk_size
        print(f"  Chunking: {chunk_size} pages/chunk (auto-enabled)")
    else:
        chunk_size = 0

    # Initialize event emitter for telemetry
    from pdf_transcriber.events import EventEmitter
    emitter = EventEmitter(job_id=paper_name, output_dir=out_dir / paper_name)

    # Use job context manager: guarantees job_completed + stop_heartbeat on exit
    async with emitter.job(
        pdf_path=str(pdf_path),
        output_dir=str(paper_dir),
        total_pages=state.total_pages,
        quality=args.quality,
        mode="streaming",
        metadata={
            "chunk_size": chunk_size if chunk_size > 0 else state.total_pages,
            "llm_enabled": config.use_llm,
        },
    ) as progress:

        # Transcribe
        try:
            with PDFProcessor(str(pdf_path), dpi) as proc:
                content = await engine.transcribe_streaming(
                    proc, "markdown", state_mgr,
                    chunk_size=chunk_size,
                    event_emitter=emitter
                )
        except Exception as e:
            summary = state_mgr.get_progress_summary()
            progress.pages_completed = summary.completed
            progress.pages_failed = summary.total - summary.completed
            print(f"\nError: Transcription failed: {e}", file=sys.stderr)
            print(f"Progress saved: {summary.completed}/{summary.total} pages")
            print("Run again with same PDF to resume")
            sys.exit(1)

        # Build metadata and finalize output
        summary = state_mgr.get_progress_summary()
        progress.pages_completed = summary.completed
        progress.pages_failed = summary.failed

        paper_meta = create_initial_metadata(
            title=paper_name,
            pdf_source=pdf_path,
            total_pages=state.total_pages,
            output_format="markdown",
            quality=args.quality,
        )

        paper_meta.transcribed_pages = summary.completed

        # Write output
        output_path = paper_dir / f"{paper_name}.md"
        final_content = generate_frontmatter(paper_meta) + "\n" + content
        output_path.write_text(final_content, encoding="utf-8")

        # Cleanup on success
        if summary.completed == summary.total:
            state_mgr.cleanup()

        print(f"\nTranscribed {summary.completed}/{summary.total} pages")

        # Run linting
        if not args.no_lint:
            print("Linting...")
            original_path = paper_dir / f"{paper_name}.original.md"
            original_path.write_text(final_content, encoding="utf-8")

            try:
                lint_report = await lint_engine.lint_file(output_path, fix=True)
                print(f"  {lint_report.total_issues} issues found, {len(lint_report.fixed)} auto-fixed")
            except Exception as e:
                print(f"  Warning: Linting failed: {e}")

        print(f"\nOutput: {output_path}")


def check_command():
    """Execute the check command."""
    print(f"PDF Transcriber v{__version__}")
    print("=" * 40)

    # Configuration
    config = Config.load()
    print("\nConfiguration:")
    print(f"  Output directory: {config.output_dir}")
    print(f"  Default quality: {config.default_quality} ({config.get_dpi()}dpi)")
    print(f"  GPU: {config.use_gpu}")
    print(f"  LLM enhanced: {config.use_llm}")

    # Output directory
    print("\nOutput directory:")
    if config.output_dir.exists():
        paper_count = sum(
            1 for d in config.output_dir.iterdir()
            if d.is_dir() and any(d.glob("*.md"))
        )
        print(f"  Status: exists ({paper_count} papers)")
    else:
        print("  Status: will be created on first transcription")

    # Ollama (if LLM enabled)
    if config.use_llm:
        print("\nOllama connection:")
        try:
            import urllib.request
            import json

            req = urllib.request.Request(
                f"{config.ollama_base_url}/api/tags",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]

                if config.ollama_model in models:
                    print("  Status: connected")
                    print(f"  Model: {config.ollama_model} (available)")
                else:
                    print("  Status: connected")
                    print(f"  Model: {config.ollama_model} (NOT INSTALLED)")
                    print(f"  Run: ollama pull {config.ollama_model}")

        except Exception as e:
            print("  Status: NOT CONNECTED")
            print(f"  Error: {e}")
            print(f"  URL: {config.ollama_base_url}")
            print("  Run: ollama serve")

    # Available tools
    print("\nMCP tools:")
    print("  - transcribe_pdf")
    print("  - clear_transcription_cache")
    print("  - lint_paper")

    print("\n" + "=" * 40)
    print("Ready to transcribe!")


def install_skill_command(args):
    """Install the Claude Code skill."""
    import importlib.resources as resources

    skill_dir = Path.home() / ".claude" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    dest = skill_dir / "transcribe.md"

    if dest.exists() and not args.force:
        print(f"Skill already exists: {dest}")
        print("Use --force to overwrite")
        sys.exit(1)

    # Copy from package resources
    try:
        skill_content = resources.files("pdf_transcriber.skills").joinpath("transcribe.md").read_text()
        dest.write_text(skill_content)
    except Exception as e:
        print(f"Error: Failed to read skill from package: {e}", file=sys.stderr)
        print("The skill file may not be included in this installation.")
        sys.exit(1)

    print(f"Installed skill: {dest}")
    print("Restart Claude Code to load the skill")
    print("Usage: /transcribe ~/path/to/paper.pdf")


def tui_command(args):
    """Execute the TUI dashboard command."""
    from pdf_transcriber.tui import run_dashboard

    # Determine output directory
    output_dir = None
    if args.output:
        output_dir = args.output.expanduser().resolve()

    print("Starting PDF Transcription Monitor...")
    print("Press 'q' to quit, 'r' to refresh, 'j/k' to navigate, 'Enter' for details")
    print()

    try:
        run_dashboard(
            output_dir=output_dir,
            refresh_interval=args.refresh,
            recent_limit=args.recent_limit,
            stale_threshold=args.stale_threshold
        )
    except KeyboardInterrupt:
        print("\n\nStopped monitoring.")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


def cleanup_command(args):
    """Execute the cleanup command."""
    from pdf_transcriber.cleanup import cleanup_telemetry, print_summary

    try:
        result = cleanup_telemetry(
            central_dir=args.telemetry_dir,
            dry_run=args.dry_run,
            verbose=args.verbose
        )

        # Print summary if not in verbose mode
        if not args.verbose:
            print_summary(result, dry_run=args.dry_run)
        else:
            # In verbose mode, just print final stats
            print("=" * 60)
            print(f"Deleted: {result.logs_deleted}, Kept: {result.logs_kept}, Errors: {len(result.errors)}")

        # Exit with error code if there were errors
        if result.errors:
            sys.exit(1)

    except Exception as e:
        print(f"Error: Cleanup failed: {e}", file=sys.stderr)
        sys.exit(1)


def tui_main():
    """Dedicated entry point for pdf-transcriber-tui command."""
    from pdf_transcriber.tui import run_dashboard

    parser = argparse.ArgumentParser(
        prog="pdf-transcriber-tui",
        description="Live TUI dashboard for monitoring PDF transcription jobs"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        help="Output directory to monitor (default: from config)"
    )
    parser.add_argument(
        "--refresh", type=int, default=5,
        help="Refresh interval in seconds (default: 5)"
    )
    parser.add_argument(
        "--recent-limit", type=int, default=50,
        help="Maximum recent completed jobs to show (default: 50)"
    )
    parser.add_argument(
        "--stale-threshold", type=int, default=120,
        help="Seconds without heartbeat before job is stalled (default: 120)"
    )

    args = parser.parse_args()

    # Determine output directory
    output_dir = None
    if args.output:
        output_dir = args.output.expanduser().resolve()

    print("Starting PDF Transcription Monitor...")
    print("Press 'q' to quit, 'r' to refresh, 'j/k' to navigate, 'Enter' for details")
    print()

    try:
        run_dashboard(
            output_dir=output_dir,
            refresh_interval=args.refresh,
            recent_limit=args.recent_limit,
            stale_threshold=args.stale_threshold
        )
    except KeyboardInterrupt:
        print("\n\nStopped monitoring.")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
