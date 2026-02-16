# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-02-16

### Added
- **Event-driven telemetry system**: JSONL-based event logging for transcription jobs
  - `events.jsonl` log file with structured events (job_started, page_completed, heartbeat, error, job_completed)
  - Typed event dataclasses with `to_dict()`/`from_dict()` serialization (`event_types.py`)
  - Hybrid storage: central cache directory (`~/.cache/pdf-transcriber/telemetry/`) with symlinks in output directories
  - Background heartbeat thread (30s interval) with CPU/memory metrics via psutil
  - Event-based resume logic: replay event log to reconstruct state on restart
  - Backward compatible: falls back to existing `state.json` when no event log exists
- **TUI dashboard** (`pdf-transcriber-tui`): Live terminal UI for monitoring transcription jobs
  - Auto-discovers active jobs from telemetry event logs
  - Progress bars, velocity (pages/hour), ETA
  - Real-time CPU/memory metrics from heartbeat events
  - Stale job detection (configurable threshold, default 120s)
  - Keyboard navigation: `j/k` navigate, `Enter` details, `r` refresh, `q` quit
- **Cleanup utility** (`pdf-transcriber-cleanup`): Safe removal of completed job telemetry
  - Only deletes logs when job_completed event exists AND final output file exists
  - Never deletes logs for active or incomplete jobs
  - `--dry-run` mode for previewing deletions, `--verbose` for reasoning
- **OpenAI-compatible LLM service support**: Use any OpenAI-compatible local server for LLM-enhanced OCR
  - New config fields: `openai_base_url`, `openai_api_key`, `openai_model`
  - Works with mlx-vlm, vLLM, LM Studio, or any server implementing the OpenAI chat API
  - Default switched from Ollama to OpenAI service for broader compatibility
- **Apple MPS acceleration**: GPU acceleration on Mac via Metal Performance Shaders
  - New `disable_table_extraction` config option (default: `True`)
  - When table extraction is disabled, Marker uses MPS instead of CPU
  - Custom processor list excluding TableRec model (which is MPS-incompatible)
- **Page verification and fallback OCR**: Detect and recover from transcription errors
  - Single-character repetition detection (e.g., `g g g g g g`)
  - Multi-word repetition hallucination detection
  - Automatic PyMuPDF fallback when Marker produces hallucinated output
  - Garbled text detection via non-ASCII ratio
- **New lint rules**:
  - `broken_norm_notation`: Fix OCR-mangled norm notation (`|$|x|$|` → `$\|x\|$`)
  - `fragmented_math_expression`: Merge OCR-split math spans (`$x$ + $y$` → `$x + y$`)
  - `html_subscript_in_math`: Fix HTML `<sub>` tags adjacent to LaTeX math
  - `merge_math_expressions`: Merge adjacent inline math expressions separated by operators
  - `bold_number_sets`: Convert bold letters to blackboard bold (`**Z**` → `$\mathbb{Z}$`)
  - `operator_subscript_correction`: Fix subscripts on operators (`lim_n` → `\lim_n`)
- **Paper slug generation** (`core/slugs.py`): Deterministic slug creation from author + title
  - `PaperRegistry` class for YAML-based slug ↔ metadata mapping
  - Unicode normalization, stop word filtering, collision avoidance
- **Metadata pass-through**: Unknown frontmatter fields preserved in `extra` dict
  - Supports downstream tools (concept-extractor, ghost resolver) adding custom fields
  - Extra fields merge at top level in YAML output

### Changed
- **Engine cache extracted** to `core/engine_cache.py` (from `transcription.py`)
  - Cache key now includes OpenAI config and table extraction setting
  - Lazy import of `TranscriptionEngine` to avoid circular dependencies
- **`ProgressSummary` typed dataclass** replaces raw dict from `get_progress_summary()`
  - Access via `.completed`, `.failed`, `.total` instead of `["completed"]`, etc.
- **Failed pages retried on resume**: Previously failed pages are now included in pending list
  - Only completed pages are skipped; failed pages get another chance
- **Default LLM service**: Changed from `marker.services.ollama.OllamaService` to `marker.services.openai.OpenAIService`
- **Default chunk size**: Changed from 25 to 1 (single-page processing prevents hallucinations and page merges)
- **Linter module refactoring**: HTML rules extracted to `html.py` and `html_math.py`, math constants to `math_constants.py`, unicode rules to `math_unicode.py`

### Dependencies
- Added `psutil>=5.9` for process monitoring and resource metrics
- Added `rich>=13.7` for TUI terminal formatting

### Planned
- Phase 4: Deprecation of old `.pdf-progress/` approach
- Conformance test suite
- CI/CD pipeline

## [1.0.0] - 2026-02-04

### Added
- Initial stable release
- PDF transcription to Markdown/LaTeX using Claude vision API
- Resume capability for interrupted transcriptions
- Quality presets (fast/balanced/high-quality)
- Rich metadata management with YAML frontmatter
- Search and filtering for transcribed papers
- LaTeX conversion tool
- Linting tools for transcription cleanup
- MCP resources for paper index and metadata
- Comprehensive documentation

### Technical Details
- Uses FastMCP for MCP protocol implementation
- Compatible with MCP SDK >=1.2.0
- Marker OCR integration for enhanced quality
- Chunking support for large PDFs
- Progress state management with resume-on-failure

---

**Note**: Breaking changes will be announced in this file with migration instructions.
