"""Unicode math symbol detection and wrapping rule.

Detects Unicode math symbols (∈, →, ∞, Greek letters, etc.) outside of
$...$ math mode and wraps them in proper LaTeX delimiters. Handles
adjacency to existing math blocks and function notation.
"""
import re
from typing import Generator

from ..models import LintIssue, Severity, Fix
from .math_constants import UNICODE_TO_LATEX, is_in_math_mode


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
            before_context = content[max(0, pos - 100):pos]
            after_context = content[match.end():min(len(content), match.end() + 100)]

            # Try specialized handlers in order
            result = _try_function_notation(char, latex, match, before_context, after_context, content, line_num, arrow_chars)
            if result is None:
                result = _try_math_adjacency(char, latex, match, before_context, after_context, content, line_num)
            if result is None:
                result = _try_variable_context(char, latex, match, before_context, after_context, content, pos, line_num)

            if result:
                issue, range_start, range_end = result
                issues.append(issue)
                processed_ranges.add((range_start, range_end))

    # Sort by line and yield
    issues.sort(key=lambda x: x.line)
    for issue in issues:
        yield issue


def _try_function_notation(char, latex, match, before_context, after_context, content, line_num, arrow_chars):
    """Handle function notation like f: X → Y."""
    if char not in arrow_chars:
        return None

    pos = match.start()
    func_pattern = re.search(
        r'([A-Za-zαβγδεζηθικλμνξπρστυφχψω][A-Za-z0-9_]*)\s*:\s*'
        r'([A-Za-z_][A-Za-z0-9_×⊗]*)\s*$',
        before_context
    )
    if not func_pattern:
        return None

    func_name = func_pattern.group(1)
    domain = func_pattern.group(2)
    codomain_match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_×⊗]*)', after_context)
    if not codomain_match:
        return None

    codomain = codomain_match.group(1)
    old_start = pos - len(func_pattern.group(0))
    old_end = match.end() + len(codomain_match.group(0))
    old_text = content[old_start:old_end]
    new_text = f'${func_name} \\colon {domain} {latex} {codomain}$'

    issue = LintIssue(
        rule="unicode_math_symbols",
        severity=Severity.AUTO_FIX,
        line=line_num,
        message=f"Function notation: {old_text} → {new_text}",
        fix=Fix(old=old_text, new=new_text)
    )
    return issue, old_start, old_end


def _try_math_adjacency(char, latex, match, before_context, after_context, content, line_num):
    """Handle symbols adjacent to existing math blocks."""
    pos = match.start()

    math_before = re.search(r'\$([^$]+)\$(\s*)$', before_context)
    math_after = re.match(r'(\s*)\$([^$]+)\$', after_context)

    if math_before and math_after:
        # Between two math blocks: $A$ ∈ $B$ → $A \in B$
        old_start = pos - len(math_before.group(0))
        old_end = match.end() + len(math_after.group(0))
        old_text = content[old_start:old_end]
        new_text = f'${math_before.group(1)} {latex} {math_after.group(2)}$'
        return _make_issue(line_num, old_text, new_text, "Merge math blocks"), old_start, old_end

    elif math_before:
        # After math block: $K^*$ ∈ R → $K^* \in R$
        trailing = ""
        trailing_match = re.match(r'(\s*[A-Za-z_][A-Za-z0-9_]*)', after_context)
        if trailing_match:
            trailing = trailing_match.group(1)
        old_start = pos - len(math_before.group(0))
        old_end = match.end() + len(trailing)
        old_text = content[old_start:old_end]
        new_text = f'${math_before.group(1)} {latex}{trailing}$'
        return _make_issue(line_num, old_text, new_text, "Extend math block"), old_start, old_end

    elif math_after:
        # Before math block: x ∈ $S$ → $x \in S$
        leading = ""
        leading_match = re.search(r'([A-Za-z_][A-Za-z0-9_]*\s*)$', before_context)
        if leading_match:
            leading = leading_match.group(1)
        old_start = pos - len(leading)
        old_end = match.end() + len(math_after.group(0))
        old_text = content[old_start:old_end]
        new_text = f'${leading.strip()} {latex} {math_after.group(2)}$'
        return _make_issue(line_num, old_text, new_text, "Extend math block"), old_start, old_end

    return None


# Common English words that shouldn't be treated as math variables
_COMMON_WORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'shall', 'can',
    'of', 'to', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
    'as', 'or', 'and', 'but', 'if', 'then', 'that', 'this',
    'it', 'its', 'we', 'they', 'he', 'she', 'not', 'so', 'up',
    'value', 'values',
})


def _try_variable_context(char, latex, match, before_context, after_context, content, pos, line_num):
    """Handle symbols adjacent to variables (not math blocks)."""
    var_before = re.search(r'([A-Za-z_][A-Za-z0-9_]*|\)|\])\s*$', before_context)
    var_after = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*|\(|\[)', after_context)

    if var_before and var_after:
        # Between two variables: x ∈ R → $x \in R$
        leading = var_before.group(0)
        trailing_match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)', after_context)
        trailing = trailing_match.group(0) if trailing_match else ""
        old_start = pos - len(leading)
        old_end = match.end() + len(trailing)
        old_text = content[old_start:old_end]
        new_text = f'${leading.strip()} {latex} {trailing.strip()}$'
        return _make_issue(line_num, old_text, new_text, "Wrap expression"), old_start, old_end

    elif var_before:
        leading = var_before.group(0).strip()

        if leading.lower() in _COMMON_WORDS:
            # Common word — wrap only the symbol
            old_text = char
            new_text = f'${latex}$'
            return _make_issue(line_num, old_text, new_text, "Wrap standalone"), pos, match.end()

        old_start = pos - len(var_before.group(0))
        old_end = match.end()
        old_text = content[old_start:old_end]

        # For superscript-like symbols (◦, ∗, ∞), use superscript notation
        if char in ('◦', '∗', '∞'):
            new_text = f'${leading}^{{{latex}}}$'
        else:
            new_text = f'${leading} {latex}$'
        return _make_issue(line_num, old_text, new_text, "Wrap with variable"), old_start, old_end

    elif var_after:
        trailing_match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)', after_context)
        trailing = trailing_match.group(0) if trailing_match else ""
        old_start = pos
        old_end = match.end() + len(trailing)
        old_text = content[old_start:old_end]
        new_text = f'${latex} {trailing.strip()}$'
        return _make_issue(line_num, old_text, new_text, "Wrap with variable"), old_start, old_end

    else:
        # Standalone symbol
        old_text = char
        new_text = f'${latex}$'
        return _make_issue(line_num, old_text, new_text, "Wrap standalone"), pos, match.end()


def _make_issue(line_num, old_text, new_text, prefix):
    """Create a LintIssue for unicode_math_symbols."""
    return LintIssue(
        rule="unicode_math_symbols",
        severity=Severity.AUTO_FIX,
        line=line_num,
        message=f"{prefix}: {old_text[:50]} → {new_text[:50]}",
        fix=Fix(old=old_text, new=new_text)
    )
