"""Imaging operations for the synchronous ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import envelopes, parsers
from onveef.transport import (
    SyncTransport,
)


class ImagingOperations(SyncTransport):
    """Imaging operations, mixed into :class:`~onveef.client.OnvifClient`."""

    def imaging_get_settings(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetImagingSettings`` result from the Imaging service, parsed by ``parsers.parse_imaging_settings`` into ``dict[str, Any]``."""
        xml = self.call(
            service="imaging",
            operation="GetImagingSettings",
            body_inner=envelopes.imaging_get_settings(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_settings(xml)

    def imaging_get_options(self, *, video_source_token: str) -> str:
        """Return the raw ``GetOptions`` response XML from the Imaging service."""
        return self.call(
            service="imaging",
            operation="GetOptions",
            body_inner=envelopes.imaging_get_options(video_source_token=video_source_token),
        )

    def imaging_get_status(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetStatus`` result from the Imaging service, parsed by ``parsers.parse_imaging_status`` into ``dict[str, Any]``."""
        xml = self.call(
            service="imaging",
            operation="GetStatus",
            body_inner=envelopes.imaging_get_status(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_status(xml)

    def imaging_set_settings(self, *, video_source_token: str, **kwargs: Any) -> None:
        """Send the ONVIF ``SetImagingSettings`` request to the Imaging service."""
        body = envelopes.imaging_set_settings(video_source_token=video_source_token, **kwargs)
        self.call(
            service="imaging",
            operation="SetImagingSettings",
            body_inner=body,
        )

    def imaging_move(
        self,
        *,
        video_source_token: str,
        focus_continuous: float | None = None,
        focus_absolute: float | None = None,
        focus_relative: float | None = None,
        speed: float | None = None,
    ) -> None:
        """Send the ONVIF ``Move`` request to the Imaging service."""
        self.call(
            service="imaging",
            operation="Move",
            body_inner=envelopes.imaging_move(
                video_source_token=video_source_token,
                focus_continuous=focus_continuous,
                focus_absolute=focus_absolute,
                focus_relative=focus_relative,
                speed=speed,
            ),
        )

    def imaging_stop(self, *, video_source_token: str) -> None:
        """Send the ONVIF ``Stop`` request to the Imaging service."""
        self.call(
            service="imaging",
            operation="Stop",
            body_inner=envelopes.imaging_stop(video_source_token=video_source_token),
        )

    def imaging_get_options_parsed(self, *, video_source_token: str) -> dict[str, Any]:
        """Return imaging setting options for ``video_source_token`` as a parsed dict (wraps ``imaging_get_options`` + ``parsers.parse_imaging_options``)."""
        xml = self.imaging_get_options(video_source_token=video_source_token)
        return parsers.parse_imaging_options(xml)

    def imaging_get_presets(self, *, video_source_token: str) -> list[dict[str, str]]:
        """Return the ONVIF ``GetPresets`` result from the Imaging service, parsed by ``parsers.parse_imaging_presets`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="imaging",
            operation="GetPresets",
            body_inner=envelopes.imaging_get_presets(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_presets(xml)

    def imaging_get_current_preset(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetCurrentPreset`` result from the Imaging service, parsed by ``parsers.parse_named_element`` into ``dict[str, Any]``."""
        xml = self.call(
            service="imaging",
            operation="GetCurrentPreset",
            body_inner=envelopes.imaging_get_current_preset(video_source_token=video_source_token),
        )
        return parsers.parse_named_element(xml, "Preset")

    def imaging_set_current_preset(self, *, video_source_token: str, preset_token: str) -> None:
        """Send the ONVIF ``SetCurrentPreset`` request to the Imaging service."""
        self.call(
            service="imaging",
            operation="SetCurrentPreset",
            body_inner=envelopes.imaging_set_current_preset(
                video_source_token=video_source_token, preset_token=preset_token
            ),
        )

    def imaging_get_move_options(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the focus move modes and ranges the imaging service supports."""
        xml = self.call(
            service="imaging",
            operation="GetMoveOptions",
            body_inner=envelopes.imaging_get_move_options(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_move_options(xml)
