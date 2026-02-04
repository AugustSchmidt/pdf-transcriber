"""Lint engine - runs rules and applies fixes."""
import logging
import re
from pathlib import Path
from typing import Optional

from .models import LintIssue, LintReport, Severity, Fix
from .rules import RULES, DEFAULT_AUTO_FIX

logger = logging.getLogger(__name__)


async def lint_file(
    path: Path,
    fix: bool = False,
    rules: Optional[list[str]] = None
) -> LintReport:
    """
    Lint a markdown file.

    Args:
        path: Path to the .md file
        fix: If True, apply auto-fixes and write back
        rules: Specific rules to run (default: all)

    Returns:
        LintReport with all issues found
    """
    content = path.read_text(encoding='utf-8')

    report = await lint_content(content, str(path), rules=rules)

    if fix and report.auto_fixable > 0:
        fixed_content, fixed_rules = apply_fixes(content, report.issues)
        report.fixed = fixed_rules

        if fixed_content != content:
            path.write_text(fixed_content, encoding='utf-8')
            logger.info(f"Wrote {len(fixed_rules)} fixes to {path}")

    return report


async def lint_content(
    content: str,
    source_path: str = "<string>",
    rules: Optional[list[str]] = None
) -> LintReport:
    """
    Lint markdown content.

    Args:
        content: The markdown content to lint
        source_path: Path for reporting (doesn't need to exist)
        rules: Specific rules to run (default: all)

    Returns:
        LintReport with all issues found
    """
    report = LintReport(paper_path=source_path)

    # Determine which rules to run
    rules_to_run = rules if rules else list(RULES.keys())

    # Skip frontmatter when linting
    content_without_frontmatter, frontmatter_lines = _extract_frontmatter(content)

    for rule_name in rules_to_run:
        if rule_name not in RULES:
            logger.warning(f"Unknown rule: {rule_name}")
            continue

        rule_func = RULES[rule_name]

        try:
            for issue in rule_func(content_without_frontmatter):
                # Adjust line numbers to account for frontmatter
                issue.line += frontmatter_lines
                report.add_issue(issue)
        except Exception as e:
            logger.error(f"Rule {rule_name} failed: {e}")

    # Sort issues by line number
    report.issues.sort(key=lambda i: i.line)

    return report


def apply_fixes(content: str, issues: list[LintIssue]) -> tuple[str, list[str]]:
    """
    Apply auto-fixes to content.

    Only applies fixes for issues with Severity.AUTO_FIX.
    Applies fixes in reverse order to preserve line numbers.

    Args:
        content: Original content
        issues: List of issues from linting

    Returns:
        Tuple of (fixed_content, list_of_applied_rule_names)
    """
    # Filter to auto-fixable issues with fixes
    fixable = [
        i for i in issues
        if i.severity == Severity.AUTO_FIX and i.fix is not None
    ]

    if not fixable:
        return content, []

    # Track which rules were applied
    applied_rules: set[str] = set()

    # For trailing whitespace, we need line-based fixing
    # For other rules, we do string replacement

    # Separate line-based vs content-based fixes
    line_fixes: dict[int, Fix] = {}  # line_num -> fix (for trailing_whitespace)
    content_fixes: list[tuple[str, str]] = []  # (old, new) pairs

    for issue in fixable:
        if issue.fix is None:
            continue

        if issue.rule == "trailing_whitespace":
            line_fixes[issue.line] = issue.fix
            applied_rules.add(issue.rule)
        else:
            content_fixes.append((issue.fix.old, issue.fix.new))
            applied_rules.add(issue.rule)

    # Apply line-based fixes first (trailing whitespace)
    if line_fixes:
        lines = content.split('\n')
        for line_num, fix in line_fixes.items():
            idx = line_num - 1
            if 0 <= idx < len(lines) and lines[idx] == fix.old:
                lines[idx] = fix.new
        content = '\n'.join(lines)

    # Apply content-based fixes
    # Sort by length of old string (longest first) to avoid partial replacements
    content_fixes.sort(key=lambda x: len(x[0]), reverse=True)

    for old, new in content_fixes:
        # Only replace first occurrence to be safe
        content = content.replace(old, new, 1)

    return content, sorted(applied_rules)


def _extract_frontmatter(content: str) -> tuple[str, int]:
    """
    Extract YAML frontmatter from content.

    Returns:
        Tuple of (content_without_frontmatter, num_frontmatter_lines)
    """
    if not content.startswith('---'):
        return content, 0

    # Find the closing ---
    match = re.match(r'^---\s*\n.*?\n---\s*\n', content, re.DOTALL)
    if not match:
        return content, 0

    frontmatter = match.group()
    frontmatter_lines = frontmatter.count('\n')

    return content[len(frontmatter):], frontmatter_lines


def get_available_rules() -> dict[str, str]:
    """
    Get list of available rules with descriptions.

    Returns:
        Dict mapping rule name to docstring
    """
    return {
        name: (func.__doc__ or "No description").strip().split('\n')[0]
        for name, func in RULES.items()
    }
