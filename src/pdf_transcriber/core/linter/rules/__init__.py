"""Lint rules for markdown and PDF artifacts."""
from . import markdown, artifacts, math

# Registry of all available rules
RULES = {
    # Markdown structure rules
    "excessive_blank_lines": markdown.excessive_blank_lines,
    "trailing_whitespace": markdown.trailing_whitespace,
    "leading_whitespace": markdown.leading_whitespace,
    "header_whitespace": markdown.header_whitespace,
    "sparse_table_row": markdown.sparse_table_row,
    "orphaned_list_marker": markdown.orphaned_list_marker,

    # PDF artifact rules
    "page_number": artifacts.page_number,
    "page_marker": artifacts.page_marker,
    "malformed_footnote": artifacts.malformed_footnote,
    "orphaned_label": artifacts.orphaned_label,
    "garbled_text": artifacts.garbled_text,
    "hyphenation_artifact": artifacts.hyphenation_artifact,
    "repeated_line": artifacts.repeated_line,
    "html_artifacts": artifacts.html_artifacts,
    "html_math_notation": artifacts.html_math_notation,
    "footnote_spacing": artifacts.footnote_spacing,

    # Math notation rules
    "unicode_math_symbols": math.unicode_math_symbols,
    "unwrapped_math_expressions": math.unwrapped_math_expressions,
    "repetition_hallucination": math.repetition_hallucination,
    "broken_math_delimiters": math.broken_math_delimiters,
    "space_in_math_variable": math.space_in_math_variable,
    "display_math_whitespace": math.display_math_whitespace,
    "bold_number_sets": math.bold_number_sets,
    "merge_math_expressions": math.merge_math_expressions,
    "operator_subscript_correction": math.operator_subscript_correction,
}

# Rules that are safe to auto-fix by default
DEFAULT_AUTO_FIX = {
    "excessive_blank_lines",
    "trailing_whitespace",
    "leading_whitespace",
    "header_whitespace",
    "display_math_whitespace",
    "page_number",
    "page_marker",
    "orphaned_label",
    "hyphenation_artifact",
    "html_artifacts",
    "html_math_notation",
    "footnote_spacing",
    "unwrapped_math_expressions",
    "broken_math_delimiters",
    "space_in_math_variable",
    "unicode_math_symbols",
    "bold_number_sets",
    "merge_math_expressions",
    "operator_subscript_correction",
}

__all__ = ["RULES", "DEFAULT_AUTO_FIX", "markdown", "artifacts", "math"]
