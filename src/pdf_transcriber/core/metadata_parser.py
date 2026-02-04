"""YAML frontmatter parsing and generation."""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import re
import logging

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PaperMetadata:
    """Metadata for a transcribed paper."""

    # Identity
    paper_slug: str | None = None  # Unique identifier for this paper

    # Bibliographic
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None

    # Processing
    source_file: str = ""
    transcribed_at: str = ""
    transcriber_version: str = "1.0.0"
    format: str = "markdown"
    quality: str = "balanced"
    total_pages: int = 0
    transcribed_pages: int = 0

    # User keywords (searchable)
    keywords: list[str] = field(default_factory=list)

    # Auto-extracted sections
    sections: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary, excluding None values."""
        data = asdict(self)
        # Remove None values for cleaner YAML
        return {k: v for k, v in data.items() if v is not None and v != ""}

    @classmethod
    def from_dict(cls, data: dict) -> "PaperMetadata":
        """Create from dictionary."""
        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


def parse_frontmatter(content: str) -> tuple[PaperMetadata | None, str]:
    """
    Extract YAML frontmatter and body from markdown/LaTeX content.

    Args:
        content: File content with potential frontmatter

    Returns:
        Tuple of (metadata, body)
        - metadata is None if no frontmatter found
        - body is the content without frontmatter
    """
    # Match YAML frontmatter: ---\n...\n---\n
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)

    if not match:
        return None, content

    frontmatter_yaml, body = match.groups()

    try:
        data = yaml.safe_load(frontmatter_yaml)
        if not isinstance(data, dict):
            logger.warning("Frontmatter is not a dictionary, ignoring")
            return None, content

        metadata = PaperMetadata.from_dict(data)
        return metadata, body

    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML frontmatter: {e}")
        return None, content


def generate_frontmatter(metadata: PaperMetadata) -> str:
    """
    Generate YAML frontmatter string from metadata.

    Args:
        metadata: Paper metadata

    Returns:
        YAML frontmatter block (including --- delimiters)
    """
    data = metadata.to_dict()

    # Custom YAML formatting for readability
    yaml_str = yaml.dump(
        data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=80
    )

    return f"---\n{yaml_str}---\n"


def update_frontmatter(content: str, updates: dict) -> str:
    """
    Update specific frontmatter fields without touching body.

    Args:
        content: File content with frontmatter
        updates: Dictionary of fields to update

    Returns:
        Updated content with modified frontmatter
    """
    metadata, body = parse_frontmatter(content)

    if metadata is None:
        # No existing frontmatter, create new
        metadata = PaperMetadata(title="Unknown")

    # Apply updates
    for key, value in updates.items():
        if hasattr(metadata, key):
            setattr(metadata, key, value)
        else:
            logger.warning(f"Unknown metadata field: {key}")

    return generate_frontmatter(metadata) + "\n" + body


def add_keywords(content: str, keywords: list[str]) -> str:
    """
    Add keywords to frontmatter.

    Args:
        content: File content
        keywords: Keywords to add

    Returns:
        Updated content
    """
    metadata, body = parse_frontmatter(content)

    if metadata is None:
        metadata = PaperMetadata(title="Unknown")

    # Add new keywords (avoid duplicates)
    existing = set(metadata.keywords)
    for kw in keywords:
        if kw not in existing:
            metadata.keywords.append(kw)

    return generate_frontmatter(metadata) + "\n" + body


def remove_keywords(content: str, keywords: list[str]) -> str:
    """
    Remove keywords from frontmatter.

    Args:
        content: File content
        keywords: Keywords to remove

    Returns:
        Updated content
    """
    metadata, body = parse_frontmatter(content)

    if metadata is None:
        return content

    # Remove keywords
    to_remove = set(keywords)
    metadata.keywords = [kw for kw in metadata.keywords if kw not in to_remove]

    return generate_frontmatter(metadata) + "\n" + body


def extract_metadata_from_file(file_path: Path) -> PaperMetadata | None:
    """
    Extract metadata from a paper file.

    Args:
        file_path: Path to .md or .tex file

    Returns:
        PaperMetadata if found, None otherwise
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        metadata, _ = parse_frontmatter(content)
        return metadata
    except Exception as e:
        logger.error(f"Failed to extract metadata from {file_path}: {e}")
        return None


def create_initial_metadata(
    title: str,
    pdf_source: Path,
    total_pages: int,
    output_format: str,
    quality: str,
    **kwargs
) -> PaperMetadata:
    """
    Create initial metadata for a new transcription.

    Args:
        title: Paper title
        pdf_source: Path to source PDF
        total_pages: Total pages in PDF
        output_format: "markdown" or "latex"
        quality: Quality preset
        **kwargs: Additional metadata fields (authors, year, keywords, etc.)

    Returns:
        PaperMetadata
    """
    now = datetime.utcnow().isoformat() + "Z"

    metadata = PaperMetadata(
        title=title,
        source_file=str(pdf_source),
        transcribed_at=now,
        format=output_format,
        quality=quality,
        total_pages=total_pages,
        transcribed_pages=total_pages,  # Will be updated during transcription
        **kwargs
    )

    return metadata
