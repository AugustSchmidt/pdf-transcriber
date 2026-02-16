"""HTML artifact detection and conversion rules.

Rules for cleaning HTML artifacts from PDF transcription output,
including malformed tags and footnote formatting fixes.

The html_math_notation rule (HTML sup/sub → LaTeX) lives in html_math.py.
"""
import re
from typing import Generator

from ..models import LintIssue, Severity, Fix
from .html_math import html_math_notation  # noqa: F401


def html_artifacts(content: str) -> Generator[LintIssue, None, None]:
    """
    Remove HTML artifacts from transcription.

    Vision-based transcription often produces unwanted HTML:
    - Page anchor spans: <span id="page-51-0"></span>
    - Malformed entities: &amp;lt; instead of <
    - Escaped HTML in sup/sub: <sup>&</sup>lt;sup>
    - Empty spans and divs
    """
    issues = []

    # 1. Page anchor spans: <span id="page-X-Y"></span> or <span id="page-X"></span>
    span_pattern = re.compile(r'<span\s+id="page-\d+(?:-\d+)?"\s*>\s*</span>', re.IGNORECASE)
    for match in span_pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1
        issues.append(LintIssue(
            rule="html_artifacts",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Page anchor span: {match.group()[:50]}",
            fix=Fix(old=match.group(), new='')
        ))

    # 2. Malformed/double-escaped HTML entities
    entity_patterns = [
        (r'&amp;lt;', '<'),      # &amp;lt; -> <
        (r'&amp;gt;', '>'),      # &amp;gt; -> >
        (r'&amp;amp;', '&'),     # &amp;amp; -> &
        (r'&amp;nbsp;', ' '),    # &amp;nbsp; -> space
        (r'&lt;', '<'),          # &lt; -> < (when not in code)
        (r'&gt;', '>'),          # &gt; -> >
    ]
    for pattern, replacement in entity_patterns:
        for match in re.finditer(pattern, content):
            line_num = content[:match.start()].count('\n') + 1
            issues.append(LintIssue(
                rule="html_artifacts",
                severity=Severity.AUTO_FIX,
                line=line_num,
                message=f"Escaped HTML entity: {match.group()} → {replacement}",
                fix=Fix(old=match.group(), new=replacement)
            ))

    # 3. Broken sup/sub tags with escaped content: <sup>&</sup>lt;sup>
    broken_tag_pattern = re.compile(r'<(sup|sub)>&</\1>(lt|gt);', re.IGNORECASE)
    for match in broken_tag_pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1
        char = '<' if match.group(2) == 'lt' else '>'
        issues.append(LintIssue(
            rule="html_artifacts",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Broken HTML tag: {match.group()} → {char}",
            fix=Fix(old=match.group(), new=char)
        ))

    # 4. Empty/useless HTML tags (but preserve valid ones like <sup>1</sup>)
    empty_tag_pattern = re.compile(r'<(span|div|p)\s*>\s*</\1>', re.IGNORECASE)
    for match in empty_tag_pattern.finditer(content):
        line_num = content[:match.start()].count('\n') + 1
        issues.append(LintIssue(
            rule="html_artifacts",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Empty HTML tag: {match.group()}",
            fix=Fix(old=match.group(), new='')
        ))

    # 5. Stray closing tags without openers (check context manually)
    stray_close_pattern = re.compile(r'</(?:span|div|p)>', re.IGNORECASE)
    for match in stray_close_pattern.finditer(content):
        # Check if there's a matching opener nearby (within 200 chars)
        start = max(0, match.start() - 200)
        context = content[start:match.start()]
        tag_name = match.group()[2:-1]  # Extract tag name

        # Count openers and closers in context
        opener_count = len(re.findall(rf'<{tag_name}[\s>]', context, re.IGNORECASE))
        closer_count = len(re.findall(rf'</{tag_name}>', context, re.IGNORECASE))

        # If more closers than openers, this is likely stray
        if closer_count >= opener_count:
            line_num = content[:match.start()].count('\n') + 1
            issues.append(LintIssue(
                rule="html_artifacts",
                severity=Severity.AUTO_FIX,
                line=line_num,
                message=f"Stray closing tag: {match.group()}",
                fix=Fix(old=match.group(), new='')
            ))

    # Sort by line number and yield
    issues.sort(key=lambda x: x.line)
    for issue in issues:
        yield issue


def html_subscript_in_math(content: str) -> Generator[LintIssue, None, None]:
    """
    Fix HTML <sub> tags adjacent to LaTeX math blocks.

    Marker's HTML-to-markdown conversion sometimes leaves <sub> tags
    next to $...$ delimiters instead of converting to LaTeX subscripts:

    - $K$<sub>v</sub> → $K_{v}$  (subscript after math)
    - $K$ <sub>v</sub> → $K_{v}$  (with space)
    - <sub>K</sub>$[x]$ → $_{K}[x]$  (orphaned subscript before math)

    The existing html_math_notation handles base<sub>X</sub> (when an
    alphabetic base precedes the tag) and $...$<sup>X</sup> (superscript
    after math). This rule fills the gap for <sub> adjacent to math
    delimiters, where the $ sign prevents the base-matching patterns
    from firing.
    """
    # Pattern 1: $...$<sub>X</sub> — subscript after math block
    # Optional whitespace between closing $ and <sub>
    pattern_sub_after = re.compile(
        r'(\$[^$]+)\$\s*<sub>([^<]+)</sub>',
        re.IGNORECASE
    )

    for match in pattern_sub_after.finditer(content):
        math_content = match.group(1)  # Includes opening $ but not closing
        sub_content = match.group(2)
        line_num = content[:match.start()].count('\n') + 1

        replacement = f'{math_content}_{{{sub_content}}}$'

        yield LintIssue(
            rule="html_subscript_in_math",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Sub after math: ...$<sub>{sub_content}</sub> → ..._{{{sub_content}}}$",
            fix=Fix(old=match.group(), new=replacement)
        )

    # Pattern 2: <sub>X</sub>$...$ — orphaned subscript before math block
    # Only when <sub> has no alphabetic base immediately before it
    # (if it does, html_math_notation handles base<sub>X</sub>)
    pattern_sub_before = re.compile(
        r'(?<![A-Za-z])<sub>([^<]+)</sub>\s*\$([^$]+\$)',
        re.IGNORECASE
    )

    for match in pattern_sub_before.finditer(content):
        sub_content = match.group(1)
        math_content = match.group(2)  # Includes closing $ but not opening
        line_num = content[:match.start()].count('\n') + 1

        replacement = f'$_{{{sub_content}}}{math_content}'

        yield LintIssue(
            rule="html_subscript_in_math",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Sub before math: <sub>{sub_content}</sub>$... → $_{{{sub_content}}}...",
            fix=Fix(old=match.group(), new=replacement)
        )


def malformed_footnote(content: str) -> Generator[LintIssue, None, None]:
    """
    Fix footnotes incorrectly converted to nested LaTeX superscripts.

    When the html_math_notation rule processes footnote markers like <sup>28</sup>,
    it can produce malformed output like ` ^{^{28}}$$` instead of preserving
    the footnote. This rule detects and fixes these patterns.

    Patterns fixed:
    - ` ^{^{28}}$$` → `<sup>28</sup>`
    - `^{^{N}}$$` at line start → `<sup>N</sup>`
    """
    # Match the malformed nested superscript pattern
    pattern = re.compile(r'(?:^| )\^{\^{(\d+)}}\$\$', re.MULTILINE)

    for match in pattern.finditer(content):
        footnote_num = match.group(1)
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="malformed_footnote",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Malformed footnote: {match.group().strip()} → <sup>{footnote_num}</sup>",
            fix=Fix(old=match.group(), new=f'<sup>{footnote_num}</sup>')
        )


def footnote_spacing(content: str) -> Generator[LintIssue, None, None]:
    """
    Ensure space after footnote markers.

    Footnote tags like <sup>90</sup> often run directly into the following
    text without a space. This rule adds a space after the closing tag
    when followed immediately by a letter or number.

    Examples:
    - <sup>90</sup>Some text → <sup>90</sup> Some text
    - <sup>12</sup>The proof → <sup>12</sup> The proof
    """
    pattern = re.compile(r'(<sup>\d+</sup>)([A-Za-z0-9])')

    for match in pattern.finditer(content):
        footnote_tag = match.group(1)
        next_char = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="footnote_spacing",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Missing space after footnote: {full_match} → {footnote_tag} {next_char}",
            fix=Fix(old=full_match, new=f'{footnote_tag} {next_char}')
        )
