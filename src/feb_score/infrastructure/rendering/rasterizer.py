"""SVG → PNG, the last step before a card is publishable.

Instagram takes pixels, not vectors, so the pipeline that ends in an SVG ends
one step short of a post. This module is that step.

**resvg, not cairosvg.** Measured (see fonts/README.md): cairosvg could not find
the vendored Inter files even when the family was named explicitly, and rendered
all five weights identically — collapsing the typographic hierarchy the design
system is built on. resvg is a separate binary rather than a library, which is
the price for output that does not depend on the host's fontconfig state.

The SAME resvg version (0.48.1) is pinned in the Dockerfile as is used on the
development machine, and fonts come from the vendored directory with system
fonts switched OFF. A card therefore rasterises to the same pixels in
production as it does locally — otherwise "I looked at it and it was fine"
would say nothing about what gets published.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

FONTS_DIR = Path(__file__).with_name("fonts")

# The card format: 4:5 portrait, the largest Instagram feed post.
CARD_WIDTH = 1080
CARD_HEIGHT = 1350

# A card is ~0.33s to rasterise; the ceiling is there so a pathological input
# cannot pin the single worker indefinitely.
_TIMEOUT_SECONDS = 30

# Env override for a binary that is not on PATH (a local build, a pinned copy).
_BINARY_ENV = "FEB_SCORE_RESVG"


class RasterizerUnavailable(RuntimeError):
    """No resvg binary could be found. The caller maps this to 503, not 500:
    the request was valid, the capability is missing."""


class RasterizationFailed(RuntimeError):
    """resvg ran and refused the input."""


def resvg_path() -> Optional[str]:
    """The resvg binary, or None if this deployment has none."""
    import os

    override = (os.environ.get(_BINARY_ENV) or "").strip()
    if override:
        return override if Path(override).is_file() else None
    return shutil.which("resvg")


def available() -> bool:
    return resvg_path() is not None


def rasterize_png(
    svg: str, *, width: int = CARD_WIDTH, height: int = CARD_HEIGHT
) -> bytes:
    """Render a self-contained SVG to PNG bytes.

    The SVG must already have its shared assets inlined — this renders in an
    EMPTY resources directory on purpose, so an SVG referencing anything on the
    filesystem gets nothing rather than reaching for a real file.
    """
    binary = resvg_path()
    if binary is None:
        raise RasterizerUnavailable(
            "resvg is not installed; PNG rendering is unavailable"
        )

    with tempfile.TemporaryDirectory(prefix="feb-raster-") as sandbox:
        args: List[str] = [
            binary,
            "--use-fonts-dir", str(FONTS_DIR),
            "--skip-system-fonts",       # the host's fonts must not leak in
            "--font-family", "Inter",
            "--resources-dir", sandbox,  # empty: no relative path resolves
            "--width", str(width),
            "--height", str(height),
            "-", "-c",                   # stdin → stdout
        ]
        try:
            done = subprocess.run(
                args,
                input=svg.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RasterizationFailed(
                f"resvg timed out after {_TIMEOUT_SECONDS}s"
            ) from exc
        except OSError as exc:  # binary vanished or is not executable
            raise RasterizerUnavailable(f"resvg could not be executed: {exc}") from exc

    if done.returncode != 0 or not done.stdout:
        detail = done.stderr.decode("utf-8", "replace").strip()[:400]
        raise RasterizationFailed(detail or f"resvg exited {done.returncode}")
    return done.stdout
