"""Expose transcribed papers as MCP resources."""
import json
import logging

from pdf_transcriber.config import Config
from pdf_transcriber.core.metadata_parser import extract_metadata_from_file

logger = logging.getLogger(__name__)


def register(mcp, config: Config):
    """Register paper resources with MCP server."""

    @mcp.resource("papers://index")
    def get_paper_index() -> str:
        """
        Get JSON index of all transcribed papers.

        Returns:
            JSON string with list of all papers and their metadata
        """
        papers = []

        if not config.output_dir.exists():
            return json.dumps({"papers": [], "total_count": 0}, indent=2)

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
                    if metadata:
                        papers.append({
                            "title": metadata.title,
                            "path": str(file_path),
                            "authors": metadata.authors,
                            "year": metadata.year,
                            "keywords": metadata.keywords,
                            "pages": metadata.total_pages
                        })
                except Exception as e:
                    logger.warning(f"Failed to index {file_path}: {e}")

        result = {
            "papers": papers,
            "total_count": len(papers)
        }

        return json.dumps(result, indent=2)

    @mcp.resource("papers://metadata/{paper_name}")
    def get_paper_metadata(paper_name: str) -> str:
        """
        Get metadata for a specific paper (read-only).

        Args:
            paper_name: Name of the paper (directory name)

        Returns:
            JSON string with paper metadata
        """
        paper_dir = config.output_dir / paper_name

        if not paper_dir.exists() or not paper_dir.is_dir():
            return json.dumps({"error": f"Paper not found: {paper_name}"}, indent=2)

        # Find the paper file (.md only)
        for file_path in paper_dir.glob("*.md"):
            # Skip original (pre-lint) files
            if file_path.stem.endswith(".original"):
                continue

            try:
                metadata = extract_metadata_from_file(file_path)
                if metadata:
                    result = {
                        "title": metadata.title,
                        "authors": metadata.authors,
                        "year": metadata.year,
                        "journal": metadata.journal,
                        "arxiv_id": metadata.arxiv_id,
                        "doi": metadata.doi,
                        "keywords": metadata.keywords,
                        "pages": metadata.total_pages,
                        "source_file": metadata.source_file,
                        "format": metadata.format,
                        "quality": metadata.quality,
                        "transcribed_at": metadata.transcribed_at
                    }
                    return json.dumps(result, indent=2)
            except Exception as e:
                logger.error(f"Failed to get metadata from {file_path}: {e}")

        return json.dumps({"error": "No metadata found"}, indent=2)
