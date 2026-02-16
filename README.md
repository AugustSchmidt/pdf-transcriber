# PDF Transcriber

Convert math-heavy PDFs to Markdown using Marker OCR with optional LLM enhancement. Includes telemetry, live monitoring, and automatic linting.

## Stability & Support

- **Status**: Stable for personal use
- **Breaking changes**: Announced in CHANGELOG
- **Issue response**: Best effort, typically within 1 week
- **Dependencies**: Updated as needed for security and compatibility
- **MCP Protocol**: Compatible with MCP SDK >=1.2.0

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

> **Note**: This is a standard [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server. While examples show Claude Code configuration, it works with any MCP-compatible agent orchestrator (Cursor, Cline, custom agents, etc.).

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

LLM enhancement is **enabled by default**. Two backend options are supported:

### Option A: OpenAI-Compatible Server (Default)

Works with any server that implements the OpenAI chat completions API — including **mlx-vlm**, **vLLM**, **LM Studio**, and **SGLang**.

1. **Install and start a local server** (example with mlx-vlm):
   ```bash
   pip install mlx-vlm
   mlx_vlm.server --model mlx-community/Qwen2.5-VL-3B-Instruct-4bit --port 8080
   ```

2. **Configure** (defaults work out of the box for mlx-vlm):
   ```bash
   # These are the defaults — only set if your setup differs
   export PDF_TRANSCRIBER_OPENAI_BASE_URL=http://localhost:8080
   export PDF_TRANSCRIBER_OPENAI_MODEL=mlx-community/Qwen2.5-VL-3B-Instruct-4bit
   ```

### Option B: Ollama

1. **Install Ollama**: https://ollama.ai
2. **Pull a vision model**:
   ```bash
   ollama pull qwen2.5vl:3b
   ```
3. **Start Ollama**:
   ```bash
   ollama serve
   ```
4. **Switch to Ollama backend**:
   ```bash
   export PDF_TRANSCRIBER_LLM_SERVICE=marker.services.ollama.OllamaService
   ```

### Disabling LLM Enhancement

```bash
# CLI flag
pdf-transcriber-cli transcribe paper.pdf --no-llm

# Environment variable
PDF_TRANSCRIBER_USE_LLM=false
```

This uses Marker OCR alone, which is still excellent for clean, typed PDFs.

### Recommended Vision Models

| Model | Size | RAM Required | Quality | Speed | Best For |
|-------|------|--------------|---------|-------|----------|
| `qwen2.5vl:3b` | 3.2 GB | 8 GB | Good | Fast | **Default** - laptops, CI |
| `qwen2.5vl:7b` | 5.5 GB | 16 GB | Better | Medium | Workstations |
| `qwen3-vl:4b` | 3.5 GB | 10 GB | Best (newest) | Medium | Best quality/size |

**Important**: Only **vision models** (VLMs) work. Text-only models like `llama3` won't process images.

## Apple MPS Acceleration

On Mac, PDF Transcriber can use Metal Performance Shaders (MPS) for GPU-accelerated OCR. This is enabled by default via the `disable_table_extraction` setting.

Marker's TableRec model is incompatible with MPS, so table extraction is disabled by default. When disabled, Marker auto-detects MPS and uses it for all other processing — typically a **2-3x speedup** over CPU.

To re-enable table extraction (forces CPU on Mac):
```bash
export PDF_TRANSCRIBER_DISABLE_TABLE_EXTRACTION=false
```

## Monitoring & Telemetry

### TUI Dashboard

Monitor active transcription jobs in real time:

```bash
# Dedicated command
pdf-transcriber-tui

# Or via CLI subcommand
pdf-transcriber-cli tui

# Monitor a specific output directory
pdf-transcriber-tui -o ~/Documents/transcriptions

# Custom refresh interval (seconds)
pdf-transcriber-tui --refresh 3
```

The dashboard shows:
- Active jobs with progress bars and ETA
- Velocity (pages/hour) and elapsed time
- CPU and memory usage from heartbeat events
- Stale job detection (default: 120s without heartbeat)

**Keyboard shortcuts**: `j/k` navigate, `Enter` details, `r` refresh, `q` quit

### Telemetry Event Log

Each transcription job writes structured events to `events.jsonl`:

| Event | When | Data |
|-------|------|------|
| `job_started` | Job begins | PDF path, total pages, quality preset |
| `page_completed` | Each page done | Duration, hallucination detected, fallback used |
| `heartbeat` | Every 30s | CPU%, memory MB, pages since last heartbeat |
| `error` | On problems | Severity, error type, page number |
| `job_completed` | Job finishes | Pages completed/failed, velocity, duration |

Events are stored in `~/.cache/pdf-transcriber/telemetry/` with symlinks in each output directory. The event log is also used for **resume-on-failure** — if a job is interrupted, it replays the log to find the last completed page.

### Cleanup

Remove telemetry logs for completed jobs:

```bash
# Preview what would be deleted
pdf-transcriber-cleanup --dry-run

# Delete completed job logs
pdf-transcriber-cleanup

# Verbose output showing reasoning for each file
pdf-transcriber-cleanup --verbose
```

Safety: only deletes logs where both a `job_completed` event exists AND the final `.md` output file exists. Never deletes logs for active or incomplete jobs.

## Page Verification & Fallback

During transcription, each page is verified for common OCR failure modes:

| Check | Detects | Action |
|-------|---------|--------|
| Single-char repetition | `g g g g g g g g` | PyMuPDF fallback |
| Multi-word repetition | `f in f in f in f in...` | PyMuPDF fallback |
| Garbled text | >50% non-ASCII characters | PyMuPDF fallback |
| Page merge comment | `<!-- Content merged -->` | Warning (informational) |

When a hallucination is detected, the page is automatically re-extracted using PyMuPDF's text extraction as a fallback. The fallback produces plain text (less formatting than Marker) but is reliable. Verification results are recorded in the telemetry event log.

## Configuration

All settings can be configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `PDF_TRANSCRIBER_OUTPUT_DIR` | Where transcriptions are saved | `./transcriptions` |
| `PDF_TRANSCRIBER_QUALITY` | fast, balanced, high-quality | `balanced` |
| `PDF_TRANSCRIBER_USE_GPU` | Enable GPU acceleration | Auto-detected |
| `PDF_TRANSCRIBER_USE_LLM` | Enable LLM-enhanced OCR | `true` |
| `PDF_TRANSCRIBER_LLM_SERVICE` | LLM service class | `marker.services.openai.OpenAIService` |
| `PDF_TRANSCRIBER_OPENAI_BASE_URL` | OpenAI-compatible server URL | `http://localhost:8080` |
| `PDF_TRANSCRIBER_OPENAI_API_KEY` | API key (local servers: `not-needed`) | `not-needed` |
| `PDF_TRANSCRIBER_OPENAI_MODEL` | Model name for OpenAI-compatible server | `mlx-community/Qwen2.5-VL-3B-Instruct-4bit` |
| `PDF_TRANSCRIBER_OLLAMA_URL` | Ollama server URL | `http://localhost:11434` |
| `PDF_TRANSCRIBER_OLLAMA_MODEL` | Ollama vision model | `qwen2.5vl:3b` |
| `PDF_TRANSCRIBER_CHUNK_SIZE` | Pages per chunk | `1` |
| `PDF_TRANSCRIBER_DISABLE_TABLE_EXTRACTION` | Disable table extraction (enables MPS on Mac) | `true` |

## CLI Commands

| Command | Description |
|---------|-------------|
| `pdf-transcriber-cli transcribe <pdf>` | Transcribe a PDF to Markdown |
| `pdf-transcriber-cli check` | Health check (config, paths, LLM server) |
| `pdf-transcriber-cli install-skill` | Install Claude Code `/transcribe` skill |
| `pdf-transcriber-cli tui` | Launch TUI monitoring dashboard |
| `pdf-transcriber-cli cleanup` | Clean up completed job telemetry |
| `pdf-transcriber-tui` | TUI dashboard (dedicated command) |
| `pdf-transcriber-cleanup` | Cleanup utility (dedicated command) |

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
- **CI/CD pipelines**: Use **CLI only** — zero agent orchestrator dependency

## Quality Presets

| Preset | DPI | Resolution | Use Case |
|--------|-----|------------|----------|
| `fast` | 100 | ~1275x1650px | Quick previews, simple documents |
| `balanced` | 150 | ~1913x2475px | **Default** - best quality/speed |
| `high-quality` | 200 | ~2550x3300px | Complex math, small text |

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
| `unwrapped_sentences` | ✅ | Joins orphaned sentence fragments |
| `excessive_horizontal_rules` | ✅ | Removes redundant `---` dividers |
| `sparse_table_row` | ⚠️ | Warns about table rows >50% empty cells |
| `orphaned_list_marker` | ⚠️ | Warns about list markers with no content |

#### PDF Artifact Rules

| Rule | Auto-Fix | Description |
|------|----------|-------------|
| `page_number` | ✅ | Removes standalone page numbers like "42" |
| `page_marker` | ✅ | Removes page break markers |
| `orphaned_label` | ✅ | Removes orphaned LaTeX labels like `def:Tilt` |
| `hyphenation_artifact` | ✅ | Rejoins words split across lines (`hy-\nphenated`) |
| `merged_content_comment` | ✅ | Removes Marker page-merge comments |
| `garbled_text` | ⚠️ | Warns about corrupted/nonsense text fragments |
| `repeated_line` | ⚠️ | Warns about likely running headers/footers |

#### HTML & Conversion Rules

| Rule | Auto-Fix | Description |
|------|----------|-------------|
| `html_artifacts` | ✅ | Removes HTML tags, entities, and stray closing tags |
| `html_math_notation` | ✅ | Converts `<sup>2</sup>` to `$^{2}$` in math context |
| `html_subscript_in_math` | ✅ | Fixes `$K$<sub>v</sub>` → `$K_{v}$` |
| `footnote_spacing` | ✅ | Adds space after footnote markers |
| `malformed_footnote` | ⚠️ | Warns about malformed footnote references |

#### Math Notation Rules

| Rule | Auto-Fix | Description |
|------|----------|-------------|
| `unicode_math_symbols` | ✅ | Converts Unicode math (α, →, ∈) to LaTeX (`\alpha`, `\to`, `\in`) |
| `unwrapped_math_expressions` | ✅ | Wraps bare math expressions in `$...$` |
| `broken_math_delimiters` | ✅ | Fixes unbalanced `$` delimiters |
| `broken_norm_notation` | ✅ | Fixes OCR-mangled norms (`\|$\|x\|$\|` → `$\lVert x \rVert$`) |
| `fragmented_math_expression` | ✅ | Merges OCR-split inline math (`$x$ + $y$` → `$x + y$`) |
| `merge_math_expressions` | ✅ | Merges adjacent math expressions separated by operators |
| `bold_number_sets` | ✅ | Converts bold to blackboard bold (`**Z**` → `$\mathbb{Z}$`) |
| `operator_subscript_correction` | ✅ | Fixes subscripts on operators (`lim_n` → `\lim_n`) |
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
    "broken_norm_notation",
    "fragmented_math_expression",
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

### Adding Custom Lint Rules

If you're seeing specific patterns in your PDFs that aren't caught by existing rules, you can add custom rules.

Rules are generator functions that take the file content and yield `LintIssue` objects:

```python
# my_rules.py
import re
from pdf_transcriber.core.linter.models import LintIssue, Severity, Fix

def my_custom_rule(content: str):
    """
    Detect and fix a specific pattern in your PDFs.

    Rules are generators that yield LintIssue objects.
    """
    pattern = re.compile(r'PATTERN_TO_MATCH')

    for match in pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="my_custom_rule",
            severity=Severity.AUTO_FIX,  # or WARNING for manual review
            line=line_num,
            message="Description of the issue",
            fix=Fix(
                old=match.group(),
                new="replacement text"
            )
        )
```

To register your rule, add it to `rules/__init__.py`:

```python
# In RULES dict:
"my_custom_rule": my_module.my_custom_rule,

# If auto-fixable, add to DEFAULT_AUTO_FIX:
DEFAULT_AUTO_FIX.add("my_custom_rule")
```

**Severity levels:**
| Level | Use Case |
|-------|----------|
| `Severity.AUTO_FIX` | Safe to fix automatically (provide a `Fix`) |
| `Severity.WARNING` | Needs human review |
| `Severity.ERROR` | Must be addressed before use |

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

Issues and PRs welcome at https://github.com/AugustSchmidt/pdf-transcriber
