"""update_paper_metadata tool implementation."""
from pathlib import Path
import logging

from pdf_transcriber.config import Config
from pdf_transcriber.core.metadata_parser import (
    parse_frontmatter,
    update_frontmatter,
    add_keywords,
    remove_keywords
)

logger = logging.getLogger(__name__)


def register(mcp, config: Config):
    """Register update_paper_metadata tool with MCP server."""

    @mcp.tool()
    async def update_paper_metadata(
        paper_path: str,
        title: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        journal: str | None = None,
        arxiv_id: str | None = None,
        doi: str | None = None,
        keywords_add: list[str] | None = None,
        keywords_remove: list[str] | None = None
    ) -> dict:
        """
        Update metadata for an existing transcribed paper.

        Modifies the YAML frontmatter of a transcribed paper file.
        Can update bibliographic information and manage keywords.

        Args:
            paper_path: Path to the transcribed markdown/latex file
            title: New title (optional)
            authors: New authors list (optional)
            year: Publication year (optional)
            journal: Journal name (optional)
            arxiv_id: arXiv identifier (optional)
            doi: DOI (optional)
            keywords_add: Keywords to add (optional)
            keywords_remove: Keywords to remove (optional)

        Returns:
            Dictionary with keys:
            - success (bool): Whether update succeeded
            - updated_fields (list[str]): List of fields that were updated
            - current_metadata (dict): Current metadata after updates
            - error (str | None): Error message if failed

        Example:
            {
                "paper_path": "~/Vaults/.../shimura-varieties.md",
                "keywords_add": ["abelian varieties", "complex multiplication"],
                "year": 2017
            }
        """
        # Validate and expand path
        paper_path = Path(paper_path).expanduser().resolve()

        if not paper_path.exists():
            return {
                "success": False,
                "updated_fields": [],
                "current_metadata": {},
                "error": f"Paper not found: {paper_path}"
            }

        # Read current content
        try:
            content = paper_path.read_text(encoding="utf-8")
        except Exception as e:
            return {
                "success": False,
                "updated_fields": [],
                "current_metadata": {},
                "error": f"Failed to read paper: {e}"
            }

        # Track which fields were updated
        updated_fields = []

        # Build updates dictionary (only non-None values)
        updates = {}
        if title is not None:
            updates["title"] = title
            updated_fields.append("title")
        if authors is not None:
            updates["authors"] = authors
            updated_fields.append("authors")
        if year is not None:
            updates["year"] = year
            updated_fields.append("year")
        if journal is not None:
            updates["journal"] = journal
            updated_fields.append("journal")
        if arxiv_id is not None:
            updates["arxiv_id"] = arxiv_id
            updated_fields.append("arxiv_id")
        if doi is not None:
            updates["doi"] = doi
            updated_fields.append("doi")

        # Apply field updates
        try:
            if updates:
                content = update_frontmatter(content, updates)

            # Handle keyword additions
            if keywords_add:
                content = add_keywords(content, keywords_add)
                updated_fields.append("keywords (added)")

            # Handle keyword removals
            if keywords_remove:
                content = remove_keywords(content, keywords_remove)
                updated_fields.append("keywords (removed)")

            # Write updated content
            paper_path.write_text(content, encoding="utf-8")

        except Exception as e:
            return {
                "success": False,
                "updated_fields": updated_fields,
                "current_metadata": {},
                "error": f"Failed to update metadata: {e}"
            }

        # Extract and return current metadata
        try:
            metadata, _ = parse_frontmatter(content)
            current_meta = metadata.to_dict() if metadata else {}
        except Exception as e:
            logger.warning(f"Failed to parse updated metadata: {e}")
            current_meta = {}

        logger.info(
            f"Updated metadata for {paper_path.name}: "
            f"fields={updated_fields}"
        )

        return {
            "success": True,
            "updated_fields": updated_fields,
            "current_metadata": current_meta,
            "error": None
        }
