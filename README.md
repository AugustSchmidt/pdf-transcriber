# PDF Transcriber

Convert math-heavy PDFs to Markdown using Marker OCR with optional LLM enhancement.

## Installation

### Recommended (isolated environment)

```bash
uv tool install pdf-transcriber
```

### Alternative (pip)

```bash
pip install pdf-transcriber
```

### Verify installation

```bash
pdf-transcriber-cli check
```

## Three Ways to Use

| Interface | Command | Use Case |
|-----------|---------|----------|
| **CLI** | `pdf-transcriber-cli transcribe paper.pdf` | Direct terminal usage |
| **Skill** | `/transcribe paper.pdf` | Claude Code slash command |
| **MCP Server** | `pdf-transcriber` | Claude Code background integration |

### 1. CLI (Direct Terminal Usage)

```bash
# Basic transcription
pdf-transcriber-cli transcribe ~/Downloads/paper.pdf

# High quality mode
pdf-transcriber-cli transcribe ~/Downloads/paper.pdf -q high-quality

# Disable LLM (faster, less accurate)
pdf-transcriber-cli transcribe ~/Downloads/paper.pdf --no-llm

# Skip automatic linting
pdf-transcriber-cli transcribe ~/Downloads/paper.pdf --no-lint

# Health check
pdf-transcriber-cli check
```

### 2. Claude Code Skill (Slash Command)

```bash
# Install the skill
pdf-transcriber-cli install-skill

# Then in Claude Code:
/transcribe ~/Downloads/paper.pdf
```

### 3. MCP Server (Claude Code Integration)

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "pdf-transcriber": {
      "command": "pdf-transcriber",
      "env": {
        "PDF_TRANSCRIBER_OUTPUT_DIR": "~/Documents/transcriptions"
      }
    }
  }
}
```

## LLM-Enhanced OCR Setup

PDF Transcriber can use a local vision LLM (VLM) to significantly improve OCR accuracy, especially for:
- Complex mathematical notation
- Handwritten annotations
- Low-quality scans
- Tables and figures

### Quick Start

1. **Install Ollama**: https://ollama.ai
2. **Pull a vision model**:
   ```bash
   ollama pull qwen2.5vl:3b
   ```
3. **Start Ollama**:
   ```bash
   ollama serve
   ```

LLM enhancement is **enabled by default**. To disable:
```bash
# CLI
pdf-transcriber-cli transcribe paper.pdf --no-llm

# Environment variable
PDF_TRANSCRIBER_USE_LLM=false
```

### Recommended Vision Models

| Model | Size | RAM Required | Quality | Speed | Best For |
|-------|------|--------------|---------|-------|----------|
| `qwen2.5vl:3b` | 3.2 GB | 8 GB | Good | Fast | **Default** - laptops, CI |
| `qwen2.5vl:7b` | 5.5 GB | 16 GB | Better | Medium | Workstations |
| `qwen3-vl:4b` | 3.5 GB | 10 GB | Best (newest) | Medium | Best quality/size |
| `llava:13b` | 8 GB | 24 GB | Good | Slow | NVIDIA GPUs |

**Important**: Only **vision models** (VLMs) work. Text-only models like `llama3` won't process images.

### Choosing a Model

- **8GB RAM / M1 MacBook**: `qwen2.5vl:3b` (default)
- **16GB RAM / M2/M3 Pro**: `qwen2.5vl:7b` or `qwen3-vl:4b`
- **24GB+ / NVIDIA GPU**: `llava:13b` or larger
- **CI/Automated pipelines**: `qwen2.5vl:3b` or disable LLM (`--no-llm`)

To use a different model:
```bash
# Environment variable
PDF_TRANSCRIBER_OLLAMA_MODEL=qwen3-vl:4b

# Or pull and use
ollama pull qwen3-vl:4b
```

### Without LLM Enhancement

If you don't want to run a local LLM:
```bash
pdf-transcriber-cli transcribe paper.pdf --no-llm
```

This uses Marker OCR alone, which is still excellent for clean, typed PDFs.

## Configuration

All settings can be configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `PDF_TRANSCRIBER_OUTPUT_DIR` | Where transcriptions are saved | `./transcriptions` |
| `PDF_TRANSCRIBER_QUALITY` | fast, balanced, high-quality | `balanced` |
| `PDF_TRANSCRIBER_USE_GPU` | Enable GPU acceleration | Auto-detected |
| `PDF_TRANSCRIBER_USE_LLM` | Enable LLM-enhanced OCR | `true` |
| `PDF_TRANSCRIBER_OLLAMA_URL` | Ollama server URL | `http://localhost:11434` |
| `PDF_TRANSCRIBER_OLLAMA_MODEL` | Vision model for OCR | `qwen2.5vl:3b` |
| `PDF_TRANSCRIBER_CHUNK_SIZE` | Pages per chunk (large PDFs) | `25` |
| `PDF_TRANSCRIBER_AUTO_CHUNK_THRESHOLD` | Auto-chunk above this page count | `100` |

## CLI Commands

| Command | Description |
|---------|-------------|
| `transcribe <pdf>` | Transcribe a PDF to Markdown |
| `check` | Health check (config, paths, Ollama) |
| `install-skill` | Install Claude Code `/transcribe` skill |

## MCP Tools

When running as an MCP server, these tools are available:

| Tool | Description |
|------|-------------|
| `transcribe_pdf` | Convert PDF to Markdown |
| `clear_transcription_cache` | Free ~2GB memory from cached OCR models |
| `lint_paper` | Fix common OCR artifacts |

## MCP Server vs CLI + Skill: When to Use What

### Context Usage Comparison

| Approach | Context Overhead | Best For |
|----------|------------------|----------|
| **MCP Server** | ~1,200 tokens (3 tools) | Frequent transcription, linting workflows |
| **CLI + Skill** | ~200 tokens (skill definition only) | Occasional use, context-constrained sessions |
| **CLI only** | 0 tokens | Automation, CI pipelines |

### Recommendation

- **Frequent transcription**: Use **MCP Server** — tools always available
- **Occasional transcription**: Use **CLI + Skill** — minimal context overhead
- **CI/CD pipelines**: Use **CLI only** — zero Claude dependency

## Quality Presets

| Preset | DPI | Resolution | Use Case |
|--------|-----|------------|----------|
| `fast` | 100 | ~1275×1650px | Quick previews, simple documents |
| `balanced` | 150 | ~1913×2475px | **Default** - best quality/speed |
| `high-quality` | 200 | ~2550×3300px | Complex math, small text |

## Linting

Transcriptions are automatically linted after transcription to fix common OCR artifacts. The original (pre-lint) version is saved as `{name}.original.md`.

### Available Lint Rules

#### Markdown Structure Rules

| Rule | Auto-Fix | Description |
|------|----------|-------------|
| `excessive_blank_lines` | ✅ | Reduces >2 consecutive blank lines |
| `trailing_whitespace` | ✅ | Removes spaces/tabs at end of lines |
| `leading_whitespace` | ✅ | Fixes inconsistent leading whitespace |
| `header_whitespace` | ✅ | Normalizes spacing around headers |
| `sparse_table_row` | ⚠️ | Warns about table rows >50% empty cells |
| `orphaned_list_marker` | ⚠️ | Warns about list markers with no content |

#### PDF Artifact Rules

| Rule | Auto-Fix | Description |
|------|----------|-------------|
| `page_number` | ✅ | Removes standalone page numbers like "42" |
| `page_marker` | ✅ | Removes page break markers |
| `orphaned_label` | ✅ | Removes orphaned LaTeX labels like `def:Tilt` |
| `hyphenation_artifact` | ✅ | Rejoins words split across lines (`hy-\nphenated`) |
| `html_artifacts` | ✅ | Converts HTML tags to markdown equivalents |
| `html_math_notation` | ✅ | Converts `<sup>2</sup>` to `$^2$` in math context |
| `footnote_spacing` | ✅ | Fixes spacing around footnote markers |
| `malformed_footnote` | ⚠️ | Warns about malformed footnote references |
| `garbled_text` | ⚠️ | Warns about corrupted/nonsense text fragments |
| `repeated_line` | ⚠️ | Warns about likely running headers/footers |

#### Math Notation Rules

| Rule | Auto-Fix | Description |
|------|----------|-------------|
| `unicode_math_symbols` | ✅ | Converts Unicode math (α, →, ∈) to LaTeX (`\alpha`, `\to`, `\in`) |
| `unwrapped_math_expressions` | ✅ | Wraps bare math expressions in `$...$` |
| `broken_math_delimiters` | ✅ | Fixes unbalanced `$` delimiters |
| `space_in_math_variable` | ✅ | Removes spaces in variable names (`x _1` → `x_1`) |
| `display_math_whitespace` | ✅ | Normalizes whitespace around `$$...$$` blocks |
| `repetition_hallucination` | ⚠️ | Warns about repeated sequences (OCR hallucination) |

### Running Specific Rules

To run only specific lint rules (via MCP or programmatically):

```python
# Run only math-related rules
lint_paper(paper_path, rules=["unicode_math_symbols", "broken_math_delimiters"])

# Run only whitespace cleanup
lint_paper(paper_path, rules=["excessive_blank_lines", "trailing_whitespace"])

# Preview issues without fixing
lint_paper(paper_path, fix=False)
```

### Customizing for Your Workflow

If you're seeing specific patterns in your PDFs, you can run targeted lint passes:

**For math-heavy papers:**
```python
lint_paper(path, rules=[
    "unicode_math_symbols",
    "unwrapped_math_expressions",
    "broken_math_delimiters",
    "space_in_math_variable"
])
```

**For scanned books with page numbers:**
```python
lint_paper(path, rules=[
    "page_number",
    "page_marker",
    "repeated_line",  # catches running headers
    "hyphenation_artifact"
])
```

**For cleaning up whitespace only:**
```python
lint_paper(path, rules=[
    "excessive_blank_lines",
    "trailing_whitespace",
    "display_math_whitespace"
])
```

### Disabling Automatic Linting

To skip linting during transcription:

```bash
# CLI
pdf-transcriber-cli transcribe paper.pdf --no-lint

# MCP tool
transcribe_pdf(pdf_path, lint=False)
```

You can then run linting manually later with custom rules.

## License

MIT

## Contributing

Issues and PRs welcome at https://github.com/gusschmidt/pdf-transcriber
