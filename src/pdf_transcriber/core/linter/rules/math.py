"""Math notation detection and repair rules."""
import re
from typing import Generator

from ..models import LintIssue, Severity, Fix
from .math_constants import UNICODE_TO_LATEX, MATH_PATTERNS, is_in_math_mode
from .math_unicode import unicode_math_symbols  # noqa: F401


def unwrapped_math_expressions(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect common unwrapped math expression patterns.

    Patterns like K◦, K∗, |K|, R^{≥0} that appear outside $...$
    should be wrapped in math delimiters.

    Auto-fixes common patterns.
    """
    for pattern, replacement in MATH_PATTERNS:
        for match in re.finditer(pattern, content):
            pos = match.start()

            # Skip if inside math mode
            if is_in_math_mode(content, pos):
                continue

            line_num = content[:pos].count('\n') + 1
            original = match.group(0)
            fixed = re.sub(pattern, replacement, original)

            yield LintIssue(
                rule="unwrapped_math_expressions",
                severity=Severity.AUTO_FIX,
                line=line_num,
                message=f"Unwrapped math: {original} → {fixed}",
                fix=Fix(old=original, new=fixed)
            )


def repetition_hallucination(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect OCR hallucination patterns where phrases repeat excessively.

    Vision models can get "stuck" generating the same tokens repeatedly,
    producing output like "over G over G over G over G..."

    This detects patterns where a short phrase (1-5 words) repeats
    5+ times consecutively.
    """
    issues_found = set()  # Track (line, phrase) to avoid duplicates

    # Pattern 1: 2-5 word phrases repeated
    pattern_long = re.compile(
        r'\b((?:\w+\s+){1,4}\w+)\s+'  # Capture group: 2-5 words
        r'(?:\1\s+){4,}',              # Same phrase repeated 4+ more times
        re.IGNORECASE
    )

    # Pattern 2: Simple 2-word phrases like "over G" repeated
    pattern_short = re.compile(
        r'\b(\w+\s+\w+)\s+'           # Capture: 2 words
        r'(?:\1\s+){4,}',              # Repeated 4+ more times
        re.IGNORECASE
    )

    # Pattern 3: Single word repeated many times (rare but possible)
    pattern_single = re.compile(
        r'\b(\w{2,})\s+'              # Single word (2+ chars)
        r'(?:\1\s+){9,}',              # Repeated 9+ more times (higher threshold)
        re.IGNORECASE
    )

    for pattern in [pattern_long, pattern_short, pattern_single]:
        for match in pattern.finditer(content):
            repeated_phrase = match.group(1)
            full_match = match.group(0)
            line_num = content[:match.start()].count('\n') + 1

            # Skip if we already reported this line/phrase combo
            key = (line_num, repeated_phrase.lower())
            if key in issues_found:
                continue
            issues_found.add(key)

            # Count actual repetitions
            repetitions = len(re.findall(re.escape(repeated_phrase), full_match, re.IGNORECASE))

            # Truncate for display
            display = full_match[:100] + '...' if len(full_match) > 100 else full_match

            yield LintIssue(
                rule="repetition_hallucination",
                severity=Severity.ERROR,  # This is serious - needs manual review
                line=line_num,
                message=(
                    f"OCR hallucination: '{repeated_phrase}' repeated {repetitions}x. "
                    f"Text: '{display}'"
                ),
                fix=None  # Needs manual review to determine correct text
            )


def broken_math_delimiters(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect malformed math delimiters.

    Patterns like:
    - |$K^*$| (should be $|K^*|$)
    - $R^{≥}$<sup>0</sup> (Unicode in math + trailing HTML)
    - Unbalanced $ signs
    """
    # Pattern 1: Absolute value outside of math mode: |$...$|
    pattern_abs_outside = re.compile(r'\|\$([^$]+)\$\|')

    for match in pattern_abs_outside.finditer(content):
        inner = match.group(1)

        # Skip if inner starts and ends with | — that's a norm notation
        # (handled by broken_norm_notation rule)
        if inner.startswith('|') and inner.endswith('|'):
            continue

        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="broken_math_delimiters",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Absolute value outside math: |${inner}$| → $|{inner}|$",
            fix=Fix(old=match.group(), new=f'$|{inner}|$')
        )

    # Pattern 2: Unicode comparison in math with trailing content
    # $R^{≥}$0 or $R^{≥}$ 0 → $R^{\geq 0}$
    pattern_trailing = re.compile(r'\$([^$]*[≥≤])\$\s*(\d+)')

    for match in pattern_trailing.finditer(content):
        math_part = match.group(1)
        trailing = match.group(2)
        line_num = content[:match.start()].count('\n') + 1

        # Normalize the comparison operator
        fixed_math = math_part.replace('≥', r'\geq ').replace('≤', r'\leq ')

        yield LintIssue(
            rule="broken_math_delimiters",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Split math expression: ${math_part}${trailing} → ${fixed_math}{trailing}$",
            fix=Fix(old=match.group(), new=f'${fixed_math}{trailing}$')
        )


def broken_norm_notation(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect and fix broken norm (double-bar) notation from OCR artifacts.

    When Marker OCR encounters double vertical bars (norm notation), it
    breaks them into combinations of pipe characters and math delimiters:

    - |$|x|$| → $\\|x\\|$  (bars outside dollar-enclosed bars)
    - $|$x$|$ → $\\|x\\|$  (dollar-bar-dollar sequences)
    - ||x|| inside math → \\|x\\|  (raw double pipes in math mode)

    This is distinct from broken_math_delimiters which handles single-bar
    absolute value |$x$| → $|x|$ (moving bars inside math mode).
    """
    # Pattern 1: |$|...|$| — bars outside dollar-enclosed inner content
    # OCR produces this when ‖ gets split across math delimiter boundaries
    pattern_bars_dollars = re.compile(
        r'\|\$\|([^$|]+)\|\$\|'
    )

    for match in pattern_bars_dollars.finditer(content):
        inner = match.group(1)
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="broken_norm_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Broken norm: |$|{inner}|$| → $\\|{inner}\\|$",
            fix=Fix(old=match.group(), new=f'$\\|{inner}\\|$')
        )

    # Pattern 2: $|$...$|$ — dollar-bar-dollar wrapping content
    # Another common OCR artifact where ‖ becomes $|$ on each side
    pattern_dollar_bar = re.compile(
        r'\$\|\$([^$|]+)\$\|\$'
    )

    for match in pattern_dollar_bar.finditer(content):
        inner = match.group(1)
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="broken_norm_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Broken norm: $|${inner}$|$ → $\\|{inner}\\|$",
            fix=Fix(old=match.group(), new=f'$\\|{inner}\\|$')
        )

    # Pattern 3: ||...|| inside math mode — raw double pipes should be \|...\|
    # Only fix inside math mode to avoid conflicts with markdown tables
    pattern_double_pipes = re.compile(
        r'\|\|([^|]+)\|\|'
    )

    for match in pattern_double_pipes.finditer(content):
        if not is_in_math_mode(content, match.start()):
            continue

        # Skip if already escaped
        if '\\|' in match.group():
            continue

        inner = match.group(1)
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="broken_norm_notation",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Norm in math: ||{inner}|| → \\|{inner}\\|",
            fix=Fix(old=match.group(), new=f'\\|{inner}\\|')
        )


def fragmented_math_expression(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect and merge fragmented inline math expressions.

    OCR often splits a single math expression into multiple $...$ blocks
    with operators or whitespace between them:

    - $x$ + $y$ → $x + y$
    - $x^2$ = $0$ → $x^2 = 0$
    - $(s \\cdot t) \\cdot $a = s$\\cdot (t \\cdot a)$ → single expression

    Merges consecutive $...$ blocks when the gap between them contains
    no words (2+ alpha chars) and no prose punctuation (, ; : . ! ? or
    paired delimiters). Gaps may contain operators, whitespace, single
    variable letters, digits, and LaTeX commands like \\cdot.

    Skips display math lines and pipe-only spans (handled by
    broken_norm_notation).
    """
    for line_idx, line in enumerate(content.split('\n')):
        stripped = line.strip()

        # Skip display math lines
        if stripped.startswith('$$') or stripped.endswith('$$'):
            continue

        # ── Find all inline $...$ spans ──
        spans = []
        i = 0
        while i < len(line):
            if line[i] == '$':
                # Skip display math $$
                if i + 1 < len(line) and line[i + 1] == '$':
                    i += 2
                    continue

                # Find closing $
                j = i + 1
                while j < len(line) and line[j] != '$':
                    j += 1

                if j < len(line):
                    inner = line[i + 1:j]
                    # Skip empty spans and pipe-only spans (norm delimiters)
                    if inner.strip() and inner not in ('|', '||'):
                        spans.append((i, j + 1))
                    i = j + 1
                else:
                    i += 1  # Unmatched $, skip
            else:
                i += 1

        if len(spans) < 2:
            continue

        # ── Group consecutive spans with mergeable gaps ──
        groups = []
        current_group = [spans[0]]

        for k in range(1, len(spans)):
            prev_end = current_group[-1][1]
            curr_start = spans[k][0]
            gap = line[prev_end:curr_start]

            # Strip LaTeX commands before checking for words
            gap_no_latex = re.sub(r'\\[a-zA-Z]+', '', gap)
            has_word = bool(re.search(r'[a-zA-Z]{2,}', gap_no_latex))
            has_punct = bool(re.search(r'[,;:.!?()\[\]]', gap))

            if not has_word and not has_punct:
                current_group.append(spans[k])
            else:
                if len(current_group) >= 2:
                    groups.append(current_group)
                current_group = [spans[k]]

        if len(current_group) >= 2:
            groups.append(current_group)

        # ── Yield a single fix per group ──
        for group in groups:
            first_start = group[0][0]
            last_end = group[-1][1]
            old_text = line[first_start:last_end]

            # Build merged content: strip inner $ boundaries, keep gaps
            parts = []
            for k, (start, end) in enumerate(group):
                parts.append(line[start + 1:end - 1])  # Inner math content
                if k < len(group) - 1:
                    gap = line[end:group[k + 1][0]]
                    parts.append(gap)

            new_text = '$' + ''.join(parts) + '$'

            if old_text != new_text:
                yield LintIssue(
                    rule="fragmented_math_expression",
                    severity=Severity.AUTO_FIX,
                    line=line_idx + 1,
                    message=f"Merge fragmented math: {old_text[:80]} → {new_text[:80]}",
                    fix=Fix(old=old_text, new=new_text)
                )


def space_in_math_variable(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect spaces incorrectly inserted into math variable names.

    OCR sometimes produces "K ◦" instead of "K◦" or "R >" instead of "R>"
    when variables have decorations.
    """
    # Pattern: Single letter, space, then math decoration
    pattern = re.compile(r'\b([A-Za-z]) ([◦∗∞\^_])')

    for match in pattern.finditer(content):
        # Skip if inside math mode (spacing might be intentional)
        if is_in_math_mode(content, match.start()):
            continue

        letter = match.group(1)
        decoration = match.group(2)
        line_num = content[:match.start()].count('\n') + 1

        yield LintIssue(
            rule="space_in_math_variable",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Spurious space in math: '{letter} {decoration}' → '{letter}{decoration}'",
            fix=Fix(old=match.group(), new=f'{letter}{decoration}')
        )


def display_math_whitespace(content: str) -> Generator[LintIssue, None, None]:
    """
    Remove unnecessary blank lines before/after display math blocks.

    In transcribed papers, display math ($$...$$) often has extra blank lines
    around it from page breaks or OCR artifacts. This normalizes spacing to
    have no blank lines immediately adjacent to display math.

    Handles:
    - Single-line display math: $$x^2 + y^2 = z^2$$
    - Multi-line display math opening/closing: $$ (on its own line)
    """
    # Pattern 1: Blank line(s) followed by a line starting with $$
    # Matches: \n\n$$  or  \n\n\n$$  etc.
    pattern_before = re.compile(r'\n(\n+)([ \t]*\$\$)')

    for match in pattern_before.finditer(content):
        blank_lines = match.group(1)
        math_start = match.group(2)
        line_num = content[:match.start()].count('\n') + 1

        if len(blank_lines) >= 1:
            yield LintIssue(
                rule="display_math_whitespace",
                severity=Severity.AUTO_FIX,
                line=line_num,
                message=f"Extra blank line(s) before display math",
                fix=Fix(old=match.group(), new=f'\n{math_start}')
            )

    # Pattern 2: Line ending with $$ followed by blank line(s)
    # Matches: $$\n\n  or  $$\n\n\n  etc.
    pattern_after = re.compile(r'(\$\$[ \t]*)\n(\n+)')

    for match in pattern_after.finditer(content):
        math_end = match.group(1)
        blank_lines = match.group(2)
        line_num = content[:match.start()].count('\n') + 1

        if len(blank_lines) >= 1:
            yield LintIssue(
                rule="display_math_whitespace",
                severity=Severity.AUTO_FIX,
                line=line_num,
                message=f"Extra blank line(s) after display math",
                fix=Fix(old=match.group(), new=f'{math_end}\n')
            )


def merge_math_expressions(content: str) -> Generator[LintIssue, None, None]:
    """
    Merge fragmented mathematical expressions into unified math mode blocks.

    Detects patterns like:
    - S = **C**[ϵ]/(ϵ 2 ) → $S = \\mathbb{C}[\\epsilon]/(\\epsilon^2)$
    - K ◦ → K → $K^\\circ \\to K$
    - Variable assignments with math symbols

    This rule runs AFTER individual symbol rules to merge their output into
    cohesive expressions. Fixes common spacing issues like "ϵ 2" → "\\epsilon^2".
    """
    # Pattern: Equation-like expressions with = and math symbols
    # Captures: [variable] = [expression with bold/**/, unicode, brackets, operators]
    equation_pattern = re.compile(
        r'\b([A-Za-z][A-Za-z0-9_]*)\s*=\s*'  # Variable =
        r'((?:'
        r'\*\*[A-Z]\*\*|'          # Bold letters like **C**
        r'[A-Za-z0-9_\[\]\(\)/\+\-\*◦∗∞×÷±⊗⊕]|'  # Math chars
        r'[α-ωΑ-Ω]|'               # Greek letters
        r'[ϵεℓ]|'                   # Special math symbols
        r'\s'                       # Spaces
        r')+)',
        re.UNICODE
    )

    for match in equation_pattern.finditer(content):
        # Skip if already fully in math mode
        if is_in_math_mode(content, match.start()):
            continue

        var = match.group(1)
        expr = match.group(2).strip()
        line_num = content[:match.start()].count('\n') + 1

        # Process the expression to fix common issues
        fixed_expr = expr

        # Fix bold number sets: **C** → \mathbb{C}
        for letter in ['C', 'Z', 'R', 'Q', 'N', 'A', 'P', 'F', 'H', 'G']:
            fixed_expr = re.sub(
                rf'\*\*\s*{letter}\s*\*\*',
                rf'\\mathbb{{{letter}}}',
                fixed_expr
            )

        # Fix Unicode to LaTeX
        for unicode_char, latex_cmd in UNICODE_TO_LATEX.items():
            fixed_expr = fixed_expr.replace(unicode_char, latex_cmd)

        # Fix spacing in superscripts: "ε 2" → "ε^2", "ϵ 2" → "\epsilon^2"
        fixed_expr = re.sub(
            r'(\\epsilon|\\varepsilon|[A-Za-z])\s+(\d+)',
            r'\1^{\2}',
            fixed_expr
        )

        # Create the final math expression
        old_text = match.group(0)
        new_text = f'${var} = {fixed_expr}$'

        # Only yield if something actually changed
        if new_text != f'${old_text}$':
            yield LintIssue(
                rule="merge_math_expressions",
                severity=Severity.AUTO_FIX,
                line=line_num,
                message=f"Merge math expression: {old_text[:60]}... → {new_text[:60]}...",
                fix=Fix(old=old_text, new=new_text)
            )


def operator_subscript_correction(content: str) -> Generator[LintIssue, None, None]:
    """
    Fix operators that incorrectly use superscripts instead of subscripts.

    In category theory and algebraic geometry, products and tensor products
    over a base use SUBSCRIPT notation:
    - \\times^{S} → \\times_{S} (fiber product over S)
    - \\otimes^{R} → \\otimes_{R} (tensor product over R)
    - \\prod^{I} → \\prod_{I} (product over index set I)
    - \\coprod^{I} → \\coprod_{I} (coproduct over index set I)

    This fixes cases where html_math_notation incorrectly converted to superscript.
    """
    # Pattern: operator with superscript that should be subscript
    pattern = re.compile(
        r'(\\(?:times|otimes|prod|coprod))\^(\{[^}]+\}|[A-Za-z][A-Za-z0-9]*)',
        re.IGNORECASE
    )

    for match in pattern.finditer(content):
        # Skip if inside math mode check - but actually we want to fix these even in math mode
        operator = match.group(1)
        subscript = match.group(2)
        line_num = content[:match.start()].count('\n') + 1

        old_text = match.group(0)
        new_text = f'{operator}_{subscript}'

        yield LintIssue(
            rule="operator_subscript_correction",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Fix operator subscript: {old_text} → {new_text}",
            fix=Fix(old=old_text, new=new_text)
        )


def bold_number_sets(content: str) -> Generator[LintIssue, None, None]:
    """
    Convert standalone bold letters to blackboard bold notation.

    In mathematical texts, bold letters representing number sets are often
    transcribed as **C**, **Z**, **R**, **Q**, **N** but should be rendered
    as $\\mathbb{C}$, $\\mathbb{Z}$, $\\mathbb{R}$, $\\mathbb{Q}$, $\\mathbb{N}$.

    Also handles:
    - **A** → $\\mathbb{A}$ (algebraic numbers, affine space)
    - **P** → $\\mathbb{P}$ (projective space, primes)
    - **F** → $\\mathbb{F}$ (finite fields)
    - **H** → $\\mathbb{H}$ (quaternions, upper half-plane)
    - **G** → $\\mathbb{G}$ (additive/multiplicative group)

    Patterns:
    - **C** → $\\mathbb{C}$
    - ** C ** → $\\mathbb{C}$ (with spaces)
    - Preserves existing math mode
    """
    # Mapping of letters to their blackboard bold equivalents
    BLACKBOARD_LETTERS = {
        'C': r'\mathbb{C}',  # Complex numbers
        'Z': r'\mathbb{Z}',  # Integers
        'R': r'\mathbb{R}',  # Real numbers
        'Q': r'\mathbb{Q}',  # Rational numbers
        'N': r'\mathbb{N}',  # Natural numbers
        'A': r'\mathbb{A}',  # Algebraic numbers / Affine space
        'P': r'\mathbb{P}',  # Projective space / Primes
        'F': r'\mathbb{F}',  # Finite fields
        'H': r'\mathbb{H}',  # Quaternions / Upper half-plane
        'G': r'\mathbb{G}',  # Additive/multiplicative group
    }

    # Pattern: **X** with optional spaces inside
    # Matches: **C**, ** C **, **Z**, etc.
    pattern = re.compile(r'\*\*\s*([A-Z])\s*\*\*')

    for match in pattern.finditer(content):
        letter = match.group(1)

        # Only process if it's one of our blackboard letters
        if letter not in BLACKBOARD_LETTERS:
            continue

        # Skip if already in math mode
        if is_in_math_mode(content, match.start()):
            continue

        line_num = content[:match.start()].count('\n') + 1
        old_text = match.group(0)
        new_text = f'${BLACKBOARD_LETTERS[letter]}$'

        yield LintIssue(
            rule="bold_number_sets",
            severity=Severity.AUTO_FIX,
            line=line_num,
            message=f"Convert bold to blackboard bold: {old_text} → {new_text}",
            fix=Fix(old=old_text, new=new_text)
        )
