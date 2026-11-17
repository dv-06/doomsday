"""Show-format normalisation.

The one rule that matters most here: Infinity Vision 3D is NOT IMAX 3D.
They are separate PVR/Cinepolis premium formats with different screens,
projection and seating, so they get separate keys and separate alerts.

Anything we cannot classify is reported as ``unknown`` rather than guessed.
"""

from __future__ import annotations

import re
from typing import Any

# Ordered most-specific first. Each entry: (key, label, regex)
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("infinity_vision_4dx_3d", "Infinity Vision 4DX 3D",
     re.compile(r"INFINITY\s*VISION.*4DX")),
    ("infinity_vision_3d", "Infinity Vision 3D",
     re.compile(r"INFINITY\s*VISION")),
    ("imax_3d", "IMAX 3D", re.compile(r"\bIMAX\b.*\b3D\b|\b3D\b.*\bIMAX\b")),
    ("imax_2d", "IMAX 2D", re.compile(r"\bIMAX\b")),
    ("ice_3d", "ICE 3D", re.compile(r"\bICE\b")),
    ("dolby_3d", "Dolby Cinema 3D", re.compile(r"DOLBY.*\b3D\b|\b3D\b.*DOLBY")),
    ("dolby_2d", "Dolby Cinema", re.compile(r"DOLBY")),
    ("4dx_3d", "4DX 3D", re.compile(r"4DX.*\b3D\b|\b3D\b.*4DX")),
    ("4dx_2d", "4DX", re.compile(r"4DX|MX4D")),
    ("screenx_3d", "ScreenX 3D", re.compile(r"SCREEN\s*X.*3D|3D.*SCREEN\s*X")),
    ("screenx_2d", "ScreenX", re.compile(r"SCREEN\s*X")),
    ("pxl_3d", "P[XL] 3D", re.compile(r"P\s*\[\s*XL\s*\].*3D|3D.*P\s*\[\s*XL\s*\]")),
    ("pxl_2d", "P[XL]", re.compile(r"P\s*\[\s*XL\s*\]")),
    ("laser_3d", "Laser 3D", re.compile(r"LASER.*\b3D\b|\b3D\b.*LASER")),
    ("3d", "3D", re.compile(r"\b3D\b|REALD|XD\b")),
    ("2d", "2D", re.compile(r"\b2D\b")),
)

_PREMIUM_KEYS = {
    "imax_3d", "imax_2d", "infinity_vision_3d", "infinity_vision_4dx_3d",
    "4dx_3d", "4dx_2d", "ice_3d", "dolby_3d", "dolby_2d", "screenx_3d",
    "screenx_2d", "pxl_3d", "pxl_2d", "laser_3d",
}

_LARGE_FORMAT_KEYS = {
    "imax_3d", "imax_2d", "infinity_vision_3d", "infinity_vision_4dx_3d",
    "ice_3d", "screenx_3d", "screenx_2d", "pxl_3d", "pxl_2d", "dolby_3d", "dolby_2d",
}

# Viewing-distance guidance per format family, used by the seat engine.
# Values are the preferred row depth (0 = first row, 1 = last row).
_FORMAT_DEPTH: dict[str, tuple[float, float, str]] = {
    "imax_3d": (0.62, 0.78, "IMAX screens are tall; sitting deeper keeps the full frame in view"),
    "imax_2d": (0.60, 0.76, "IMAX screens are tall; sitting deeper keeps the full frame in view"),
    "infinity_vision_3d": (0.58, 0.74, "Infinity Vision uses a large-format screen; mid-rear rows stay comfortable"),
    "infinity_vision_4dx_3d": (0.45, 0.65, "4DX motion seats read best slightly forward of the rear block"),
    "4dx_3d": (0.45, 0.65, "4DX motion seats read best slightly forward of the rear block"),
    "4dx_2d": (0.45, 0.65, "4DX motion seats read best slightly forward of the rear block"),
    "dolby_3d": (0.60, 0.76, "Dolby auditoria are tuned for a deeper centre seat"),
    "dolby_2d": (0.60, 0.76, "Dolby auditoria are tuned for a deeper centre seat"),
    "3d": (0.58, 0.74, "3D brightness and framing are best a little behind the middle"),
    "2d": (0.55, 0.72, "Centre-middle to rear is the classic sweet spot"),
}
_DEFAULT_DEPTH = (0.55, 0.72, "Centre-middle to rear avoids neck strain and edge distortion")


def normalise_format(raw: str | None, *, price_max: float | None = None) -> dict[str, Any]:
    """Return a stable format descriptor for a raw source string."""
    text = (raw or "").strip()
    upper = re.sub(r"\s+", " ", text.upper())

    if not upper:
        return {
            "key": "unknown", "label": "Not published", "family": "unknown",
            "is_3d": None, "is_premium": False, "is_large_format": False,
            "confidence": "unknown", "raw": raw or "",
        }

    for key, label, pattern in _PATTERNS:
        if pattern.search(upper):
            inferred = key.endswith("_3d") or key == "3d"
            explicit = "3D" in upper
            return {
                "key": key,
                "label": label,
                "family": "premium" if key in _PREMIUM_KEYS else ("3d" if inferred else "2d"),
                "is_3d": bool(inferred),
                "is_premium": key in _PREMIUM_KEYS,
                "is_large_format": key in _LARGE_FORMAT_KEYS,
                "confidence": "explicit" if explicit or key in {"2d", "imax_2d"} else "inferred",
                "raw": text,
            }

    return {
        "key": "unknown", "label": text or "Unknown", "family": "unknown",
        "is_3d": None, "is_premium": False, "is_large_format": False,
        "confidence": "unknown", "raw": text,
    }


def format_depth_guidance(format_key: str) -> tuple[float, float, str]:
    return _FORMAT_DEPTH.get(format_key, _DEFAULT_DEPTH)


def is_premium_key(format_key: str) -> bool:
    return format_key in _PREMIUM_KEYS
