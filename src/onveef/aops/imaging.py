"""Imaging operations for the asyncio ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import envelopes, parsers
from onveef.atransport import AsyncTransport


class ImagingOperations(AsyncTransport):
    """Imaging operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def imaging_get_settings(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the imaging settings for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetImagingSettings",
            body_inner=envelopes.imaging_get_settings(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_settings(xml)

    async def imaging_get_options(self, *, video_source_token: str) -> str:
        """Return the raw imaging options XML for a video source."""
        return await self.call(
            service="imaging",
            operation="GetOptions",
            body_inner=envelopes.imaging_get_options(video_source_token=video_source_token),
        )

    async def imaging_get_options_parsed(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the parsed imaging options for a video source."""
        xml = await self.imaging_get_options(video_source_token=video_source_token)
        return parsers.parse_imaging_options(xml)

    async def imaging_get_status(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the imaging status (e.g. focus) for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetStatus",
            body_inner=envelopes.imaging_get_status(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_status(xml)

    async def imaging_set_settings(self, *, video_source_token: str, **kwargs: Any) -> None:
        """Set imaging settings for a video source (brightness, contrast, focus, ...)."""
        body = envelopes.imaging_set_settings(video_source_token=video_source_token, **kwargs)
        await self.call(
            service="imaging",
            operation="SetImagingSettings",
            body_inner=body,
        )

    async def imaging_move(
        self,
        *,
        video_source_token: str,
        focus_continuous: float | None = None,
        focus_absolute: float | None = None,
        focus_relative: float | None = None,
        speed: float | None = None,
    ) -> None:
        """Drive the imaging (focus) actuator continuously/absolutely/relatively."""
        await self.call(
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

    async def imaging_stop(self, *, video_source_token: str) -> None:
        """Stop imaging (focus) movement for a video source."""
        await self.call(
            service="imaging",
            operation="Stop",
            body_inner=envelopes.imaging_stop(video_source_token=video_source_token),
        )

    async def imaging_get_presets(self, *, video_source_token: str) -> list[dict[str, str]]:
        """Return the imaging presets for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetPresets",
            body_inner=envelopes.imaging_get_presets(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_presets(xml)

    async def imaging_get_current_preset(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the current imaging preset for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetCurrentPreset",
            body_inner=envelopes.imaging_get_current_preset(video_source_token=video_source_token),
        )
        return parsers.parse_named_element(xml, "Preset")

    async def imaging_set_current_preset(
        self, *, video_source_token: str, preset_token: str
    ) -> None:
        """Apply an imaging preset to a video source."""
        await self.call(
            service="imaging",
            operation="SetCurrentPreset",
            body_inner=envelopes.imaging_set_current_preset(
                video_source_token=video_source_token, preset_token=preset_token
            ),
        )

    async def imaging_get_move_options(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the focus move modes and ranges the imaging service supports."""
        xml = await self.call(
            service="imaging",
            operation="GetMoveOptions",
            body_inner=envelopes.imaging_get_move_options(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_move_options(xml)
