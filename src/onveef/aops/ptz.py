"""PTZ operations for the asyncio ONVIF client."""

from __future__ import annotations

import contextlib
from typing import Any

from onveef import envelopes, parsers, ptz
from onveef.atransport import AsyncTransport
from onveef.exceptions import OnvifCapabilityMissingError
from onveef.ops.ptz import _LENS_UNANSWERED


class PtzOperations(AsyncTransport):
    """PTZ operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def ptz_get_nodes(self) -> list[dict[str, Any]]:
        """Return the device's PTZ nodes."""
        xml = await self.call(
            service="ptz",
            operation="GetNodes",
            body_inner=envelopes.ptz_get_nodes(),
        )
        return parsers.parse_ptz_nodes(xml)

    async def ptz_get_status(self, *, profile_token: str) -> dict[str, Any]:
        """Return the PTZ status for a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetStatus",
            body_inner=envelopes.ptz_get_status(profile_token=profile_token),
        )
        return parsers.parse_ptz_status(xml)

    async def ptz_continuous_move(
        self,
        *,
        profile_token: str,
        pan: float | None,
        tilt: float | None,
        zoom: float | None,
        timeout: str = "",
        pan_tilt_space: str = "",
        zoom_space: str = "",
    ) -> None:
        """Send the ONVIF ``ContinuousMove`` request to the PTZ service.

        ``pan_tilt_space``/``zoom_space`` name the velocity spaces (URIs listed by
        :meth:`ptz_get_nodes`); empty means the node's default space.
        """
        await self.call(
            service="ptz",
            operation="ContinuousMove",
            body_inner=envelopes.ptz_continuous_move(
                profile_token=profile_token,
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                timeout=timeout,
                pan_tilt_space=pan_tilt_space,
                zoom_space=zoom_space,
            ),
        )

    async def ptz_absolute_move(
        self,
        *,
        profile_token: str,
        pan: float | None,
        tilt: float | None,
        zoom: float | None,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
        pan_tilt_space: str = "",
        zoom_space: str = "",
    ) -> None:
        """Send the ONVIF ``AbsoluteMove`` request to the PTZ service.

        ``pan_tilt_space``/``zoom_space`` name the position spaces the coordinates are in
        (e.g. a degrees space from :meth:`ptz_get_nodes`); empty means the node's default.
        """
        await self.call(
            service="ptz",
            operation="AbsoluteMove",
            body_inner=envelopes.ptz_absolute_move(
                profile_token=profile_token,
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
                pan_tilt_space=pan_tilt_space,
                zoom_space=zoom_space,
            ),
        )

    async def ptz_relative_move(
        self,
        *,
        profile_token: str,
        pan: float | None,
        tilt: float | None,
        zoom: float | None,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
        pan_tilt_space: str = "",
        zoom_space: str = "",
    ) -> None:
        """Send the ONVIF ``RelativeMove`` request to the PTZ service.

        ``pan_tilt_space``/``zoom_space`` name the translation spaces; see
        :meth:`ptz_center` for moving in ``TranslationSpaceFov``.
        """
        await self.call(
            service="ptz",
            operation="RelativeMove",
            body_inner=envelopes.ptz_relative_move(
                profile_token=profile_token,
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
                pan_tilt_space=pan_tilt_space,
                zoom_space=zoom_space,
            ),
        )

    async def ptz_stop(
        self, *, profile_token: str, pan_tilt: bool = True, zoom: bool = True
    ) -> None:
        """Stop PTZ pan/tilt and/or zoom motion for a profile."""
        await self.call(
            service="ptz",
            operation="Stop",
            body_inner=envelopes.ptz_stop(
                profile_token=profile_token, pan_tilt=pan_tilt, zoom=zoom
            ),
        )

    async def ptz_get_presets(self, *, profile_token: str) -> list[dict[str, Any]]:
        """Return the PTZ presets for a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetPresets",
            body_inner=envelopes.ptz_get_presets(profile_token=profile_token),
        )
        return parsers.parse_ptz_presets(xml)

    async def ptz_set_preset(
        self,
        *,
        profile_token: str,
        preset_name: str = "",
        preset_token: str = "",
    ) -> str:
        """Create or update a PTZ preset and return its token."""
        xml = await self.call(
            service="ptz",
            operation="SetPreset",
            body_inner=envelopes.ptz_set_preset(
                profile_token=profile_token,
                preset_name=preset_name,
                preset_token=preset_token,
            ),
        )
        return parsers.parse_set_preset_token(xml) or preset_token

    async def ptz_remove_preset(self, *, profile_token: str, preset_token: str) -> None:
        """Remove a PTZ preset."""
        await self.call(
            service="ptz",
            operation="RemovePreset",
            body_inner=envelopes.ptz_remove_preset(
                profile_token=profile_token, preset_token=preset_token
            ),
        )

    async def ptz_goto_preset(
        self,
        *,
        profile_token: str,
        preset_token: str,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Move PTZ to a stored preset, optionally at a given speed."""
        await self.call(
            service="ptz",
            operation="GotoPreset",
            body_inner=envelopes.ptz_goto_preset(
                profile_token=profile_token,
                preset_token=preset_token,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
            ),
        )

    async def ptz_set_home_position(self, *, profile_token: str) -> None:
        """Store the current PTZ position as the home position."""
        await self.call(
            service="ptz",
            operation="SetHomePosition",
            body_inner=envelopes.ptz_set_home_position(profile_token=profile_token),
        )

    async def ptz_goto_home_position(
        self,
        *,
        profile_token: str,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Move PTZ to the home position, optionally at a given speed."""
        await self.call(
            service="ptz",
            operation="GotoHomePosition",
            body_inner=envelopes.ptz_goto_home_position(
                profile_token=profile_token,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
            ),
        )

    async def ptz_get_configurations(self) -> list[dict[str, Any]]:
        """Return the device's PTZ configurations."""
        xml = await self.call(
            service="ptz",
            operation="GetConfigurations",
            body_inner=envelopes.ptz_get_configurations(),
        )
        return parsers.parse_ptz_configurations(xml)

    async def ptz_get_compatible_configurations(
        self, *, profile_token: str
    ) -> list[dict[str, Any]]:
        """Return PTZ configurations compatible with a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetCompatibleConfigurations",
            body_inner=envelopes.ptz_get_compatible_configurations(profile_token=profile_token),
        )
        return parsers.parse_ptz_configurations(xml)

    async def ptz_get_configuration_options(self, *, configuration_token: str) -> dict[str, Any]:
        """Return the option ranges for a PTZ configuration."""
        xml = await self.call(
            service="ptz",
            operation="GetConfigurationOptions",
            body_inner=envelopes.ptz_get_configuration_options(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_ptz_configuration_options(xml)

    async def ptz_send_auxiliary_command(self, *, profile_token: str, auxiliary_data: str) -> None:
        """Send a PTZ auxiliary command (e.g. a wiper or IR light)."""
        await self.call(
            service="ptz",
            operation="SendAuxiliaryCommand",
            body_inner=envelopes.ptz_send_auxiliary_command(
                profile_token=profile_token, auxiliary_data=auxiliary_data
            ),
        )

    async def ptz_get_preset_tours(self, *, profile_token: str) -> list[dict[str, Any]]:
        """Return the PTZ preset tours for a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetPresetTours",
            body_inner=envelopes.ptz_get_preset_tours(profile_token=profile_token),
        )
        return parsers.parse_preset_tours(xml)

    async def ptz_operate_preset_tour(
        self, *, profile_token: str, preset_tour_token: str, operation: str
    ) -> None:
        """Start/stop/pause a PTZ preset tour."""
        await self.call(
            service="ptz",
            operation="OperatePresetTour",
            body_inner=envelopes.ptz_operate_preset_tour(
                profile_token=profile_token,
                preset_tour_token=preset_tour_token,
                operation=operation,
            ),
        )

    async def ptz_get_preset_tour(
        self, *, profile_token: str, preset_tour_token: str
    ) -> dict[str, Any]:
        """Return one preset tour in full, including the spots it visits."""
        xml = await self.call(
            service="ptz",
            operation="GetPresetTour",
            body_inner=envelopes.ptz_get_preset_tour(
                profile_token=profile_token, preset_tour_token=preset_tour_token
            ),
        )
        return parsers.parse_preset_tour(xml)

    async def ptz_create_preset_tour(self, *, profile_token: str) -> str:
        """Create an empty preset tour and return its token.

        ONVIF splits tour creation in two: this reserves the token, then
        :meth:`ptz_modify_preset_tour` fills in the name, schedule and spots.
        """
        xml = await self.call(
            service="ptz",
            operation="CreatePresetTour",
            body_inner=envelopes.ptz_create_preset_tour(profile_token=profile_token),
        )
        return parsers.parse_created_token(xml, tag="PresetTourToken")

    async def ptz_modify_preset_tour(
        self,
        *,
        profile_token: str,
        preset_tour_token: str,
        name: str = "",
        auto_start: bool = False,
        state: str = "Idle",
        recurring_time: int | None = None,
        recurring_duration: str = "",
        direction: str = "",
        random_order: bool | None = None,
        tour_spots: list[dict[str, Any]] | None = None,
    ) -> None:
        """Define a preset tour: its name, start condition and the spots it visits.

        Each entry in ``tour_spots`` is a dict of ``preset_token`` (or ``home: True``), an
        optional ``stay_time`` ISO-8601 duration and optional ``pan``/``tilt``/``zoom``
        move speeds. The tour is replaced wholesale, so send every field you want kept —
        read the current one with :meth:`ptz_get_preset_tour` first.
        Check :meth:`ptz_get_preset_tour_options` for the limits the device imposes.
        """
        await self.call(
            service="ptz",
            operation="ModifyPresetTour",
            body_inner=envelopes.ptz_modify_preset_tour(
                profile_token=profile_token,
                preset_tour_token=preset_tour_token,
                name=name,
                auto_start=auto_start,
                state=state,
                recurring_time=recurring_time,
                recurring_duration=recurring_duration,
                direction=direction,
                random_order=random_order,
                tour_spots=list(tour_spots or []),
            ),
        )

    async def ptz_remove_preset_tour(self, *, profile_token: str, preset_tour_token: str) -> None:
        """Delete a preset tour."""
        await self.call(
            service="ptz",
            operation="RemovePresetTour",
            body_inner=envelopes.ptz_remove_preset_tour(
                profile_token=profile_token, preset_tour_token=preset_tour_token
            ),
        )

    async def ptz_get_preset_tour_options(
        self, *, profile_token: str, preset_tour_token: str = ""
    ) -> dict[str, Any]:
        """Return the limits a preset tour must stay within on this device."""
        xml = await self.call(
            service="ptz",
            operation="GetPresetTourOptions",
            body_inner=envelopes.ptz_get_preset_tour_options(
                profile_token=profile_token, preset_tour_token=preset_tour_token
            ),
        )
        return parsers.parse_preset_tour_options(xml)

    async def ptz_geo_move(
        self,
        *,
        profile_token: str,
        lat: float,
        lon: float,
        elevation: float = 0.0,
        pan_speed: float | None = None,
        tilt_speed: float | None = None,
        zoom_speed: float | None = None,
        area_height: float | None = None,
        area_width: float | None = None,
    ) -> None:
        """Aim the camera at a geographic coordinate (Profile T geo-positioning).

        The device does the geometry from its own position and orientation, so this only
        works where :meth:`get_geo_location` reports one. ``area_height``/``area_width``
        (metres) ask it to frame an area rather than a point.
        """
        await self.call(
            service="ptz",
            operation="GeoMove",
            body_inner=envelopes.ptz_geo_move(
                profile_token=profile_token,
                lat=lat,
                lon=lon,
                elevation=elevation,
                pan_speed=pan_speed,
                tilt_speed=tilt_speed,
                zoom_speed=zoom_speed,
                area_height=area_height,
                area_width=area_width,
            ),
        )

    async def ptz_capabilities(self, *, profile_token: str = "") -> dict[str, Any]:
        """Summarise what the PTZ behind a media profile can do.

        Reads the profile, its PTZ node and — for focus and iris — the imaging options of
        its video source, and condenses them with :func:`onveef.ptz.capabilities`: which
        move types and axes exist, ``click_to_center`` (and the ``fov_space`` it needs),
        ``presets``, ``preset_tours``, ``home``, ``focus``/``iris`` and the speed ranges.

        Args:
            profile_token: The profile to drive; by default the first with a PTZ
                configuration.

        Raises:
            OnvifCapabilityMissingError: no PTZ service, no such profile, or a profile
                without a PTZ configuration.
        """
        profile, node = await self._ptz_profile_and_node(profile_token)
        source = str((profile.get("video_source") or {}).get("source_token") or "")
        imaging_options: dict[str, Any] = {}
        move_options: dict[str, Any] = {}
        if source and await self._has("imaging"):
            with contextlib.suppress(*_LENS_UNANSWERED):
                imaging_options = parsers.parse_imaging_options_normalized(
                    await self.call(
                        service="imaging",
                        operation="GetOptions",
                        body_inner=envelopes.imaging_get_options(video_source_token=source),
                    )
                )
            with contextlib.suppress(*_LENS_UNANSWERED):
                move_options = parsers.parse_imaging_move_options(
                    await self.call(
                        service="imaging",
                        operation="GetMoveOptions",
                        body_inner=envelopes.imaging_get_move_options(video_source_token=source),
                    )
                )
        return ptz.capabilities(
            profile=profile, node=node, imaging_options=imaging_options, move_options=move_options
        )

    async def ptz_center(
        self,
        *,
        profile_token: str,
        x: float,
        y: float,
        zoom: float | None = None,
        pan_tilt_space: str = "",
    ) -> None:
        """Centre the camera on a point of the current picture (click-to-center).

        ``x``/``y`` locate the point as fractions of the picture, 0 to 1 from the left and
        from the top — a click at ``(offsetX / width, offsetY / height)``. The camera makes
        a relative move in its ``TranslationSpaceFov`` (:func:`onveef.ptz.fov_translation`);
        ``zoom`` adds a relative zoom in the default zoom space.

        Finding that space costs a ``GetProfiles`` and a ``GetNodes``; when centring
        repeatedly, pass ``pan_tilt_space=ptz_capabilities()["fov_space"]`` to skip them.

        Raises:
            ValueError: ``x`` or ``y`` outside 0..1.
            OnvifCapabilityMissingError: the PTZ node has no ``TranslationSpaceFov``.
        """
        pan, tilt = ptz.fov_translation(x, y)
        space = pan_tilt_space
        if not space:
            _, node = await self._ptz_profile_and_node(profile_token)
            space = ptz.fov_space(node)
            if not space:
                raise OnvifCapabilityMissingError(
                    "This PTZ node has no TranslationSpaceFov, so it cannot click-to-center."
                )
        await self.ptz_relative_move(
            profile_token=profile_token, pan=pan, tilt=tilt, zoom=zoom, pan_tilt_space=space
        )

    async def _ptz_profile_and_node(
        self, profile_token: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The media profile to drive and its PTZ node."""
        service, use_media2 = await self._media_service()
        profiles = parsers.parse_profiles(
            await self.call(
                service=service,
                operation="GetProfiles",
                body_inner=envelopes.media_get_profiles(use_media2=use_media2),
            )
        )
        if profile_token:
            profile = next((p for p in profiles if p.get("token") == profile_token), None)
            if profile is None:
                raise OnvifCapabilityMissingError(f"The device has no profile '{profile_token}'.")
            if not profile.get("ptz"):
                raise OnvifCapabilityMissingError(
                    f"Profile '{profile_token}' has no PTZ configuration."
                )
        else:
            profile = next((p for p in profiles if p.get("ptz")), None)
            if profile is None:
                raise OnvifCapabilityMissingError("No media profile has a PTZ configuration.")
        nodes = await self.ptz_get_nodes()
        node_token = str((profile.get("ptz") or {}).get("node_token") or "")
        node = next((n for n in nodes if node_token and n.get("token") == node_token), None)
        if node is None:
            if not nodes:
                raise OnvifCapabilityMissingError("The device reports no PTZ node.")
            node = nodes[0]
        return profile, node
