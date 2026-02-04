"""PDF Transcriber MCP Server - Main entry point."""
import logging
import sys

from mcp.server.fastmcp import FastMCP

from pdf_transcriber.config import Config
from pdf_transcriber.tools import transcribe, metadata, lint
from pdf_transcriber.resources import paper_resources

# Configure logging to stderr (CRITICAL: stdout is reserved for JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("pdf-transcriber")

# Load configuration
config = Config.load()

logger.info(f"PDF Transcriber v{config.version} starting...")
logger.info(f"Output directory: {config.output_dir}")
logger.info(f"Default quality: {config.default_quality} ({config.get_dpi()}dpi)")
logger.info(f"OCR Engine: {config.ocr_engine} (GPU: {config.use_gpu})")


def main():
    """Main entry point for the MCP server."""
    try:
        # Register tools
        logger.info("Registering tools...")
        transcribe.register(mcp, config)
        metadata.register(mcp, config)
        lint.register(mcp, config)
        logger.info(
            "Tools registered: transcribe_pdf, clear_transcription_cache, "
            "update_paper_metadata, lint_paper, get_lint_rules"
        )

        # Register resources
        logger.info("Registering resources...")
        paper_resources.register(mcp, config)
        logger.info("Resources registered: papers://index, papers://metadata/{name}")

        # Run the server
        logger.info("Starting MCP server on stdio...")
        mcp.run(transport="stdio")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
