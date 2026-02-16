"""Marker OCR transcription with streaming and batch modes."""
import logging
import asyncio
import re
import time
from typing import Callable, Awaitable
from pathlib import Path

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict

from pdf_transcriber.core.pdf_processor import PDFProcessor
from pdf_transcriber.core.state_manager import StateManager
from pdf_transcriber.core.engine_cache import TranscriptionResult
from pdf_transcriber.events import EventEmitter
from pdf_transcriber.core.verification import (
    verify_page_content,
    fallback_to_pymupdf,
    should_retry_with_fallback
)

logger = logging.getLogger(__name__)


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
        llm_service: str = "marker.services.openai.OpenAIService",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "qwen2.5vl:3b",
        openai_base_url: str = "http://localhost:8080",
        openai_api_key: str = "not-needed",
        openai_model: str = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit",
        # Processor customization
        disable_table_extraction: bool = False
    ):
        """
        Initialize transcription engine.

        Args:
            use_gpu: Whether to use GPU acceleration
            batch_size: Number of pages per batch (not currently used)
            langs: Languages for OCR (default: ["English"])
            use_llm: Enable Marker's LLM-enhanced OCR mode
            llm_service: LLM service class path
            ollama_base_url: Ollama server URL
            ollama_model: Ollama vision model name
            openai_base_url: OpenAI-compatible server URL
            openai_api_key: API key for OpenAI-compatible server
            openai_model: Model name for OpenAI-compatible server
        """
        self.use_gpu = use_gpu
        self.batch_size = batch_size
        self.langs = langs or ["English"]
        self.disable_table_extraction = disable_table_extraction

        # LLM settings
        self.use_llm = use_llm
        self.llm_service = llm_service
        self.ollama_base_url = ollama_base_url
        self.ollama_model = ollama_model
        self.openai_base_url = openai_base_url
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model

        # Load Marker models (heavy operation - do once)
        model_name = openai_model if "openai" in llm_service else ollama_model
        llm_status = f", LLM: {model_name}" if use_llm else ""

        # Configure device based on table extraction setting
        import torch
        if disable_table_extraction:
            # Table extraction disabled - can use MPS on Mac
            device = None  # Let Marker auto-detect (will use MPS if available)
            device_info = f"Auto (MPS on Mac, table extraction disabled)"
        else:
            # Table extraction enabled - force CPU on Mac to avoid MPS errors
            # (TableRec model is incompatible with MPS and causes device mismatch)
            device = "cpu" if torch.backends.mps.is_available() else None
            device_info = "CPU (forced on Mac to avoid MPS/TableRec conflict)" if device == "cpu" else f"GPU: {use_gpu}"

        logger.info(f"Loading Marker OCR models ({device_info}{llm_status})...")
        self.models = create_model_dict(device=device)
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
        progress_callback: Callable[[int, int, str], Awaitable[None]] | None = None,
        event_emitter: EventEmitter | None = None
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
            event_emitter: Optional EventEmitter for telemetry

        Returns:
            Full document content (all pages concatenated)
        """
        pdf_path = Path(processor.pdf_path)
        total_pages = processor.total_pages

        logger.info(f"Starting Marker OCR on {pdf_path.name} ({total_pages} pages)")

        # Start heartbeat if event emitter provided
        if event_emitter:
            event_emitter.start_heartbeat(total_pages)

        # Check if any work needed
        initial_pending = state_mgr.get_pending_pages()
        if not initial_pending:
            logger.info("No pending pages - assembling from completed pages")
            if event_emitter:
                event_emitter.stop_heartbeat()
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
                # Track chunk timing
                chunk_start_time = time.time()

                # Process this chunk
                page_contents = await self._process_chunk(
                    pdf_path, chunk_pages, total_pages
                )

                chunk_duration = time.time() - chunk_start_time

                # Save each page to state manager
                for page_num in sorted(page_contents.keys()):
                    page_start_time = time.time()

                    content = page_contents[page_num]

                    # VERIFICATION: Check for hallucinations and artifacts
                    verification = verify_page_content(content, page_num)

                    # Track whether we used fallback for telemetry
                    used_fallback = False
                    hallucination_found = not verification.is_valid

                    if not verification.is_valid and should_retry_with_fallback(verification):
                        # Hallucination detected - retry with PyMuPDF fallback
                        logger.warning(
                            f"Page {page_num}: {verification.error_type} - "
                            f"retrying with PyMuPDF fallback"
                        )

                        # Emit error event before fallback
                        if event_emitter:
                            event_emitter.emit_error(
                                severity="warning",
                                error_type=verification.error_type,
                                error_message=verification.error_message,
                                page_number=page_num
                            )

                        try:
                            # Extract with PyMuPDF
                            fallback_content = await fallback_to_pymupdf(pdf_path, page_num)

                            # Add note about fallback
                            content = (
                                f"<!-- Transcribed via PyMuPDF fallback - "
                                f"Marker had {verification.error_type} -->\n\n"
                                f"{fallback_content}"
                            )

                            used_fallback = True

                            logger.info(
                                f"Page {page_num}: Successfully recovered via PyMuPDF "
                                f"({len(fallback_content)} chars)"
                            )

                        except Exception as fallback_error:
                            # Fallback failed - keep original (flawed) content
                            logger.error(
                                f"Page {page_num}: PyMuPDF fallback failed: {fallback_error}. "
                                f"Keeping original content with error marker."
                            )

                            # Add error marker to original content
                            content = (
                                f"<!-- TRANSCRIPTION ERROR: {verification.error_type} - "
                                f"fallback failed: {fallback_error} -->\n\n"
                                f"{content}"
                            )

                    # Detect diagrams and add placeholders
                    content = self._add_diagram_placeholders(content, page_num)

                    # Save to state
                    state_mgr.mark_page_complete(page_num, content)

                    # Calculate page duration (approximate from chunk timing)
                    page_duration_ms = int((chunk_duration / len(page_contents)) * 1000)

                    # Emit page_completed event with verification details
                    if event_emitter:
                        event_emitter.emit_page_completed(
                            page_num,
                            page_duration_ms,
                            hallucination_detected=hallucination_found,
                            fallback_used="pymupdf" if used_fallback else None,
                            verification_error=verification.error_type if hallucination_found else None
                        )
                        event_emitter.update_current_page(page_num)

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
                error_msg = str(e)
                logger.error(f"Chunk failed (pages {min(chunk_pages)}-{max(chunk_pages)}): {e}")

                # Emit error event
                if event_emitter:
                    event_emitter.emit_error(
                        severity="error",
                        error_type="chunk_processing_fail",
                        error_message=error_msg,
                        page_number=min(chunk_pages)
                    )

                # Mark chunk pages as failed, continue to next chunk
                for page_num in chunk_pages:
                    state_mgr.mark_page_failed(page_num, error_msg)
                continue

        logger.info(f"✓ Transcription complete: {pages_processed} pages processed")

        # Stop heartbeat
        if event_emitter:
            event_emitter.stop_heartbeat()

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
                # Pass all service configs - Marker's assign_config() picks what's relevant
                converter_config.update({
                    'ollama_base_url': self.ollama_base_url,
                    'ollama_model': self.ollama_model,
                    'openai_base_url': self.openai_base_url,
                    'openai_api_key': self.openai_api_key,
                    'openai_model': self.openai_model,
                })
                model_name = self.openai_model if "openai" in self.llm_service else self.ollama_model
                logger.info(f"LLM-enhanced mode: using {model_name}")

            # Build custom processor list if table extraction disabled
            processor_list = None
            if self.disable_table_extraction:
                # Exclude table-related processors to avoid loading TableRec model
                # (which is incompatible with MPS on Mac)
                processor_list = [
                    "marker.processors.order.OrderProcessor",
                    "marker.processors.block_relabel.BlockRelabelProcessor",
                    "marker.processors.line_merge.LineMergeProcessor",
                    "marker.processors.blockquote.BlockquoteProcessor",
                    "marker.processors.code.CodeProcessor",
                    "marker.processors.document_toc.DocumentTOCProcessor",
                    "marker.processors.equation.EquationProcessor",
                    "marker.processors.footnote.FootnoteProcessor",
                    "marker.processors.ignoretext.IgnoreTextProcessor",
                    "marker.processors.line_numbers.LineNumbersProcessor",
                    "marker.processors.list.ListProcessor",
                    "marker.processors.page_header.PageHeaderProcessor",
                    "marker.processors.sectionheader.SectionHeaderProcessor",
                    # TableProcessor excluded - uses TableRec model (MPS incompatible)
                    # LLMTableProcessor excluded
                    # LLMTableMergeProcessor excluded
                    "marker.processors.llm.llm_form.LLMFormProcessor",
                    "marker.processors.text.TextProcessor",
                    "marker.processors.llm.llm_complex.LLMComplexRegionProcessor",
                    "marker.processors.llm.llm_image_description.LLMImageDescriptionProcessor",
                    "marker.processors.llm.llm_equation.LLMEquationProcessor",
                    "marker.processors.llm.llm_handwriting.LLMHandwritingProcessor",
                    "marker.processors.llm.llm_mathblock.LLMMathBlockProcessor",
                    "marker.processors.llm.llm_sectionheader.LLMSectionHeaderProcessor",
                    "marker.processors.llm.llm_page_correction.LLMPageCorrectionProcessor",
                    "marker.processors.reference.ReferenceProcessor",
                    "marker.processors.blank_page.BlankPageProcessor",
                    "marker.processors.debug.DebugProcessor",
                ]
                logger.info("Table extraction disabled - using custom processor list (MPS enabled)")

            converter = PdfConverter(
                artifact_dict=self.models,
                processor_list=processor_list,
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
        max_concurrent: int = 3,
        event_emitter: EventEmitter | None = None
    ) -> str:
        """
        Batch transcription for Marker.

        Note: Marker is already optimized for full-PDF processing.
        This method delegates to transcribe_streaming() since batch
        processing individual pages would be less efficient.

        Args:
            processor: PDFProcessor instance
            output_format: Output format
            state_mgr: State manager
            max_concurrent: Max concurrent pages (unused)
            event_emitter: Optional event emitter for telemetry
        """
        logger.info("Batch mode for Marker delegates to streaming mode")
        return await self.transcribe_streaming(
            processor,
            output_format,
            state_mgr,
            event_emitter=event_emitter
        )
