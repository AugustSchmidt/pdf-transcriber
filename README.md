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
| `PDF_TRANSCRIBER_OUTPUT_DIR` | Where transcriptions are saved | `~/Documents/pdf-transcriptions` |
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
| `update_paper_metadata` | Update paper title, authors, keywords |
| `lint_paper` | Fix common OCR artifacts |
| `get_lint_rules` | List available lint rules |

## MCP Server vs CLI + Skill: When to Use What

### Context Usage Comparison

| Approach | Context Overhead | Best For |
|----------|------------------|----------|
| **MCP Server** | ~3,000 tokens (tool schemas + resources) | Frequent transcription, multi-step workflows |
| **CLI + Skill** | ~200 tokens (skill definition only) | Occasional use, context-constrained sessions |
| **CLI only** | 0 tokens | Automation, CI pipelines |

### Pros and Cons

#### MCP Server

**Pros:**
- Tools always available without manual invocation
- Rich integration (resources, tool chaining)
- Automatic paper registry and metadata management
- Claude can search/list papers without leaving conversation

**Cons:**
- ~3,000 tokens of context per session (tool definitions)
- Requires MCP server configuration
- Server must be running in background

#### CLI + Skill

**Pros:**
- Minimal context usage (~200 tokens when skill invoked)
- Simpler setup (just install skill)
- Works without MCP infrastructure
- Good for users who transcribe occasionally

**Cons:**
- Must explicitly invoke `/transcribe`
- No automatic tool availability
- Can't chain with other MCP tools

#### CLI Only

**Pros:**
- Zero context overhead
- Works in any terminal
- Best for automation/scripting
- No Claude Code dependency

**Cons:**
- No Claude integration
- Manual workflow only

### Recommendation

- **Research workflows** (frequent transcription, paper management): Use **MCP Server**
- **Occasional transcription**: Use **CLI + Skill**
- **CI/CD pipelines**: Use **CLI only**
- **Context-limited sessions**: Start with **CLI + Skill**, switch to MCP if needed

## Quality Presets

| Preset | DPI | Resolution | Use Case |
|--------|-----|------------|----------|
| `fast` | 100 | ~1275×1650px | Quick previews, simple documents |
| `balanced` | 150 | ~1913×2475px | **Default** - best quality/speed |
| `high-quality` | 200 | ~2550×3300px | Complex math, small text |

## Linting

Transcriptions are automatically linted to fix common OCR artifacts:

- **Page numbers**: Removes standalone numbers
- **Orphaned labels**: Removes orphaned LaTeX labels
- **Blank lines**: Normalizes excessive whitespace
- **Hyphenation**: Rejoins words split across lines
- **Math cleanup**: Fixes Unicode→LaTeX in math blocks

The original (pre-lint) version is saved as `{name}.original.md`.

## License

MIT

## Contributing

Issues and PRs welcome at https://github.com/gusschmidt/pdf-transcriber
