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
        tag_name = match.group()[2:-1]  # Extract tag name (e.g., "span" from "</span>")

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


def html_math_notation(content: str) -> Generator[LintIssue, None, None]:
    """
    Convert HTML sup/sub notation to proper LaTeX math.

    Transcription often produces HTML like:
    - O<sup>X</sup> → $\\mathcal{O}_X$ (structure sheaf - note subscript!)
    - K<sup>∗</sup> → $K^*$
    - A<sup>+</sup> → $A^+$
    - f<sup>-1</sup> → $f^{-1}$
    - colim<sub>i</sub> → $\\operatorname{colim}_i$
    - y <sup>p</sup> → $y^{p}$ (with space before tag)
    - <sup>−</sup><sup>1</sup> → $^{-1}$ (chained superscripts)
    """
    issues = []

    # Special cases that need specific LaTeX formatting
    SPECIAL_BASES = {
        # Structure sheaf O always uses mathcal and subscript
        'O': ('\\mathcal{O}', 'sub'),  # O^X → \mathcal{O}_X
        # Operators
        'lim': ('\\lim', 'preserve'),
        'colim': ('\\operatorname{colim}', 'preserve'),
        'Hom': ('\\operatorname{Hom}', 'preserve'),
        'Spec': ('\\operatorname{Spec}', 'preserve'),
        'Spf': ('\\operatorname{Spf}', 'preserve'),
        'Spa': ('\\operatorname{Spa}', 'preserve'),
        'Gal': ('\\operatorname{Gal}', 'preserve'),
    }

    def is_in_math_mode(content: str, pos: int) -> bool:
        """Check if position is inside $...$ math mode."""
        before = content[max(0, pos - 100):pos]
        dollars_before = len(re.findall(r'(?<!\\)\$', before))
        return dollars_before % 2 == 1

    def is_footnote_context(content: str, match_start: int) -> bool:
        """Check if this looks like a footnote marker (not math)."""
        # Look at immediate context before the match
        before = content[max(0, match_start - 20):match_start]
        # Footnotes typically come after </span>, sentence-end punctuation, or at line start
        footnote_indicators = ['</span>', '. ', '? ', '! ', '\n']
        return any(before.rstrip().endswith(ind.rstrip()) for ind in footnote_indicators) or before.strip() == ''

    # Pattern 1: base<sup>exponent</sup> or base<sub>subscript</sub> (no space)
    pattern_no_space = re.compile(
        r'([A-Za-z]+)<(sup|sub)>([^<]+)</\2>',
        re.IGNORECASE
    )

    # Pattern 2: base <sup>exponent</sup> (with space before tag)
    # Only match SINGLE letters as base (not full words like "ignoring")
    # Multi-letter words before <sup> are usually prose, not math
    pattern_with_space = re.compile(
        r'(?<![A-Za-z])([A-Za-z]) <(sup|sub)>([^<]+)</\2>',
        re.IGNORECASE
    )

    # Pattern 3: Chained superscripts like <sup>−</sup><sup>1</sup> → ^{-1}
    pattern_chained = re.compile(
        r'<sup>([−\-])</sup><sup>(\d+)</sup>',
        re.IGNORECASE
    )

    # Pattern 4: Standalone numeric superscript in math context (like R><sup>0</sup>)
    # Only match when preceded by math-like characters
    pattern_math_context = re.compile(
        r'([>≥<≤=])[ ]*<sup>(\d+)</sup>',
        re.IGNORECASE
    )

    # Pattern 5: Absolute value with superscript: |x| <sup>n</sup> → |x|^{n}
    # Common in analysis: |f|^n, |K*|, etc.
    pattern_abs_value = re.compile(
        r'(\|[^|]+\|) <(sup|sub)>([^<]+)</\2>',
        re.IGNORECASE
    )

    # Pattern 6: Parenthesized expression with superscript: (stuff) <sup>n</sup>
    # Common for grouped expressions like (K°°)^2, (-)^*, etc.
    # Limit to short expressions (max 20 chars inside parens) to avoid matching prose
    pattern_paren = re.compile(
        r'(\([^)]{1,20}\)) <(sup|sub)>([^<]+)</\2>',
        re.IGNORECASE
    )

    # Pattern 7: Functor notation (−)<sup>∗</sup> or (M/tM)<sup>∗</sup>
    # Common in category theory and algebra for dual/adjoint functors
    pattern_functor = re.compile(
        r'(\([^)]{1,30}\))<(sup|sub)>([∗*+\-−]+)</\2>',
        re.IGNORECASE
    )

    # Pattern 8: Infinity after math mode: $...$<sup>∞</sup> → merge into math
    # Common for p^∞, t^∞, etc.
    pattern_infinity = re.compile(
        r'(\$[^$]+)\$<sup>(∞|\\infty)</sup>',
        re.IGNORECASE
    )

    # Pattern 9: Tensor product subscript: ⊗<sup>R</sup> → ⊗_R
    # In standard notation, the ring goes as subscript: ⊗_R
    pattern_tensor = re.compile(
        r'(⊗)\s*<sup>([A-Za-z]+)</sup>',
        re.IGNORECASE
    )

    # Pattern 10: Standalone infinity/star superscript after letter with space
    # Like: t <sup>∞</sup> or f <sup>∗</sup>
    pattern_special_script = re.compile(
        r'(?<![A-Za-z])([A-Za-z]) <sup>([∞∗*])</sup>',
        re.IGNORECASE
    )

    # Pattern 11: Garbled perfectoid notation - maximal ideal
    # <sup>K</sup>◦◦ → $K^{\circ\circ}$ (maximal ideal in perfectoid spaces)
    pattern_circ_circ = re.compile(
        r'<sup>([A-Za-z]+)</sup>◦◦',
        re.IGNORECASE
    )

    # Pattern 12: Garbled perfectoid notation - ring of integers
    # <sup>K</sup>◦ → $K^{\circ}$ (ring of integers)
    # Must not match ◦◦ (handled by pattern 11)
    pattern_circ = re.compile(
        r'<sup>([A-Za-z]+)</sup>◦(?!◦)',
        re.IGNORECASE
    )

    # Pattern 13: Garbled completion notation
    # <sup>A</sup><sup>b</sup> → $\widehat{A}$ (completion - "b" from broken hat)
    pattern_completion_double = re.compile(
        r'<sup>([A-Za-z]+)</sup><sup>b</sup>',
        re.IGNORECASE
    )

    # Pattern 14: Garbled completion notation variant
    # <sup>A</sup>b → $\widehat{A}$ (completion - variant)
    pattern_completion_single = re.compile(
        r'<sup>([A-Za-z]+)</sup>b(?![A-Za-z])',
        re.IGNORECASE
    )

    # Pattern 15: Garbled flat/tilt notation
    # <sup>K</sup>♭ or <sup>K</sup>[ → $K^\flat$ (tilt)
    pattern_flat = re.compile(
        r'<sup>([A-Za-z]+)</sup>[♭\[]',
        re.IGNORECASE
    )

    # Pattern 16: Garbled operators in sup tags (OCR error)
    # <sup>⊂</sup>, <sup>→</sup>, <sup>=</sup> → just the operator
    pattern_garbled_operator = re.compile(
        r'<sup>([⊂⊃→←↔=≈∅∈∉])</sup>',
        re.IGNORECASE
    )

    # Pattern 17: Letter in sup followed by subscript-like notation
    # <sup>A</sup>Zar, <sup>A</sup>hens → $A_{\mathrm{Zar}}$, $A_{\mathrm{hens}}$
    pattern_garbled_subscript = re.compile(
        r'<sup>([A-Za-z])</sup>(Zar|hens|perf|red|et|fppf|fpqc)',
        re.IGNORECASE
    )

    # Pattern 18: Chained p-infinity with space: (t 1 <sup>p</sup><sup>∞</sup>)
    # Common broken pattern in p-adic context
    pattern_p_infinity_spaced = re.compile(
        r'<sup>p</sup><sup>([∞∗])</sup>',
        re.IGNORECASE
    )

    # Pattern 19: Math mode followed by sup tag - merge into math
    # $R^{≥}$<sup>0</sup> → $R^{\geq 0}$
    # $t^{−}$<sup>c</sup> → $t^{-c}$
    pattern_math_trailing_sup = re.compile(
        r'(\$[^$]+)\$<sup>([^<]+)</sup>',
        re.IGNORECASE
    )

    # Pattern 20: Index set notation - element of with sup
    # i∈<sup>I</sup>, {Mi}i∈<sup>I</sup> → the I should not be superscript
    pattern_index_set = re.compile(
        r'([a-zA-Z])∈<sup>([A-Za-z])</sup>',
        re.IGNORECASE
    )

    # Process chained superscripts first (like <sup>−</sup><sup>1</sup>)
    for match in pattern_chained.finditer(content):
        sign = match.group(1)
        num = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1

        # Normalize minus sign
        sign = '-' if sign in ('−', '-') else sign
        replacement = f'^{{{sign}{num}}}'

        # If not in math mode, wrap in $
        if not is_in_math_mode(content, match.start()):
            replacement = f'${replacement}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Chained superscript: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process math-context patterns (like ><sup>0</sup>)
    for match in pattern_math_context.finditer(content):
        operator = match.group(1)
        num = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1

        # Keep the operator, just convert the superscript
        replacement = f'{operator}^{{{num}}}'

        if not is_in_math_mode(content, match.start()):
            replacement = f'${replacement}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Math context sup: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process absolute value patterns (|x| <sup>n</sup> → |x|^{n})
    for match in pattern_abs_value.finditer(content):
        base = match.group(1)  # The |...| part
        tag_type = match.group(2).lower()
        script_content = match.group(3)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
        replacement = f'{base}{latex_script}' if in_math_mode else f'${base}{latex_script}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Abs value math: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process parenthesized expressions ((stuff) <sup>n</sup> → (stuff)^{n})
    # Valid math superscript content: letters, numbers, *, +, -, ∞, ∗, etc.
    valid_script_pattern = re.compile(r'^[A-Za-z0-9+\-−∗*∞]+$')

    for match in pattern_paren.finditer(content):
        base = match.group(1)  # The (...) part
        tag_type = match.group(2).lower()
        script_content = match.group(3)
        full_match = match.group(0)

        # Skip if superscript content doesn't look like math (e.g., arrows)
        if not valid_script_pattern.match(script_content):
            continue

        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
        replacement = f'{base}{latex_script}' if in_math_mode else f'${base}{latex_script}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Paren math: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process patterns with space before tag
    for match in pattern_with_space.finditer(content):
        base = match.group(1)
        tag_type = match.group(2).lower()
        script_content = match.group(3)
        full_match = match.group(0)

        # Skip if it looks like a footnote
        if tag_type == 'sup' and script_content.isdigit() and is_footnote_context(content, match.start()):
            continue

        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        if base in SPECIAL_BASES:
            latex_base, script_behavior = SPECIAL_BASES[base]
            if script_behavior == 'sub':
                latex_script = f'_{{{script_content}}}'
            else:
                latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
            replacement = f'{latex_base}{latex_script}' if in_math_mode else f'${latex_base}{latex_script}$'
        else:
            latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
            replacement = f'{base}{latex_script}' if in_math_mode else f'${base}{latex_script}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"HTML math (spaced): {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process patterns without space (original pattern)
    for match in pattern_no_space.finditer(content):
        base = match.group(1)
        tag_type = match.group(2).lower()
        script_content = match.group(3)
        full_match = match.group(0)

        # Skip if it looks like a footnote
        if tag_type == 'sup' and script_content.isdigit() and is_footnote_context(content, match.start()):
            continue

        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        if base in SPECIAL_BASES:
            latex_base, script_behavior = SPECIAL_BASES[base]
            if script_behavior == 'sub':
                latex_script = f'_{{{script_content}}}'
            elif script_behavior == 'preserve':
                latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
            else:
                latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
            replacement = f'{latex_base}{latex_script}' if in_math_mode else f'${latex_base}{latex_script}$'
        else:
            latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
            replacement = f'{base}{latex_script}' if in_math_mode else f'${base}{latex_script}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"HTML math: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process functor notation: (−)<sup>∗</sup> → $(-)^{*}$
    for match in pattern_functor.finditer(content):
        base = match.group(1)  # The (...) part
        tag_type = match.group(2).lower()
        script_content = match.group(3)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        # Normalize star symbols
        normalized_script = script_content.replace('∗', '*')
        latex_script = f'^{{{normalized_script}}}' if tag_type == 'sup' else f'_{{{normalized_script}}}'
        replacement = f'{base}{latex_script}' if in_math_mode else f'${base}{latex_script}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Functor: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process infinity after math: $x^{p}$<sup>∞</sup> → $x^{p^\infty}$
    for match in pattern_infinity.finditer(content):
        math_content = match.group(1)  # The $...$ part without closing $
        inf_symbol = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1

        # Check if math ends with a superscript like ^{p} or ^p
        # If so, nest infinity inside: ^{p} → ^{p^\infty}
        superscript_match = re.search(r'\^(\{[^}]+\}|[A-Za-z0-9])$', math_content)

        if superscript_match:
            # Nest infinity inside existing superscript
            existing_sup = superscript_match.group(1)
            if existing_sup.startswith('{'):
                # ^{p} → ^{p^\infty}
                inner = existing_sup[1:-1]  # Remove braces
                new_sup = f'^{{{inner}^{{\\infty}}}}'
            else:
                # ^p → ^{p^\infty}
                new_sup = f'^{{{existing_sup}^{{\\infty}}}}'
            replacement = math_content[:superscript_match.start()] + new_sup + '$'
        else:
            # No existing superscript, just add ^{\infty}
            replacement = f'{math_content}^{{\\infty}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Infinity merge: {full_match[:50]} → {replacement[:50]}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process tensor subscripts: ⊗<sup>R</sup> → $⊗_R$ (should be subscript)
    for match in pattern_tensor.finditer(content):
        tensor = match.group(1)
        ring = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        # Tensor product subscript: ⊗_R
        replacement = f'{tensor}_{{{ring}}}' if in_math_mode else f'${tensor}_{{{ring}}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Tensor sub: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process special scripts (∞, ∗) after single letter with space
    for match in pattern_special_script.finditer(content):
        base = match.group(1)
        script = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        # Normalize symbols
        if script == '∞':
            latex_script = '^{\\infty}'
        elif script in ('∗', '*'):
            latex_script = '^{*}'
        else:
            latex_script = f'^{{{script}}}'

        replacement = f'{base}{latex_script}' if in_math_mode else f'${base}{latex_script}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Special script: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process garbled perfectoid notation: <sup>K</sup>◦◦ → $K^{\circ\circ}$
    for match in pattern_circ_circ.finditer(content):
        base = match.group(1)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        replacement = f'{base}^{{\\circ\\circ}}' if in_math_mode else f'${base}^{{\\circ\\circ}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Maximal ideal: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process garbled perfectoid notation: <sup>K</sup>◦ → $K^{\circ}$
    for match in pattern_circ.finditer(content):
        base = match.group(1)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        replacement = f'{base}^{{\\circ}}' if in_math_mode else f'${base}^{{\\circ}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Ring of integers: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process garbled completion: <sup>A</sup><sup>b</sup> → $\widehat{A}$
    for match in pattern_completion_double.finditer(content):
        base = match.group(1)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        replacement = f'\\widehat{{{base}}}' if in_math_mode else f'$\\widehat{{{base}}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Completion: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process garbled completion variant: <sup>A</sup>b → $\widehat{A}$
    for match in pattern_completion_single.finditer(content):
        base = match.group(1)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        replacement = f'\\widehat{{{base}}}' if in_math_mode else f'$\\widehat{{{base}}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Completion: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process garbled flat/tilt: <sup>K</sup>♭ or <sup>K</sup>[ → $K^\flat$
    for match in pattern_flat.finditer(content):
        base = match.group(1)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        replacement = f'{base}^{{\\flat}}' if in_math_mode else f'${base}^{{\\flat}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Tilt: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process garbled operators: <sup>⊂</sup> → ⊂ (these shouldn't be superscripts)
    for match in pattern_garbled_operator.finditer(content):
        operator = match.group(1)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1

        # Just return the operator without sup tags
        replacement = operator

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Garbled operator: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process garbled subscripts: <sup>A</sup>Zar → $A_{\mathrm{Zar}}$
    for match in pattern_garbled_subscript.finditer(content):
        base = match.group(1)
        subscript = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        # Format as proper subscript with mathrm for text subscripts
        replacement = f'{base}_{{\\mathrm{{{subscript}}}}}' if in_math_mode else f'${base}_{{\\mathrm{{{subscript}}}}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Garbled subscript: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process chained p-infinity: <sup>p</sup><sup>∞</sup> → ^{p^\infty}
    for match in pattern_p_infinity_spaced.finditer(content):
        inf_symbol = match.group(1)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        # Convert to nested superscript
        replacement = '^{p^{\\infty}}' if in_math_mode else '$^{p^{\\infty}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"p-infinity: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process math + trailing sup: $R^{≥}$<sup>0</sup> → $R^{\geq 0}$
    for match in pattern_math_trailing_sup.finditer(content):
        math_content = match.group(1)  # $...$ without closing $
        sup_content = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1

        # Check if math ends with a superscript - if so, merge
        # e.g., $R^{≥}$ + <sup>0</sup> → $R^{\geq 0}$
        superscript_match = re.search(r'\^(\{[^}]*\}|[A-Za-z0-9≥≤−+])$', math_content)

        if superscript_match:
            existing_sup = superscript_match.group(1)
            if existing_sup.startswith('{'):
                # ^{≥} + 0 → ^{\geq 0}
                inner = existing_sup[1:-1]
                # Normalize symbols
                inner = inner.replace('≥', '\\geq ').replace('≤', '\\leq ').replace('−', '-')
                new_sup = f'^{{{inner}{sup_content}}}'
            else:
                # ^≥ + 0 → ^{\geq 0}
                normalized = existing_sup.replace('≥', '\\geq ').replace('≤', '\\leq ').replace('−', '-')
                new_sup = f'^{{{normalized}{sup_content}}}'
            replacement = math_content[:superscript_match.start()] + new_sup + '$'
        else:
            # No existing superscript, just append
            replacement = f'{math_content}^{{{sup_content}}}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Math+sup merge: {full_match[:40]}... → {replacement[:40]}...",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Process index set notation: i∈<sup>I</sup> → i \in I
    for match in pattern_index_set.finditer(content):
        element = match.group(1)
        index_set = match.group(2)
        full_match = match.group(0)
        line_num = content[:match.start()].count('\n') + 1
        in_math_mode = is_in_math_mode(content, match.start())

        # The index set should NOT be a superscript - it's just ∈ I
        replacement = f'{element} \\in {index_set}' if in_math_mode else f'${element} \\in {index_set}$'

        issues.append(LintIssue(
            rule="html_math_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Index set: {full_match} → {replacement}",
            fix=Fix(old=full_match, new=replacement)
        ))

    # Sort by line number
    issues.sort(key=lambda x: x.line)
    for issue in issues:
        yield issue


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
    # Space + ^{^{digits}}$$ OR start of line + ^{^{digits}}$$
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
    # Match <sup>number</sup> immediately followed by a word character (letter/number)
    # without any space in between
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
