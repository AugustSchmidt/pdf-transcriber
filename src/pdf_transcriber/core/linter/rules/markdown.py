"""Markdown structure linting rules."""
import re
from typing import Generator

from ..models import LintIssue, Severity, Fix


def excessive_blank_lines(content: str) -> Generator[LintIssue, None, None]:
    """
    Flag more than 2 consecutive blank lines.

    Multiple blank lines waste tokens and don't improve readability.
    Normalizes to exactly 2 blank lines (one empty line between paragraphs).
    """
    pattern = re.compile(r'\n{4,}')

    for match in pattern.finditer(content):
        num_blanks = len(match.group()) - 1
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="excessive_blank_lines",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"{num_blanks} consecutive blank lines (max 2)",
            fix=Fix(
                old=match.group(),
                new="\n\n\n"  # Normalize to 2 blank lines
            )
        )


def trailing_whitespace(content: str) -> Generator[LintIssue, None, None]:
    """
    Flag trailing whitespace on lines.

    Trailing whitespace wastes tokens and can cause diff noise.
    """
    lines = content.split('\n')

    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        trailing_count = len(line) - len(stripped)

        if trailing_count > 0:
            yield LintIssue(
                rule="trailing_whitespace",
                severity=Severity.AUTO_FIX,
                line=i,
                message=f"Trailing whitespace ({trailing_count} chars)",
                fix=Fix(old=line, new=stripped)
            )


def sparse_table_row(content: str) -> Generator[LintIssue, None, None]:
    """
    Flag table rows that are more than 50% empty cells.

    Common artifact from TOC transcription where vision models
    create tables with many empty columns.
    """
    table_row_pattern = re.compile(r'^\|.*\|$', re.MULTILINE)

    for match in table_row_pattern.finditer(content):
        row = match.group()
        cells = row.split('|')[1:-1]  # Exclude outer pipes

        if len(cells) <= 3:
            continue  # Small tables are fine

        empty_cells = sum(1 for c in cells if c.strip() == '')
        empty_ratio = empty_cells / len(cells)

        if empty_ratio > 0.5:
            line_num = content[:match.start()].count('\n') + 1
            yield LintIssue(
                rule="sparse_table_row",
                severity=Severity.WARNING,
                line=line_num,
                message=f"Table row is {empty_cells}/{len(cells)} empty ({empty_ratio:.0%})",
                fix=None  # Needs manual review - might need table restructure
            )


def orphaned_list_marker(content: str) -> Generator[LintIssue, None, None]:
    """
    Flag list markers that have no content after them.

    Often caused by transcription errors where list content
    ends up on the next line or is missing entirely.
    """
    # Match: start of line, optional whitespace, list marker, only whitespace to EOL
    pattern = re.compile(r'^([ \t]*(?:[-*+]|\d+\.))[ \t]*$', re.MULTILINE)

    for match in pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1
        marker = match.group(1).strip()

        yield LintIssue(
            rule="orphaned_list_marker",
            severity=Severity.WARNING,
            line=line_num,
            message=f"List marker '{marker}' with no content",
            fix=Fix(old=match.group() + '\n', new='')
        )


def leading_whitespace(content: str) -> Generator[LintIssue, None, None]:
    """
    Flag leading whitespace on lines (outside of code blocks).

    Leading whitespace in transcribed papers is almost always an OCR artifact.
    Preserves indentation inside fenced code blocks.
    """
    lines = content.split('\n')
    in_code_block = False

    for i, line in enumerate(lines, 1):
        # Track fenced code blocks
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            continue

        # Check for leading whitespace (spaces or tabs)
        if line and line[0] in ' \t':
            stripped = line.lstrip()
            leading_count = len(line) - len(stripped)

            # Skip if it's a blank line (all whitespace)
            if not stripped:
                continue

            yield LintIssue(
                rule="leading_whitespace",
                severity=Severity.AUTO_FIX,
                line=i,
                message=f"Leading whitespace ({leading_count} chars)",
                fix=Fix(old=line, new=stripped)
            )


def header_whitespace(content: str) -> Generator[LintIssue, None, None]:
    """
    Remove extra blank lines before headers.

    In transcribed papers, headers often have unnecessary blank lines
    before them from page breaks or section transitions. This normalizes
    to have exactly one blank line before headers.
    """
    # Pattern: 2+ blank lines followed by a header line
    # Matches: \n\n\n# Header  or  \n\n\n## Subsection  etc.
    pattern = re.compile(r'\n(\n{2,})(#{1,6}\s+[^\n]+)')

    for match in pattern.finditer(content):
        blank_lines = match.group(1)
        header = match.group(2)
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="header_whitespace",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Extra blank lines before header: '{header[:40]}...'",
            fix=Fix(old=match.group(), new=f'\n\n{header}')
        )


def long_line(content: str, max_length: int = 500) -> Generator[LintIssue, None, None]:
    """
    Flag extremely long lines.

    Very long lines often indicate broken content that wasn't
    properly line-wrapped, or tables that didn't parse correctly.
    """
    lines = content.split('\n')

    for i, line in enumerate(lines, 1):
        if len(line) > max_length:
            # Show a preview of the line start
            preview = line[:60] + "..." if len(line) > 60 else line

            yield LintIssue(
                rule="long_line",
                severity=Severity.WARNING,
                line=i,
                message=f"Line is {len(line)} chars (max {max_length}): {preview}",
                fix=None  # Needs manual review
            )
