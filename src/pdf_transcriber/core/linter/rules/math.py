"""Math notation detection and repair rules."""
import re
from typing import Generator

from ..models import LintIssue, Severity, Fix


# Unicode to LaTeX mapping for common math symbols
UNICODE_TO_LATEX = {
    # Greek letters (commonly appear outside $...$)
    '◦': r'\circ',
    '∗': '*',
    '∞': r'\infty',
    'Ω': r'\Omega',
    'α': r'\alpha',
    'β': r'\beta',
    'γ': r'\gamma',
    'δ': r'\delta',
    'ε': r'\varepsilon',
    'ζ': r'\zeta',
    'η': r'\eta',
    'θ': r'\theta',
    'ι': r'\iota',
    'κ': r'\kappa',
    'λ': r'\lambda',
    'μ': r'\mu',
    'ν': r'\nu',
    'ξ': r'\xi',
    'π': r'\pi',
    'ρ': r'\rho',
    'σ': r'\sigma',
    'τ': r'\tau',
    'υ': r'\upsilon',
    'φ': r'\varphi',
    'χ': r'\chi',
    'ψ': r'\psi',
    'ω': r'\omega',
    'Γ': r'\Gamma',
    'Δ': r'\Delta',
    'Θ': r'\Theta',
    'Λ': r'\Lambda',
    'Ξ': r'\Xi',
    'Π': r'\Pi',
    'Σ': r'\Sigma',
    'Υ': r'\Upsilon',
    'Φ': r'\Phi',
    'Ψ': r'\Psi',

    # Relations
    '∈': r'\in',
    '∉': r'\notin',
    '⊂': r'\subset',
    '⊃': r'\supset',
    '⊆': r'\subseteq',
    '⊇': r'\supseteq',
    '≤': r'\leq',
    '≥': r'\geq',
    '≠': r'\neq',
    '≈': r'\approx',
    '≡': r'\equiv',
    '∼': r'\sim',
    '≃': r'\simeq',
    '≅': r'\cong',
    '∝': r'\propto',

    # Arrows
    '→': r'\to',
    '←': r'\leftarrow',
    '↔': r'\leftrightarrow',
    '⇒': r'\Rightarrow',
    '⇐': r'\Leftarrow',
    '⇔': r'\Leftrightarrow',
    '↦': r'\mapsto',
    '↪': r'\hookrightarrow',
    '↠': r'\twoheadrightarrow',

    # Operators
    '×': r'\times',
    '÷': r'\div',
    '±': r'\pm',
    '∓': r'\mp',
    '⊗': r'\otimes',
    '⊕': r'\oplus',
    '∩': r'\cap',
    '∪': r'\cup',
    '∧': r'\wedge',
    '∨': r'\vee',
    '∘': r'\circ',
    '·': r'\cdot',
    '†': r'\dagger',
    '‡': r'\ddagger',

    # Quantifiers and logic
    '∀': r'\forall',
    '∃': r'\exists',
    '∄': r'\nexists',
    '¬': r'\neg',
    '∅': r'\emptyset',

    # Calculus and analysis
    '∂': r'\partial',
    '∇': r'\nabla',
    '∫': r'\int',
    '∑': r'\sum',
    '∏': r'\prod',
    '√': r'\sqrt',

    # Misc
    '⊥': r'\perp',
    '∥': r'\parallel',
    '⟨': r'\langle',
    '⟩': r'\rangle',
    '⌊': r'\lfloor',
    '⌋': r'\rfloor',
    '⌈': r'\lceil',
    '⌉': r'\rceil',
    '♭': r'\flat',
    '♯': r'\sharp',
    '♮': r'\natural',
    'ℓ': r'\ell',
    'ℕ': r'\mathbb{N}',
    'ℤ': r'\mathbb{Z}',
    'ℚ': r'\mathbb{Q}',
    'ℝ': r'\mathbb{R}',
    'ℂ': r'\mathbb{C}',
}

# Patterns that indicate unwrapped math when outside $...$
MATH_PATTERNS = [
    # Letter with Unicode superscript/subscript
    (r'([A-Za-z])◦◦', r'$\1^{\circ\circ}$'),  # K◦◦ → $K^{\circ\circ}$
    (r'([A-Za-z])◦(?!◦)', r'$\1^{\circ}$'),   # K◦ → $K^{\circ}$ (not K◦◦)
    (r'([A-Za-z])∗', r'$\1^*$'),               # K∗ → $K^*$

    # Common perfectoid/p-adic patterns
    (r'\|([A-Za-z])\|', r'$|\1|$'),            # |K| → $|K|$
    (r'\|([A-Za-z])\∗\|', r'$|\1^*|$'),        # |K∗| → $|K^*|$
]


def is_in_math_mode(content: str, pos: int) -> bool:
    """Check if position is inside $...$ math mode."""
    # Look backwards for unescaped $
    before = content[max(0, pos - 200):pos]
    dollars = len(re.findall(r'(?<!\\)\$', before))
    return dollars % 2 == 1


def unicode_math_symbols(content: str) -> Generator[LintIssue, None, None]:
    """
    Detect and fix Unicode math symbols outside of math mode.

    Unicode symbols like ◦, ∈, →, Ω should be inside $...$ delimiters
    to render properly in LaTeX/markdown math.

    Handles adjacency to existing math blocks:
    - ``$K^*$ ∈ R`` → ``$K^* \\in R$`` (extend existing math)
    - ``x ∈ $S$`` → ``$x \\in S$`` (merge into existing math)
    - ``K ∈ R`` → ``$K \\in R$`` (new math block for the expression)
    - Standalone ``∞`` → ``$\\infty$``
    """
    issues = []
    processed_ranges = set()  # Track ranges we've already handled

    # Process arrows FIRST - they may be part of function notation like "f: X → Y"
    # which should capture the entire expression including any Greek letter function names
    arrow_chars = ('→', '←', '↔', '↦', '⇒', '⇐', '⇔', '↪', '↠')

    # Reorder: arrows first, then everything else
    ordered_items = []
    for char, latex in UNICODE_TO_LATEX.items():
        if char in arrow_chars:
            ordered_items.insert(0, (char, latex))  # Arrows go first
        else:
            ordered_items.append((char, latex))

    # Process all Unicode symbols
    for char, latex in ordered_items:
        for match in re.finditer(re.escape(char), content):
            pos = match.start()

            # Skip if inside math mode
            if is_in_math_mode(content, pos):
                continue

            # Skip if we've already processed this position
            if any(start <= pos < end for start, end in processed_ranges):
                continue

            line_num = content[:pos].count('\n') + 1

            # Look for adjacent math context
            # Check before: is there a $...$ immediately before (with optional space)?
            before_context = content[max(0, pos - 100):pos]
            after_context = content[match.end():min(len(content), match.end() + 100)]

            # Special case: Function notation like "f: X → Y" or "φ: A → B"
            # This is common in math and should be captured as a whole
            if char in ('→', '←', '↔', '↦', '⇒', '⇐', '⇔', '↪', '↠'):
                # Pattern: [letter][optional subscript]: [expr] [arrow] [expr]
                func_pattern = re.search(
                    r'([A-Za-zαβγδεζηθικλμνξπρστυφχψω][A-Za-z0-9_]*)\s*:\s*'
                    r'([A-Za-z_][A-Za-z0-9_×⊗]*)\s*$',
                    before_context
                )
                if func_pattern:
                    func_name = func_pattern.group(1)
                    domain = func_pattern.group(2)

                    # Look for codomain after the arrow
                    codomain_match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_×⊗]*)', after_context)
                    if codomain_match:
                        codomain = codomain_match.group(1)

                        old_start = pos - len(func_pattern.group(0))
                        old_end = match.end() + len(codomain_match.group(0))
                        old_text = content[old_start:old_end]

                        # Use \colon for function notation (proper LaTeX)
                        new_text = f'${func_name} \\colon {domain} {latex} {codomain}$'

                        issues.append(LintIssue(
                            rule="unicode_math_symbols",
                            severity=Severity.AUTO_FIX,
                            line=line_num,
                            message=f"Function notation: {old_text} → {new_text}",
                            fix=Fix(old=old_text, new=new_text)
                        ))
                        processed_ranges.add((old_start, old_end))
                        continue

            # Pattern: $...$[space]*[unicode] - math block ends right before
            math_before = re.search(r'\$([^$]+)\$(\s*)$', before_context)

            # Pattern: [unicode][space]*$...$  - math block starts right after
            math_after = re.match(r'(\s*)\$([^$]+)\$', after_context)

            # Check for math-like content adjacent (variables, operators)
            # Math-like: single letters, subscripts, common math words
            var_before = re.search(r'([A-Za-z_][A-Za-z0-9_]*|\)|\])\s*$', before_context)
            var_after = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*|\(|\[)', after_context)

            if math_before and math_after:
                # Unicode symbol between two math blocks: $A$ ∈ $B$ → $A \in B$
                math_content_before = math_before.group(1)
                space_before = math_before.group(2)
                space_after = math_after.group(1)
                math_content_after = math_after.group(2)

                old_start = pos - len(math_before.group(0))
                old_end = match.end() + len(math_after.group(0))
                old_text = content[old_start:old_end]
                new_text = f'${math_content_before} {latex} {math_content_after}$'

                issues.append(LintIssue(
                    rule="unicode_math_symbols",
                    severity=Severity.AUTO_FIX,
                    line=line_num,
                    message=f"Merge math blocks: {old_text[:50]}... → {new_text[:50]}...",
                    fix=Fix(old=old_text, new=new_text)
                ))
                processed_ranges.add((old_start, old_end))

            elif math_before:
                # Unicode symbol after math block: $K^*$ ∈ R → $K^* \in R$
                math_content = math_before.group(1)
                space = math_before.group(2)

                # Capture any trailing math-like content
                trailing = ""
                trailing_match = re.match(r'(\s*[A-Za-z_][A-Za-z0-9_]*)', after_context)
                if trailing_match:
                    trailing = trailing_match.group(1)

                old_start = pos - len(math_before.group(0))
                old_end = match.end() + len(trailing)
                old_text = content[old_start:old_end]
                new_text = f'${math_content} {latex}{trailing}$'

                issues.append(LintIssue(
                    rule="unicode_math_symbols",
                    severity=Severity.AUTO_FIX,
                    line=line_num,
                    message=f"Extend math block: {old_text[:50]} → {new_text[:50]}",
                    fix=Fix(old=old_text, new=new_text)
                ))
                processed_ranges.add((old_start, old_end))

            elif math_after:
                # Unicode symbol before math block: x ∈ $S$ → $x \in S$
                space = math_after.group(1)
                math_content = math_after.group(2)

                # Capture any leading math-like content
                leading = ""
                leading_match = re.search(r'([A-Za-z_][A-Za-z0-9_]*\s*)$', before_context)
                if leading_match:
                    leading = leading_match.group(1)

                old_start = pos - len(leading)
                old_end = match.end() + len(math_after.group(0))
                old_text = content[old_start:old_end]
                new_text = f'${leading.strip()} {latex} {math_content}$'

                issues.append(LintIssue(
                    rule="unicode_math_symbols",
                    severity=Severity.AUTO_FIX,
                    line=line_num,
                    message=f"Extend math block: {old_text[:50]} → {new_text[:50]}",
                    fix=Fix(old=old_text, new=new_text)
                ))
                processed_ranges.add((old_start, old_end))

            elif var_before and var_after:
                # Between two variables: x ∈ R → $x \in R$
                leading = var_before.group(0)
                trailing_match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)', after_context)
                trailing = trailing_match.group(0) if trailing_match else ""

                old_start = pos - len(leading)
                old_end = match.end() + len(trailing)
                old_text = content[old_start:old_end]
                new_text = f'${leading.strip()} {latex} {trailing.strip()}$'

                issues.append(LintIssue(
                    rule="unicode_math_symbols",
                    severity=Severity.AUTO_FIX,
                    line=line_num,
                    message=f"Wrap expression: {old_text} → {new_text}",
                    fix=Fix(old=old_text, new=new_text)
                ))
                processed_ranges.add((old_start, old_end))

            elif var_before:
                # After a variable: K∗ → $K^*$ or K ∈ → $K \in$
                leading = var_before.group(0).strip()

                # Skip common English words - these aren't math variables
                # Fall through to standalone handling instead
                common_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                               'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                               'could', 'should', 'may', 'might', 'must', 'shall', 'can',
                               'of', 'to', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                               'as', 'or', 'and', 'but', 'if', 'then', 'that', 'this',
                               'it', 'its', 'we', 'they', 'he', 'she', 'not', 'so', 'up',
                               'value', 'values'}
                if leading.lower() in common_words:
                    # Fall through to standalone symbol handling
                    old_text = char
                    new_text = f'${latex}$'

                    issues.append(LintIssue(
                        rule="unicode_math_symbols",
                        severity=Severity.AUTO_FIX,
                        line=line_num,
                        message=f"Wrap standalone: {old_text} → {new_text}",
                        fix=Fix(old=old_text, new=new_text)
                    ))
                    processed_ranges.add((pos, match.end()))
                    continue

                old_start = pos - len(var_before.group(0))
                old_end = match.end()
                old_text = content[old_start:old_end]

                # For superscript-like symbols (◦, ∗, ∞), use superscript notation
                if char in ('◦', '∗', '∞'):
                    # latex already has the backslash, just use it directly
                    new_text = f'${leading}^{{{latex}}}$'
                else:
                    new_text = f'${leading} {latex}$'

                issues.append(LintIssue(
                    rule="unicode_math_symbols",
                    severity=Severity.AUTO_FIX,
                    line=line_num,
                    message=f"Wrap with variable: {old_text} → {new_text}",
                    fix=Fix(old=old_text, new=new_text)
                ))
                processed_ranges.add((old_start, old_end))

            elif var_after:
                # Before a variable: ∈ R → $\in R$
                trailing_match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)', after_context)
                trailing = trailing_match.group(0) if trailing_match else ""

                old_start = pos
                old_end = match.end() + len(trailing)
                old_text = content[old_start:old_end]
                new_text = f'${latex} {trailing.strip()}$'

                issues.append(LintIssue(
                    rule="unicode_math_symbols",
                    severity=Severity.AUTO_FIX,
                    line=line_num,
                    message=f"Wrap with variable: {old_text} → {new_text}",
                    fix=Fix(old=old_text, new=new_text)
                ))
                processed_ranges.add((old_start, old_end))

            else:
                # Standalone symbol: ∞ → $\infty$
                old_text = char
                new_text = f'${latex}$'

                issues.append(LintIssue(
                    rule="unicode_math_symbols",
                    severity=Severity.AUTO_FIX,
                    line=line_num,
                    message=f"Wrap standalone: {old_text} → {new_text}",
                    fix=Fix(old=old_text, new=new_text)
                ))
                processed_ranges.add((pos, match.end()))

    # Sort by line and yield
    issues.sort(key=lambda x: x.line)
    for issue in issues:
        yield issue


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
