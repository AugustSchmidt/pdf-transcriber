"""Engine cache and factory for TranscriptionEngine.

Caches TranscriptionEngine instances by configuration to avoid
reloading Marker OCR models (~5-15 seconds) on each transcription call.
"""
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# Engine Cache - Avoids reloading Marker models on each transcription
# ============================================================================

_engine_cache: dict[str, "TranscriptionEngine"] = {}


def _make_cache_key(
    use_gpu: bool,
    use_llm: bool,
    llm_service: str,
    ollama_base_url: str,
    ollama_model: str,
    openai_base_url: str,
    openai_model: str,
    langs: tuple[str, ...],
    disable_table_extraction: bool
) -> str:
    """Generate cache key from engine configuration."""
    return f"{use_gpu}|{use_llm}|{llm_service}|{ollama_base_url}|{ollama_model}|{openai_base_url}|{openai_model}|{langs}|{disable_table_extraction}"


def get_transcription_engine(
    use_gpu: bool = False,
    batch_size: int = 1,
    langs: list[str] | None = None,
    use_llm: bool = False,
    llm_service: str = "marker.services.openai.OpenAIService",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "qwen2.5vl:3b",
    openai_base_url: str = "http://localhost:8080",
    openai_api_key: str = "not-needed",
    openai_model: str = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit",
    disable_table_extraction: bool = False
) -> "TranscriptionEngine":
    """
    Get or create a TranscriptionEngine with caching.

    This factory function caches engines by their configuration to avoid
    reloading Marker models (~5-15 seconds) on each transcription call.

    Args:
        use_gpu: Whether to use GPU acceleration
        batch_size: Number of pages per batch (not currently used)
        langs: Languages for OCR (default: ["English"])
        use_llm: Enable Marker's LLM-enhanced OCR mode
        llm_service: LLM service class path
        ollama_base_url: Ollama server URL
        ollama_model: Ollama vision model name
        openai_base_url: OpenAI-compatible server URL (for mlx-vlm, vLLM, etc.)
        openai_api_key: API key (use "not-needed" for local servers)
        openai_model: Model name for the OpenAI-compatible server

    Returns:
        Cached or newly created TranscriptionEngine
    """
    # Import here to avoid circular imports
    from pdf_transcriber.core.transcription import TranscriptionEngine

    langs_tuple = tuple(langs or ["English"])
    cache_key = _make_cache_key(
        use_gpu, use_llm, llm_service, ollama_base_url, ollama_model,
        openai_base_url, openai_model, langs_tuple, disable_table_extraction
    )

    if cache_key in _engine_cache:
        model_name = openai_model if "openai" in llm_service else ollama_model
        logger.info(f"Using cached TranscriptionEngine (LLM: {model_name if use_llm else 'disabled'})")
        return _engine_cache[cache_key]

    logger.info(f"Creating new TranscriptionEngine (will be cached for reuse)")
    engine = TranscriptionEngine(
        use_gpu=use_gpu,
        batch_size=batch_size,
        langs=list(langs_tuple),
        use_llm=use_llm,
        llm_service=llm_service,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        disable_table_extraction=disable_table_extraction
    )
    _engine_cache[cache_key] = engine

    return engine


def clear_engine_cache() -> int:
    """
    Clear the engine cache to free memory.

    Returns:
        Number of engines that were cached
    """
    count = len(_engine_cache)
    _engine_cache.clear()  # Use .clear() to mutate in-place (avoids rebinding issues)
    if count > 0:
        logger.info(f"Cleared {count} cached TranscriptionEngine(s)")
    return count


@dataclass
class TranscriptionResult:
    """Result from transcribing a single page."""
    content: str
    tokens_used: int  # Always 0 for local OCR
    success: bool
    error: str | None = None
