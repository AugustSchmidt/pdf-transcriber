"""HTML-to-LaTeX math notation conversion rule.

Converts HTML sup/sub tags produced by vision-based PDF transcription
into proper LaTeX math notation. Handles standard script notation,
garbled OCR patterns (perfectoid, completion, flat/tilt), and
fragmented math expressions.
"""
import re
from typing import Generator

from ..models import LintIssue, Severity, Fix
from .math_constants import is_in_math_mode


def _is_footnote_context(content: str, match_start: int) -> bool:
    """Check if this looks like a footnote marker (not math)."""
    before = content[max(0, match_start - 20):match_start]
    footnote_indicators = ['</span>', '. ', '? ', '! ', '\n']
    return any(before.rstrip().endswith(ind.rstrip()) for ind in footnote_indicators) or before.strip() == ''


# Special bases that need specific LaTeX formatting
_SPECIAL_BASES = {
    'O': ('\\mathcal{O}', 'sub'),
    'lim': ('\\lim', 'preserve'),
    'colim': ('\\operatorname{colim}', 'preserve'),
    'Hom': ('\\operatorname{Hom}', 'preserve'),
    'Spec': ('\\operatorname{Spec}', 'preserve'),
    'Spf': ('\\operatorname{Spf}', 'preserve'),
    'Spa': ('\\operatorname{Spa}', 'preserve'),
    'Gal': ('\\operatorname{Gal}', 'preserve'),
}

# Compiled regex patterns
_PAT_NO_SPACE = re.compile(r'([A-Za-z]+)<(sup|sub)>([^<]+)</\2>', re.IGNORECASE)
_PAT_WITH_SPACE = re.compile(r'(?<![A-Za-z])([A-Za-z]) <(sup|sub)>([^<]+)</\2>', re.IGNORECASE)
_PAT_CHAINED = re.compile(r'<sup>([−\-])</sup><sup>(\d+)</sup>', re.IGNORECASE)
_PAT_MATH_CTX = re.compile(r'([>≥<≤=])[ ]*<sup>(\d+)</sup>', re.IGNORECASE)
_PAT_ABS = re.compile(r'(\|[^|]+\|) <(sup|sub)>([^<]+)</\2>', re.IGNORECASE)
_PAT_PAREN = re.compile(r'(\([^)]{1,20}\)) <(sup|sub)>([^<]+)</\2>', re.IGNORECASE)
_PAT_FUNCTOR = re.compile(r'(\([^)]{1,30}\))<(sup|sub)>([∗*+\-−]+)</\2>', re.IGNORECASE)
_PAT_INFINITY = re.compile(r'(\$[^$]+)\$<sup>(∞|\\infty)</sup>', re.IGNORECASE)
_PAT_FRAG_OP = re.compile(r'(\\(?:times|otimes|prod|coprod))\$\s*<sup>([A-Za-z′\'][^<]*)</sup>', re.IGNORECASE)
_PAT_TENSOR = re.compile(r'(⊗)\s*<sup>([A-Za-z]+)</sup>', re.IGNORECASE)
_PAT_SPECIAL = re.compile(r'(?<![A-Za-z])([A-Za-z]) <sup>([∞∗*])</sup>', re.IGNORECASE)
_PAT_GARBLED_OP = re.compile(r'<sup>([⊂⊃→←↔=≈∅∈∉])</sup>', re.IGNORECASE)
_PAT_GARBLED_SUB = re.compile(r'<sup>([A-Za-z])</sup>(Zar|hens|perf|red|et|fppf|fpqc)', re.IGNORECASE)
_PAT_P_INF = re.compile(r'<sup>p</sup><sup>([∞∗])</sup>', re.IGNORECASE)
_PAT_MATH_SUP = re.compile(r'(\$[^$]+)\$<sup>([^<]+)</sup>', re.IGNORECASE)
_PAT_INDEX = re.compile(r'([a-zA-Z])∈<sup>([A-Za-z])</sup>', re.IGNORECASE)
_VALID_SCRIPT = re.compile(r'^[A-Za-z0-9+\-−∗*∞]+$')

# Table-driven garbled OCR patterns: (pattern, template_math, template_wrap, message)
# template_math is used inside math mode, template_wrap wraps in $...$
_GARBLED_BASE_PATTERNS = [
    (_PAT_CHAINED_CIRC_CIRC := re.compile(r'<sup>([A-Za-z]+)</sup>◦◦', re.IGNORECASE),
     '{base}^{{\\circ\\circ}}', '${base}^{{\\circ\\circ}}$', 'Maximal ideal'),
    (re.compile(r'<sup>([A-Za-z]+)</sup>◦(?!◦)', re.IGNORECASE),
     '{base}^{{\\circ}}', '${base}^{{\\circ}}$', 'Ring of integers'),
    (re.compile(r'<sup>([A-Za-z]+)</sup><sup>b</sup>', re.IGNORECASE),
     '\\widehat{{{base}}}', '$\\widehat{{{base}}}$', 'Completion'),
    (re.compile(r'<sup>([A-Za-z]+)</sup>b(?![A-Za-z])', re.IGNORECASE),
     '\\widehat{{{base}}}', '$\\widehat{{{base}}}$', 'Completion'),
    (re.compile(r'<sup>([A-Za-z]+)</sup>[♭\[]', re.IGNORECASE),
     '{base}^{{\\flat}}', '${base}^{{\\flat}}$', 'Tilt'),
]


def _emit(issues, line_num, full_match, replacement, msg):
    """Append a LintIssue for html_math_notation."""
    issues.append(LintIssue(
        rule="html_math_notation", severity=Severity.AUTO_FIX, line=line_num,
        message=f"{msg}: {full_match[:40]} → {replacement[:40]}",
        fix=Fix(old=full_match, new=replacement)
    ))


def _process_base_script(content, pattern, issues, msg_prefix):
    """Process base<sup|sub>script patterns (with or without space)."""
    for match in pattern.finditer(content):
        base = match.group(1)
        tag_type = match.group(2).lower()
        script_content = match.group(3)
        full_match = match.group(0)

        if tag_type == 'sup' and script_content.isdigit() and _is_footnote_context(content, match.start()):
            continue

        line_num = content[:match.start()].count('\n') + 1
        in_math = is_in_math_mode(content, match.start())

        if base in _SPECIAL_BASES:
            latex_base, behavior = _SPECIAL_BASES[base]
            if behavior == 'sub':
                latex_script = f'_{{{script_content}}}'
            else:
                latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
            replacement = f'{latex_base}{latex_script}' if in_math else f'${latex_base}{latex_script}$'
        else:
            latex_script = f'^{{{script_content}}}' if tag_type == 'sup' else f'_{{{script_content}}}'
            replacement = f'{base}{latex_script}' if in_math else f'${base}{latex_script}$'

        _emit(issues, line_num, full_match, replacement, msg_prefix)


def html_math_notation(content: str) -> Generator[LintIssue, None, None]:
    """
    Convert HTML sup/sub notation to proper LaTeX math.

    Transcription often produces HTML like:
    - O<sup>X</sup> → $\\mathcal{O}_X$ (structure sheaf)
    - K<sup>∗</sup> → $K^*$
    - f<sup>-1</sup> → $f^{-1}$
    - <sup>−</sup><sup>1</sup> → $^{-1}$ (chained superscripts)
    """
    issues = []

    # --- Chained superscripts: <sup>−</sup><sup>1</sup> ---
    for match in _PAT_CHAINED.finditer(content):
        sign = '-' if match.group(1) in ('−', '-') else match.group(1)
        replacement = f'^{{{sign}{match.group(2)}}}'
        if not is_in_math_mode(content, match.start()):
            replacement = f'${replacement}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Chained superscript")

    # --- Math-context patterns: ><sup>0</sup> ---
    for match in _PAT_MATH_CTX.finditer(content):
        replacement = f'{match.group(1)}^{{{match.group(2)}}}'
        if not is_in_math_mode(content, match.start()):
            replacement = f'${replacement}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Math context sup")

    # --- Absolute value: |x| <sup>n</sup> ---
    for match in _PAT_ABS.finditer(content):
        tag_type = match.group(2).lower()
        s = f'^{{{match.group(3)}}}' if tag_type == 'sup' else f'_{{{match.group(3)}}}'
        in_math = is_in_math_mode(content, match.start())
        replacement = f'{match.group(1)}{s}' if in_math else f'${match.group(1)}{s}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Abs value math")

    # --- Parenthesized: (stuff) <sup>n</sup> ---
    for match in _PAT_PAREN.finditer(content):
        if not _VALID_SCRIPT.match(match.group(3)):
            continue
        tag_type = match.group(2).lower()
        s = f'^{{{match.group(3)}}}' if tag_type == 'sup' else f'_{{{match.group(3)}}}'
        in_math = is_in_math_mode(content, match.start())
        replacement = f'{match.group(1)}{s}' if in_math else f'${match.group(1)}{s}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Paren math")

    # --- Base scripts (with and without space) ---
    _process_base_script(content, _PAT_WITH_SPACE, issues, "HTML math (spaced)")
    _process_base_script(content, _PAT_NO_SPACE, issues, "HTML math")

    # --- Functor notation: (−)<sup>∗</sup> ---
    for match in _PAT_FUNCTOR.finditer(content):
        tag_type = match.group(2).lower()
        normalized = match.group(3).replace('∗', '*')
        s = f'^{{{normalized}}}' if tag_type == 'sup' else f'_{{{normalized}}}'
        in_math = is_in_math_mode(content, match.start())
        replacement = f'{match.group(1)}{s}' if in_math else f'${match.group(1)}{s}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Functor")

    # --- Infinity after math: $x^{p}$<sup>∞</sup> ---
    for match in _PAT_INFINITY.finditer(content):
        math_content = match.group(1)
        sup_match = re.search(r'\^(\{[^}]+\}|[A-Za-z0-9])$', math_content)
        if sup_match:
            existing = sup_match.group(1)
            inner = existing[1:-1] if existing.startswith('{') else existing
            new_sup = f'^{{{inner}^{{\\infty}}}}'
            replacement = math_content[:sup_match.start()] + new_sup + '$'
        else:
            replacement = f'{math_content}^{{\\infty}}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Infinity merge")

    # --- Fragmented operator: \times$<sup>S</sup> ---
    for match in _PAT_FRAG_OP.finditer(content):
        replacement = f'{match.group(1)}_{{{match.group(2)}}}'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Fix fragmented operator")

    # --- Tensor subscript: ⊗<sup>R</sup> ---
    for match in _PAT_TENSOR.finditer(content):
        in_math = is_in_math_mode(content, match.start())
        replacement = f'{match.group(1)}_{{{match.group(2)}}}' if in_math else f'${match.group(1)}_{{{match.group(2)}}}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Tensor sub")

    # --- Special scripts: t <sup>∞</sup> ---
    for match in _PAT_SPECIAL.finditer(content):
        script = match.group(2)
        if script == '∞':
            ls = '^{\\infty}'
        elif script in ('∗', '*'):
            ls = '^{*}'
        else:
            ls = f'^{{{script}}}'
        in_math = is_in_math_mode(content, match.start())
        replacement = f'{match.group(1)}{ls}' if in_math else f'${match.group(1)}{ls}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Special script")

    # --- Garbled OCR patterns (table-driven) ---
    for pattern, tmpl_math, tmpl_wrap, msg in _GARBLED_BASE_PATTERNS:
        for match in pattern.finditer(content):
            base = match.group(1)
            in_math = is_in_math_mode(content, match.start())
            replacement = tmpl_math.format(base=base) if in_math else tmpl_wrap.format(base=base)
            _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, msg)

    # --- Garbled operators: <sup>⊂</sup> → ⊂ ---
    for match in _PAT_GARBLED_OP.finditer(content):
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), match.group(1), "Garbled operator")

    # --- Garbled subscripts: <sup>A</sup>Zar → $A_{\mathrm{Zar}}$ ---
    for match in _PAT_GARBLED_SUB.finditer(content):
        base, sub = match.group(1), match.group(2)
        in_math = is_in_math_mode(content, match.start())
        replacement = f'{base}_{{\\mathrm{{{sub}}}}}' if in_math else f'${base}_{{\\mathrm{{{sub}}}}}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Garbled subscript")

    # --- p-infinity: <sup>p</sup><sup>∞</sup> ---
    for match in _PAT_P_INF.finditer(content):
        in_math = is_in_math_mode(content, match.start())
        replacement = '^{p^{\\infty}}' if in_math else '$^{p^{\\infty}}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "p-infinity")

    # --- Math + trailing sup: $R^{≥}$<sup>0</sup> ---
    for match in _PAT_MATH_SUP.finditer(content):
        math_content, sup_content = match.group(1), match.group(2)
        op_match = re.search(r'\\(times|otimes|prod|coprod)\s*$', math_content)
        if op_match:
            replacement = f'{math_content}_{{{sup_content}}}$'
            msg_type = "operator subscript"
        else:
            sup_match = re.search(r'\^(\{[^}]*\}|[A-Za-z0-9≥≤−+])$', math_content)
            if sup_match:
                existing = sup_match.group(1)
                if existing.startswith('{'):
                    inner = existing[1:-1].replace('≥', '\\geq ').replace('≤', '\\leq ').replace('−', '-')
                else:
                    inner = existing.replace('≥', '\\geq ').replace('≤', '\\leq ').replace('−', '-')
                replacement = math_content[:sup_match.start()] + f'^{{{inner}{sup_content}}}' + '$'
                msg_type = "merge superscript"
            else:
                replacement = f'{math_content}^{{{sup_content}}}$'
                msg_type = "add superscript"
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, f"Math+sup {msg_type}")

    # --- Index set: i∈<sup>I</sup> → i \in I ---
    for match in _PAT_INDEX.finditer(content):
        el, idx = match.group(1), match.group(2)
        in_math = is_in_math_mode(content, match.start())
        replacement = f'{el} \\in {idx}' if in_math else f'${el} \\in {idx}$'
        _emit(issues, content[:match.start()].count('\n') + 1, match.group(0), replacement, "Index set")

    # Sort by line number and yield
    issues.sort(key=lambda x: x.line)
    yield from issues
