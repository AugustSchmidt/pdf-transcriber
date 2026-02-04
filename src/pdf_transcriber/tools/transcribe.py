"""transcribe_pdf tool implementation."""
from pathlib import Path
import logging

from pdf_transcriber.config import Config
from pdf_transcriber.core.pdf_processor import PDFProcessor
from pdf_transcriber.core.transcription import get_transcription_engine, clear_engine_cache
from pdf_transcriber.core.state_manager import StateManager
from pdf_transcriber.core.metadata_parser import (
    create_initial_metadata,
    generate_frontmatter
)
from pdf_transcriber.core.linter import engine as lint_engine

logger = logging.getLogger(__name__)


def register(mcp, config: Config):
    """Register transcribe_pdf tool with MCP server."""

    @mcp.tool()
    async def transcribe_pdf(
        pdf_path: str,
        quality: str = "balanced",
        mode: str = "streaming",
        output_dir: str | None = None,
        resume: bool = True,
        metadata: dict | None = None,
        lint: bool = True,
        chunk_size: int | None = None
    ) -> dict:
        """
        Convert a PDF to Markdown using vision-based transcription.

        This tool uses Marker OCR with optional LLM enhancement to transcribe
        PDF pages to Markdown. It supports resume-on-failure, quality presets,
        and rich metadata.

        Args:
            pdf_path: Path to the PDF file to transcribe
            quality: Quality preset - "fast" (100 DPI), "balanced" (150 DPI, default), or "high-quality" (200 DPI)
            mode: Processing mode - "streaming" (page-by-page, default) or "batch" (concurrent)
            output_dir: Override default output directory (default: ./transcriptions)
            resume: If True, resume from previous progress if available (default: True)
            metadata: Optional metadata dict with fields: title, authors (list), year (int), journal, arxiv_id, doi, keywords (list)
            lint: If True (default), run linting with auto-fix after transcription. Original saved as {name}.original.md
            chunk_size: Pages per processing chunk (None = auto-detect based on PDF size, 0 = disable chunking)

        Returns:
            Dictionary with keys:
            - success (bool): Whether transcription succeeded
            - output_path (str | None): Path to final output file
            - pages_transcribed (int): Number of pages successfully transcribed
            - total_pages (int): Total pages in PDF
            - partial_content (str | None): Partial transcription if failed
            - error (str | None): Error message if failed
            - metadata (dict): Final metadata applied
            - lint_results (dict | None): Linting results if lint=True

        Example:
            {
                "pdf_path": "~/Downloads/paper.pdf",
                "quality": "balanced",
                "metadata": {
                    "title": "Introduction to Algebraic Geometry",
                    "authors": ["Hartshorne"],
                    "keywords": ["algebraic geometry", "sheaves"]
                }
            }
        """
        # Validate and expand paths
        pdf_path = Path(pdf_path).expanduser().resolve()
        if not pdf_path.exists():
            return {
                "success": False,
                "output_path": None,
                "pages_transcribed": 0,
                "total_pages": 0,
                "partial_content": None,
                "error": f"PDF not found: {pdf_path}",
                "metadata": {},
                "lint_results": None
            }

        if quality not in config.quality_presets:
            return {
                "success": False,
                "output_path": None,
                "pages_transcribed": 0,
                "total_pages": 0,
                "partial_content": None,
                "error": f"Invalid quality: {quality}. Must be one of {list(config.quality_presets.keys())}",
                "metadata": {},
                "lint_results": None
            }

        # Determine output location
        paper_name = pdf_path.stem
        out_dir = Path(output_dir).expanduser() if output_dir else config.output_dir
        paper_dir = out_dir / paper_name
        paper_dir.mkdir(parents=True, exist_ok=True)

        # Get DPI from quality preset
        dpi = config.get_dpi(quality)

        logger.info(
            f"Starting transcription: {pdf_path.name} "
            f"(quality={quality}/{dpi}dpi, mode={mode})"
        )

        # Initialize state manager
        state_mgr = StateManager(out_dir, paper_name)

        # Check for existing job
        if resume and state_mgr.has_existing_job():
            state = state_mgr.load_state()
            if state:
                logger.info(
                    f"Resuming job: {len(state.completed_pages)}/{state.total_pages} "
                    f"pages done"
                )
        else:
            # Start fresh
            try:
                with PDFProcessor(str(pdf_path), dpi) as proc:
                    total_pages = proc.total_pages
            except Exception as e:
                return {
                    "success": False,
                    "output_path": None,
                    "pages_transcribed": 0,
                    "total_pages": 0,
                    "partial_content": None,
                    "error": f"Failed to open PDF: {e}",
                    "metadata": {},
                    "lint_results": None
                }

            state = state_mgr.create_job(
                str(pdf_path), total_pages, "markdown", quality
            )

        # Get transcription engine (cached to avoid reloading models)
        engine = get_transcription_engine(
            use_gpu=config.use_gpu,
            batch_size=config.marker_batch_size,
            langs=config.marker_langs,
            # LLM-enhanced OCR settings
            use_llm=config.use_llm,
            llm_service=config.llm_service,
            ollama_base_url=config.ollama_base_url,
            ollama_model=config.ollama_model
        )

        # Determine actual chunk size (auto-chunking logic)
        if chunk_size is not None:
            # Explicit chunk_size: use it (0 = disable chunking)
            actual_chunk_size = chunk_size
        elif state.total_pages > config.auto_chunk_threshold:
            # Large PDF: auto-enable chunking with default size
            actual_chunk_size = config.chunk_size
            logger.info(
                f"Auto-chunking enabled: {state.total_pages} pages > "
                f"{config.auto_chunk_threshold} threshold (chunk_size={actual_chunk_size})"
            )
        else:
            # Small PDF: process all at once
            actual_chunk_size = 0

        # Transcribe
        try:
            with PDFProcessor(str(pdf_path), dpi) as proc:
                if mode == "streaming":
                    content = await engine.transcribe_streaming(
                        proc, "markdown", state_mgr,
                        chunk_size=actual_chunk_size
                    )
                elif mode == "batch":
                    content = await engine.transcribe_batch(
                        proc, "markdown", state_mgr, config.max_concurrent_pages
                    )
                else:
                    return {
                        "success": False,
                        "output_path": None,
                        "pages_transcribed": 0,
                        "total_pages": state.total_pages,
                        "partial_content": None,
                        "error": f"Invalid mode: {mode}. Must be 'streaming' or 'batch'",
                        "metadata": {},
                        "lint_results": None
                    }

        except Exception as e:
            # Return partial result on failure
            partial = state_mgr.assemble_output()
            summary = state_mgr.get_progress_summary()

            logger.error(f"Transcription failed: {e}")

            return {
                "success": False,
                "output_path": None,
                "pages_transcribed": summary["completed"],
                "total_pages": summary["total"],
                "partial_content": partial if partial else None,
                "error": f"Transcription failed: {e}",
                "metadata": metadata or {},
                "lint_results": None
            }

        # Build metadata
        meta_dict = metadata or {}
        paper_title = meta_dict.get("title", paper_name)
        paper_authors = meta_dict.get("authors", [])
        paper_year = meta_dict.get("year")

        paper_meta = create_initial_metadata(
            title=paper_title,
            pdf_source=pdf_path,
            total_pages=state.total_pages,
            output_format="markdown",
            quality=quality,
            authors=paper_authors,
            year=paper_year,
            journal=meta_dict.get("journal"),
            arxiv_id=meta_dict.get("arxiv_id"),
            doi=meta_dict.get("doi"),
            keywords=meta_dict.get("keywords", [])
        )

        # Update transcribed_pages count
        summary = state_mgr.get_progress_summary()
        paper_meta.transcribed_pages = summary["completed"]

        # Write final output with frontmatter
        output_path = paper_dir / f"{paper_name}.md"

        try:
            final_content = generate_frontmatter(paper_meta) + "\n" + content
            output_path.write_text(final_content, encoding="utf-8")
        except Exception as e:
            return {
                "success": False,
                "output_path": None,
                "pages_transcribed": summary["completed"],
                "total_pages": summary["total"],
                "partial_content": content,
                "error": f"Failed to write output file: {e}",
                "metadata": paper_meta.to_dict(),
                "lint_results": None
            }

        # Cleanup progress files on success
        if summary["completed"] == summary["total"]:
            state_mgr.cleanup()

        logger.info(
            f"Transcription complete: {output_path} "
            f"({summary['completed']}/{summary['total']} pages)"
        )

        # Run linting if enabled
        lint_results = None
        if lint:
            try:
                # Save original (non-linted) version for manual review
                original_path = paper_dir / f"{paper_name}.original.md"
                original_path.write_text(final_content, encoding="utf-8")
                logger.info(f"Saved original (pre-lint) to: {original_path}")

                # Run linter with auto-fix
                lint_report = await lint_engine.lint_file(output_path, fix=True)
                lint_results = {
                    "total_issues": lint_report.total_issues,
                    "auto_fixed": len(lint_report.fixed),
                    "warnings": lint_report.warnings,
                    "fixed_rules": lint_report.fixed,
                    "original_path": str(original_path)
                }

                logger.info(
                    f"Linting: {lint_report.total_issues} issues found, "
                    f"{len(lint_report.fixed)} auto-fixed. "
                    f"Original saved to {original_path.name}"
                )

            except Exception as e:
                logger.warning(f"Linting failed (file still saved): {e}")
                lint_results = {"error": str(e)}

        return {
            "success": True,
            "output_path": str(output_path),
            "pages_transcribed": summary["completed"],
            "total_pages": summary["total"],
            "partial_content": None,
            "error": None,
            "metadata": {
                "title": paper_meta.title,
                "authors": paper_meta.authors,
                "keywords": paper_meta.keywords,
                "year": paper_meta.year
            },
            "lint_results": lint_results
        }

    @mcp.tool()
    async def clear_transcription_cache() -> dict:
        """
        Clear the cached transcription engine to free memory.

        The transcription engine caches Marker OCR models (~2GB) to speed up
        sequential transcriptions. Call this tool when you're done transcribing
        to reclaim memory.

        Returns:
            Dictionary with:
            - cleared (int): Number of cached engines that were cleared
            - message (str): Status message
        """
        count = clear_engine_cache()

        if count > 0:
            message = f"Cleared {count} cached engine(s), freeing ~2GB memory"
            logger.info(message)
        else:
            message = "No cached engines to clear"

        return {
            "cleared": count,
            "message": message
        }
