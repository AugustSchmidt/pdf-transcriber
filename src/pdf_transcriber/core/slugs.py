"""Paper slug generation and registry integration.

Generates unique, deterministic slugs for papers based on author names
and title keywords. Integrates with the vault's paper registry.

NOTE: Paper slug utilities also in concept-extractor/core/registries.py.
Keep PaperRegistry interface in sync.
"""

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    pass


# =============================================================================
# Normalization Utilities
# =============================================================================

def normalize_text(text: str) -> str:
    """Normalize text to ASCII kebab-case.

    Examples:
        "Introduction to Shimura Varieties" -> "introduction-shimura-varieties"
        "Étale Cohomology" -> "etale-cohomology"
    """
    # Normalize unicode (é -> e, etc.)
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')

    # Split CamelCase before lowercasing (e.g., "SiegelModular" -> "Siegel-Modular")
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', text)
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', text)

    # Convert to lowercase
    text = text.lower()

    # Replace non-alphanumeric with hyphens
    text = re.sub(r'[^a-z0-9]+', '-', text)

    # Clean up multiple hyphens and strip
    text = re.sub(r'-+', '-', text)
    text = text.strip('-')

    return text


def extract_key_words(title: str, max_words: int = 3) -> list[str]:
    """Extract key words from a title for slug generation.

    Removes common words and returns up to max_words significant terms.
    """
    # Common words to skip
    stop_words = {
        'a', 'an', 'the', 'of', 'on', 'in', 'to', 'for', 'and', 'or',
        'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were',
        'introduction', 'notes', 'lecture', 'lectures', 'course',
        'some', 'new', 'old', 'more', 'further',
    }

    # Normalize and split
    normalized = normalize_text(title)
    words = [w for w in normalized.split('-') if w and w not in stop_words]

    return words[:max_words]


def extract_last_name(author: str) -> str:
    """Extract last name from author string.

    Handles formats like:
    - "J.S. Milne" -> "milne"
    - "Pierre Deligne" -> "deligne"
    - "Milne, J.S." -> "milne"
    """
    author = author.strip()

    # Handle "Last, First" format
    if ',' in author:
        author = author.split(',')[0]
    else:
        # Take last word (handles "First Last" and "F. Last")
        parts = author.split()
        if parts:
            author = parts[-1]

    return author.lower()


# =============================================================================
# Paper Slug Generation
# =============================================================================

def generate_paper_slug(
    title: str,
    authors: list[str],
    year: int | None = None,
    existing_slugs: set[str] | None = None,
) -> str:
    """Generate a unique slug for a paper.

    Format: author-keywords or author1-author2-keywords
    Adds year suffix if collision detected.

    Args:
        title: Paper title
        authors: List of author names (last names preferred)
        year: Publication year (used for disambiguation)
        existing_slugs: Set of existing paper slugs

    Returns:
        A unique paper slug

    Examples:
        ("Introduction to Shimura Varieties", ["Milne"])
            -> "milne-shimura-varieties"
        ("Berkeley Lectures on p-adic Geometry", ["Scholze", "Weinstein"])
            -> "scholze-weinstein-berkeley-lectures"
    """
    # Extract author component
    if not authors:
        author_part = "unknown"
    elif len(authors) == 1:
        author_part = extract_last_name(authors[0])
    elif len(authors) == 2:
        author_part = f"{extract_last_name(authors[0])}-{extract_last_name(authors[1])}"
    else:
        author_part = f"{extract_last_name(authors[0])}-et-al"

    author_part = normalize_text(author_part)

    # Extract key words from title
    key_words = extract_key_words(title, max_words=3)
    title_part = '-'.join(key_words) if key_words else 'untitled'

    base_slug = f"{author_part}-{title_part}"

    if existing_slugs is None or base_slug not in existing_slugs:
        return base_slug

    # Try with year
    if year:
        with_year = f"{base_slug}-{year}"
        if with_year not in existing_slugs:
            return with_year

    # Fallback: add numeric suffix
    for i in range(2, 100):
        candidate = f"{base_slug}-{i}"
        if candidate not in existing_slugs:
            return candidate

    raise ValueError(
        f"Could not generate unique paper slug for '{title}' by {authors}."
    )


# =============================================================================
# Paper Registry
# =============================================================================

class PaperRegistry:
    """Interface to the paper registry YAML file."""

    def __init__(self, registry_path: Path):
        self.path = registry_path
        self._data: dict | None = None

    def load(self) -> dict:
        """Load registry from disk."""
        if self.path.exists():
            with open(self.path) as f:
                self._data = yaml.safe_load(f) or {'papers': {}}
        else:
            self._data = {'papers': {}}
        return self._data

    def save(self) -> None:
        """Save registry to disk."""
        if self._data is None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve header comments
        header = """# Paper Registry
#
# Central registry mapping paper slugs to metadata.
# Maintained by pdf-transcriber and concept-extractor.

"""
        with open(self.path, 'w') as f:
            f.write(header)
            yaml.dump(
                self._data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    def get(self, slug: str) -> dict | None:
        """Get paper metadata by slug."""
        if self._data is None:
            self.load()
        return self._data.get('papers', {}).get(slug)

    def exists(self, slug: str) -> bool:
        """Check if a paper slug exists."""
        return self.get(slug) is not None

    def get_all_slugs(self) -> set[str]:
        """Get all registered paper slugs."""
        if self._data is None:
            self.load()
        return set(self._data.get('papers', {}).keys())

    def find_by_alias(self, alias: str) -> str | None:
        """Find paper slug by alias."""
        if self._data is None:
            self.load()

        alias_lower = alias.lower()
        for slug, info in self._data.get('papers', {}).items():
            if slug.lower() == alias_lower:
                return slug
            for a in info.get('aliases', []):
                if a.lower() == alias_lower:
                    return slug
        return None

    def register(
        self,
        slug: str,
        title: str,
        authors: list[str],
        year: int | None = None,
        paper_type: str = "article",
        transcription_path: str | None = None,
        pdf_path: str | None = None,
        aliases: list[str] | None = None,
        **extra,
    ) -> None:
        """Register a new paper or update existing."""
        if self._data is None:
            self.load()

        entry = {
            'title': title,
            'authors': authors,
        }

        if year:
            entry['year'] = year
        entry['type'] = paper_type
        entry['paths'] = {
            'transcription': transcription_path,
            'pdf': pdf_path,
        }

        if aliases:
            entry['aliases'] = aliases

        entry.update(extra)

        self._data['papers'][slug] = entry

    def update_path(self, slug: str, path_type: str, path: str | None) -> None:
        """Update a specific path for a paper."""
        if self._data is None:
            self.load()

        if slug in self._data.get('papers', {}):
            if 'paths' not in self._data['papers'][slug]:
                self._data['papers'][slug]['paths'] = {}
            self._data['papers'][slug]['paths'][path_type] = path


def get_or_create_paper_slug(
    registry: PaperRegistry,
    title: str,
    authors: list[str],
    year: int | None = None,
    paper_type: str = "article",
) -> tuple[str, bool]:
    """Get existing paper slug or create a new one.

    Returns:
        Tuple of (slug, is_new) where is_new indicates if this is a new paper.
    """
    existing_slugs = registry.get_all_slugs()

    # Check if we can match an existing paper
    candidate_slug = generate_paper_slug(title, authors, year, existing_slugs=None)
    if candidate_slug in existing_slugs:
        # Found exact match
        return candidate_slug, False

    # Generate new unique slug
    slug = generate_paper_slug(title, authors, year, existing_slugs)
    return slug, True
