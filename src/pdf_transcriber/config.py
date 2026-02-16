"""Configuration management with environment variable overrides."""
from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class Config:
    """Configuration for PDF transcriber MCP server."""

    # Output directory (default to vault transcriptions directory)
    output_dir: Path = field(
        default_factory=lambda: Path.home() / "Vaults/PersonalVault/Math/Literature/Transcriptions"
    )


    # Quality presets (DPI values)
    quality_presets: dict = field(default_factory=lambda: {
        "fast": 100,          # ~1275x1650px - Lightweight
        "balanced": 150,      # ~1913x2475px - DEFAULT - Best quality/size ratio
        "high-quality": 200   # ~2550x3300px - High quality (may approach API limits)
    })
    default_quality: str = "balanced"

    # Processing (markdown only - LaTeX removed for distribution)
    default_mode: str = "streaming"   # "streaming" or "batch"
    max_concurrent_pages: int = 3     # For batch mode (future)
    disable_table_extraction: bool = True  # Disabled by default to enable MPS on Mac (set False to extract tables)

    # Marker OCR settings
    ocr_engine: str = "marker"
    use_gpu: bool = True  # Auto-detected in load()
    marker_batch_size: int = 1  # Pages per batch (not currently used)
    marker_langs: list = field(default_factory=lambda: ["English"])

    # LLM-enhanced OCR settings (Marker's built-in LLM mode)
    # NOTE: Requires a VISION model (VLM) - text-only models won't work
    use_llm: bool = True  # Enable Marker's LLM-enhanced OCR (default: on)
    llm_service: str = "marker.services.openai.OpenAIService"  # LLM service class

    # Ollama settings (when llm_service = marker.services.ollama.OllamaService)
    ollama_base_url: str = "http://localhost:11434"  # Ollama server URL
    ollama_model: str = "qwen2.5vl:3b"

    # OpenAI-compatible settings (when llm_service = marker.services.openai.OpenAIService)
    # Works with mlx-vlm, vLLM, LM Studio, or any OpenAI-compatible endpoint
    openai_base_url: str = "http://localhost:8080"  # mlx-vlm default port
    openai_api_key: str = "not-needed"  # Local servers don't need keys
    openai_model: str = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit"

    # Chunking settings
    chunk_size: int = 1  # Pages per chunk (1 = single-page processing, prevents page merges & hallucinations)
    auto_chunk_threshold: int = 0  # Disabled - always use chunk_size=1 for reliability

    # State management
    progress_dir_name: str = ".pdf-progress"

    # Index
    index_file: str = ".paper-index.json"

    # Versioning
    version: str = "1.0.0"

    @classmethod
    def load(cls) -> "Config":
        """Load config with environment variable overrides."""
        config = cls()

        # Override output directory from env
        if val := os.environ.get("PDF_TRANSCRIBER_OUTPUT_DIR"):
            config.output_dir = Path(val).expanduser()


        # Override quality preset from env
        if val := os.environ.get("PDF_TRANSCRIBER_QUALITY"):
            if val in config.quality_presets:
                config.default_quality = val

        # Auto-detect GPU
        try:
            import torch
            config.use_gpu = torch.cuda.is_available()
        except ImportError:
            config.use_gpu = False

        # Override GPU setting from env
        if val := os.environ.get("PDF_TRANSCRIBER_USE_GPU"):
            config.use_gpu = val.lower() in ("true", "1", "yes")

        # Override chunking settings from env
        if val := os.environ.get("PDF_TRANSCRIBER_CHUNK_SIZE"):
            config.chunk_size = int(val)
        if val := os.environ.get("PDF_TRANSCRIBER_AUTO_CHUNK_THRESHOLD"):
            config.auto_chunk_threshold = int(val)

        # Override LLM settings from env
        if val := os.environ.get("PDF_TRANSCRIBER_USE_LLM"):
            config.use_llm = val.lower() in ("true", "1", "yes")
        if val := os.environ.get("PDF_TRANSCRIBER_LLM_SERVICE"):
            config.llm_service = val
        if val := os.environ.get("PDF_TRANSCRIBER_OLLAMA_URL"):
            config.ollama_base_url = val
        if val := os.environ.get("PDF_TRANSCRIBER_OLLAMA_MODEL"):
            config.ollama_model = val
        if val := os.environ.get("PDF_TRANSCRIBER_OPENAI_BASE_URL"):
            config.openai_base_url = val
        if val := os.environ.get("PDF_TRANSCRIBER_OPENAI_API_KEY"):
            config.openai_api_key = val
        if val := os.environ.get("PDF_TRANSCRIBER_OPENAI_MODEL"):
            config.openai_model = val

        # Override table extraction setting from env
        if val := os.environ.get("PDF_TRANSCRIBER_DISABLE_TABLE_EXTRACTION"):
            config.disable_table_extraction = val.lower() in ("true", "1", "yes")

        # Ensure output directory exists
        config.output_dir.mkdir(parents=True, exist_ok=True)

        return config

    def get_dpi(self, quality: str | None = None) -> int:
        """Get DPI value for a quality preset."""
        quality = quality or self.default_quality
        return self.quality_presets.get(quality, self.quality_presets["balanced"])
