"""Imaging operations for the synchronous ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import envelopes, parsers, updates
from onveef.exceptions import OnvifValidationError
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
        """Send the ONVIF ``SetImagingSettings`` request to the Imaging service.

        Sends exactly the settings given (see :func:`onveef.envelopes.imaging_set_settings`).
        A block's mode is mandatory in the schema, so prefer :meth:`imaging_update_settings`
        to change, say, one exposure limit: it fills the mode in from the current settings.
        """
        body = envelopes.imaging_set_settings(video_source_token=video_source_token, **kwargs)
        self.call(
            service="imaging",
            operation="SetImagingSettings",
            body_inner=body,
        )

    def imaging_update_settings(
        self,
        *,
        video_source_token: str,
        validate: bool = True,
        force_persistence: bool = True,
        **changes: Any,
    ) -> dict[str, Any]:
        """Change some imaging settings, adding what the schema requires from the current ones.

        Takes the keyword arguments of :meth:`imaging_set_settings` (names in
        :data:`onveef.updates.IMAGING_SETTING_NAMES`). Each changed block gets the mode it
        needs from the device's current settings (:func:`onveef.updates.fill_imaging_modes`),
        so ``imaging_update_settings(video_source_token="VS0", exposure_max_time=33333)``
        works without knowing the exposure mode. With ``validate`` the changes are first
        checked against :meth:`imaging_get_options_normalized`.

        Returns:
            The settings sent — the changes plus any modes filled in; ``{}`` if there was
            nothing to change.

        Raises:
            TypeError: for a setting name ``imaging_set_settings`` does not know.
            OnvifValidationError: a value is outside what the device offers; nothing sent.
        """
        unknown = sorted(set(changes) - updates.IMAGING_SETTING_NAMES)
        if unknown:
            raise TypeError(f"Unknown imaging setting(s): {', '.join(unknown)}")
        asked = {key: value for key, value in changes.items() if value is not None and value != ""}
        if not asked:
            return {}
        if validate:
            options = self.imaging_get_options_normalized(video_source_token=video_source_token)
            problems = updates.check_imaging(asked, options)
            if problems:
                raise OnvifValidationError(problems)
        current = self.imaging_get_settings(video_source_token=video_source_token)
        settings = updates.fill_imaging_modes(asked, current)
        self.imaging_set_settings(
            video_source_token=video_source_token, force_persistence=force_persistence, **settings
        )
        return settings

    def imaging_get_options_normalized(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the imaging options in one predictable shape (``{}`` if none reported).

        See :func:`onveef.parsers.parse_imaging_options_normalized`; every setting is a
        ``{min, max}`` range, a list of modes, or ``None`` when the device does not offer it.
        """
        return parsers.parse_imaging_options_normalized(
            self.imaging_get_options(video_source_token=video_source_token)
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
