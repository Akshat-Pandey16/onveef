"""Recording, Replay and Search (Profile G) operations for the asyncio ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import envelopes, parsers, urls
from onveef.atransport import AsyncTransport


class RecordingOperations(AsyncTransport):
    """Recording, Replay and Search (Profile G) operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def get_recordings(self) -> list[dict[str, Any]]:
        """Return the device's recordings (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetRecordings",
            body_inner=envelopes.recording_get_recordings(),
        )
        return parsers.parse_recordings(xml)

    async def create_recording(
        self,
        *,
        source_id: str,
        source_name: str,
        source_location: str = "",
        source_description: str = "",
        source_address: str = "",
        content: str = "",
        max_retention: str = "PT0S",
    ) -> str:
        """Create a recording and return its token (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="CreateRecording",
            body_inner=envelopes.recording_create_recording(
                source_id=source_id,
                source_name=source_name,
                source_location=source_location,
                source_description=source_description,
                source_address=source_address,
                content=content,
                max_retention=max_retention,
            ),
        )
        return parsers.parse_created_token(xml, tag="RecordingToken")

    async def delete_recording(self, *, recording_token: str) -> None:
        """Delete a recording (Profile G)."""
        await self.call(
            service="recording",
            operation="DeleteRecording",
            body_inner=envelopes.recording_delete_recording(recording_token=recording_token),
        )

    async def get_recording_configuration(self, *, recording_token: str) -> dict[str, Any]:
        """Return a recording's configuration (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetRecordingConfiguration",
            body_inner=envelopes.recording_get_recording_configuration(
                recording_token=recording_token
            ),
        )
        return parsers.parse_recording_configuration(xml)

    async def set_recording_configuration(
        self,
        *,
        recording_token: str,
        source_id: str,
        source_name: str,
        source_location: str = "",
        source_description: str = "",
        source_address: str = "",
        content: str = "",
        max_retention: str = "PT0S",
    ) -> None:
        """Set a recording's configuration (Profile G)."""
        await self.call(
            service="recording",
            operation="SetRecordingConfiguration",
            body_inner=envelopes.recording_set_recording_configuration(
                recording_token=recording_token,
                source_id=source_id,
                source_name=source_name,
                source_location=source_location,
                source_description=source_description,
                source_address=source_address,
                content=content,
                max_retention=max_retention,
            ),
        )

    async def get_recording_jobs(self) -> list[dict[str, Any]]:
        """Return the device's recording jobs (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetRecordingJobs",
            body_inner=envelopes.recording_get_recording_jobs(),
        )
        return parsers.parse_recording_jobs(xml)

    async def create_recording_job(
        self,
        *,
        recording_token: str,
        mode: str = "Active",
        priority: int = 10,
        source_token: str = "",
        source_type: str = "",
    ) -> str:
        """Create a recording job and return its token (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="CreateRecordingJob",
            body_inner=envelopes.recording_create_recording_job(
                recording_token=recording_token,
                mode=mode,
                priority=priority,
                source_token=source_token,
                source_type=source_type,
            ),
        )
        return parsers.parse_created_token(xml, tag="JobToken")

    async def delete_recording_job(self, *, job_token: str) -> None:
        """Delete a recording job (Profile G)."""
        await self.call(
            service="recording",
            operation="DeleteRecordingJob",
            body_inner=envelopes.recording_delete_recording_job(job_token=job_token),
        )

    async def set_recording_job_mode(self, *, job_token: str, mode: str) -> None:
        """Set a recording job's mode (Profile G)."""
        await self.call(
            service="recording",
            operation="SetRecordingJobMode",
            body_inner=envelopes.recording_set_recording_job_mode(job_token=job_token, mode=mode),
        )

    async def get_recording_summary(self) -> dict[str, Any]:
        """Return the recording search summary (Profile G)."""
        xml = await self.call(
            service="search",
            operation="GetRecordingSummary",
            body_inner=envelopes.search_get_recording_summary(),
        )
        return parsers.parse_recording_summary(xml)

    async def find_recordings(
        self,
        *,
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Start a recording search and return its search token (Profile G)."""
        xml = await self.call(
            service="search",
            operation="FindRecordings",
            body_inner=envelopes.search_find_recordings(
                included_sources=included_sources,
                included_recordings=included_recordings,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    async def get_recording_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for a recording search (Profile G)."""
        xml = await self.call(
            service="search",
            operation="GetRecordingSearchResults",
            body_inner=envelopes.search_get_recording_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_recording_search_results(xml)

    async def find_events(
        self,
        *,
        start_point: str,
        end_point: str = "",
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        filter_expression: str = "",
        include_start_state: bool = False,
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Start an event search and return its search token (Profile G)."""
        xml = await self.call(
            service="search",
            operation="FindEvents",
            body_inner=envelopes.search_find_events(
                start_point=start_point,
                end_point=end_point,
                included_sources=included_sources,
                included_recordings=included_recordings,
                filter_expression=filter_expression,
                include_start_state=include_start_state,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    async def get_event_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for an event search (Profile G)."""
        xml = await self.call(
            service="search",
            operation="GetEventSearchResults",
            body_inner=envelopes.search_get_event_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_event_search_results(xml)

    async def find_ptz_position(
        self,
        *,
        start_point: str,
        end_point: str = "",
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        filter_expression: str = "",
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Start a PTZ-position search and return its search token (Profile G)."""
        xml = await self.call(
            service="search",
            operation="FindPTZPosition",
            body_inner=envelopes.search_find_ptz_position(
                start_point=start_point,
                end_point=end_point,
                included_sources=included_sources,
                included_recordings=included_recordings,
                filter_expression=filter_expression,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    async def get_ptz_position_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for a PTZ-position search (Profile G)."""
        xml = await self.call(
            service="search",
            operation="GetPTZPositionSearchResults",
            body_inner=envelopes.search_get_ptz_position_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_ptz_position_search_results(xml)

    async def find_metadata(
        self,
        *,
        start_point: str,
        end_point: str = "",
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        filter_expression: str = "",
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Start a metadata search and return its search token (Profile G)."""
        xml = await self.call(
            service="search",
            operation="FindMetadata",
            body_inner=envelopes.search_find_metadata(
                start_point=start_point,
                end_point=end_point,
                included_sources=included_sources,
                included_recordings=included_recordings,
                filter_expression=filter_expression,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    async def get_metadata_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for a metadata search (Profile G)."""
        xml = await self.call(
            service="search",
            operation="GetMetadataSearchResults",
            body_inner=envelopes.search_get_metadata_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_metadata_search_results(xml)

    async def end_search(self, *, search_token: str) -> None:
        """End an in-progress search (Profile G)."""
        await self.call(
            service="search",
            operation="EndSearch",
            body_inner=envelopes.search_end_search(search_token=search_token),
        )

    async def get_replay_uri(
        self,
        *,
        recording_token: str,
        stream: str = "RTP-Unicast",
        protocol: str = "RTSP",
        with_credentials: bool = False,
    ) -> str:
        """Return the replay (RTSP) URI for a recording (Profile G), host-rewritten."""
        xml = await self.call(
            service="replay",
            operation="GetReplayUri",
            body_inner=envelopes.replay_get_replay_uri(
                recording_token=recording_token, stream=stream, protocol=protocol
            ),
        )
        uri = self._fix_url(parsers.parse_stream_uri(xml))
        if with_credentials:
            return urls.with_credentials(
                uri, self._credentials.username, self._credentials.password
            )
        return uri

    async def get_replay_configuration(self) -> dict[str, Any]:
        """Return the replay service configuration (Profile G)."""
        xml = await self.call(
            service="replay",
            operation="GetReplayConfiguration",
            body_inner=envelopes.replay_get_replay_configuration(),
        )
        return parsers.parse_replay_configuration(xml)

    async def set_replay_configuration(self, *, session_timeout: str = "PT60S") -> None:
        """Set the replay service session timeout (Profile G)."""
        await self.call(
            service="replay",
            operation="SetReplayConfiguration",
            body_inner=envelopes.replay_set_replay_configuration(session_timeout=session_timeout),
        )

    async def get_recording_options(self, *, recording_token: str) -> dict[str, Any]:
        """Return the track and job capacity a recording still has available (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetRecordingOptions",
            body_inner=envelopes.recording_get_recording_options(recording_token=recording_token),
        )
        return parsers.parse_named_element(xml, "Options")

    async def get_track_configuration(
        self, *, recording_token: str, track_token: str
    ) -> dict[str, Any]:
        """Return a recording track's type and description (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetTrackConfiguration",
            body_inner=envelopes.recording_get_track_configuration(
                recording_token=recording_token, track_token=track_token
            ),
        )
        return parsers.parse_track_configuration(xml)

    async def set_track_configuration(
        self, *, recording_token: str, track_token: str, track_type: str, description: str = ""
    ) -> None:
        """Set a recording track's type and description (Profile G)."""
        await self.call(
            service="recording",
            operation="SetTrackConfiguration",
            body_inner=envelopes.recording_set_track_configuration(
                recording_token=recording_token,
                track_token=track_token,
                track_type=track_type,
                description=description,
            ),
        )

    async def create_track(
        self, *, recording_token: str, track_type: str, description: str = ""
    ) -> str:
        """Add a track to a recording and return its new token.

        ``track_type`` is ``Video``, ``Audio``, ``Metadata`` or ``Extended``. A recording
        needs one track per stream it is to hold; :meth:`get_recording_options` says how
        many more the device will allow.
        """
        xml = await self.call(
            service="recording",
            operation="CreateTrack",
            body_inner=envelopes.recording_create_track(
                recording_token=recording_token, track_type=track_type, description=description
            ),
        )
        return parsers.parse_created_token(xml, tag="TrackToken")

    async def delete_track(self, *, recording_token: str, track_token: str) -> None:
        """Delete a track from a recording, discarding the media it holds."""
        await self.call(
            service="recording",
            operation="DeleteTrack",
            body_inner=envelopes.recording_delete_track(
                recording_token=recording_token, track_token=track_token
            ),
        )

    async def get_recording_job_state(self, *, job_token: str) -> dict[str, Any]:
        """Return whether a recording job is actually recording, and per-source detail.

        A job can be ``Active`` in configuration yet idle in practice — a receiver that
        never connected, a source that went away. This is the operation that tells the
        two apart.
        """
        xml = await self.call(
            service="recording",
            operation="GetRecordingJobState",
            body_inner=envelopes.recording_get_recording_job_state(job_token=job_token),
        )
        return parsers.parse_recording_job_state(xml)

    async def get_search_state(self, *, search_token: str) -> str:
        """Return a search session's state (``Queued``, ``Searching``, ``Completed``…)."""
        xml = await self.call(
            service="search",
            operation="GetSearchState",
            body_inner=envelopes.search_get_search_state(search_token=search_token),
        )
        return parsers.parse_text_element(xml, "State")

    async def get_media_attributes(
        self,
        *,
        recording_tokens: list[str] | None = None,
        time: str = "",
        include_all: bool = False,
    ) -> list[dict[str, Any]]:
        """Return each recording's real time span and per-track codecs (Profile G).

        This is what a replay timeline is built from: without it you know a recording
        exists but not which range of it you may seek within, or what you get when you do.
        Pass ``include_all=True`` for every track rather than only those with data.
        """
        xml = await self.call(
            service="search",
            operation="GetMediaAttributes",
            body_inner=envelopes.search_get_media_attributes(
                recording_tokens=list(recording_tokens or []),
                time=time,
                include_all=include_all,
            ),
        )
        return parsers.parse_media_attributes(xml)
