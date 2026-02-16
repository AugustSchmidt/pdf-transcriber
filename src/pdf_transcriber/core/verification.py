"""Page content verification and fallback OCR."""
import re
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result from verifying transcribed page content."""
    is_valid: bool
    error_type: str | None = None
    error_message: str | None = None
    matched_pattern: str | None = None


def verify_page_content(content: str, page_num: int) -> VerificationResult:
    """
    Verify that page content doesn't contain hallucinations or artifacts.

    Checks for:
    - Repetition hallucinations (token loops from context overflow)
    - Merged content comments (Marker page splitting failures)
    - Garbled text patterns

    Args:
        content: The transcribed page content
        page_num: Page number (for logging)

    Returns:
        VerificationResult indicating if content is valid
    """
    # Check 1a: Single-character repetition hallucinations
    # Pattern: A single letter repeated 5+ times separated by whitespace
    # Example: "g g g g g g g g g g" (Prop. 5 in Serre, Local Fields)
    # This catches cases the multi-word pattern misses because the last
    # token lacks trailing whitespace, making backreference count off-by-one.
    single_char_pattern = re.compile(
        r'\b([a-zA-Z])\s+(?:\1\s+){3,}\1?\b'  # single char repeated 5+ times
    )

    match = single_char_pattern.search(content)
    if match:
        repeated_char = match.group(1)
        full_match = match.group(0)
        repeat_count = full_match.count(repeated_char)

        logger.warning(
            f"Page {page_num}: Single-character repetition hallucination - "
            f"'{repeated_char}' repeated {repeat_count}x"
        )

        return VerificationResult(
            is_valid=False,
            error_type="repetition_hallucination",
            error_message=f"Detected '{repeated_char}' repeated {repeat_count} times",
            matched_pattern=full_match[:200]
        )

    # Check 1b: Multi-word repetition hallucinations
    # Pattern: Any 1-5 word phrase repeated 10+ times
    # Example: "f in f in f in f in..." or "fixed points of E fixed points of E..."
    repetition_pattern = re.compile(
        r'\b((?:\w+\s+){1,5})\1{9,}',  # 1-5 words repeated 10+ times
        re.IGNORECASE
    )

    match = repetition_pattern.search(content)
    if match:
        repeated_unit = match.group(1).strip()
        full_match = match.group(0)
        repeat_count = len(full_match) // len(match.group(1))

        logger.warning(
            f"Page {page_num}: Repetition hallucination detected - "
            f"'{repeated_unit}' repeated {repeat_count}x"
        )

        return VerificationResult(
            is_valid=False,
            error_type="repetition_hallucination",
            error_message=f"Detected '{repeated_unit}' repeated {repeat_count} times",
            matched_pattern=full_match[:200]  # First 200 chars of match
        )

    # Check 2: Content merged comments (indicator of Marker failure)
    # Pattern: <!-- Content merged with page N -->
    merged_pattern = re.compile(
        r'<!--\s*Content merged with page \d+\s*-->',
        re.IGNORECASE
    )

    if merged_pattern.search(content):
        logger.warning(
            f"Page {page_num}: Contains 'Content merged' comment - "
            "Marker failed to split pages properly"
        )

        return VerificationResult(
            is_valid=False,
            error_type="page_merge_failure",
            error_message="Marker failed to split pages correctly",
            matched_pattern=merged_pattern.search(content).group(0)
        )

    # Check 3: Excessive gibberish (>50% non-ASCII or unprintable chars)
    if len(content) > 100:  # Only check non-trivial pages
        non_ascii_count = sum(1 for c in content if ord(c) > 127 or not c.isprintable() and c not in '\n\t ')
        non_ascii_ratio = non_ascii_count / len(content)

        if non_ascii_ratio > 0.5:
            logger.warning(
                f"Page {page_num}: Excessive non-ASCII content "
                f"({non_ascii_ratio:.1%}) - likely garbled"
            )

            return VerificationResult(
                is_valid=False,
                error_type="garbled_text",
                error_message=f"Non-ASCII ratio: {non_ascii_ratio:.1%}",
                matched_pattern=None
            )

    # All checks passed
    return VerificationResult(is_valid=True)


async def fallback_to_pymupdf(pdf_path: Path, page_num: int) -> str:
    """
    Extract text from a single page using PyMuPDF as fallback.

    This is a simpler text-only extraction used when Marker OCR fails
    or produces hallucinations. It doesn't preserve formatting as well
    as Marker but is more reliable.

    Args:
        pdf_path: Path to the PDF file
        page_num: 1-indexed page number to extract

    Returns:
        Extracted text content
    """
    try:
        import pymupdf
    except ImportError:
        logger.error("PyMuPDF not installed - cannot use fallback extraction")
        raise ImportError(
            "PyMuPDF is required for fallback extraction. "
            "Install with: pip install pymupdf"
        )

    try:
        doc = pymupdf.open(pdf_path)
        page = doc[page_num - 1]  # PyMuPDF uses 0-indexing
        text = page.get_text()
        doc.close()

        # Basic cleanup
        # Remove page number at top (usually standalone number)
        text = re.sub(r'^\d+\s*\n', '', text, count=1)

        # Remove common headers
        text = re.sub(r'Pre-publication version.*?Algebraic Geometry\s*\n', '', text)

        logger.info(f"Page {page_num}: Extracted {len(text)} chars via PyMuPDF fallback")
        return text.strip()

    except Exception as e:
        logger.error(f"PyMuPDF extraction failed for page {page_num}: {e}")
        raise


def should_retry_with_fallback(verification: VerificationResult) -> bool:
    """
    Determine if we should retry with PyMuPDF based on verification result.

    Some failures are worth retrying (repetitions, garbled text),
    others are not (page merge comments just mean Marker combined pages,
    which is informational but not a content quality issue).

    Args:
        verification: The verification result

    Returns:
        True if we should retry with PyMuPDF
    """
    if verification.is_valid:
        return False

    # Retry on these error types
    retry_types = {
        "repetition_hallucination",
        "garbled_text",
    }

    # Don't retry on page_merge_failure - that's just informational
    # (Marker combined pages, but the content itself is fine)

    return verification.error_type in retry_types
