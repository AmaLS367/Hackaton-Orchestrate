"""Optional offline OCR through a locally installed Tesseract binary.

No Python OCR package is required. Without Tesseract (or with GHOST_AUDIT_OCR=0)
images stay deferred, exactly as before. Results are cached per file digest.
"""

import os
import shutil
import subprocess
from pathlib import Path

_CACHE: dict[str, str | None] = {}
_WINDOWS_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def tesseract_binary() -> str | None:
    if os.environ.get("GHOST_AUDIT_OCR", "1") == "0":
        return None
    configured = os.environ.get("GHOST_AUDIT_TESSERACT")
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    return str(_WINDOWS_DEFAULT) if _WINDOWS_DEFAULT.is_file() else None


def image_text(path: Path, digest: str) -> str | None:
    """Raw OCR text, or None when OCR is unavailable or fails. Never raises."""
    binary = tesseract_binary()
    if binary is None:
        return None
    key = binary + ":" + digest
    if key not in _CACHE:
        try:
            completed = subprocess.run([binary, str(path), "stdout"], capture_output=True,
                                       timeout=120, check=False)
            text = completed.stdout.decode("utf-8", errors="replace")
            _CACHE[key] = text if completed.returncode == 0 and text.strip() else None
        except (OSError, subprocess.SubprocessError):
            _CACHE[key] = None
    return _CACHE[key]
