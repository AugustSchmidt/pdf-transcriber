"""Marker OCR transcription with streaming and batch modes."""
from dataclasses import dataclass
import logging
import asyncio
import re
from typing import Callable, Awaitable
from pathlib import Path

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict

from pdf_transcriber.core.pdf_processor import PDFProcessor
from pdf_transcriber.core.state_manager import StateManager

logger = logging.getLogger(__name__)

# ============================================================================
# Engine Cache - Avoids reloading Marker models on each transcription
# ============================================================================

_engine_cache: dict[str, "TranscriptionEngine"] = {}


def _make_cache_key(
    use_gpu: bool,
    use_llm: bool,
    llm_service: str,
    ollama_base_url: str,
    ollama_model: str,
    langs: tuple[str, ...]
) -> str:
    """Generate cache key from engine configuration."""
    return f"{use_gpu}|{use_llm}|{llm_service}|{ollama_base_url}|{ollama_model}|{langs}"


def get_transcription_engine(
    use_gpu: bool = False,
    batch_size: int = 1,
    langs: list[str] | None = None,
    use_llm: bool = False,
    llm_service: str = "marker.services.ollama.OllamaService",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "qwen2.5vl:3b"
) -> "TranscriptionEngine":
    """
    Get or create a TranscriptionEngine with caching.

    This factory function caches engines by their configuration to avoid
    reloading Marker models (~5-15 seconds) on each transcription call.

    Args:
        use_gpu: Whether to use GPU acceleration
        batch_size: Number of pages per batch (not currently used)
        langs: Languages for OCR (default: ["English"])
        use_llm: Enable Marker's LLM-enhanced OCR mode
        llm_service: LLM service class path
        ollama_base_url: Ollama server URL
        ollama_model: Ollama vision model name

    Returns:
        Cached or newly created TranscriptionEngine
    """
    langs_tuple = tuple(langs or ["English"])
    cache_key = _make_cache_key(
        use_gpu, use_llm, llm_service, ollama_base_url, ollama_model, langs_tuple
    )

    if cache_key in _engine_cache:
        logger.info(f"Using cached TranscriptionEngine (LLM: {ollama_model if use_llm else 'disabled'})")
        return _engine_cache[cache_key]

    logger.info(f"Creating new TranscriptionEngine (will be cached for reuse)")
    engine = TranscriptionEngine(
        use_gpu=use_gpu,
        batch_size=batch_size,
        langs=list(langs_tuple),
        use_llm=use_llm,
        llm_service=llm_service,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model
    )
    _engine_cache[cache_key] = engine

    return engine


def clear_engine_cache() -> int:
    """
    Clear the engine cache to free memory.

    Returns:
        Number of engines that were cached
    """
    count = len(_engine_cache)
    _engine_cache.clear()  # Use .clear() to mutate in-place (avoids rebinding issues)
    if count > 0:
        logger.info(f"Cleared {count} cached TranscriptionEngine(s)")
    return count


@dataclass
class TranscriptionResult:
    """Result from transcribing a single page."""
    content: str
    tokens_used: int  # Always 0 for local OCR
    success: bool
    error: str | None = None


class TranscriptionEngine:
    """
    Marker OCR transcription engine.

    Orchestrates local OCR transcription of PDF pages to LaTeX/Markdown.
    """

    def __init__(
        self,
        use_gpu: bool = False,
        batch_size: int = 1,
        langs: list[str] | None = None,
        # LLM-enhanced OCR parameters
        use_llm: bool = False,
        llm_service: str = "marker.services.ollama.OllamaService",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "qwen2.5vl:3b"
    ):
        """
        Initialize transcription engine.

        Args:
            use_gpu: Whether to use GPU acceleration
            batch_size: Number of pages per batch (not currently used)
            langs: Languages for OCR (default: ["English"])
            use_llm: Enable Marker's LLM-enhanced OCR mode
            llm_service: LLM service class path (e.g., marker.services.ollama.OllamaService)
            ollama_base_url: Ollama server URL
            ollama_model: Ollama vision model name (e.g., qwen2.5vl:3b, qwen2.5vl:7b)
        """
        self.use_gpu = use_gpu
        self.batch_size = batch_size
        self.langs = langs or ["English"]

        # LLM settings
        self.use_llm = use_llm
        self.llm_service = llm_service
        self.ollama_base_url = ollama_base_url
        self.ollama_model = ollama_model

        # Load Marker models (heavy operation - do once)
        llm_status = f", LLM: {ollama_model}" if use_llm else ""
        logger.info(f"Loading Marker OCR models (GPU: {use_gpu}{llm_status})...")
        self.models = create_model_dict()
        logger.info(f"✓ Marker models loaded successfully")

    def get_system_prompt(self, output_format: str) -> str:
        """
        Note: Marker doesn't use system prompts like Claude.
        This method is kept for API compatibility but returns empty string.
        Output format is controlled by Marker's internal settings.
        """
        return ""

    async def transcribe_page(
        self,
        image_base64: str,
        media_type: str,
        output_format: str,
        page_num: int,
        total_pages: int
    ) -> TranscriptionResult:
        """
        Transcribe a single page using Marker OCR.

        Note: This method exists for API compatibility but is not the primary
        way to use Marker. Use transcribe_streaming() instead which processes
        the full PDF more efficiently.

        Args:
            image_base64: Base64-encoded PNG image (from PDFProcessor)
            media_type: MIME type (unused for Marker)
            output_format: "markdown" or "latex"
            page_num: Current page number
            total_pages: Total pages in document

        Returns:
            TranscriptionResult indicating this method is not supported
        """
        return TranscriptionResult(
            content="",
            tokens_used=0,
            success=False,
            error="Single-page transcription not supported. Use transcribe_streaming() for full PDF processing."
        )

    async def transcribe_streaming(
        self,
        processor: PDFProcessor,
        output_format: str,
        state_mgr: StateManager,
        chunk_size: int = 0,
        progress_callback: Callable[[int, int, str], Awaitable[None]] | None = None
    ) -> str:
        """
        Transcribe PDF pages using Marker with optional chunking.

        This is the PRIMARY method for Marker OCR. When chunk_size > 0, processes
        the PDF in batches for memory efficiency and crash recovery.

        Args:
            processor: PDFProcessor instance with PDF loaded
            output_format: "markdown" or "latex"
            state_mgr: StateManager for resume capability
            chunk_size: Pages per chunk (0 = process all at once)
            progress_callback: Optional callback(current, total, status)

        Returns:
            Full document content (all pages concatenated)
        """
        pdf_path = Path(processor.pdf_path)
        total_pages = processor.total_pages

        logger.info(f"Starting Marker OCR on {pdf_path.name} ({total_pages} pages)")

        # Check if any work needed
        initial_pending = state_mgr.get_pending_pages()
        if not initial_pending:
            logger.info("No pending pages - assembling from completed pages")
            return state_mgr.assemble_output()

        if chunk_size > 0:
            logger.info(f"Chunked mode: {chunk_size} pages per chunk")
        else:
            logger.info("Non-chunked mode: processing all pages at once")

        # Main processing loop
        pages_processed = 0
        while True:
            chunk_pages = state_mgr.get_next_chunk(chunk_size)
            if not chunk_pages:
                break

            try:
                # Process this chunk
                page_contents = await self._process_chunk(
                    pdf_path, chunk_pages, total_pages
                )

                # Save each page to state manager
                for page_num in sorted(page_contents.keys()):
                    content = page_contents[page_num]

                    # Detect diagrams and add placeholders
                    content = self._add_diagram_placeholders(content, page_num)

                    # Save to state
                    state_mgr.mark_page_complete(page_num, content)

                    # Progress callback
                    pages_processed += 1
                    if progress_callback:
                        await progress_callback(
                            pages_processed,
                            total_pages,
                            f"Processed page {page_num}/{total_pages}"
                        )

                # Update chunk progress checkpoint
                state_mgr.update_chunk_progress(max(chunk_pages))

            except Exception as e:
                logger.error(f"Chunk failed (pages {min(chunk_pages)}-{max(chunk_pages)}): {e}")
                # Mark chunk pages as failed, continue to next chunk
                for page_num in chunk_pages:
                    state_mgr.mark_page_failed(page_num, str(e))
                continue

        logger.info(f"✓ Transcription complete: {pages_processed} pages processed")

        # Return assembled output
        return state_mgr.assemble_output()

    async def _process_chunk(
        self,
        pdf_path: Path,
        page_numbers: list[int],
        total_pages: int
    ) -> dict[int, str]:
        """
        Process a chunk of pages with Marker OCR.

        Uses Marker's page_range config to process only specific pages
        without splitting the PDF file.

        Args:
            pdf_path: Path to the PDF file
            page_numbers: 1-indexed page numbers to process
            total_pages: Total pages in the document

        Returns:
            Dictionary mapping 1-indexed page number to transcribed content
        """
        chunk_start = min(page_numbers)
        chunk_end = max(page_numbers)
        logger.info(f"Processing chunk: pages {chunk_start}-{chunk_end} ({len(page_numbers)} pages)")

        # Convert 1-indexed pages to 0-indexed for Marker
        page_range_0idx = [p - 1 for p in page_numbers]

        try:
            # Build converter config
            converter_config = {
                'use_llm': self.use_llm,
                'page_range': page_range_0idx  # Marker processes only these pages
            }

            # LLM service parameter (passed separately, not in config)
            llm_service_param = None

            # Add LLM-specific settings if enabled
            if self.use_llm:
                # llm_service is a constructor param, not a config key
                llm_service_param = self.llm_service
                # Ollama settings go in config dict - assign_config() sets them on OllamaService
                converter_config.update({
                    'ollama_base_url': self.ollama_base_url,
                    'ollama_model': self.ollama_model
                })
                logger.info(f"LLM-enhanced mode: using {self.ollama_model}")

            converter = PdfConverter(
                artifact_dict=self.models,
                llm_service=llm_service_param,  # Pass as constructor param
                config=converter_config
            )

            result = await asyncio.to_thread(converter, str(pdf_path))
            full_text = result.markdown

            logger.info(f"✓ Chunk OCR complete (pages {chunk_start}-{chunk_end})")

        except Exception as e:
            logger.error(f"Marker OCR failed for chunk: {e}", exc_info=True)
            raise

        # Split output by page markers
        # The output will have len(page_numbers) pages, numbered 1..N relative to chunk
        relative_contents = self._split_by_pages(full_text, len(page_numbers))

        # Remap relative page numbers (1, 2, 3...) to original page numbers
        page_contents = {}
        sorted_pages = sorted(page_numbers)

        # Handle case where Marker didn't split pages properly
        if len(relative_contents) < len(page_numbers):
            # Marker returned fewer pages than requested - assign to ALL requested pages
            # This prevents the loop from re-running Marker for each remaining page
            logger.warning(
                f"Marker returned {len(relative_contents)} page(s) for {len(page_numbers)} requested. "
                f"Marking all pages as processed."
            )
            combined_content = relative_contents.get(1, full_text.strip())
            # Assign combined content to first page, mark rest as processed (no content)
            for i, page_num in enumerate(sorted_pages):
                if i < len(relative_contents):
                    # Use whatever content Marker returned for this relative position
                    page_contents[page_num] = relative_contents.get(i + 1, "")
                elif i == 0:
                    # Fallback: assign all content to first page
                    page_contents[page_num] = combined_content
                else:
                    # Mark remaining pages as processed with note
                    page_contents[page_num] = f"<!-- Content merged with page {sorted_pages[0]} -->"
        else:
            # Normal case: map relative pages to original page numbers
            for relative_idx, content in relative_contents.items():
                if relative_idx <= len(sorted_pages):
                    original_page = sorted_pages[relative_idx - 1]
                    page_contents[original_page] = content

        return page_contents

    def _split_by_pages(self, full_text: str, total_pages: int) -> dict[int, str]:
        """
        Split Marker output into individual pages.

        Marker uses "---" as page break markers in markdown output.
        This method splits the text and assigns to page numbers.
        """
        # Marker uses "---" for page breaks
        # Split carefully to preserve actual horizontal rules vs page breaks
        lines = full_text.split('\n')

        pages = {}
        current_page = 1
        current_content = []

        for line in lines:
            # Check if this is a page break (standalone ---)
            if line.strip() == '---' and len(current_content) > 0:
                # Save current page
                pages[current_page] = '\n'.join(current_content).strip()
                current_page += 1
                current_content = []
            else:
                current_content.append(line)

        # Save final page
        if current_content and current_page <= total_pages:
            pages[current_page] = '\n'.join(current_content).strip()

        # Handle case where Marker didn't add breaks
        if len(pages) == 0:
            logger.warning(
                "Marker didn't produce page breaks. "
                "Assigning all content to page 1."
            )
            pages[1] = full_text.strip()
        elif len(pages) < total_pages:
            logger.warning(
                f"Marker produced {len(pages)} page breaks but PDF has {total_pages} pages. "
                f"Some pages may be missing."
            )

        return pages

    def _add_diagram_placeholders(self, content: str, page_num: int) -> str:
        """
        Detect diagram regions and add [DIAGRAM] placeholders.

        Marker converts diagrams to images. We'll detect image references
        and replace with placeholders for manual TikZ addition later.

        Args:
            content: Page markdown content
            page_num: Page number

        Returns:
            Content with diagram placeholders
        """
        # Marker embeds images as: ![](image_path) or ![alt text](image_path)
        # Replace with placeholder
        pattern = r'!\[.*?\]\([^)]+\)'

        def replace_diagram(match):
            original = match.group(0)
            return (
                f"\n\n[DIAGRAM - Page {page_num}]\n"
                f"<!-- TODO: Add TikZ source code for diagram -->\n"
                f"<!-- Original image reference: {original} -->\n\n"
            )

        content = re.sub(pattern, replace_diagram, content)

        return content

    async def transcribe_batch(
        self,
        processor: PDFProcessor,
        output_format: str,
        state_mgr: StateManager,
        max_concurrent: int = 3
    ) -> str:
        """
        Batch transcription for Marker.

        Note: Marker is already optimized for full-PDF processing.
        This method delegates to transcribe_streaming() since batch
        processing individual pages would be less efficient.
        """
        logger.info("Batch mode for Marker delegates to streaming mode")
        return await self.transcribe_streaming(
            processor,
            output_format,
            state_mgr
        )
