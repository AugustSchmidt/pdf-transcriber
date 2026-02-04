# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-02-04

### Added

- Initial public release
- **MCP Server** with tools:
  - `transcribe_pdf` - Convert PDFs to Markdown
  - `clear_transcription_cache` - Free memory from OCR models
  - `update_paper_metadata` - Update paper metadata
  - `search_papers` - Search transcribed papers
  - `list_papers` - List all transcriptions
  - `lint_paper` - Fix OCR artifacts
  - `get_lint_rules` - List available lint rules
- **CLI** (`pdf-transcriber-cli`):
  - `transcribe` command with quality presets
  - `list` command to view transcriptions
  - `check` command for health checks
  - `install-skill` command for Claude Code integration
- **Claude Code Skill** (`/transcribe`)
- **LLM-enhanced OCR** via Ollama (optional)
- **Quality presets**: fast, balanced, high-quality
- **Auto-chunking** for large PDFs (100+ pages)
- **Resume support** for interrupted transcriptions
- **Automatic linting** with OCR artifact cleanup

### Features

- Marker OCR integration for high-quality transcription
- Optional LLM enhancement for complex documents
- YAML frontmatter with rich metadata
- Progress persistence and resume capability
- GPU acceleration (when available)

### Supported Models

- `qwen2.5vl:3b` (default) - 3.2 GB, good for laptops
- `qwen2.5vl:7b` - 5.5 GB, better quality
- `qwen3-vl:4b` - 3.5 GB, newest and best quality/size
- Any Ollama-compatible vision model
