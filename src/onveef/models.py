from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from onveef.wsdiscovery import DiscoveredDevice

__all__ = (
    "DeviceInformation",
    "DiscoveredDevice",
    "ImagingSettings",
    "NetworkInterface",
    "NotificationMessage",
    "PTZPreset",
    "PTZStatus",
    "Profile",
    "PullMessage",
    "Recording",
    "RecordingTrack",
    "SystemDateTime",
    "VideoEncoder",
)


@dataclass(slots=True)
class DeviceInformation:
    manufacturer: str = ""
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    hardware_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceInformation:
        return cls(
            manufacturer=data.get("Manufacturer", ""),
            model=data.get("Model", ""),
            firmware_version=data.get("FirmwareVersion", ""),
            serial_number=data.get("SerialNumber", ""),
            hardware_id=data.get("HardwareId", ""),
        )


@dataclass(slots=True)
class VideoEncoder:
    token: str = ""
    name: str = ""
    encoding: str = ""
    width: int | None = None
    height: int | None = None
    fps_limit: int | None = None
    bitrate_kbps: int | None = None
    gop: int | None = None
    quality: str = ""
    h264_profile: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VideoEncoder:
        return cls(
            token=data.get("token", ""),
            name=data.get("name", ""),
            encoding=data.get("encoding", ""),
            width=data.get("width"),
            height=data.get("height"),
            fps_limit=data.get("fps_limit"),
            bitrate_kbps=data.get("bitrate_kbps"),
            gop=data.get("gop"),
            quality=str(data.get("quality", "")),
            h264_profile=data.get("h264_profile", ""),
        )


@dataclass(slots=True)
class Profile:
    token: str = ""
    name: str = ""
    video_encoder: VideoEncoder | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        encoder = data.get("video_encoder")
        return cls(
            token=data.get("token", ""),
            name=data.get("name", ""),
            video_encoder=VideoEncoder.from_dict(encoder) if isinstance(encoder, dict) else None,
        )


@dataclass(slots=True)
class PTZStatus:
    pan: float | None = None
    tilt: float | None = None
    zoom: float | None = None
    move_status_pan_tilt: str = ""
    move_status_zoom: str = ""
    utc_time: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PTZStatus:
        move_raw = data.get("move_status")
        move: dict[str, Any] = move_raw if isinstance(move_raw, dict) else {}
        return cls(
            pan=data.get("pan"),
            tilt=data.get("tilt"),
            zoom=data.get("zoom"),
            move_status_pan_tilt=move.get("pan_tilt", ""),
            move_status_zoom=move.get("zoom", ""),
            utc_time=data.get("utc_time", ""),
        )


@dataclass(slots=True)
class SystemDateTime:
    date_time_type: str = ""
    daylight_savings: bool = False
    timezone: str = ""
    utc: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemDateTime:
        utc_raw = data.get("UTCDateTime")
        utc: datetime | None = None
        if isinstance(utc_raw, dict):
            try:
                utc = datetime(
                    utc_raw["year"],
                    utc_raw["month"],
                    utc_raw["day"],
                    utc_raw.get("hour", 0),
                    utc_raw.get("minute", 0),
                    utc_raw.get("second", 0),
                    tzinfo=UTC,
                )
            except (KeyError, ValueError, TypeError):
                utc = None
        return cls(
            date_time_type=data.get("date_time_type", ""),
            daylight_savings=bool(data.get("daylight_savings", False)),
            timezone=data.get("timezone", ""),
            utc=utc,
        )


@dataclass(slots=True)
class NetworkInterface:
    token: str = ""
    enabled: bool = False
    name: str = ""
    hardware_address: str = ""
    ipv4_addresses: list[str] = field(default_factory=list)
    ipv6_addresses: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkInterface:
        ipv4 = data.get("ipv4", {}) if isinstance(data.get("ipv4"), dict) else {}
        ipv6 = data.get("ipv6", {}) if isinstance(data.get("ipv6"), dict) else {}
        return cls(
            token=data.get("token", ""),
            enabled=bool(data.get("enabled", False)),
            name=data.get("name", ""),
            hardware_address=data.get("hardware_address", ""),
            ipv4_addresses=[a["address"] for a in ipv4.get("addresses", [])],
            ipv6_addresses=[a["address"] for a in ipv6.get("addresses", [])],
        )


@dataclass(slots=True)
class PTZPreset:
    """A stored PTZ preset position as returned by ``GetPresets``.

    Mirrors one item from :func:`onveef.parsers.parse_ptz_presets`. ``pan``, ``tilt`` and
    ``zoom`` are only populated when the device includes a ``PTZPosition`` for the preset.
    """

    token: str = ""
    name: str = ""
    pan: float | None = None
    tilt: float | None = None
    zoom: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PTZPreset:
        """Build a :class:`PTZPreset` from a ``parse_ptz_presets`` item dict."""
        return cls(
            token=data.get("token", ""),
            name=data.get("name", ""),
            pan=data.get("pan"),
            tilt=data.get("tilt"),
            zoom=data.get("zoom"),
        )


@dataclass(slots=True)
class RecordingTrack:
    """A single track within a recording.

    Mirrors one entry of the ``tracks`` list produced by
    :func:`onveef.parsers.parse_recordings`. ``configuration`` is the device's free-form
    track configuration preserved verbatim as a nested dict.
    """

    token: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingTrack:
        """Build a :class:`RecordingTrack` from a ``parse_recordings`` track dict."""
        cfg = data.get("configuration")
        return cls(
            token=data.get("token", ""),
            configuration=cfg if isinstance(cfg, dict) else {},
        )


@dataclass(slots=True)
class Recording:
    """A recording entry as returned by ``GetRecordings``.

    Mirrors one item from :func:`onveef.parsers.parse_recordings`. ``configuration`` holds
    the device's free-form recording configuration; ``tracks`` lists the media tracks.
    """

    token: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)
    tracks: list[RecordingTrack] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recording:
        """Build a :class:`Recording` from a ``parse_recordings`` item dict."""
        cfg = data.get("configuration")
        raw_tracks = data.get("tracks")
        tracks = raw_tracks if isinstance(raw_tracks, list) else []
        return cls(
            token=data.get("token", ""),
            configuration=cfg if isinstance(cfg, dict) else {},
            tracks=[RecordingTrack.from_dict(t) for t in tracks if isinstance(t, dict)],
        )


@dataclass(slots=True)
class PullMessage:
    """A single event notification pulled from a pull-point subscription.

    Mirrors one entry of the ``messages`` list produced by
    :func:`onveef.parsers.parse_pull_messages`. ``source`` and ``data`` are the flattened
    ``SimpleItem`` name/value pairs from the message's ``Source`` and ``Data`` sections.
    """

    topic: str = ""
    utc_time: str = ""
    property_operation: str = ""
    source: dict[str, str] = field(default_factory=dict)
    data: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PullMessage:
        """Build a :class:`PullMessage` from a ``parse_pull_messages`` message dict."""
        src = data.get("source")
        payload = data.get("data")
        return cls(
            topic=data.get("topic", ""),
            utc_time=data.get("utc_time", ""),
            property_operation=data.get("property_operation", ""),
            source=src if isinstance(src, dict) else {},
            data=payload if isinstance(payload, dict) else {},
        )


NotificationMessage = PullMessage
"""Alias for :class:`PullMessage`, matching the ONVIF ``NotificationMessage`` element name."""


@dataclass(slots=True)
class ImagingSettings:
    """Imaging settings as returned by ``GetImagingSettings``.

    Mirrors :func:`onveef.parsers.parse_imaging_settings`. The scalar fields map to the
    stable top-level keys; the grouped settings (``backlight_compensation``,
    ``wide_dynamic_range``, ``white_balance``, ``exposure`` and ``focus``) are preserved as
    nested dicts because their contents vary by device and mode.
    """

    brightness: float | None = None
    color_saturation: float | None = None
    contrast: float | None = None
    sharpness: float | None = None
    ir_cut_filter: str = ""
    backlight_compensation: dict[str, Any] = field(default_factory=dict)
    wide_dynamic_range: dict[str, Any] = field(default_factory=dict)
    white_balance: dict[str, Any] = field(default_factory=dict)
    exposure: dict[str, Any] = field(default_factory=dict)
    focus: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImagingSettings:
        """Build an :class:`ImagingSettings` from a ``parse_imaging_settings`` dict."""

        def _group(key: str) -> dict[str, Any]:
            value = data.get(key)
            return value if isinstance(value, dict) else {}

        return cls(
            brightness=data.get("Brightness"),
            color_saturation=data.get("ColorSaturation"),
            contrast=data.get("Contrast"),
            sharpness=data.get("Sharpness"),
            ir_cut_filter=data.get("IrCutFilter", ""),
            backlight_compensation=_group("BacklightCompensation"),
            wide_dynamic_range=_group("WideDynamicRange"),
            white_balance=_group("WhiteBalance"),
            exposure=_group("Exposure"),
            focus=_group("Focus"),
        )
