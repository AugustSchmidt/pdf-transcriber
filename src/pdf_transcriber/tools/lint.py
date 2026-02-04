"""lint_paper tool implementation."""
import logging
from pathlib import Path

from pdf_transcriber.config import Config
from pdf_transcriber.core.linter import engine

logger = logging.getLogger(__name__)


def register(mcp, config: Config):
    """Register lint_paper tool with MCP server."""

    @mcp.tool()
    async def lint_paper(
        paper_path: str,
        fix: bool = True,
        rules: list[str] | None = None
    ) -> dict:
        """
        Lint a transcribed paper for formatting issues and PDF artifacts.

        Checks for markdown structure issues and common PDF transcription artifacts.
        Can auto-fix safe issues like extra blank lines, trailing whitespace,
        page numbers, and orphaned LaTeX labels.

        Markdown rules:
        - excessive_blank_lines: >2 consecutive blank lines (auto-fix)
        - trailing_whitespace: spaces/tabs at end of lines (auto-fix)
        - sparse_table_row: table rows >50% empty cells (warning)
        - orphaned_list_marker: list markers with no content (warning)
        - long_line: lines >500 chars (warning)

        PDF artifact rules:
        - page_number: standalone numbers like "42" (auto-fix)
        - orphaned_label: LaTeX labels like "def:Tilt" (auto-fix)
        - garbled_text: corrupted/nonsense text fragments (warning)
        - hyphenation_artifact: words split across lines (auto-fix)
        - repeated_line: likely running headers/footers (warning)

        Args:
            paper_path: Path to the .md file (absolute or relative to output dir)
            fix: Auto-fix safe issues and write back to file (default: True)
            rules: List of specific rules to run (default: all rules)

        Returns:
            Dictionary with:
            - paper_path (str): Path that was linted
            - total_issues (int): Total issues found
            - auto_fixable (int): Issues that can be auto-fixed
            - warnings (int): Issues needing manual review
            - errors (int): Critical issues
            - issues (list): Individual issues with line numbers
            - fixed (list): Rules that were auto-applied (if fix=True)

        Example:
            {
                "paper_path": "Lecture Notes on Perfectoid Spaces - Bhatt/...",
                "fix": true
            }
        """
        # Resolve path
        path = Path(paper_path)
        if not path.is_absolute():
            path = config.output_dir / paper_path

        if not path.exists():
            return {"error": f"File not found: {path}"}

        if path.suffix != '.md':
            return {"error": f"Expected .md file, got: {path.suffix}"}

        logger.info(f"Linting {path} (fix={fix}, rules={rules})")

        try:
            # Run linter
            report = await engine.lint_file(path, fix=fix, rules=rules)

            logger.info(
                f"Lint complete: {report.total_issues} issues "
                f"({report.auto_fixable} auto-fixable, {report.warnings} warnings)"
            )

            if fix and report.fixed:
                logger.info(f"Auto-fixed: {', '.join(report.fixed)}")

            return report.to_dict()

        except Exception as e:
            logger.error(f"Lint failed: {e}", exc_info=True)
            return {"error": str(e)}

    @mcp.tool()
    async def generate_lint_report(
        paper_path: str,
        output_path: str | None = None
    ) -> dict:
        """
        Generate a markdown lint report for manual review.

        Creates a lint-report.md file in the paper's directory (or at output_path)
        listing all issues grouped by rule with line numbers for easy navigation.

        Args:
            paper_path: Path to the .md file to lint
            output_path: Optional custom output path (default: same dir as paper)

        Returns:
            Dictionary with:
            - report_path (str): Path to generated report
            - total_issues (int): Total issues found
            - warnings (int): Number of warnings needing review
        """
        from pathlib import Path

        # Resolve path
        path = Path(paper_path)
        if not path.is_absolute():
            path = config.output_dir / paper_path

        if not path.exists():
            return {"error": f"File not found: {path}"}

        # Run linter
        report = await engine.lint_file(path, fix=False)

        # Determine output path
        if output_path:
            out_path = Path(output_path)
        else:
            out_path = path.parent / "lint-report.md"

        # Generate markdown report
        lines = [
            f"# Lint Report: {path.stem}",
            "",
            f"**Source:** `{path.name}`",
            f"**Total issues:** {report.total_issues}",
            f"**Auto-fixable:** {report.auto_fixable}",
            f"**Warnings to review:** {report.warnings}",
            "",
            "---",
            "",
        ]

        # Group by rule
        by_rule: dict[str, list] = {}
        for issue in report.issues:
            if issue.rule not in by_rule:
                by_rule[issue.rule] = []
            by_rule[issue.rule].append(issue)

        for rule, issues in sorted(by_rule.items()):
            severity = issues[0].severity.value
            emoji = "✅" if severity == "auto_fix" else "⚠️"
            lines.append(f"## {emoji} {rule} ({len(issues)} issues)")
            lines.append("")

            for issue in issues:
                msg = issue.message[:120] + "..." if len(issue.message) > 120 else issue.message
                lines.append(f"- **Line {issue.line}**: {msg}")

            lines.append("")

        out_path.write_text("\n".join(lines), encoding="utf-8")

        logger.info(f"Lint report written to {out_path}")

        return {
            "report_path": str(out_path),
            "total_issues": report.total_issues,
            "warnings": report.warnings
        }

    @mcp.tool()
    async def get_lint_rules() -> dict:
        """
        Get list of available lint rules with descriptions.

        Returns:
            Dictionary mapping rule names to their descriptions.

        Example response:
            {
                "rules": {
                    "excessive_blank_lines": "Flag more than 2 consecutive blank lines.",
                    "page_number": "Detect and remove standalone page numbers.",
                    ...
                }
            }
        """
        return {"rules": engine.get_available_rules()}
