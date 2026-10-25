"""Optional offline OCR through a locally installed Tesseract binary.

No Python OCR package is required. Without Tesseract (or with GHOST_AUDIT_OCR=0)
images stay deferred, exactly as before. Results are cached per file digest.
"""

import csv
import io
import os
import shutil
import subprocess
from pathlib import Path

_CACHE: dict[str, str | None] = {}
_PANEL_CACHE: dict[str, list[tuple[str, str]]] = {}
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
            completed = subprocess.run(
                [binary, str(path), "stdout"], capture_output=True, timeout=120, check=False
            )
            text = completed.stdout.decode("utf-8", errors="replace")
            _CACHE[key] = text if completed.returncode == 0 and text.strip() else None
        except (OSError, subprocess.SubprocessError):
            _CACHE[key] = None
    return _CACHE[key]


def panels_from_tsv(tsv: str) -> list[tuple[str, str]]:
    """Extract isolated right-hand detail panels from spatial OCR words.

    The exact resource title anchors the column; neighbouring table rows are
    excluded. No spelling repair, expected identity, filename, or case ID is used.
    """
    import re

    rows = list(csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE))
    page = next((r for r in rows if r["level"] == "1"), None)
    if page is None:
        return []
    width = int(page["width"])
    words = [r for r in rows if r["level"] == "5" and r.get("text", "").strip()]
    titles = [
        r
        for r in words
        if int(r["left"]) >= width * 0.72 and re.fullmatch(r"[a-z]+(?:_[a-z]+)*_\d+", r["text"])
    ]
    result = []
    for title in titles:
        x, y = int(title["left"]), int(title["top"])
        # Only the first resource title in a column identifies a detail panel.
        if any(int(t["top"]) < y and abs(int(t["left"]) - x) < 24 for t in titles):
            continue
        selected = [r for r in words if int(r["left"]) >= x - 12 and int(r["top"]) >= y - 2]
        lines = []
        for r in sorted(selected, key=lambda r: (int(r["top"]), int(r["left"]))):
            top = int(r["top"])
            if not lines or top - lines[-1][0] > 8:
                lines.append((top, [r]))
            else:
                lines[-1][1].append(r)
        text = "\n".join(
            " ".join(w["text"] for w in sorted(ws, key=lambda w: int(w["left"]))) for _, ws in lines
        )
        result.append((title["text"], text))
    return result


def image_panels(path: Path, digest: str) -> list[tuple[str, str]]:
    """Alternate sparse-text segmentation, with original spatial provenance retained."""
    binary = tesseract_binary()
    if binary is None:
        return []
    key = binary + ":" + digest
    if key not in _PANEL_CACHE:
        try:
            completed = subprocess.run(
                [binary, str(path), "stdout", "--psm", "11", "tsv"],
                capture_output=True,
                timeout=120,
                check=False,
            )
            _PANEL_CACHE[key] = (
                panels_from_tsv(completed.stdout.decode("utf-8", errors="replace"))
                if completed.returncode == 0
                else []
            )
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, csv.Error):
            _PANEL_CACHE[key] = []
    return _PANEL_CACHE[key]
