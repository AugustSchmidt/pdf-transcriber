"""PDF artifact detection and removal rules."""
import re
from collections import defaultdict
from typing import Generator

from ..models import LintIssue, Severity, Fix


def page_number(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect and remove standalone page numbers.

    Page numbers often get transcribed as isolated lines containing
    just a number. These add no value and waste tokens.
    """
    # Match lines that are just a number (with optional whitespace)
    # Must be on its own line (not part of a table or list)
    pattern = re.compile(r'^[ \t]*(\d{1,4})[ \t]*$', re.MULTILINE)

    for match in pattern.finditer(content):
        num = int(match.group(1))

        # Heuristic: likely a page number if 1-999
        # Exclude 0 and very large numbers
        if not (1 <= num <= 999):
            continue

        # Check context - skip if in a table row or list
        start = match.start()
        line_start = content.rfind('\n', 0, start) + 1
        line_before = content[line_start:start]

        if '|' in line_before:
            continue  # Part of a table

        line_num = content[:start].count('\n') + 1

        yield LintIssue(
            rule="page_number",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Standalone number '{num}' (likely page number)",
            fix=Fix(old=match.group() + '\n', new='')
        )


def orphaned_label(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect orphaned LaTeX labels that weren't properly processed.

    LaTeX labels like "def:Tilt" or "thm:main" sometimes end up
    as standalone lines when the surrounding environment isn't
    properly transcribed.
    """
    # Match common label prefixes on their own line
    pattern = re.compile(
        r'^[ \t]*((?:def|thm|lem|prop|cor|ex|rem|eq|sec|chap|fig|tab|'
        r'defn|lemma|theorem|proposition|corollary|example|remark|'
        r'equation|section|chapter|figure|table):'
        r'[A-Za-z0-9_-]+)[ \t]*$',
        re.MULTILINE | re.IGNORECASE
    )

    for match in pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1
        label = match.group(1)

        yield LintIssue(
            rule="orphaned_label",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Orphaned LaTeX label: {label}",
            fix=Fix(old=match.group() + '\n', new='')
        )


def garbled_text(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect likely garbled/corrupted text fragments.

    Vision models sometimes produce nonsense text, especially
    from headers, captions, or partially visible text.
    """
    lines = content.split('\n')

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip empty, very short, or very long lines
        if len(stripped) < 4 or len(stripped) > 40:
            continue

        # Skip lines that are clearly valid markdown/content
        if stripped.startswith(('#', '-', '*', '|', '$', '\\', '>', '[')):
            continue
        if stripped.startswith('<!--') or stripped.endswith('-->'):
            continue

        # Skip normal prose (common characters only)
        if re.match(r'^[\w\s.,;:!?\'"()\-\u2013\u2014]+$', stripped):
            continue

        # Skip math-like content
        if re.search(r'[∈∉⊂⊃∪∩∧∨∀∃→←↔≤≥≠≈∞∫∑∏√]', stripped):
            continue

        # Check for unusual character patterns suggesting garbled text
        # Nordic/special chars that rarely appear in math papers
        weird_chars = set('æœøåäöüßþðđ')
        has_weird = any(c.lower() in weird_chars for c in stripped)

        # Low ratio of alphanumeric to total characters
        alnum_count = sum(1 for c in stripped if c.isalnum())
        alnum_ratio = alnum_count / len(stripped) if stripped else 0

        # Heuristic: weird chars + low alnum ratio = probably garbled
        if has_weird and alnum_ratio < 0.7:
            yield LintIssue(
                rule="garbled_text",
                severity=Severity.WARNING,
                line=i,
                message=f"Possibly garbled text: '{stripped}'",
                fix=None  # Needs manual review
            )


def hyphenation_artifact(content: str) -> Generator[LintIssue, None, None]:
    """
    Fix word hyphenation split across lines.

    PDFs often hyphenate words at line breaks. When transcribed,
    this can result in "theo-\\nrem" instead of "theorem".
    """
    # Pattern: word ending in hyphen, newline, lowercase continuation
    # Be careful not to match intentional hyphens (e.g., "well-known")
    pattern = re.compile(r'(\b[a-zA-Z]{2,})-\n([a-z]{2,}\b)')

    for match in pattern.finditer(content):
        part1 = match.group(1)
        part2 = match.group(2)
        combined = part1 + part2
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="hyphenation_artifact",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Hyphenated word: {part1}-{part2} → {combined}",
            fix=Fix(old=match.group(), new=combined + ' ')
        )


def page_marker(content: str) -> Generator[LintIssue, None, None]:
    """
    Remove HTML comment page markers from transcription.

    Vision-based transcription often inserts markers like:
    - <!-- Page 25 -->
    - <!-- Page 123 -->
    - <!-- Content merged with page 1 -->

    These add no value and clutter the document.
    """
    # Match various page-related HTML comments
    patterns = [
        r'<!-- ?Page \d+ ?-->',
        r'<!-- ?Content merged with page \d+ ?-->',
        r'<!-- ?End of page \d+ ?-->',
        r'<!-- ?Start of page \d+ ?-->',
    ]
    combined_pattern = re.compile('|'.join(patterns), re.IGNORECASE)

    for match in combined_pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="page_marker",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Page marker: {match.group()}",
            fix=Fix(old=match.group(), new='')
        )


def repeated_line(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect repeated short lines (likely headers/footers).

    Running headers and footers from PDFs often get transcribed
    on every page, creating duplicate content.
    """
    lines = content.split('\n')
    line_occurrences: dict[str, list[int]] = defaultdict(list)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Only consider lines of reasonable length
        if not (5 < len(stripped) < 60):
            continue

        # Skip common valid repeated content
        if stripped.startswith(('#', '|', '-', '*', '>')):
            continue
        if stripped.startswith('<!--') or stripped.endswith('-->'):
            continue

        # Normalize whitespace for comparison
        normalized = ' '.join(stripped.split())
        line_occurrences[normalized].append(i)

    # Flag lines that appear 3+ times
    for text, occurrences in line_occurrences.items():
        if len(occurrences) >= 3:
            # Report just the first occurrence, but mention count
            yield LintIssue(
                rule="repeated_line",
                severity=Severity.WARNING,
                line=occurrences[0],
                message=(
                    f"Line appears {len(occurrences)} times "
                    f"(lines {', '.join(map(str, occurrences[:5]))}{'...' if len(occurrences) > 5 else ''}): "
                    f"'{text[:50]}{'...' if len(text) > 50 else ''}'"
                ),
                fix=None  # Complex fix - needs to identify which are headers/footers
            )


def merged_content_comment(content: str) -> Generator[LintIssue, None, None]:
    """
    Remove "Content merged with page X" comments.

    When Marker doesn't split pages properly, it adds comments like:
    <!-- Content merged with page 26 -->
    These are transcription artifacts that should be removed.
    """
    # Match the merged content comment pattern
    pattern = re.compile(
        r'<!--\s*Content merged with page \d+\s*-->',
        re.IGNORECASE
    )

    for match in pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1

        # Also remove the newline after if present
        end_pos = match.end()
        if end_pos < len(content) and content[end_pos] == '\n':
            old_text = match.group() + '\n'
        else:
            old_text = match.group()

        yield LintIssue(
            rule="merged_content_comment",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message="Merged content comment artifact",
            fix=Fix(old=old_text, new='')
        )
