"""PTZ geometry and capability helpers.

:func:`fov_translation` turns a point on the picture into the ``TranslationSpaceFov`` move
that centres the camera on it, and :func:`capabilities` condenses a PTZ node, its media
profile and the lens options into what the camera can actually do. Both are pure; the
client methods :meth:`~onveef.client.OnvifClient.ptz_center` and
:meth:`~onveef.client.OnvifClient.ptz_capabilities` do the I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

__all__ = ("FOV_TRANSLATION_SPACE", "capabilities", "fov_space", "fov_translation")

FOV_TRANSLATION_SPACE = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/TranslationSpaceFov"
"""The relative pan/tilt space measured in the current field of view (click-to-center)."""


def fov_translation(x: float, y: float) -> tuple[float, float]:
    """Map a point on the picture to the pan/tilt translation that centres it.

    ``x`` and ``y`` run from 0 to 1, left to right and top to bottom — how a click on a
    video element is usually measured. ``TranslationSpaceFov`` puts its origin at the image
    centre and ``(1, 1)`` at the upper-right corner, so the move is ``(2x - 1, 1 - 2y)``.

    Raises:
        ValueError: if ``x`` or ``y`` is not within 0..1.
    """
    for name, value in (("x", x), ("y", y)):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be a fraction of the picture, 0 to 1; got {value!r}.")
    return round(2 * x - 1, 4), round(1 - 2 * y, 4)


def fov_space(node: Mapping[str, Any]) -> str:
    """The ``TranslationSpaceFov`` URI a parsed PTZ node advertises, or ``""`` if none."""
    spaces = node.get("spaces")
    relative = spaces.get("relative_pan_tilt") if isinstance(spaces, Mapping) else None
    for space in relative or ():
        uri = str(space.get("uri") or "").strip()
        if uri.lower() == FOV_TRANSLATION_SPACE.lower():
            return uri
    return ""


def _finite(bounds: Any) -> dict[str, float] | None:
    if not isinstance(bounds, Mapping):
        return None
    low, high = bounds.get("min"), bounds.get("max")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return None
    if not (math.isfinite(low) and math.isfinite(high)):
        return None
    return {"min": float(low), "max": float(high)}


def _count(value: Any) -> int:
    try:
        return max(int(float(str(value).strip())), 0)
    except (ValueError, OverflowError):
        return 0


def _first_x_range(spaces: Mapping[str, Any], label: str) -> dict[str, float] | None:
    for space in spaces.get(label) or ():
        found = _finite(space.get("x"))
        if found is not None:
            return found
    return None


def capabilities(
    *,
    profile: Mapping[str, Any],
    node: Mapping[str, Any],
    imaging_options: Mapping[str, Any] | None = None,
    move_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Condense a PTZ node, its profile and the lens options into what the camera can do.

    Args:
        profile: The media profile the PTZ configuration belongs to
            (:func:`~onveef.parsers.parse_profiles`).
        node: Its PTZ node (:func:`~onveef.parsers.parse_ptz_nodes`).
        imaging_options: The video source's
            :func:`~onveef.parsers.parse_imaging_options_normalized`, for focus and iris.
        move_options: Its :func:`~onveef.parsers.parse_imaging_move_options`.

    Returns:
        ``profile_token``, ``node_token``, ``video_source_token``; booleans ``pan_tilt``,
        ``zoom``, ``continuous_pan_tilt``, ``continuous_zoom``, ``absolute_pan_tilt``,
        ``absolute_zoom``, ``relative_pan_tilt``, ``relative_zoom``, ``click_to_center``,
        ``presets``, ``home``, ``preset_tours``, ``geo_move``, ``focus`` (continuous focus
        moves), ``auto_focus`` (switchable AUTO/MANUAL), ``iris`` (manual iris) and
        ``auto_iris``; ``fov_space`` (the URI
        :meth:`~onveef.client.OnvifClient.ptz_center` moves in), counts
        ``max_presets`` and ``max_preset_tours``, ``auxiliary_commands``, and the finite
        ``pan_tilt_speed``, ``zoom_speed``, ``focus_speed`` and ``iris_range`` ranges (or
        ``None``).
    """
    raw_spaces = node.get("spaces")
    spaces: Mapping[str, Any] = raw_spaces if isinstance(raw_spaces, Mapping) else {}

    def has(label: str) -> bool:
        return bool(spaces.get(label))

    video_source = profile.get("video_source")
    focus_options = (imaging_options or {}).get("focus") or {}
    exposure_options = (imaging_options or {}).get("exposure") or {}
    focus_modes = {str(mode).upper() for mode in focus_options.get("auto_focus_modes") or ()}
    exposure_modes = {str(mode).upper() for mode in exposure_options.get("modes") or ()}
    iris_range = _finite(exposure_options.get("iris"))
    iris = (
        iris_range is not None
        and iris_range["max"] > iris_range["min"]
        and "MANUAL" in exposure_modes
    )
    continuous_focus = (move_options or {}).get("continuous")
    fov = fov_space(node)
    max_presets = _count(node.get("max_presets"))
    max_tours = _count(node.get("max_preset_tours"))
    return {
        "profile_token": str(profile.get("token") or ""),
        "node_token": str(node.get("token") or ""),
        "video_source_token": (
            str(video_source.get("source_token") or "") if isinstance(video_source, Mapping) else ""
        ),
        "pan_tilt": any(
            has(label)
            for label in ("absolute_pan_tilt", "relative_pan_tilt", "continuous_pan_tilt")
        ),
        "zoom": any(has(label) for label in ("absolute_zoom", "relative_zoom", "continuous_zoom")),
        "continuous_pan_tilt": has("continuous_pan_tilt"),
        "continuous_zoom": has("continuous_zoom"),
        "absolute_pan_tilt": has("absolute_pan_tilt"),
        "absolute_zoom": has("absolute_zoom"),
        "relative_pan_tilt": has("relative_pan_tilt"),
        "relative_zoom": has("relative_zoom"),
        "click_to_center": bool(fov),
        "fov_space": fov,
        "presets": max_presets > 0,
        "max_presets": max_presets,
        "home": str(node.get("home_supported") or "").strip().lower() in ("true", "1"),
        "preset_tours": max_tours > 0,
        "max_preset_tours": max_tours,
        "geo_move": bool(node.get("geo_move")),
        "auxiliary_commands": list(node.get("auxiliary_commands") or []),
        "pan_tilt_speed": _first_x_range(spaces, "pan_tilt_speed"),
        "zoom_speed": _first_x_range(spaces, "zoom_speed"),
        "focus": isinstance(continuous_focus, Mapping),
        "focus_speed": (
            _finite(continuous_focus.get("speed"))
            if isinstance(continuous_focus, Mapping)
            else None
        ),
        "auto_focus": {"AUTO", "MANUAL"} <= focus_modes,
        "iris": iris,
        "iris_range": iris_range if iris else None,
        "auto_iris": iris and "AUTO" in exposure_modes,
    }
