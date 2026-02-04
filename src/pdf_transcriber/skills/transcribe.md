---
name: transcribe
description: Transcribe a PDF to Markdown using Marker OCR
arguments:
  - name: pdf_path
    description: Path to the PDF file to transcribe
    required: true
  - name: quality
    description: Quality preset (fast, balanced, high-quality)
    default: balanced
---

<command-name>transcribe</command-name>

Transcribe a PDF to Markdown using the pdf-transcriber MCP server.

## Instructions

1. **Call the transcribe tool** with the provided arguments:
   ```
   mcp__pdf-transcriber__transcribe_pdf(
       pdf_path="{{pdf_path}}",
       quality="{{quality}}"
   )
   ```

2. **Report the results** to the user:
   - Success/failure status
   - Output file path
   - Number of pages transcribed
   - Any linting fixes applied

## Example Usage

User: `/transcribe ~/Downloads/paper.pdf`

Response after tool call:
```
Transcribed 42 pages to ~/Documents/pdf-transcriptions/paper/paper.md
- Quality: balanced (150 DPI)
- Linting: 12 issues auto-fixed
```

## Notes

- If the MCP server isn't connected, suggest running `pdf-transcriber-cli check`
- For very large PDFs (100+ pages), mention that chunking is auto-enabled
- If transcription fails partway, let the user know they can re-run to resume
