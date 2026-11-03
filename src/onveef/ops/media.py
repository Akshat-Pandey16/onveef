"""Media and Media2 operations for the synchronous ONVIF client."""

from __future__ import annotations

import contextlib
from typing import Any

from onveef import envelopes, parsers, updates, urls
from onveef.exceptions import (
    OnvifCapabilityMissingError,
    OnvifFaultError,
    OnvifOperationNotSupportedError,
    OnvifTransportError,
    OnvifValidationError,
)
from onveef.transport import (
    SyncTransport,
    fetch_snapshot_bytes,
)

# An options variant a device cannot answer is skipped, not fatal: the others may answer.
_OPTIONS_REFUSED = (
    OnvifFaultError,
    OnvifOperationNotSupportedError,
    OnvifCapabilityMissingError,
    OnvifTransportError,
)


class MediaOperations(SyncTransport):
    """Media and Media2 operations, mixed into :class:`~onveef.client.OnvifClient`."""

    def create_profile(self, *, name: str, token: str = "") -> str:
        """Return the ONVIF ``CreateProfile`` result from the Media service, parsed by ``parsers.parse_profile_create`` into ``str``."""
        service, _ = self._media_service()
        xml = self.call(
            service=service,
            operation="CreateProfile",
            body_inner=envelopes.media_create_profile(name=name, token=token),
        )
        return parsers.parse_profile_create(xml) or token

    def delete_profile(self, *, profile_token: str) -> None:
        """Send the ONVIF ``DeleteProfile`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="DeleteProfile",
            body_inner=envelopes.media_delete_profile(profile_token=profile_token),
        )

    def add_video_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddVideoSourceConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddVideoSourceConfiguration",
            body_inner=envelopes.media_add_video_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def add_video_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddVideoEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddVideoEncoderConfiguration",
            body_inner=envelopes.media_add_video_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_video_encoder_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveVideoEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemoveVideoEncoderConfiguration",
            body_inner=envelopes.media_remove_video_encoder_configuration(
                profile_token=profile_token
            ),
        )

    def add_ptz_configuration(self, *, profile_token: str, configuration_token: str) -> None:
        """Send the ONVIF ``AddPTZConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddPTZConfiguration",
            body_inner=envelopes.media_add_ptz_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_ptz_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemovePTZConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemovePTZConfiguration",
            body_inner=envelopes.media_remove_ptz_configuration(profile_token=profile_token),
        )

    def get_profiles(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetProfiles`` result from the Media service, parsed by ``parsers.parse_profiles`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetProfiles",
            body_inner=envelopes.media_get_profiles(use_media2=use_media2),
        )
        return parsers.parse_profiles(xml)

    def get_video_sources(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetVideoSources`` result from the Media service, parsed by ``parsers.parse_video_sources`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetVideoSources",
            body_inner=envelopes.media_get_video_sources(use_media2=use_media2),
        )
        return parsers.parse_video_sources(xml)

    def _video_encoder_configurations(self, service: str) -> list[dict[str, Any]]:
        xml = self.call(
            service=service,
            operation="GetVideoEncoderConfigurations",
            body_inner=envelopes.media_get_video_encoder_configurations(
                use_media2=service == "media2"
            ),
        )
        configs = parsers.parse_video_encoder_configurations(xml)
        for config in configs:
            config["service"] = service
        return configs

    def get_video_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the list of video encoder configurations, preferring the Media2 service and falling back to legacy Media.

        Each configuration carries ``service`` (``"media2"`` or ``"media"``), the service it
        was read from.
        """
        prefer_media2 = self._has("media2")
        if prefer_media2:
            try:
                configs = self._video_encoder_configurations("media2")
                if configs:
                    return configs
            except OnvifCapabilityMissingError:
                pass
        if self._has("media"):
            return self._video_encoder_configurations("media")
        if prefer_media2:
            return self._video_encoder_configurations("media2")
        raise OnvifCapabilityMissingError("Device does not advertise a Media service.")

    def get_stream_uri(
        self,
        *,
        profile_token: str,
        stream: str = "RTP-Unicast",
        protocol: str = "RTSP",
        protocol2: str = "RtspUnicast",
        with_credentials: bool = False,
    ) -> str:
        """Return the RTSP stream URI for a profile.

        The host is rewritten to the address this client reached the device on (unless
        ``rewrite_host=False``), because cameras habitually report their own LAN address.

        Args:
            profile_token: The media profile to stream.
            stream: Media1 ``StreamSetup`` stream type.
            protocol: Media1 transport protocol.
            protocol2: Media2 transport protocol.
            with_credentials: Embed this client's percent-encoded username and password in
                the URI, which is what ffmpeg, OpenCV, GStreamer and go2rtc expect. Note
                this puts the password in a string that is easy to log by accident.
        """
        service, use_media2 = self._media_service()
        xml = self.call(
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

    def get_snapshot_uri(self, *, profile_token: str, with_credentials: bool = False) -> str:
        """Return the JPEG snapshot URI for a profile, host-rewritten like the stream URI.

        Pass ``with_credentials=True`` to embed percent-encoded credentials in the URI.
        """
        service, use_media2 = self._media_service()
        xml = self.call(
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

    def get_snapshot(self, *, profile_token: str) -> tuple[bytes, str]:
        """Fetch a JPEG snapshot for a profile as ``(image_bytes, content_type)``.

        Resolves the snapshot URI then downloads it with the client's credentials and TLS
        setting (HTTP Digest auth, falling back to Basic).
        """
        uri = self.get_snapshot_uri(profile_token=profile_token)
        return fetch_snapshot_bytes(
            snapshot_uri=uri,
            credentials=self._credentials,
            timeout_s=self._timeout_s,
            verify_tls=self._verify_tls,
        )

    def set_video_encoder_configuration(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        width: int,
        height: int,
        quality: float,
        fps: int | None = None,
        bitrate_kbps: int | None = None,
        gop: int | None = None,
        h264_profile: str = "",
        force_persistence: bool = True,
        encoding_interval: int | None = None,
        session_timeout: str = "",
        multicast: dict[str, Any] | None = None,
        guaranteed_frame_rate: bool | None = None,
    ) -> None:
        """Send the ONVIF ``SetVideoEncoderConfiguration`` request to the Media service.

        Media1 replaces the configuration as a whole and requires its multicast settings and
        session timeout, so whichever of ``multicast``, ``session_timeout``,
        ``encoding_interval`` and ``guaranteed_frame_rate`` is not given is read back from
        the device first and written unchanged — sending defaults instead would reset the
        stream's multicast setup to ``0.0.0.0``. Pass ``fps`` and ``bitrate_kbps`` together
        (or neither); ``h264_profile`` also names the MPEG-4 profile for ``MPEG4``. To
        change a few fields and keep the rest, use :meth:`update_video_encoder_configuration`.
        """
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration is only supported via the legacy Media service."
            )
        current: dict[str, Any] = {}
        if multicast is None or not session_timeout or encoding_interval is None:
            current = next(
                (c for c in self._video_encoder_configurations("media") if c.get("token") == token),
                {},
            )
        if guaranteed_frame_rate is None:
            guaranteed_frame_rate = current.get("guaranteed_frame_rate")
        self.call(
            service="media",
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
                use_count=int(current.get("use_count") or 0),
                session_timeout=session_timeout or str(current.get("session_timeout") or "PT60S"),
                force_persistence=force_persistence,
                encoding_interval=(
                    encoding_interval
                    if encoding_interval is not None
                    else int(current.get("encoding_interval") or 1)
                ),
                multicast=multicast if multicast is not None else current.get("multicast"),
                guaranteed_frame_rate=guaranteed_frame_rate,
            ),
        )

    def get_audio_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioEncoderConfigurations`` result from the Media service, parsed by ``parsers.parse_audio_encoder_configurations`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioEncoderConfigurations",
            body_inner=envelopes.media_get_audio_encoder_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_encoder_configurations(xml)

    def set_audio_encoder_configuration(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        bitrate_kbps: int,
        sample_rate: int,
        force_persistence: bool = True,
        session_timeout: str = "",
        multicast: dict[str, Any] | None = None,
    ) -> None:
        """Send the ONVIF ``SetAudioEncoderConfiguration`` request to the Media service.

        Like :meth:`set_video_encoder_configuration`, an unspecified ``multicast`` or
        ``session_timeout`` is read back from the device and kept rather than reset.
        ``encoding`` may be a Media2 RTP name (``PCMU``, ``MP4A-LATM``…); it is sent as the
        Media1 codec family.
        """
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioEncoderConfiguration is only supported via the legacy Media service."
            )
        current: dict[str, Any] = {}
        if multicast is None or not session_timeout:
            xml = self.call(
                service="media",
                operation="GetAudioEncoderConfigurations",
                body_inner=envelopes.media_get_audio_encoder_configurations(use_media2=False),
            )
            current = next(
                (c for c in parsers.parse_audio_encoder_configurations(xml) if c["token"] == token),
                {},
            )
        self.call(
            service="media",
            operation="SetAudioEncoderConfiguration",
            body_inner=envelopes.media_set_audio_encoder_configuration(
                token=token,
                name=name,
                encoding=encoding,
                bitrate_kbps=bitrate_kbps,
                sample_rate=sample_rate,
                use_count=int(current.get("use_count") or 0),
                session_timeout=session_timeout or str(current.get("session_timeout") or "PT60S"),
                force_persistence=force_persistence,
                multicast=multicast if multicast is not None else current.get("multicast"),
            ),
        )

    def get_audio_sources(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioSources`` result from the Media service, parsed by ``parsers.parse_audio_sources`` into ``list[dict[str, Any]]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioSources requires the legacy Media service.")
        xml = self.call(
            service="media",
            operation="GetAudioSources",
            body_inner=envelopes.media_get_audio_sources(),
        )
        return parsers.parse_audio_sources(xml)

    def get_audio_outputs(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioOutputs`` result from the Media service, parsed by ``parsers.parse_audio_outputs`` into ``list[dict[str, Any]]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioOutputs requires the legacy Media service.")
        xml = self.call(
            service="media",
            operation="GetAudioOutputs",
            body_inner=envelopes.media_get_audio_outputs(),
        )
        return parsers.parse_audio_outputs(xml)

    def get_audio_output_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioOutputConfigurations`` result from the Media service, parsed by ``parsers.parse_audio_output_configurations`` into ``list[dict[str, Any]]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetAudioOutputConfigurations requires the legacy Media service."
            )
        xml = self.call(
            service="media",
            operation="GetAudioOutputConfigurations",
            body_inner=envelopes.media_get_audio_output_configurations(),
        )
        return parsers.parse_audio_output_configurations(xml)

    def set_audio_output_configuration(
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
        """Send the ONVIF ``SetAudioOutputConfiguration`` request to the Media service."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioOutputConfiguration requires the legacy Media service."
            )
        self.call(
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

    def get_video_encoder_options(
        self, *, configuration_token: str, profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetVideoEncoderConfigurationOptions`` result from the Media service, parsed by ``parsers.parse_video_encoder_options`` into ``dict[str, Any]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetVideoEncoderConfigurationOptions requires the legacy Media service."
            )
        xml = self.call(
            service="media",
            operation="GetVideoEncoderConfigurationOptions",
            body_inner=envelopes.media_get_video_encoder_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    def get_video_encoder_options_raw(
        self,
        *,
        configuration_token: str = "",
        profile_token: str = "",
        prefer: str = "auto",
    ) -> tuple[str, str]:
        """Return ``(service_name, response_xml)`` for ``GetVideoEncoderConfigurationOptions``, selecting Media2 or Media per ``prefer``."""
        if prefer == "media2" and self._has("media2"):
            return (
                "media2",
                self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media2_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if self._has("media"):
            return (
                "media",
                self.call(
                    service="media",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if self._has("media2"):
            return (
                "media2",
                self.call(
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

    def get_video_encoder_options_normalized(
        self, *, configuration_token: str = "", profile_token: str = "", prefer: str = "auto"
    ) -> list[dict[str, Any]]:
        """Return encoder options normalized into one shape across Media1 and Media2.

        Media1 and Media2 describe the same capabilities with different element names and
        attribute-vs-element layouts. This flattens both into a list of per-encoding dicts
        (``encoding``, ``resolutions``, ``fps``, ``bitrate_kbps``, ``gop``, ``quality``,
        ``profiles``), which is what you want when building an encoder-settings UI.
        """
        _service, xml = self.get_video_encoder_options_raw(
            configuration_token=configuration_token,
            profile_token=profile_token,
            prefer=prefer,
        )
        return parsers.parse_video_encoder_options_normalized(xml)

    def set_video_encoder_configuration_media2(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        width: int,
        height: int,
        quality: float | None,
        fps: float | None,
        bitrate_kbps: int | None,
        gop: int | None,
        h264_profile: str = "",
        h265_profile: str = "",
        use_count: int = 0,
        profile: str = "",
        constant_bitrate: bool | None = None,
        guaranteed_frame_rate: bool | None = None,
        multicast: dict[str, Any] | None = None,
    ) -> None:
        """Send the ONVIF ``SetVideoEncoderConfiguration`` request to the Media2 service.

        See :func:`onveef.envelopes.media2_set_video_encoder_configuration`. The
        configuration is replaced as a whole, so pass the current ``constant_bitrate``,
        ``guaranteed_frame_rate`` and ``multicast`` to keep them — or use
        :meth:`update_video_encoder_configuration`, which does.
        """
        if not self._has("media2"):
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration (Media2) requires the Media2 service."
            )
        self.call(
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
                profile=profile,
                constant_bitrate=constant_bitrate,
                guaranteed_frame_rate=guaranteed_frame_rate,
                multicast=multicast,
            ),
        )

    def get_video_encoder_options_merged(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return every encoding, resolution and rate an encoder configuration accepts.

        Devices answer ``GetVideoEncoderConfigurationOptions`` differently over Media2 and
        Media1, and Media2 may answer differently again when asked per profile, so this
        asks each way the device supports — Media2 for the configuration and for every
        profile using it, then Media1 if Media2 gave nothing — and unions the answers per
        encoding. Returns the shape of :meth:`get_video_encoder_options_normalized`;
        variants the device refuses are skipped, so ``[]`` means it described nothing.
        """
        answers: list[list[dict[str, Any]]] = []
        if self._has("media2"):
            with contextlib.suppress(*_OPTIONS_REFUSED):
                answers.append(self._video_encoder_options("media2", configuration_token, ""))
            profiles: list[dict[str, Any]] = []
            with contextlib.suppress(*_OPTIONS_REFUSED):
                profiles = self.get_profiles()
            for profile_token in dict.fromkeys(
                str(profile.get("token") or "")
                for profile in profiles
                if (profile.get("video_encoder") or {}).get("token") == configuration_token
            ):
                with contextlib.suppress(*_OPTIONS_REFUSED):
                    answers.append(
                        self._video_encoder_options("media2", configuration_token, profile_token)
                    )
        if not any(answers) and self._has("media"):
            with contextlib.suppress(*_OPTIONS_REFUSED):
                answers.append(self._video_encoder_options("media", configuration_token, ""))
        return parsers.merge_video_encoder_options(*answers)

    def _video_encoder_options(
        self, service: str, configuration_token: str, profile_token: str
    ) -> list[dict[str, Any]]:
        body = (
            envelopes.media2_get_video_encoder_options(
                configuration_token=configuration_token, profile_token=profile_token
            )
            if service == "media2"
            else envelopes.media_get_video_encoder_options(
                configuration_token=configuration_token, profile_token=profile_token
            )
        )
        xml = self.call(
            service=service, operation="GetVideoEncoderConfigurationOptions", body_inner=body
        )
        return parsers.parse_video_encoder_options_normalized(xml)

    def update_video_encoder_configuration(
        self,
        *,
        configuration_token: str,
        encoding: str | None = None,
        width: int | None = None,
        height: int | None = None,
        quality: float | None = None,
        frame_rate: float | None = None,
        bitrate_kbps: int | None = None,
        gop: int | None = None,
        profile: str | None = None,
        constant_bitrate: bool | None = None,
        guaranteed_frame_rate: bool | None = None,
        encoding_interval: int | None = None,
        multicast: dict[str, Any] | None = None,
        name: str | None = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Change some settings of a video encoder configuration and keep all the others.

        ``SetVideoEncoderConfiguration`` replaces the whole configuration, so changing the
        bit rate alone means sending the resolution, frame rate, GOP, profile, rate-control
        mode and multicast setup back exactly as they were. This reads the configuration,
        overlays the arguments that are not ``None`` (:func:`onveef.updates.merge_video_encoder`),
        checks them against the encoder's options (:meth:`get_video_encoder_options_merged`)
        and writes the result over Media2 when the device has it, falling back to Media1
        when Media2 refuses — except for H.265, which Media1 cannot express::

            cam.update_video_encoder_configuration(configuration_token="VE0", bitrate_kbps=2048)

        Args:
            configuration_token: The encoder configuration to change.
            frame_rate: Frames per second (Media2 accepts fractions such as ``29.97``).
            profile: The codec profile, e.g. ``Main`` or ``High``.
            validate: Check the changed values against the encoder's options first. Turn
                off only for a device whose options are known to be wrong.

        Returns:
            The configuration as written (see :func:`onveef.updates.merge_video_encoder`)
            plus ``service``, ``"media2"`` or ``"media"``.

        Raises:
            OnvifValidationError: a changed value is not one the encoder offers; nothing was
                written. ``errors`` names each field and why.
            OnvifCapabilityMissingError: no encoder configuration has that token.
        """
        changes = {
            key: value
            for key, value in {
                "encoding": encoding,
                "width": width,
                "height": height,
                "quality": quality,
                "frame_rate": frame_rate,
                "bitrate_kbps": bitrate_kbps,
                "gop": gop,
                "profile": profile,
                "constant_bitrate": constant_bitrate,
                "guaranteed_frame_rate": guaranteed_frame_rate,
                "encoding_interval": encoding_interval,
                "multicast": multicast,
                "name": name,
            }.items()
            if value is not None
        }
        current = next(
            (
                config
                for config in self.get_video_encoder_configurations()
                if config.get("token") == configuration_token
            ),
            None,
        )
        if current is None:
            raise OnvifCapabilityMissingError(
                f"The device has no video encoder configuration '{configuration_token}'."
            )
        merged = updates.merge_video_encoder(current, changes)
        options = (
            self.get_video_encoder_options_merged(configuration_token=configuration_token)
            if validate or merged["quality"] is None
            else []
        )
        if validate:
            problems = updates.check_video_encoder(merged, options, changed=changes)
            if problems:
                raise OnvifValidationError(problems)
        service = self._write_video_encoder(configuration_token, merged, options)
        return {**merged, "service": service}

    def _write_video_encoder(
        self, token: str, merged: dict[str, Any], options: list[dict[str, Any]]
    ) -> str:
        """Write a merged encoder configuration over Media2, else Media1; return which."""
        if merged["width"] is None or merged["height"] is None:
            raise OnvifValidationError(
                {"resolution": ["The device reported no resolution for this encoder."]}
            )
        quality = merged["quality"]
        if quality is None:
            bounds = next(
                (o.get("quality") for o in options if o.get("encoding") == merged["encoding"]),
                None,
            )
            quality = None if bounds is None else round((bounds["min"] + bounds["max"]) / 2)
        if quality is None:
            raise OnvifValidationError(
                {"quality": ["The device reported no quality for this encoder; pass one."]}
            )
        # Both rate limits travel together in a RateControl, or neither is sent.
        rated = merged["frame_rate"] is not None and merged["bitrate_kbps"] is not None
        frame_rate = merged["frame_rate"] if rated else None
        bitrate = merged["bitrate_kbps"] if rated else None
        if self._has("media2"):
            try:
                self.set_video_encoder_configuration_media2(
                    token=token,
                    name=str(merged["name"]),
                    encoding=str(merged["encoding"]),
                    width=int(merged["width"]),
                    height=int(merged["height"]),
                    quality=float(quality),
                    fps=frame_rate,
                    bitrate_kbps=bitrate,
                    gop=merged["gop"],
                    profile=str(merged["profile"]),
                    constant_bitrate=merged["constant_bitrate"] if rated else None,
                    guaranteed_frame_rate=merged["guaranteed_frame_rate"],
                    multicast=merged["multicast"],
                    use_count=int(merged["use_count"]),
                )
            except (OnvifFaultError, OnvifOperationNotSupportedError):
                if merged["encoding"] == "H265" or not self._has("media"):
                    raise
            else:
                return "media2"
        self.set_video_encoder_configuration(
            token=token,
            name=str(merged["name"]),
            encoding=str(merged["encoding"]),
            width=int(merged["width"]),
            height=int(merged["height"]),
            quality=float(quality),
            fps=None if frame_rate is None else round(frame_rate),
            bitrate_kbps=bitrate,
            gop=merged["gop"],
            h264_profile=str(merged["profile"]),
            encoding_interval=merged["encoding_interval"],
            multicast=merged["multicast"],
            guaranteed_frame_rate=merged["guaranteed_frame_rate"],
        )
        return "media"

    def get_video_analytics_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetVideoAnalyticsConfigurations`` result from the Media service, parsed by ``parsers.parse_video_analytics_configurations`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetVideoAnalyticsConfigurations",
            body_inner=envelopes.media_get_video_analytics_configurations(use_media2=use_media2),
        )
        return parsers.parse_video_analytics_configurations(xml)

    def get_osds(self, *, configuration_token: str = "") -> list[dict[str, Any]]:
        """Return the ONVIF ``GetOSDs`` result from the Media service, parsed by ``parsers.parse_osds`` into ``list[dict[str, Any]]``."""
        self._require_media1("GetOSDs")
        xml = self.call(
            service="media",
            operation="GetOSDs",
            body_inner=envelopes.media_get_osds(configuration_token=configuration_token),
        )
        return parsers.parse_osds(xml)

    def get_osd(self, *, osd_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetOSD`` result from the Media service, parsed by ``parsers.parse_osd`` into ``dict[str, Any]``."""
        self._require_media1("GetOSD")
        xml = self.call(
            service="media",
            operation="GetOSD",
            body_inner=envelopes.media_get_osd(osd_token=osd_token),
        )
        return parsers.parse_osd(xml)

    def get_osd_options(self, *, configuration_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetOSDOptions`` result from the Media service, parsed by ``parsers.parse_osd_options`` into ``dict[str, Any]``."""
        self._require_media1("GetOSDOptions")
        xml = self.call(
            service="media",
            operation="GetOSDOptions",
            body_inner=envelopes.media_get_osd_options(configuration_token=configuration_token),
        )
        return parsers.parse_osd_options(xml)

    def create_osd(
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
        self._require_media1("CreateOSD")
        xml = self.call(
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

    def set_osd(
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
        self._require_media1("SetOSD")
        self.call(
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

    def delete_osd(self, *, osd_token: str) -> None:
        """Send the ONVIF ``DeleteOSD`` request to the Media service."""
        self._require_media1("DeleteOSD")
        self.call(
            service="media",
            operation="DeleteOSD",
            body_inner=envelopes.media_delete_osd(osd_token=osd_token),
        )

    def get_metadata_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetMetadataConfigurations`` result from the Media service, parsed by ``parsers.parse_metadata_configurations`` into ``list[dict[str, Any]]``."""
        self._require_media1("GetMetadataConfigurations")
        xml = self.call(
            service="media",
            operation="GetMetadataConfigurations",
            body_inner=envelopes.media_get_metadata_configurations(),
        )
        return parsers.parse_metadata_configurations(xml)

    def get_metadata_configuration(self, *, configuration_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetMetadataConfiguration`` result from the Media service, parsed by ``parsers.parse_metadata_configuration`` into ``dict[str, Any]``."""
        self._require_media1("GetMetadataConfiguration")
        xml = self.call(
            service="media",
            operation="GetMetadataConfiguration",
            body_inner=envelopes.media_get_metadata_configuration(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_metadata_configuration(xml)

    def get_metadata_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetMetadataConfigurationOptions`` result from the Media service, parsed by ``parsers.parse_video_encoder_options`` into ``dict[str, Any]``."""
        self._require_media1("GetMetadataConfigurationOptions")
        xml = self.call(
            service="media",
            operation="GetMetadataConfigurationOptions",
            body_inner=envelopes.media_get_metadata_configuration_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    def set_metadata_configuration(
        self,
        *,
        token: str,
        name: str,
        analytics: bool = True,
        ptz_status: bool = False,
        ptz_position: bool = False,
        use_count: int = 0,
        events: bool | None = None,
        events_topic_filter: str | None = None,
        session_timeout: str = "",
        multicast: dict[str, Any] | None = None,
    ) -> None:
        """Send the ONVIF ``SetMetadataConfiguration`` request to the Media service.

        The configuration is replaced as a whole. ``events``/``events_topic_filter``,
        ``session_timeout`` and ``multicast`` left at their defaults are read back from the
        device and kept — so updating the analytics flag no longer silently stops the
        metadata stream carrying events, or resets its multicast setup.
        """
        self._require_media1("SetMetadataConfiguration")
        current: dict[str, Any] = {}
        if (
            events is None
            or events_topic_filter is None
            or multicast is None
            or not session_timeout
        ):
            current = next(
                (c for c in self.get_metadata_configurations() if c.get("token") == token), {}
            )
        self.call(
            service="media",
            operation="SetMetadataConfiguration",
            body_inner=envelopes.media_set_metadata_configuration(
                token=token,
                name=name,
                analytics=analytics,
                ptz_status=ptz_status,
                ptz_position=ptz_position,
                use_count=use_count,
                session_timeout=session_timeout or str(current.get("session_timeout") or "PT60S"),
                multicast=multicast if multicast is not None else current.get("multicast"),
                events=bool(current.get("events")) if events is None else events,
                events_topic_filter=(
                    str(current.get("events_topic_filter") or "")
                    if events_topic_filter is None
                    else events_topic_filter
                ),
            ),
        )

    def add_metadata_configuration(self, *, profile_token: str, configuration_token: str) -> None:
        """Send the ONVIF ``AddMetadataConfiguration`` request to the Media service."""
        self._require_media1("AddMetadataConfiguration")
        self.call(
            service="media",
            operation="AddMetadataConfiguration",
            body_inner=envelopes.media_add_metadata_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_metadata_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveMetadataConfiguration`` request to the Media service."""
        self._require_media1("RemoveMetadataConfiguration")
        self.call(
            service="media",
            operation="RemoveMetadataConfiguration",
            body_inner=envelopes.media_remove_metadata_configuration(profile_token=profile_token),
        )

    def add_audio_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddAudioSourceConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddAudioSourceConfiguration",
            body_inner=envelopes.media_add_audio_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def add_audio_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddAudioEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddAudioEncoderConfiguration",
            body_inner=envelopes.media_add_audio_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_audio_encoder_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveAudioEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemoveAudioEncoderConfiguration",
            body_inner=envelopes.media_remove_audio_encoder_configuration(
                profile_token=profile_token
            ),
        )

    def remove_audio_source_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveAudioSourceConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemoveAudioSourceConfiguration",
            body_inner=envelopes.media_remove_audio_source_configuration(
                profile_token=profile_token
            ),
        )

    def start_multicast_streaming(self, *, profile_token: str) -> None:
        """Send the ONVIF ``StartMulticastStreaming`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="StartMulticastStreaming",
            body_inner=envelopes.media_start_multicast_streaming(profile_token=profile_token),
        )

    def stop_multicast_streaming(self, *, profile_token: str) -> None:
        """Send the ONVIF ``StopMulticastStreaming`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="StopMulticastStreaming",
            body_inner=envelopes.media_stop_multicast_streaming(profile_token=profile_token),
        )

    def media2_create_profile(
        self, *, name: str, configurations: list[dict[str, str]] | None = None
    ) -> str:
        """Return the ONVIF ``CreateProfile`` result from the Media2 service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="media2",
            operation="CreateProfile",
            body_inner=envelopes.media2_create_profile(name=name, configurations=configurations),
        )
        return parsers.parse_created_token(xml, tag="Token")

    def media2_delete_profile(self, *, token: str) -> None:
        """Send the ONVIF ``DeleteProfile`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="DeleteProfile",
            body_inner=envelopes.media2_delete_profile(token=token),
        )

    def media2_get_profiles(self, *, types: list[str] | None = None) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetProfiles`` result from the Media2 service, parsed by ``parsers.parse_profiles`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="media2",
            operation="GetProfiles",
            body_inner=envelopes.media2_get_profiles(types=types),
        )
        return parsers.parse_profiles(xml)

    def media2_add_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]], name: str = ""
    ) -> None:
        """Send the ONVIF ``AddConfiguration`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="AddConfiguration",
            body_inner=envelopes.media2_add_configuration(
                profile_token=profile_token, configurations=configurations, name=name
            ),
        )

    def media2_remove_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]]
    ) -> None:
        """Send the ONVIF ``RemoveConfiguration`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="RemoveConfiguration",
            body_inner=envelopes.media2_remove_configuration(
                profile_token=profile_token, configurations=configurations
            ),
        )

    def media2_set_synchronization_point(self, *, profile_token: str) -> None:
        """Send the ONVIF ``SetSynchronizationPoint`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="SetSynchronizationPoint",
            body_inner=envelopes.media2_set_synchronization_point(profile_token=profile_token),
        )

    def get_profile(self, *, profile_token: str) -> dict[str, Any]:
        """Return a single media profile by token (legacy Media service).

        Media2 has no single-profile operation, so this requires the Media1 service.
        """
        self._require_media1("GetProfile")
        xml = self.call(
            service="media",
            operation="GetProfile",
            body_inner=envelopes.media_get_profile(profile_token=profile_token),
        )
        profiles = parsers.parse_profiles(xml)
        return profiles[0] if profiles else {}

    def get_video_source_configurations(self) -> list[dict[str, Any]]:
        """Return the device's video source configurations (crop bounds, rotation, source).

        These carry the ``configuration_token`` that :meth:`add_video_source_configuration`
        needs — without this operation there is no way to discover one.
        """
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetVideoSourceConfigurations",
            body_inner=envelopes.media_get_video_source_configurations(use_media2=use_media2),
        )
        return parsers.parse_video_source_configurations(xml)

    def get_video_source_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the bounds ranges, source tokens and rotation modes a video source accepts."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetVideoSourceConfigurationOptions",
            body_inner=envelopes.media_get_video_source_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_video_source_configuration_options(xml)

    def set_video_source_configuration(
        self,
        *,
        token: str,
        name: str,
        source_token: str,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
        use_count: int | None = None,
        rotate: str = "",
        force_persistence: bool = True,
        rotate_degree: int | None = None,
    ) -> None:
        """Set a video source configuration's crop bounds and optional rotation.

        Without ``width``/``height`` the current bounds are read back from the device and
        kept (writing ``0x0`` would crop the picture away); with them, an unset ``x``/``y``
        is 0. ``rotate`` is ``OFF``, ``ON`` or ``AUTO`` and ``rotate_degree`` the angle for
        ``ON``; see :meth:`set_video_source_rotation` to change only the rotation.
        """
        service, use_media2 = self._media_service()
        if width is None or height is None:
            current = next(
                (c for c in self.get_video_source_configurations() if c.get("token") == token),
                {},
            )
            bounds = current.get("bounds") or {}
            x = bounds.get("x") or 0 if x is None else x
            y = bounds.get("y") or 0 if y is None else y
            width = bounds.get("width") or 0 if width is None else width
            height = bounds.get("height") or 0 if height is None else height
        self.call(
            service=service,
            operation="SetVideoSourceConfiguration",
            body_inner=envelopes.media_set_video_source_configuration(
                token=token,
                name=name,
                source_token=source_token,
                x=int(x or 0),
                y=int(y or 0),
                width=int(width or 0),
                height=int(height or 0),
                use_media2=use_media2,
                use_count=use_count,
                rotate=rotate,
                rotate_degree=rotate_degree,
                force_persistence=force_persistence,
            ),
        )

    def set_video_source_rotation(
        self, *, configuration_token: str, mode: str, degree: int | None = None
    ) -> None:
        """Rotate the picture of a video source configuration, keeping everything else.

        ``mode`` is ``OFF``, ``ON`` or ``AUTO``; ``degree`` the angle for ``ON``. Check
        :meth:`get_video_source_configuration_options` first: ``rotate_degrees`` lists the
        angles the device accepts, and ``rotate_reboot`` warns that it reboots to apply one.
        """
        current = next(
            (
                c
                for c in self.get_video_source_configurations()
                if c.get("token") == configuration_token
            ),
            None,
        )
        if current is None:
            raise OnvifCapabilityMissingError(
                f"The device has no video source configuration '{configuration_token}'."
            )
        bounds = current.get("bounds") or {}
        self.set_video_source_configuration(
            token=configuration_token,
            name=str(current.get("name") or configuration_token),
            source_token=str(current.get("source_token") or ""),
            x=int(bounds.get("x") or 0),
            y=int(bounds.get("y") or 0),
            width=int(bounds.get("width") or 0),
            height=int(bounds.get("height") or 0),
            use_count=current.get("use_count"),
            rotate=mode,
            rotate_degree=degree,
        )

    def get_compatible_video_encoder_configurations(
        self, *, profile_token: str
    ) -> list[dict[str, Any]]:
        """Return the encoder configurations that may legally be added to a profile."""
        self._require_media1("GetCompatibleVideoEncoderConfigurations")
        xml = self.call(
            service="media",
            operation="GetCompatibleVideoEncoderConfigurations",
            body_inner=envelopes.media_get_compatible_video_encoder_configurations(
                profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_configurations(xml)

    def get_audio_encoder_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> list[dict[str, Any]]:
        """Return the encodings, bitrates and sample rates the audio encoder accepts."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioEncoderConfigurationOptions",
            body_inner=envelopes.media_get_audio_encoder_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_encoder_configuration_options(xml)

    def get_guaranteed_number_of_video_encoder_instances(
        self, *, configuration_token: str
    ) -> dict[str, int | None]:
        """Return how many simultaneous encoder instances a video source can guarantee."""
        self._require_media1("GetGuaranteedNumberOfVideoEncoderInstances")
        xml = self.call(
            service="media",
            operation="GetGuaranteedNumberOfVideoEncoderInstances",
            body_inner=envelopes.media_get_guaranteed_number_of_video_encoder_instances(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_encoder_instances(xml)

    def media2_get_masks(self, *, configuration_token: str = "") -> list[dict[str, Any]]:
        """Return the Media2 privacy masks, optionally scoped to one configuration."""
        xml = self.call(
            service="media2",
            operation="GetMasks",
            body_inner=envelopes.media2_get_masks(configuration_token=configuration_token),
        )
        return parsers.parse_masks(xml)

    def media2_delete_mask(self, *, token: str) -> None:
        """Delete a Media2 privacy mask by token."""
        self.call(
            service="media2",
            operation="DeleteMask",
            body_inner=envelopes.media2_delete_mask(token=token),
        )

    def get_audio_source_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio source configurations.

        These carry the ``configuration_token`` that
        :meth:`add_audio_source_configuration` needs — the audio-side counterpart of
        :meth:`get_video_source_configurations`.
        """
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioSourceConfigurations",
            body_inner=envelopes.media_get_audio_source_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_source_configurations(xml)

    def get_audio_source_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the audio inputs a source configuration may be pointed at."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioSourceConfigurationOptions",
            body_inner=envelopes.media_get_audio_source_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_source_configuration_options(xml)

    def set_audio_source_configuration(
        self,
        *,
        token: str,
        name: str,
        source_token: str,
        use_count: int = 0,
        force_persistence: bool = True,
    ) -> None:
        """Point an audio source configuration at a different audio input."""
        service, use_media2 = self._media_service()
        self.call(
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

    def get_audio_output_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the outputs, send-primacy modes and level range an audio output accepts."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioOutputConfigurationOptions",
            body_inner=envelopes.media_get_audio_output_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_output_configuration_options(xml)

    def get_video_source_modes(self, *, video_source_token: str) -> list[dict[str, Any]]:
        """Return the sensor modes a video source supports (aspect ratio, max resolution).

        A mode fixes the ceiling the encoder may then be configured within, so a
        resolution the camera clearly supports but that never appears in
        :meth:`get_video_encoder_options_normalized` is usually gated behind another mode.
        """
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetVideoSourceModes",
            body_inner=envelopes.media_get_video_source_modes(
                video_source_token=video_source_token, use_media2=use_media2
            ),
        )
        return parsers.parse_video_source_modes(xml)

    def set_video_source_mode(self, *, video_source_token: str, mode_token: str) -> bool:
        """Switch a video source to another sensor mode; returns whether it will reboot.

        A ``True`` return means the device is restarting to apply the mode, and every
        other operation will fail until it comes back.
        """
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="SetVideoSourceMode",
            body_inner=envelopes.media_set_video_source_mode(
                video_source_token=video_source_token,
                mode_token=mode_token,
                use_media2=use_media2,
            ),
        )
        return parsers.parse_text_element(xml, "Reboot").strip().lower() in ("true", "1")

    def get_audio_decoder_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio *decoder* configurations — the backchannel side.

        A decoder configuration added to a profile is what lets you send audio *to* the
        device (intercom, doorbell talk-down). Pair it with
        :meth:`get_audio_decoder_configuration_options` to learn which codec to encode in.
        """
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioDecoderConfigurations",
            body_inner=envelopes.media_get_audio_decoder_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_decoder_configurations(xml)

    def get_audio_decoder_configuration(self, *, configuration_token: str) -> dict[str, Any]:
        """Return a single audio decoder configuration by token (legacy Media service)."""
        self._require_media1("GetAudioDecoderConfiguration")
        xml = self.call(
            service="media",
            operation="GetAudioDecoderConfiguration",
            body_inner=envelopes.media_get_audio_decoder_configuration(
                configuration_token=configuration_token
            ),
        )
        configurations = parsers.parse_audio_decoder_configurations(xml)
        return configurations[0] if configurations else {}

    def get_audio_decoder_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the codecs, bitrates and sample rates the backchannel will accept."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioDecoderConfigurationOptions",
            body_inner=envelopes.media_get_audio_decoder_configuration_options(
                use_media2=use_media2,
                configuration_token=configuration_token,
                profile_token=profile_token,
            ),
        )
        return parsers.parse_audio_decoder_configuration_options(xml)

    def set_audio_decoder_configuration(
        self, *, token: str, name: str, use_count: int = 0, force_persistence: bool = True
    ) -> None:
        """Rename an audio decoder configuration and persist it across reboots."""
        service, use_media2 = self._media_service()
        self.call(
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

    def add_audio_decoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Wire an audio decoder into a profile, enabling the RTSP backchannel on it."""
        self._require_media1("AddAudioDecoderConfiguration")
        self.call(
            service="media",
            operation="AddAudioDecoderConfiguration",
            body_inner=envelopes.media_add_audio_decoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_audio_decoder_configuration(self, *, profile_token: str) -> None:
        """Remove the audio decoder configuration from a profile."""
        self._require_media1("RemoveAudioDecoderConfiguration")
        self.call(
            service="media",
            operation="RemoveAudioDecoderConfiguration",
            body_inner=envelopes.media_remove_audio_decoder_configuration(
                profile_token=profile_token
            ),
        )

    def add_video_analytics_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Attach a video analytics configuration to a profile.

        The Analytics service edits rules and modules on a configuration the camera
        already has; this is what puts a configuration on a profile in the first place,
        so its events and metadata start flowing.
        """
        self._require_media1("AddVideoAnalyticsConfiguration")
        self.call(
            service="media",
            operation="AddVideoAnalyticsConfiguration",
            body_inner=envelopes.media_add_video_analytics_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_video_analytics_configuration(self, *, profile_token: str) -> None:
        """Detach the video analytics configuration from a profile."""
        self._require_media1("RemoveVideoAnalyticsConfiguration")
        self.call(
            service="media",
            operation="RemoveVideoAnalyticsConfiguration",
            body_inner=envelopes.media_remove_video_analytics_configuration(
                profile_token=profile_token
            ),
        )

    def set_video_analytics_configuration(
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
        self._require_media1("SetVideoAnalyticsConfiguration")
        self.call(
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
