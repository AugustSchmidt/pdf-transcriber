"""search_papers tool implementation."""
from pathlib import Path
import logging
import re

from pdf_transcriber.config import Config
from pdf_transcriber.core.metadata_parser import extract_metadata_from_file

logger = logging.getLogger(__name__)


def register(mcp, config: Config):
    """Register search_papers tool with MCP server."""

    @mcp.tool()
    async def search_papers(
        query: str,
        search_fields: list[str] | None = None,
        limit: int = 10
    ) -> dict:
        """
        Search transcribed papers by metadata and keywords.

        Performs a simple text-based search across paper metadata and content.
        Searches in title, authors, keywords, and optionally full content.

        Args:
            query: Natural language search query (searches for words in query)
            search_fields: Fields to search - ["title", "authors", "keywords", "content"]
                          (default: ["title", "authors", "keywords"])
            limit: Maximum results to return (default: 10)

        Returns:
            Dictionary with keys:
            - results (list): List of matching papers with metadata
            - total_matches (int): Total number of matches found

        Example:
            {
                "query": "shimura varieties",
                "search_fields": ["title", "keywords"],
                "limit": 5
            }
        """
        # Default search fields
        if search_fields is None:
            search_fields = ["title", "authors", "keywords"]

        # Normalize query for searching
        query_lower = query.lower()
        query_words = re.findall(r'\w+', query_lower)

        results = []

        # Scan output directory for papers
        if not config.output_dir.exists():
            return {
                "results": [],
                "total_matches": 0
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
                    result = await _search_file(
                        file_path, query_words, search_fields
                    )
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.warning(f"Failed to search {file_path}: {e}")

        # Sort by relevance score (descending)
        results.sort(key=lambda x: x["relevance_score"], reverse=True)

        # Apply limit
        limited_results = results[:limit]

        logger.info(
            f"Search for '{query}': {len(results)} matches, "
            f"returning {len(limited_results)}"
        )

        return {
            "results": limited_results,
            "total_matches": len(results)
        }


async def _search_file(
    file_path: Path,
    query_words: list[str],
    search_fields: list[str]
) -> dict | None:
    """
    Search a single file.

    Returns:
        Result dict if matches, None otherwise
    """
    # Extract metadata
    metadata = extract_metadata_from_file(file_path)

    if metadata is None:
        return None

    # Build searchable text from requested fields
    searchable_parts = []

    if "title" in search_fields and metadata.title:
        searchable_parts.append(metadata.title.lower())

    if "authors" in search_fields and metadata.authors:
        searchable_parts.extend([a.lower() for a in metadata.authors])

    if "keywords" in search_fields and metadata.keywords:
        searchable_parts.extend([k.lower() for k in metadata.keywords])

    if "content" in search_fields:
        # Read file content (expensive, only if requested)
        try:
            content = file_path.read_text(encoding="utf-8")
            # Remove frontmatter for content search
            content_match = re.search(r'---\s*\n.*?\n---\s*\n(.*)$', content, re.DOTALL)
            if content_match:
                searchable_parts.append(content_match.group(1).lower())
        except Exception as e:
            logger.warning(f"Failed to read content from {file_path}: {e}")

    searchable_text = " ".join(searchable_parts)

    # Calculate relevance score (how many query words match)
    matches = sum(1 for word in query_words if word in searchable_text)

    if matches == 0:
        return None

    # Calculate relevance score as percentage of query words that matched
    relevance_score = matches / len(query_words) if query_words else 0.0

    # Extract snippet (first occurrence of a query word)
    snippet = ""
    for word in query_words:
        pattern = re.compile(rf'\b.{{0,50}}{re.escape(word)}.{{0,50}}\b', re.IGNORECASE)
        match = pattern.search(searchable_text)
        if match:
            snippet = "..." + match.group(0) + "..."
            break

    return {
        "title": metadata.title,
        "path": str(file_path),
        "authors": metadata.authors,
        "year": metadata.year,
        "keywords": metadata.keywords,
        "relevance_score": relevance_score,
        "snippet": snippet
    }
