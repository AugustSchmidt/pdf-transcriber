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

        Checks for markdown structure issues, PDF transcription artifacts, and
        math notation problems. Can auto-fix safe issues.

        Args:
            paper_path: Path to the .md file (absolute or relative to output dir)
            fix: Auto-fix safe issues and write back to file (default: True)
            rules: List of specific rules to run (default: all rules).
                   Available rules: excessive_blank_lines, trailing_whitespace,
                   page_number, orphaned_label, hyphenation_artifact,
                   unicode_math_symbols, html_artifacts, and more.

        Returns:
            Dictionary with:
            - paper_path (str): Path that was linted
            - total_issues (int): Total issues found
            - auto_fixable (int): Issues that can be auto-fixed
            - warnings (int): Issues needing manual review
            - issues (list): Individual issues with line numbers
            - fixed (list): Rules that were auto-applied (if fix=True)
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
