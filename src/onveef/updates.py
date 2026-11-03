"""Read-modify-write: merge a partial change into a device configuration and check it.

ONVIF ``Set*Configuration`` operations replace a configuration as a whole, so changing one
field means sending every other field back as it was — and a field that is left out is
quietly reset (a dropped ``ConstantBitRate`` turns a CBR stream into VBR; a missing
``Multicast`` wipes the multicast setup). These pure functions do the merging, and check
the result against what the device's own ``Get*Options`` answer allows, for
:meth:`~onveef.client.OnvifClient.update_video_encoder_configuration` and
:meth:`~onveef.client.OnvifClient.imaging_update_settings`. They never touch the network.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from onveef.parsers import _norm_enc

__all__ = (
    "IMAGING_SETTING_NAMES",
    "VIDEO_ENCODER_FIELDS",
    "check_imaging",
    "check_video_encoder",
    "fill_imaging_modes",
    "merge_video_encoder",
)

VIDEO_ENCODER_FIELDS = (
    "name",
    "encoding",
    "width",
    "height",
    "quality",
    "frame_rate",
    "bitrate_kbps",
    "gop",
    "profile",
    "constant_bitrate",
    "guaranteed_frame_rate",
    "encoding_interval",
    "multicast",
)
"""The fields :func:`merge_video_encoder` accepts in a change."""

_TOLERANCE = 1e-6


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != ""), None)


def _as_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return None if number is None else int(number)


def _changed_or_kept(changes: Mapping[str, Any], current: Mapping[str, Any], key: str) -> Any:
    value = changes.get(key)
    return value if value is not None else current.get(key)


def merge_video_encoder(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay ``changes`` on a video encoder configuration, keeping every field not changed.

    Args:
        current: One configuration from
            :func:`~onveef.parsers.parse_video_encoder_configurations`.
        changes: Any of :data:`VIDEO_ENCODER_FIELDS`; ``None`` values are ignored.

    Returns:
        The configuration to write: :data:`VIDEO_ENCODER_FIELDS` plus ``use_count`` and
        ``session_timeout``. The codec profile is only kept while the codec is — H.264's
        ``High`` means nothing to H.265 — and ``encoding`` is normalised (``HEVC`` is
        ``H265``, ``MPEG4`` is ``MPV4-ES``).
    """
    encoding = _norm_enc(str(_first(changes.get("encoding"), current.get("encoding"), "H264")))
    same_codec = encoding == _norm_enc(str(current.get("encoding") or ""))
    kept_profile = (
        _first(
            current.get("profile"),
            current.get("h265_profile" if encoding == "H265" else "h264_profile"),
        )
        if same_codec
        else None
    )
    return {
        "name": _first(changes.get("name"), current.get("name"), current.get("token")),
        "encoding": encoding,
        "width": _as_int(_first(changes.get("width"), current.get("width"))),
        "height": _as_int(_first(changes.get("height"), current.get("height"))),
        "quality": _as_float(_first(changes.get("quality"), current.get("quality"))),
        "frame_rate": _as_float(
            _first(changes.get("frame_rate"), current.get("frame_rate"), current.get("fps_limit"))
        ),
        "bitrate_kbps": _as_int(_first(changes.get("bitrate_kbps"), current.get("bitrate_kbps"))),
        "gop": _as_int(_first(changes.get("gop"), current.get("gop"))),
        "profile": str(_first(changes.get("profile"), kept_profile) or ""),
        "constant_bitrate": _changed_or_kept(changes, current, "constant_bitrate"),
        "guaranteed_frame_rate": _changed_or_kept(changes, current, "guaranteed_frame_rate"),
        "encoding_interval": _as_int(
            _first(changes.get("encoding_interval"), current.get("encoding_interval"))
        ),
        "multicast": _changed_or_kept(changes, current, "multicast"),
        "use_count": _as_int(current.get("use_count")) or 0,
        "session_timeout": str(current.get("session_timeout") or "PT60S"),
    }


def _outside(value: float, bounds: Mapping[str, float] | None) -> bool:
    return bounds is not None and not (
        bounds["min"] - _TOLERANCE <= value <= bounds["max"] + _TOLERANCE
    )


def _span(bounds: Mapping[str, float]) -> str:
    return f"{bounds['min']:g} to {bounds['max']:g}"


def check_video_encoder(
    merged: Mapping[str, Any],
    options: Iterable[Mapping[str, Any]],
    *,
    changed: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """Check a merged encoder configuration against what the encoder accepts.

    Args:
        merged: The output of :func:`merge_video_encoder`.
        options: Per-encoding options, as
            :func:`~onveef.parsers.parse_video_encoder_options_normalized` or
            :func:`~onveef.parsers.merge_video_encoder_options` return them.
        changed: The fields the caller changed. Only those are judged — a device whose
            current value already sits outside its own advertised range must not block an
            unrelated change — unless the encoding changed, which makes every field
            answerable to the new codec's options.

    Returns:
        Each problem field (``encoding``, ``resolution``, ``frame_rate``,
        ``bitrate_kbps``, ``quality``, ``gop``, ``encoding_interval``, ``profile``,
        ``constant_bitrate``, ``guaranteed_frame_rate``) mapped to its reasons; ``{}`` when
        everything is acceptable or the device offered no options to judge by.
    """
    by_encoding = {str(block.get("encoding") or ""): block for block in options}
    by_encoding.pop("", None)
    if not by_encoding:
        return {}
    encoding = str(merged["encoding"])
    asked = None if changed is None else set(changed)
    allowed = by_encoding.get(encoding)
    if allowed is None:
        if asked is not None and "encoding" not in asked:
            return {}  # nothing to judge the other fields by
        offered = ", ".join(sorted(by_encoding))
        return {"encoding": [f"This encoder cannot use {encoding}; the device offers {offered}."]}
    errors: dict[str, list[str]] = {}
    sizes = {(item["width"], item["height"]) for item in allowed.get("resolutions") or []}
    size = (merged["width"], merged["height"])
    if sizes and size not in sizes:
        errors["resolution"] = [f"{size[0]}x{size[1]} is not a {encoding} resolution it offers."]
    rate = merged["frame_rate"]
    if rate is not None:
        rates = allowed.get("frame_rates") or []
        if rates and not any(abs(rate - choice) < 0.01 for choice in rates):
            listed = ", ".join(f"{choice:g}" for choice in rates)
            errors["frame_rate"] = [f"{rate:g} fps is not offered; choose one of {listed}."]
        elif _outside(rate, allowed.get("fps")):
            errors["frame_rate"] = [f"The frame rate must be {_span(allowed['fps'])} fps."]
    for field, label in (
        ("bitrate_kbps", "The bit rate must be {} kbit/s."),
        ("quality", "The quality must be {}."),
        ("gop", "The GOP length must be {} frames."),
        ("encoding_interval", "The encoding interval must be {}."),
    ):
        value = merged.get(field)
        bounds = allowed.get(field)
        if value is not None and bounds is not None and _outside(float(value), bounds):
            errors[field] = [label.format(_span(bounds))]
    profiles = allowed.get("profiles") or []
    if merged["profile"] and profiles and merged["profile"] not in profiles:
        errors["profile"] = [f"The {encoding} profile must be one of {', '.join(profiles)}."]
    if merged["constant_bitrate"] and allowed.get("constant_bitrate_supported") is False:
        errors["constant_bitrate"] = ["This encoder has no constant bit rate mode."]
    if merged["guaranteed_frame_rate"] and allowed.get("guaranteed_frame_rate_supported") is False:
        errors["guaranteed_frame_rate"] = ["This encoder cannot guarantee its frame rate."]
    if asked is None or "encoding" in asked:
        return errors
    if asked & {"width", "height"}:
        asked.add("resolution")
    return {field: reasons for field, reasons in errors.items() if field in asked}


# Settings whose schema block needs a mode element whenever anything in the block is sent:
# (mode setting, the settings that live in its block, parse_imaging_settings block, key).
_IMAGING_REQUIRED_MODES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "backlight_compensation_mode",
        ("backlight_compensation_level",),
        "BacklightCompensation",
        "mode",
    ),
    ("wide_dynamic_range_mode", ("wide_dynamic_range_level",), "WideDynamicRange", "mode"),
    (
        "white_balance_mode",
        ("white_balance_cr_gain", "white_balance_cb_gain"),
        "WhiteBalance",
        "mode",
    ),
    (
        "exposure_mode",
        (
            "exposure_priority",
            "exposure_min_time",
            "exposure_max_time",
            "exposure_min_gain",
            "exposure_max_gain",
            "exposure_min_iris",
            "exposure_max_iris",
            "exposure_time",
            "exposure_gain",
            "exposure_iris",
        ),
        "Exposure",
        "mode",
    ),
    (
        "focus_auto_mode",
        ("focus_default_speed", "focus_near_limit", "focus_far_limit"),
        "Focus",
        "auto_focus_mode",
    ),
    (
        "image_stabilization_mode",
        ("image_stabilization_level",),
        "ImageStabilization",
        "mode",
    ),
    ("tone_compensation_mode", ("tone_compensation_level",), "ToneCompensation", "mode"),
    ("defogging_mode", ("defogging_level",), "Defogging", "mode"),
    (
        "ir_cut_auto_boundary_type",
        ("ir_cut_auto_boundary_offset", "ir_cut_auto_response_time"),
        "IrCutFilterAutoAdjustment",
        "boundary_type",
    ),
)

IMAGING_SETTING_NAMES = frozenset(
    {
        "brightness",
        "contrast",
        "color_saturation",
        "sharpness",
        "ir_cut_filter",
        "noise_reduction_level",
    }
    | {mode for mode, _, _, _ in _IMAGING_REQUIRED_MODES}
    | {setting for _, settings, _, _ in _IMAGING_REQUIRED_MODES for setting in settings}
)
"""Every setting :meth:`~onveef.client.OnvifClient.imaging_update_settings` accepts."""


def fill_imaging_modes(changes: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Add the mode each changed imaging block needs, taken from the current settings.

    ``Exposure`` is invalid without ``Mode``, ``Focus`` without ``AutoFocusMode``,
    ``IrCutFilterAutoAdjustment`` without ``BoundaryType`` and so on, so changing only an
    exposure limit means re-sending the exposure mode the device already has.

    Args:
        changes: ``imaging_set_settings`` keyword arguments, ``None``/``""`` ones ignored.
        current: The device's settings, from :func:`~onveef.parsers.parse_imaging_settings`.

    Returns:
        The changes plus the modes they need. A missing IR-cut boundary type becomes
        ``Common``; any other mode the device does not report is left out.
    """
    filled = {key: value for key, value in changes.items() if value is not None and value != ""}
    for mode, settings, block, key in _IMAGING_REQUIRED_MODES:
        if mode in filled or not any(setting in filled for setting in settings):
            continue
        reported = current.get(block)
        value = reported.get(key) if isinstance(reported, Mapping) else None
        if value:
            filled[mode] = value
        elif block == "IrCutFilterAutoAdjustment":
            filled[mode] = "Common"
    return filled


# setting -> path in parse_imaging_options_normalized's output to its {min, max} range.
_IMAGING_RANGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("brightness", ("brightness",)),
    ("contrast", ("contrast",)),
    ("color_saturation", ("color_saturation",)),
    ("sharpness", ("sharpness",)),
    ("backlight_compensation_level", ("backlight_compensation", "level")),
    ("wide_dynamic_range_level", ("wide_dynamic_range", "level")),
    ("white_balance_cr_gain", ("white_balance", "cr_gain")),
    ("white_balance_cb_gain", ("white_balance", "cb_gain")),
    ("exposure_min_time", ("exposure", "min_exposure_time")),
    ("exposure_max_time", ("exposure", "max_exposure_time")),
    ("exposure_min_gain", ("exposure", "min_gain")),
    ("exposure_max_gain", ("exposure", "max_gain")),
    ("exposure_min_iris", ("exposure", "min_iris")),
    ("exposure_max_iris", ("exposure", "max_iris")),
    ("exposure_time", ("exposure", "exposure_time")),
    ("exposure_gain", ("exposure", "gain")),
    ("exposure_iris", ("exposure", "iris")),
    ("focus_default_speed", ("focus", "default_speed")),
    ("focus_near_limit", ("focus", "near_limit")),
    ("focus_far_limit", ("focus", "far_limit")),
    ("image_stabilization_level", ("image_stabilization", "level")),
    ("tone_compensation_level", ("tone_compensation", "level")),
    ("defogging_level", ("defogging", "level")),
    ("noise_reduction_level", ("noise_reduction", "level")),
)
# setting -> path to the list of values it may take.
_IMAGING_CHOICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("backlight_compensation_mode", ("backlight_compensation", "modes")),
    ("wide_dynamic_range_mode", ("wide_dynamic_range", "modes")),
    ("white_balance_mode", ("white_balance", "modes")),
    ("exposure_mode", ("exposure", "modes")),
    ("exposure_priority", ("exposure", "priorities")),
    ("focus_auto_mode", ("focus", "auto_focus_modes")),
    ("ir_cut_filter", ("ir_cut_filter_modes",)),
    ("image_stabilization_mode", ("image_stabilization", "modes")),
    ("ir_cut_auto_boundary_type", ("ir_cut_auto_adjustment", "boundary_types")),
    ("tone_compensation_mode", ("tone_compensation", "modes")),
    ("defogging_mode", ("defogging", "modes")),
)


def _at(options: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = options
    for key in path:
        value = value.get(key) if isinstance(value, Mapping) else None
    return value


def check_imaging(changes: Mapping[str, Any], options: Mapping[str, Any]) -> dict[str, list[str]]:
    """Check imaging changes against the device's imaging options.

    Args:
        changes: ``imaging_set_settings`` keyword arguments; ``None``/``""`` are ignored.
        options: The device's options, from
            :func:`~onveef.parsers.parse_imaging_options_normalized`.

    Returns:
        Each problem setting mapped to its reasons — a value outside the advertised range,
        a mode not in the advertised list, or a setting the device does not offer at all.
        ``{}`` when everything is acceptable or ``options`` is empty.
    """
    if not options:
        return {}
    errors: dict[str, list[str]] = {}
    for setting, path in _IMAGING_RANGES:
        value = _as_float(changes.get(setting))
        if value is None:
            continue
        bounds = _at(options, path)
        if not isinstance(bounds, Mapping):
            errors[setting] = ["The device does not offer this setting."]
        elif _outside(value, bounds):
            errors[setting] = [f"Must be from {_span(bounds)}."]
    for setting, path in _IMAGING_CHOICES:
        value = changes.get(setting)
        if not value:
            continue
        offered = _at(options, path) or []
        if value not in offered:
            errors[setting] = (
                [f"Must be one of {', '.join(offered)}."]
                if offered
                else ["The device does not offer this setting."]
            )
    return errors
