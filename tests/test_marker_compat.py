"""Guard the Marker 1.x API surface the transcriber is built on.

Marker 2.0 runs Surya's layout/OCR model in an external llama.cpp or vLLM
inference server and removes processors named in core/transcription.py, so
the 1.x release line requires marker-pdf<2.
"""
import re
from importlib.metadata import version
from pathlib import Path

from marker.util import strings_to_classes

TRANSCRIPTION_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "pdf_transcriber" / "core" / "transcription.py"
)


def test_marker_major_version_is_supported():
    installed = version("marker-pdf")
    assert int(installed.split(".")[0]) == 1, (
        f"marker-pdf {installed} is installed; pdf-transcriber 1.x requires marker-pdf<2"
    )


def test_custom_processor_list_resolves():
    names = re.findall(r'"(marker\.processors\.[\w.]+)"', TRANSCRIPTION_SOURCE.read_text())
    assert names, "no processor paths found in transcription.py"
    strings_to_classes(names)
