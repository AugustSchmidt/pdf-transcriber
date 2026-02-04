"""list_papers tool implementation."""
import logging

from pdf_transcriber.config import Config
from pdf_transcriber.core.metadata_parser import extract_metadata_from_file

logger = logging.getLogger(__name__)


def register(mcp, config: Config):
    """Register list_papers tool with MCP server."""

    @mcp.tool()
    async def list_papers(
        sort_by: str = "title",
        filter_keywords: list[str] | None = None,
        filter_year_min: int | None = None,
        filter_year_max: int | None = None
    ) -> dict:
        """
        List all transcribed papers with optional filtering.

        Returns a list of all papers in the output directory with their metadata.
        Supports sorting and filtering by year and keywords.

        Args:
            sort_by: Sort field - "title", "year", or "transcribed_at" (default: "title")
            filter_keywords: Only include papers with ALL these keywords (optional)
            filter_year_min: Minimum publication year (optional)
            filter_year_max: Maximum publication year (optional)

        Returns:
            Dictionary with keys:
            - papers (list): List of paper metadata dicts
            - total_count (int): Total number of papers found

        Example:
            {
                "filter_keywords": ["algebraic geometry"],
                "filter_year_min": 2000,
                "sort_by": "year"
            }
        """
        papers = []

        # Scan output directory for papers
        if not config.output_dir.exists():
            return {
                "papers": [],
                "total_count": 0
            }

        for paper_dir in config.output_dir.iterdir():
            if not paper_dir.is_dir():
                continue

            # Look for .md files only (markdown output)
            for file_path in paper_dir.glob("*.md"):
                # Skip original (pre-lint) files
                if file_path.stem.endswith(".original"):
                    continue

                try:
                    metadata = extract_metadata_from_file(file_path)
                    if metadata is None:
                        continue

                    # Apply filters
                    if filter_keywords:
                        # Check if paper has ALL required keywords
                        paper_keywords_lower = [k.lower() for k in metadata.keywords]
                        if not all(
                            kw.lower() in paper_keywords_lower
                            for kw in filter_keywords
                        ):
                            continue

                    if filter_year_min is not None:
                        if metadata.year is None or metadata.year < filter_year_min:
                            continue

                    if filter_year_max is not None:
                        if metadata.year is None or metadata.year > filter_year_max:
                            continue

                    # Add to results
                    papers.append({
                        "title": metadata.title,
                        "path": str(file_path),
                        "authors": metadata.authors,
                        "year": metadata.year,
                        "keywords": metadata.keywords,
                        "pages": metadata.total_pages,
                        "transcribed_at": metadata.transcribed_at
                    })

                except Exception as e:
                    logger.warning(f"Failed to process {file_path}: {e}")

        # Sort papers
        if sort_by == "title":
            papers.sort(key=lambda p: p["title"].lower())
        elif sort_by == "year":
            papers.sort(key=lambda p: p["year"] if p["year"] is not None else 0, reverse=True)
        elif sort_by == "transcribed_at":
            papers.sort(key=lambda p: p["transcribed_at"], reverse=True)
        else:
            logger.warning(f"Unknown sort_by: {sort_by}, defaulting to title")
            papers.sort(key=lambda p: p["title"].lower())

        logger.info(f"Listed {len(papers)} papers (sort_by={sort_by})")

        return {
            "papers": papers,
            "total_count": len(papers)
        }
