"""Cross-platform file helpers (POSIX and native Windows).

All text is UTF-8, never the locale encoding (cp1252 on Windows would
corrupt non-ASCII notes). Writes never translate line endings: the caller
decides between LF and CRLF, so saving a file does not rewrite every line.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"

ENCODING = "utf-8"


def detect_newline(path: Path) -> str:
    """Return the line ending a file already uses: ``"\\r\\n"`` or ``"\\n"``.

    Missing, unreadable or LF files give ``"\\n"``. Text read by the parser is
    normalised to ``"\\n"``; writing with the detected ending keeps a CRLF
    file CRLF instead of rewriting every line.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(65536)
    except OSError:
        return "\n"
    return "\r\n" if b"\r\n" in head else "\n"


def write_text(path: Path, content: str, newline: str = "\n") -> None:
    """Write ``content`` as UTF-8, turning each ``"\\n"`` into ``newline``.

    ``newline="\\n"`` writes the string byte-for-byte (no CRLF on Windows).
    """
    with open(path, "w", encoding=ENCODING, newline=newline) as fh:
        fh.write(content)


def replace(
    src: Path,
    dst: Path,
    *,
    is_windows: bool | None = None,
    retries: int = 10,
    delay: float = 0.05,
) -> None:
    """``os.replace`` with a short retry on Windows.

    On Windows replacing a file that another process (an editor, a virus
    scanner, a reader) has open fails with ``PermissionError`` for a moment.
    POSIX behaviour is unchanged: one attempt, errors propagate.
    """
    if is_windows is None:
        is_windows = IS_WINDOWS
    attempts = retries if is_windows else 1
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
