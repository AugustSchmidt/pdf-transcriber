# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

## [Unreleased]

### Planned
- Conformance test suite
- CI/CD pipeline
- Automated dependency updates
- Enhanced error reporting

---

**Note**: Breaking changes will be announced in this file with migration instructions.
