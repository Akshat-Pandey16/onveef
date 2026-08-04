"""Media and Media2 operations for the asyncio ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import envelopes, parsers, urls
from onveef.atransport import AsyncTransport
from onveef.exceptions import (
    OnvifCapabilityMissingError,
)
from onveef.transport import (
    fetch_snapshot_bytes,
)


class MediaOperations(AsyncTransport):
    """Media and Media2 operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def create_profile(self, *, name: str, token: str = "") -> str:
        """Create a media profile and return its token."""
        service, _ = await self._media_service()
        xml = await self.call(
            service=service,
            operation="CreateProfile",
            body_inner=envelopes.media_create_profile(name=name, token=token),
        )
        return parsers.parse_profile_create(xml) or token

    async def delete_profile(self, *, profile_token: str) -> None:
        """Delete a media profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="DeleteProfile",
            body_inner=envelopes.media_delete_profile(profile_token=profile_token),
        )

    async def add_video_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add a video source configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddVideoSourceConfiguration",
            body_inner=envelopes.media_add_video_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def add_video_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add a video encoder configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddVideoEncoderConfiguration",
            body_inner=envelopes.media_add_video_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_video_encoder_configuration(self, *, profile_token: str) -> None:
        """Remove the video encoder configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemoveVideoEncoderConfiguration",
            body_inner=envelopes.media_remove_video_encoder_configuration(
                profile_token=profile_token
            ),
        )

    async def add_ptz_configuration(self, *, profile_token: str, configuration_token: str) -> None:
        """Add a PTZ configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddPTZConfiguration",
            body_inner=envelopes.media_add_ptz_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_ptz_configuration(self, *, profile_token: str) -> None:
        """Remove the PTZ configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemovePTZConfiguration",
            body_inner=envelopes.media_remove_ptz_configuration(profile_token=profile_token),
        )

    async def add_audio_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add an audio source configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddAudioSourceConfiguration",
            body_inner=envelopes.media_add_audio_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def add_audio_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add an audio encoder configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddAudioEncoderConfiguration",
            body_inner=envelopes.media_add_audio_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_audio_encoder_configuration(self, *, profile_token: str) -> None:
        """Remove the audio encoder configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemoveAudioEncoderConfiguration",
            body_inner=envelopes.media_remove_audio_encoder_configuration(
                profile_token=profile_token
            ),
        )

    async def remove_audio_source_configuration(self, *, profile_token: str) -> None:
        """Remove the audio source configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemoveAudioSourceConfiguration",
            body_inner=envelopes.media_remove_audio_source_configuration(
                profile_token=profile_token
            ),
        )

    async def get_profiles(self) -> list[dict[str, Any]]:
        """Return the device's media profiles."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetProfiles",
            body_inner=envelopes.media_get_profiles(use_media2=use_media2),
        )
        return parsers.parse_profiles(xml)

    async def get_video_sources(self) -> list[dict[str, Any]]:
        """Return the device's video sources."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetVideoSources",
            body_inner=envelopes.media_get_video_sources(use_media2=use_media2),
        )
        return parsers.parse_video_sources(xml)

    async def get_video_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the device's video encoder configurations (preferring Media2)."""
        prefer_media2 = await self._has("media2")
        if prefer_media2:
            try:
                xml = await self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurations",
                    body_inner=envelopes.media_get_video_encoder_configurations(use_media2=True),
                )
                configs = parsers.parse_video_encoder_configurations(xml)
                if configs:
                    return configs
            except OnvifCapabilityMissingError:
                pass
        if await self._has("media"):
            xml = await self.call(
                service="media",
                operation="GetVideoEncoderConfigurations",
                body_inner=envelopes.media_get_video_encoder_configurations(use_media2=False),
            )
            return parsers.parse_video_encoder_configurations(xml)
        if prefer_media2:
            xml = await self.call(
                service="media2",
                operation="GetVideoEncoderConfigurations",
                body_inner=envelopes.media_get_video_encoder_configurations(use_media2=True),
            )
            return parsers.parse_video_encoder_configurations(xml)
        raise OnvifCapabilityMissingError("Device does not advertise a Media service.")

    async def get_stream_uri(
        self,
        *,
        profile_token: str,
        stream: str = "RTP-Unicast",
        protocol: str = "RTSP",
        protocol2: str = "RtspUnicast",
        with_credentials: bool = False,
    ) -> str:
        """Return the RTSP stream URI for a profile, host-rewritten to the connected address.

        Pass ``with_credentials=True`` to embed percent-encoded credentials in the URI, which
        is what ffmpeg, OpenCV, GStreamer and go2rtc expect.
        """
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetStreamUri",
            body_inner=envelopes.media_get_stream_uri(
                profile_token=profile_token,
                use_media2=use_media2,
                stream=stream,
                protocol=protocol,
                protocol2=protocol2,
            ),
        )
        uri = self._fix_url(parsers.parse_stream_uri(xml))
        if with_credentials:
            return urls.with_credentials(
                uri, self._credentials.username, self._credentials.password
            )
        return uri

    async def get_snapshot_uri(self, *, profile_token: str, with_credentials: bool = False) -> str:
        """Return the JPEG snapshot URI for a profile, host-rewritten like the stream URI."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetSnapshotUri",
            body_inner=envelopes.media_get_snapshot_uri(
                profile_token=profile_token, use_media2=use_media2
            ),
        )
        uri = self._fix_url(parsers.parse_snapshot_uri(xml))
        if with_credentials:
            return urls.with_credentials(
                uri, self._credentials.username, self._credentials.password
            )
        return uri

    async def get_snapshot(self, *, profile_token: str) -> tuple[bytes, str]:
        """Fetch a JPEG snapshot for a profile as ``(image_bytes, content_type)``.

        Resolves the snapshot URI then downloads it with the client's credentials and TLS
        setting (HTTP Digest auth, falling back to Basic).
        """
        uri = await self.get_snapshot_uri(profile_token=profile_token)
        return fetch_snapshot_bytes(
            snapshot_uri=uri,
            credentials=self._credentials,
            timeout_s=self._timeout_s,
            verify_tls=self._verify_tls,
        )

    async def set_video_encoder_configuration(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        width: int,
        height: int,
        quality: float,
        fps: int,
        bitrate_kbps: int,
        gop: int,
        h264_profile: str = "",
        force_persistence: bool = True,
    ) -> None:
        """Set a video encoder configuration via the legacy Media service."""
        if await self._has("media"):
            service = "media"
        else:
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration is only supported via the legacy Media service."
            )
        await self.call(
            service=service,
            operation="SetVideoEncoderConfiguration",
            body_inner=envelopes.media_set_video_encoder_configuration(
                token=token,
                name=name,
                encoding=encoding,
                width=width,
                height=height,
                quality=quality,
                fps=fps,
                bitrate_kbps=bitrate_kbps,
                gop=gop,
                h264_profile=h264_profile,
                force_persistence=force_persistence,
            ),
        )

    async def get_video_encoder_options(
        self, *, configuration_token: str, profile_token: str = ""
    ) -> dict[str, Any]:
        """Return video encoder configuration options via the legacy Media service."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetVideoEncoderConfigurationOptions requires the legacy Media service."
            )
        xml = await self.call(
            service="media",
            operation="GetVideoEncoderConfigurationOptions",
            body_inner=envelopes.media_get_video_encoder_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    async def get_video_encoder_options_raw(
        self,
        *,
        configuration_token: str = "",
        profile_token: str = "",
        prefer: str = "auto",
    ) -> tuple[str, str]:
        """Return ``(service, raw_xml)`` of video encoder options from Media or Media2."""
        if prefer == "media2" and await self._has("media2"):
            return (
                "media2",
                await self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media2_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if await self._has("media"):
            return (
                "media",
                await self.call(
                    service="media",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if await self._has("media2"):
            return (
                "media2",
                await self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media2_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        raise OnvifCapabilityMissingError(
            "GetVideoEncoderConfigurationOptions requires a Media or Media2 service."
        )

    async def get_video_encoder_options_normalized(
        self, *, configuration_token: str = "", profile_token: str = "", prefer: str = "auto"
    ) -> list[dict[str, Any]]:
        """Return encoder options normalized into one shape across Media1 and Media2.

        Media1 and Media2 describe the same capabilities with different element names and
        attribute-vs-element layouts. This flattens both into a list of per-encoding dicts
        (``encoding``, ``resolutions``, ``fps``, ``bitrate_kbps``, ``gop``, ``quality``,
        ``profiles``), which is what you want when building an encoder-settings UI.
        """
        _service, xml = await self.get_video_encoder_options_raw(
            configuration_token=configuration_token,
            profile_token=profile_token,
            prefer=prefer,
        )
        return parsers.parse_video_encoder_options_normalized(xml)

    async def set_video_encoder_configuration_media2(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        width: int,
        height: int,
        quality: float | None,
        fps: int | None,
        bitrate_kbps: int | None,
        gop: int | None,
        h264_profile: str = "",
        h265_profile: str = "",
        use_count: int = 0,
    ) -> None:
        """Set a video encoder configuration via the Media2 service."""
        if not await self._has("media2"):
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration (Media2) requires the Media2 service."
            )
        await self.call(
            service="media2",
            operation="SetVideoEncoderConfiguration",
            body_inner=envelopes.media2_set_video_encoder_configuration(
                token=token,
                name=name,
                encoding=encoding,
                width=width,
                height=height,
                quality=quality,
                fps=fps,
                bitrate_kbps=bitrate_kbps,
                gop=gop,
                h264_profile=h264_profile,
                h265_profile=h265_profile,
                use_count=use_count,
            ),
        )

    async def get_audio_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio encoder configurations."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioEncoderConfigurations",
            body_inner=envelopes.media_get_audio_encoder_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_encoder_configurations(xml)

    async def set_audio_encoder_configuration(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        bitrate_kbps: int,
        sample_rate: int,
        force_persistence: bool = True,
    ) -> None:
        """Set an audio encoder configuration via the legacy Media service."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioEncoderConfiguration is only supported via the legacy Media service."
            )
        await self.call(
            service="media",
            operation="SetAudioEncoderConfiguration",
            body_inner=envelopes.media_set_audio_encoder_configuration(
                token=token,
                name=name,
                encoding=encoding,
                bitrate_kbps=bitrate_kbps,
                sample_rate=sample_rate,
                force_persistence=force_persistence,
            ),
        )

    async def get_audio_sources(self) -> list[dict[str, Any]]:
        """Return the device's audio sources (legacy Media service)."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioSources requires the legacy Media service.")
        xml = await self.call(
            service="media",
            operation="GetAudioSources",
            body_inner=envelopes.media_get_audio_sources(),
        )
        return parsers.parse_audio_sources(xml)

    async def get_audio_outputs(self) -> list[dict[str, Any]]:
        """Return the device's audio outputs (legacy Media service)."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioOutputs requires the legacy Media service.")
        xml = await self.call(
            service="media",
            operation="GetAudioOutputs",
            body_inner=envelopes.media_get_audio_outputs(),
        )
        return parsers.parse_audio_outputs(xml)

    async def get_audio_output_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio output configurations (legacy Media service)."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetAudioOutputConfigurations requires the legacy Media service."
            )
        xml = await self.call(
            service="media",
            operation="GetAudioOutputConfigurations",
            body_inner=envelopes.media_get_audio_output_configurations(),
        )
        return parsers.parse_audio_output_configurations(xml)

    async def set_audio_output_configuration(
        self,
        *,
        token: str,
        name: str,
        output_token: str,
        output_level: int,
        send_primacy: str = "",
        use_count: int = 0,
        force_persistence: bool = True,
    ) -> None:
        """Set an audio output configuration via the legacy Media service."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioOutputConfiguration requires the legacy Media service."
            )
        await self.call(
            service="media",
            operation="SetAudioOutputConfiguration",
            body_inner=envelopes.media_set_audio_output_configuration(
                token=token,
                name=name,
                output_token=output_token,
                output_level=output_level,
                send_primacy=send_primacy,
                use_count=use_count,
                force_persistence=force_persistence,
            ),
        )

    async def get_video_analytics_configurations(self) -> list[dict[str, Any]]:
        """Return the device's video analytics configurations."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetVideoAnalyticsConfigurations",
            body_inner=envelopes.media_get_video_analytics_configurations(use_media2=use_media2),
        )
        return parsers.parse_video_analytics_configurations(xml)

    async def start_multicast_streaming(self, *, profile_token: str) -> None:
        """Start multicast streaming for a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="StartMulticastStreaming",
            body_inner=envelopes.media_start_multicast_streaming(profile_token=profile_token),
        )

    async def stop_multicast_streaming(self, *, profile_token: str) -> None:
        """Stop multicast streaming for a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="StopMulticastStreaming",
            body_inner=envelopes.media_stop_multicast_streaming(profile_token=profile_token),
        )

    async def get_osds(self, *, configuration_token: str = "") -> list[dict[str, Any]]:
        """Return the device's OSD entries (legacy Media service)."""
        await self._require_media1("GetOSDs")
        xml = await self.call(
            service="media",
            operation="GetOSDs",
            body_inner=envelopes.media_get_osds(configuration_token=configuration_token),
        )
        return parsers.parse_osds(xml)

    async def get_osd(self, *, osd_token: str) -> dict[str, Any]:
        """Return a single OSD entry (legacy Media service)."""
        await self._require_media1("GetOSD")
        xml = await self.call(
            service="media",
            operation="GetOSD",
            body_inner=envelopes.media_get_osd(osd_token=osd_token),
        )
        return parsers.parse_osd(xml)

    async def get_osd_options(self, *, configuration_token: str) -> dict[str, Any]:
        """Return OSD options for a video source configuration (legacy Media service)."""
        await self._require_media1("GetOSDOptions")
        xml = await self.call(
            service="media",
            operation="GetOSDOptions",
            body_inner=envelopes.media_get_osd_options(configuration_token=configuration_token),
        )
        return parsers.parse_osd_options(xml)

    async def create_osd(
        self,
        *,
        video_source_configuration_token: str,
        osd_type: str = "Text",
        position_type: str = "UpperLeft",
        pos_x: float | None = None,
        pos_y: float | None = None,
        text_type: str = "Plain",
        plain_text: str = "",
        font_size: int | None = None,
        date_format: str = "",
        time_format: str = "",
    ) -> str:
        """Create an on-screen display overlay (legacy Media service).

        Args:
            video_source_configuration_token: The video source the OSD is drawn on.
            osd_type: ``Text`` or ``Image``.
            position_type: ``UpperLeft``, ``UpperRight``, ``LowerLeft``, ``LowerRight`` or
                ``Custom`` — ``Custom`` uses ``pos_x``/``pos_y``.
            pos_x: Normalised -1..1 horizontal position, used only for ``Custom``.
            pos_y: Normalised -1..1 vertical position, used only for ``Custom``.
            text_type: ``Plain``, ``Date``, ``Time`` or ``DateAndTime``.
            plain_text: The text drawn when ``text_type`` is ``Plain``.
            font_size: Font size in points; omitted when ``None``.
            date_format: Device-specific date format string.
            time_format: Device-specific time format string.
        """
        await self._require_media1("CreateOSD")
        xml = await self.call(
            service="media",
            operation="CreateOSD",
            body_inner=envelopes.media_create_osd(
                video_source_configuration_token=video_source_configuration_token,
                osd_type=osd_type,
                position_type=position_type,
                pos_x=pos_x,
                pos_y=pos_y,
                text_type=text_type,
                plain_text=plain_text,
                font_size=font_size,
                date_format=date_format,
                time_format=time_format,
            ),
        )
        return parsers.parse_created_token(xml, tag="OSDToken")

    async def set_osd(
        self,
        *,
        osd_token: str,
        video_source_configuration_token: str,
        osd_type: str = "Text",
        position_type: str = "UpperLeft",
        pos_x: float | None = None,
        pos_y: float | None = None,
        text_type: str = "Plain",
        plain_text: str = "",
        font_size: int | None = None,
        date_format: str = "",
        time_format: str = "",
    ) -> None:
        """Update an on-screen display overlay (legacy Media service).

        Args:
            osd_token: The OSD to update.\n            video_source_configuration_token: The video source the OSD is drawn on.
            osd_type: ``Text`` or ``Image``.
            position_type: ``UpperLeft``, ``UpperRight``, ``LowerLeft``, ``LowerRight`` or
                ``Custom`` — ``Custom`` uses ``pos_x``/``pos_y``.
            pos_x: Normalised -1..1 horizontal position, used only for ``Custom``.
            pos_y: Normalised -1..1 vertical position, used only for ``Custom``.
            text_type: ``Plain``, ``Date``, ``Time`` or ``DateAndTime``.
            plain_text: The text drawn when ``text_type`` is ``Plain``.
            font_size: Font size in points; omitted when ``None``.
            date_format: Device-specific date format string.
            time_format: Device-specific time format string.
        """
        await self._require_media1("SetOSD")
        await self.call(
            service="media",
            operation="SetOSD",
            body_inner=envelopes.media_set_osd(
                osd_token=osd_token,
                video_source_configuration_token=video_source_configuration_token,
                osd_type=osd_type,
                position_type=position_type,
                pos_x=pos_x,
                pos_y=pos_y,
                text_type=text_type,
                plain_text=plain_text,
                font_size=font_size,
                date_format=date_format,
                time_format=time_format,
            ),
        )

    async def delete_osd(self, *, osd_token: str) -> None:
        """Delete an OSD entry (legacy Media service)."""
        await self._require_media1("DeleteOSD")
        await self.call(
            service="media",
            operation="DeleteOSD",
            body_inner=envelopes.media_delete_osd(osd_token=osd_token),
        )

    async def get_metadata_configurations(self) -> list[dict[str, Any]]:
        """Return the device's metadata configurations (legacy Media service)."""
        await self._require_media1("GetMetadataConfigurations")
        xml = await self.call(
            service="media",
            operation="GetMetadataConfigurations",
            body_inner=envelopes.media_get_metadata_configurations(),
        )
        return parsers.parse_metadata_configurations(xml)

    async def get_metadata_configuration(self, *, configuration_token: str) -> dict[str, Any]:
        """Return a single metadata configuration (legacy Media service)."""
        await self._require_media1("GetMetadataConfiguration")
        xml = await self.call(
            service="media",
            operation="GetMetadataConfiguration",
            body_inner=envelopes.media_get_metadata_configuration(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_metadata_configuration(xml)

    async def get_metadata_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return metadata configuration options (legacy Media service)."""
        await self._require_media1("GetMetadataConfigurationOptions")
        xml = await self.call(
            service="media",
            operation="GetMetadataConfigurationOptions",
            body_inner=envelopes.media_get_metadata_configuration_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    async def set_metadata_configuration(
        self,
        *,
        token: str,
        name: str,
        analytics: bool = True,
        ptz_status: bool = False,
        ptz_position: bool = False,
        use_count: int = 0,
    ) -> None:
        """Set a metadata configuration (legacy Media service)."""
        await self._require_media1("SetMetadataConfiguration")
        await self.call(
            service="media",
            operation="SetMetadataConfiguration",
            body_inner=envelopes.media_set_metadata_configuration(
                token=token,
                name=name,
                analytics=analytics,
                ptz_status=ptz_status,
                ptz_position=ptz_position,
                use_count=use_count,
            ),
        )

    async def add_metadata_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add a metadata configuration to a profile (legacy Media service)."""
        await self._require_media1("AddMetadataConfiguration")
        await self.call(
            service="media",
            operation="AddMetadataConfiguration",
            body_inner=envelopes.media_add_metadata_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_metadata_configuration(self, *, profile_token: str) -> None:
        """Remove the metadata configuration from a profile (legacy Media service)."""
        await self._require_media1("RemoveMetadataConfiguration")
        await self.call(
            service="media",
            operation="RemoveMetadataConfiguration",
            body_inner=envelopes.media_remove_metadata_configuration(profile_token=profile_token),
        )

    async def media2_create_profile(
        self, *, name: str, configurations: list[dict[str, str]] | None = None
    ) -> str:
        """Create a Media2 profile and return its token."""
        xml = await self.call(
            service="media2",
            operation="CreateProfile",
            body_inner=envelopes.media2_create_profile(name=name, configurations=configurations),
        )
        return parsers.parse_created_token(xml, tag="Token")

    async def media2_delete_profile(self, *, token: str) -> None:
        """Delete a Media2 profile."""
        await self.call(
            service="media2",
            operation="DeleteProfile",
            body_inner=envelopes.media2_delete_profile(token=token),
        )

    async def media2_get_profiles(self, *, types: list[str] | None = None) -> list[dict[str, Any]]:
        """Return Media2 profiles, optionally filtered by configuration ``types``."""
        xml = await self.call(
            service="media2",
            operation="GetProfiles",
            body_inner=envelopes.media2_get_profiles(types=types),
        )
        return parsers.parse_profiles(xml)

    async def media2_add_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]], name: str = ""
    ) -> None:
        """Add configurations to a Media2 profile."""
        await self.call(
            service="media2",
            operation="AddConfiguration",
            body_inner=envelopes.media2_add_configuration(
                profile_token=profile_token, configurations=configurations, name=name
            ),
        )

    async def media2_remove_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]]
    ) -> None:
        """Remove configurations from a Media2 profile."""
        await self.call(
            service="media2",
            operation="RemoveConfiguration",
            body_inner=envelopes.media2_remove_configuration(
                profile_token=profile_token, configurations=configurations
            ),
        )

    async def media2_set_synchronization_point(self, *, profile_token: str) -> None:
        """Request a Media2 synchronization point for a profile."""
        await self.call(
            service="media2",
            operation="SetSynchronizationPoint",
            body_inner=envelopes.media2_set_synchronization_point(profile_token=profile_token),
        )

    async def get_profile(self, *, profile_token: str) -> dict[str, Any]:
        """Return a single media profile by token (legacy Media service).

        Media2 has no single-profile operation, so this requires the Media1 service.
        """
        await self._require_media1("GetProfile")
        xml = await self.call(
            service="media",
            operation="GetProfile",
            body_inner=envelopes.media_get_profile(profile_token=profile_token),
        )
        profiles = parsers.parse_profiles(xml)
        return profiles[0] if profiles else {}

    async def get_video_source_configurations(self) -> list[dict[str, Any]]:
        """Return the device's video source configurations (crop bounds, rotation, source).

        These carry the ``configuration_token`` that :meth:`add_video_source_configuration`
        needs — without this operation there is no way to discover one.
        """
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetVideoSourceConfigurations",
            body_inner=envelopes.media_get_video_source_configurations(use_media2=use_media2),
        )
        return parsers.parse_video_source_configurations(xml)

    async def get_video_source_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the bounds ranges, source tokens and rotation modes a video source accepts."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetVideoSourceConfigurationOptions",
            body_inner=envelopes.media_get_video_source_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_video_source_configuration_options(xml)

    async def set_video_source_configuration(
        self,
        *,
        token: str,
        name: str,
        source_token: str,
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
        use_count: int | None = None,
        rotate: str = "",
        force_persistence: bool = True,
    ) -> None:
        """Set a video source configuration's crop bounds and optional rotation mode."""
        service, use_media2 = await self._media_service()
        await self.call(
            service=service,
            operation="SetVideoSourceConfiguration",
            body_inner=envelopes.media_set_video_source_configuration(
                token=token,
                name=name,
                source_token=source_token,
                x=x,
                y=y,
                width=width,
                height=height,
                use_media2=use_media2,
                use_count=use_count,
                rotate=rotate,
                force_persistence=force_persistence,
            ),
        )

    async def get_compatible_video_encoder_configurations(
        self, *, profile_token: str
    ) -> list[dict[str, Any]]:
        """Return the encoder configurations that may legally be added to a profile."""
        await self._require_media1("GetCompatibleVideoEncoderConfigurations")
        xml = await self.call(
            service="media",
            operation="GetCompatibleVideoEncoderConfigurations",
            body_inner=envelopes.media_get_compatible_video_encoder_configurations(
                profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_configurations(xml)

    async def get_audio_encoder_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> list[dict[str, Any]]:
        """Return the encodings, bitrates and sample rates the audio encoder accepts."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioEncoderConfigurationOptions",
            body_inner=envelopes.media_get_audio_encoder_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_encoder_configuration_options(xml)

    async def get_guaranteed_number_of_video_encoder_instances(
        self, *, configuration_token: str
    ) -> dict[str, int | None]:
        """Return how many simultaneous encoder instances a video source can guarantee."""
        await self._require_media1("GetGuaranteedNumberOfVideoEncoderInstances")
        xml = await self.call(
            service="media",
            operation="GetGuaranteedNumberOfVideoEncoderInstances",
            body_inner=envelopes.media_get_guaranteed_number_of_video_encoder_instances(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_encoder_instances(xml)

    async def media2_get_masks(self, *, configuration_token: str = "") -> list[dict[str, Any]]:
        """Return the Media2 privacy masks, optionally scoped to one configuration."""
        xml = await self.call(
            service="media2",
            operation="GetMasks",
            body_inner=envelopes.media2_get_masks(configuration_token=configuration_token),
        )
        return parsers.parse_masks(xml)

    async def media2_delete_mask(self, *, token: str) -> None:
        """Delete a Media2 privacy mask by token."""
        await self.call(
            service="media2",
            operation="DeleteMask",
            body_inner=envelopes.media2_delete_mask(token=token),
        )

    async def get_audio_source_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio source configurations.

        These carry the ``configuration_token`` that
        :meth:`add_audio_source_configuration` needs — the audio-side counterpart of
        :meth:`get_video_source_configurations`.
        """
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioSourceConfigurations",
            body_inner=envelopes.media_get_audio_source_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_source_configurations(xml)

    async def get_audio_source_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the audio inputs a source configuration may be pointed at."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioSourceConfigurationOptions",
            body_inner=envelopes.media_get_audio_source_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_source_configuration_options(xml)

    async def set_audio_source_configuration(
        self,
        *,
        token: str,
        name: str,
        source_token: str,
        use_count: int = 0,
        force_persistence: bool = True,
    ) -> None:
        """Point an audio source configuration at a different audio input."""
        service, use_media2 = await self._media_service()
        await self.call(
            service=service,
            operation="SetAudioSourceConfiguration",
            body_inner=envelopes.media_set_audio_source_configuration(
                token=token,
                name=name,
                source_token=source_token,
                use_media2=use_media2,
                use_count=use_count,
                force_persistence=force_persistence,
            ),
        )

    async def get_audio_output_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the outputs, send-primacy modes and level range an audio output accepts."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioOutputConfigurationOptions",
            body_inner=envelopes.media_get_audio_output_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_output_configuration_options(xml)

    async def get_video_source_modes(self, *, video_source_token: str) -> list[dict[str, Any]]:
        """Return the sensor modes a video source supports (aspect ratio, max resolution).

        A mode fixes the ceiling the encoder may then be configured within, so a
        resolution the camera clearly supports but that never appears in
        :meth:`get_video_encoder_options_normalized` is usually gated behind another mode.
        """
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetVideoSourceModes",
            body_inner=envelopes.media_get_video_source_modes(
                video_source_token=video_source_token, use_media2=use_media2
            ),
        )
        return parsers.parse_video_source_modes(xml)

    async def set_video_source_mode(self, *, video_source_token: str, mode_token: str) -> bool:
        """Switch a video source to another sensor mode; returns whether it will reboot.

        A ``True`` return means the device is restarting to apply the mode, and every
        other operation will fail until it comes back.
        """
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="SetVideoSourceMode",
            body_inner=envelopes.media_set_video_source_mode(
                video_source_token=video_source_token,
                mode_token=mode_token,
                use_media2=use_media2,
            ),
        )
        return parsers.parse_text_element(xml, "Reboot").strip().lower() in ("true", "1")

    async def get_audio_decoder_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio *decoder* configurations — the backchannel side.

        A decoder configuration added to a profile is what lets you send audio *to* the
        device (intercom, doorbell talk-down). Pair it with
        :meth:`get_audio_decoder_configuration_options` to learn which codec to encode in.
        """
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioDecoderConfigurations",
            body_inner=envelopes.media_get_audio_decoder_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_decoder_configurations(xml)

    async def get_audio_decoder_configuration(self, *, configuration_token: str) -> dict[str, Any]:
        """Return a single audio decoder configuration by token (legacy Media service)."""
        await self._require_media1("GetAudioDecoderConfiguration")
        xml = await self.call(
            service="media",
            operation="GetAudioDecoderConfiguration",
            body_inner=envelopes.media_get_audio_decoder_configuration(
                configuration_token=configuration_token
            ),
        )
        configurations = parsers.parse_audio_decoder_configurations(xml)
        return configurations[0] if configurations else {}

    async def get_audio_decoder_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the codecs, bitrates and sample rates the backchannel will accept."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioDecoderConfigurationOptions",
            body_inner=envelopes.media_get_audio_decoder_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_decoder_configuration_options(xml)

    async def set_audio_decoder_configuration(
        self, *, token: str, name: str, use_count: int = 0, force_persistence: bool = True
    ) -> None:
        """Rename an audio decoder configuration and persist it across reboots."""
        service, use_media2 = await self._media_service()
        await self.call(
            service=service,
            operation="SetAudioDecoderConfiguration",
            body_inner=envelopes.media_set_audio_decoder_configuration(
                token=token,
                name=name,
                use_media2=use_media2,
                use_count=use_count,
                force_persistence=force_persistence,
            ),
        )

    async def add_audio_decoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Wire an audio decoder into a profile, enabling the RTSP backchannel on it."""
        await self._require_media1("AddAudioDecoderConfiguration")
        await self.call(
            service="media",
            operation="AddAudioDecoderConfiguration",
            body_inner=envelopes.media_add_audio_decoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_audio_decoder_configuration(self, *, profile_token: str) -> None:
        """Remove the audio decoder configuration from a profile."""
        await self._require_media1("RemoveAudioDecoderConfiguration")
        await self.call(
            service="media",
            operation="RemoveAudioDecoderConfiguration",
            body_inner=envelopes.media_remove_audio_decoder_configuration(
                profile_token=profile_token
            ),
        )

    async def add_video_analytics_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Attach a video analytics configuration to a profile.

        The Analytics service edits rules and modules on a configuration the camera
        already has; this is what puts a configuration on a profile in the first place,
        so its events and metadata start flowing.
        """
        await self._require_media1("AddVideoAnalyticsConfiguration")
        await self.call(
            service="media",
            operation="AddVideoAnalyticsConfiguration",
            body_inner=envelopes.media_add_video_analytics_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_video_analytics_configuration(self, *, profile_token: str) -> None:
        """Detach the video analytics configuration from a profile."""
        await self._require_media1("RemoveVideoAnalyticsConfiguration")
        await self.call(
            service="media",
            operation="RemoveVideoAnalyticsConfiguration",
            body_inner=envelopes.media_remove_video_analytics_configuration(
                profile_token=profile_token
            ),
        )

    async def set_video_analytics_configuration(
        self,
        *,
        token: str,
        name: str,
        modules: list[dict[str, Any]] | None = None,
        rules: list[dict[str, Any]] | None = None,
        use_count: int = 0,
        force_persistence: bool = True,
    ) -> None:
        """Replace a video analytics configuration's engine and rule blocks wholesale.

        ``modules`` and ``rules`` take the same ``name``/``type``/``parameters`` dicts the
        Analytics service's own operations use. This overwrites the configuration, so read
        it with :meth:`get_video_analytics_configurations` first if you mean to amend it.
        """
        await self._require_media1("SetVideoAnalyticsConfiguration")
        await self.call(
            service="media",
            operation="SetVideoAnalyticsConfiguration",
            body_inner=envelopes.media_set_video_analytics_configuration(
                token=token,
                name=name,
                modules=list(modules or []),
                rules=list(rules or []),
                use_count=use_count,
                force_persistence=force_persistence,
            ),
        )
