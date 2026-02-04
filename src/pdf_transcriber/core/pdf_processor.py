"""PDF to image conversion using PyMuPDF."""
from pathlib import Path
import base64
import logging

try:
    import fitz  # PyMuPDF
except ImportError:
    raise ImportError(
        "PyMuPDF is required for PDF processing. "
        "Install with: pip install pymupdf"
    )

logger = logging.getLogger(__name__)


class PDFProcessor:
    """
    PDF processor with context manager support.

    Converts PDF pages to base64-encoded PNG images for Claude vision API.
    Uses PyMuPDF (fitz) for rendering with configurable DPI.
    """

    def __init__(self, pdf_path: str | Path, dpi: int = 150):
        """
        Initialize PDF processor.

        Args:
            pdf_path: Path to PDF file
            dpi: Resolution for rendering (default: 150)
                 - 100 DPI: ~1275×1650px (fast)
                 - 150 DPI: ~1913×2475px (balanced - recommended)
                 - 200 DPI: ~2550×3300px (high quality)
        """
        self.pdf_path = Path(pdf_path).expanduser().resolve()
        self.dpi = dpi
        self.doc = None

        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")

    def __enter__(self):
        """Open PDF document."""
        try:
            self.doc = fitz.open(self.pdf_path)
            logger.info(
                f"Opened PDF: {self.pdf_path.name} "
                f"({self.total_pages} pages at {self.dpi} DPI)"
            )
            return self
        except Exception as e:
            raise ValueError(f"Failed to open PDF: {e}") from e

    def __exit__(self, *args):
        """Close PDF document."""
        if self.doc:
            self.doc.close()
            self.doc = None

    @property
    def total_pages(self) -> int:
        """Get total number of pages in PDF."""
        if not self.doc:
            raise RuntimeError("PDF not opened. Use context manager: 'with PDFProcessor(...) as proc:'")
        return len(self.doc)

    def get_page_as_base64(self, page_num: int) -> tuple[str, str]:
        """
        Convert single page to base64-encoded PNG.

        Args:
            page_num: 1-indexed page number

        Returns:
            Tuple of (base64_data, media_type)

        Raises:
            RuntimeError: If PDF not opened
            IndexError: If page_num out of range
        """
        if not self.doc:
            raise RuntimeError("PDF not opened. Use context manager.")

        if page_num < 1 or page_num > self.total_pages:
            raise IndexError(
                f"Page {page_num} out of range (1-{self.total_pages})"
            )

        # PyMuPDF uses 0-indexing
        page = self.doc[page_num - 1]

        # Create transformation matrix for desired DPI
        # Standard PDF resolution is 72 DPI, so scale factor = dpi / 72
        mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)

        # Render page to pixmap
        try:
            pix = page.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes("png")
            base64_data = base64.standard_b64encode(png_bytes).decode("utf-8")

            logger.debug(
                f"Rendered page {page_num}: {pix.width}×{pix.height}px, "
                f"{len(png_bytes) / 1024:.1f}KB"
            )

            return base64_data, "image/png"

        except Exception as e:
            raise RuntimeError(f"Failed to render page {page_num}: {e}") from e

    def get_page_dimensions(self, page_num: int) -> tuple[int, int]:
        """
        Get rendered page dimensions at current DPI.

        Args:
            page_num: 1-indexed page number

        Returns:
            Tuple of (width, height) in pixels
        """
        if not self.doc:
            raise RuntimeError("PDF not opened. Use context manager.")

        if page_num < 1 or page_num > self.total_pages:
            raise IndexError(f"Page {page_num} out of range")

        page = self.doc[page_num - 1]
        mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
        rect = page.rect * mat

        return int(rect.width), int(rect.height)

    def get_all_page_dimensions(self) -> list[tuple[int, int]]:
        """
        Get dimensions for all pages.

        Returns:
            List of (width, height) tuples for each page
        """
        if not self.doc:
            raise RuntimeError("PDF not opened. Use context manager.")

        return [
            self.get_page_dimensions(i + 1)
            for i in range(self.total_pages)
        ]

    def validate_page_dimensions(self, max_dimension: int = 2000) -> list[int]:
        """
        Check if any pages exceed API dimension limits.

        Args:
            max_dimension: Maximum allowed dimension in pixels (default: 2000)

        Returns:
            List of page numbers that exceed the limit
        """
        oversized = []

        for page_num in range(1, self.total_pages + 1):
            width, height = self.get_page_dimensions(page_num)
            if width > max_dimension or height > max_dimension:
                oversized.append(page_num)

        if oversized:
            logger.warning(
                f"{len(oversized)} pages exceed {max_dimension}px limit at {self.dpi} DPI: "
                f"pages {oversized[:5]}{'...' if len(oversized) > 5 else ''}"
            )

        return oversized
