# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versioning is
[SemVer](https://semver.org/) (0.x while the API stabilises).

## [0.6.0]

### Added
- **Push events are complete.** `parsers.parse_notification()` decodes the
  WS-BaseNotification `Notify` envelope a device POSTs to your consumer, returning the
  same message dicts `PullMessages` yields, and never raising on malformed input.
  `events_subscribe()` now parses its reply with the new `parsers.parse_subscribe()`
  (which also surfaces `reference_parameters`) and host-rewrites the returned
  subscription-manager URL like every other device-reported address. The README carries a
  twenty-line ASGI consumer. Previously the coverage table claimed "pull-point and push"
  while the push half stopped at the `Subscribe` request.
- **Audio source and output configurations**, closing on the audio side the gap 0.5.0
  closed for video — you could add an audio source configuration to a profile but had no
  way to discover its token: `get_audio_source_configurations`,
  `get_audio_source_configuration_options`, `set_audio_source_configuration` and
  `get_audio_output_configuration_options`.
- **Audio backchannel (Profile T two-way audio)**: `get_audio_decoder_configurations`,
  `get_audio_decoder_configuration`, `get_audio_decoder_configuration_options`,
  `set_audio_decoder_configuration`, `add_audio_decoder_configuration` and
  `remove_audio_decoder_configuration`. Intercoms, doorbells and talk-down were previously
  unreachable.
- **Video source modes**: `get_video_source_modes` / `set_video_source_mode`. Cameras gate
  encoder resolutions behind the active sensor mode, so resolutions a camera clearly
  supports could not be reached — or even seen — at all.
- **Profile G completion**: `create_track`, `delete_track`, `get_track_configuration`,
  `set_track_configuration`, `get_recording_job_state` (configured vs actually recording),
  `get_search_state`, and `get_media_attributes` — the operation that reports a
  recording's real time span and per-track codecs, without which a replay timeline is
  guesswork.
- **PTZ preset tours are writable**: `ptz_create_preset_tour`, `ptz_modify_preset_tour`
  (name, start condition, tour spots), `ptz_remove_preset_tour`,
  `ptz_get_preset_tour_options`, plus the single-tour `ptz_get_preset_tour` whose builder
  had shipped with no client method. Tours could previously only be run, not configured.
- **`ptz_geo_move`** (Profile T geo-positioning), the PTZ counterpart to the
  `get_geo_location`/`set_geo_location` already present on the device side.
- **Analytics configurations can be attached to profiles**:
  `add_video_analytics_configuration`, `remove_video_analytics_configuration` and
  `set_video_analytics_configuration`. Rule and module CRUD only ever edited a
  configuration the camera already had wired up.
- **Profile A write operations**: `create_credential`/`modify_credential`/`get_credentials`;
  schedules (`get_schedule_info_list`, `get_schedules`, `get_schedule_state`,
  `create_schedule`, `modify_schedule`, `delete_schedule`) and special-day groups; access
  profiles (`get_access_profile_info_list`, `get_access_profiles`, `create_access_profile`,
  `modify_access_profile`, `delete_access_profile`); plus `get_access_points` and
  `get_doors`. The Schedule and Access Rules services are now resolved and routed to.

### Fixed
- **`GetSupportedAnalyticsModules` and `GetSupportedRules` always returned `[]`.** Both
  were parsed with the *configured*-item parsers, which look for `AnalyticsModule` and
  `Rule`; the responses carry `AnalyticsModuleDescription` and `RuleDescription`. There was
  no error — the result read as "this camera supports no analytics". New
  `parse_supported_analytics_modules` / `parse_supported_rules` return each type's name,
  `fixed`/`max_instances`, its parameters as name-to-XSD-type, and the messages it emits.
- **`imaging_move` sent focus values devices reject.** Position, distance and speed were
  emitted as `x=` attributes, carried over from the PTZ vector helper; ONVIF's
  `AbsoluteFocus`/`RelativeFocus`/`ContinuousFocus` take `xs:float` **child elements**.
  PTZ vectors, which genuinely are attributes, are unchanged.
- `ptz_get_configuration_options`, `imaging_get_move_options` and `get_zero_configuration`
  returned shapes that depended on how many children the device sent — one option came back
  as a string, two as a list. Each now has a dedicated parser with a stable shape (the full
  tree is still available under `raw`).

### Changed
- **The client is split by service.** `OnvifClient` is now composed from a transport core
  (`onveef.transport`) plus one mixin per ONVIF service (`onveef.ops.device`,
  `onveef.ops.media`, `onveef.ops.ptz`, `onveef.ops.imaging`, `onveef.ops.events`,
  `onveef.ops.analytics`, `onveef.ops.recording`, `onveef.ops.accesscontrol`), with
  `onveef.atransport` / `onveef.aops` mirroring them for asyncio. Two 3300-line modules
  became navigable files of a few hundred lines each. **Every public import path is
  unchanged** — `from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint`
  and `from onveef import ...` work exactly as before.
- `parse_preset_tours` now also returns each tour's `starting_condition` and `tour_spots`.
- Package metadata: `Development Status :: 4 - Beta` (was Alpha), broader keywords, and a
  description that names what the library is.
- The README no longer describes the project name as a placeholder; `onveef` is the name.

### Testing
- A test now fails the build if any builder or parser in `envelopes`, `parsers` or `pacs`
  has no caller — the check that would have caught `ptz_get_preset_tour` shipping
  unreachable.
- 774 tests at 84% coverage.

## [0.5.0]

### Added
- **Command-line interface** (`onveef` / `python -m onveef`): `discover`, `info`,
  `services`, `capabilities`, `profiles`, `stream-uri`, `snapshot`, `ptz`, `events`, `raw`
  and `dump`. `--json` on any command; `dump` captures a device's raw responses as test
  fixtures in one shot.
- **Host rewriting** (`onveef.urls`, `rewrite_host=True` by default). Every address a device
  reports about itself — service XAddrs, pull-point subscription references, stream,
  snapshot and replay URIs — is re-pointed at the host you actually connected to. Devices
  behind NAT, a port forward, a Docker bridge, or with a stale DHCP lease now work instead
  of failing every call after discovery. HTTP(S) endpoints take the connected scheme, host
  and port; RTSP keeps its own port and only has the host corrected.
- **Credential injection** for media URIs: `get_stream_uri(with_credentials=True)`,
  `get_snapshot_uri(...)`, `get_replay_uri(...)` and `onveef.urls.with_credentials()`
  percent-encode the username and password correctly, including passwords containing
  `@`, `:` or `/`.
- **Managed pull-point subscriptions**: `client.pull_point(...)` returns a context manager
  that renews at half the termination interval, re-creates the subscription when the device
  has forgotten it, iterates notifications, and unsubscribes on exit. `async with` /
  `async for` on the async client.
- **Transport injection**: `transport=`, `proxy=` and `http_client=` on both clients, so
  downstream projects can drive the full request path with `httpx.MockTransport` or share a
  connection pool. `verify_tls` now also accepts a CA-bundle path or an `ssl.SSLContext`.
- **New operations** (sync and async): `get_profile`, `get_video_source_configurations`,
  `get_video_source_configuration_options`, `set_video_source_configuration` (crop bounds
  and rotation), `get_compatible_video_encoder_configurations`,
  `get_audio_encoder_configuration_options`,
  `get_guaranteed_number_of_video_encoder_instances`,
  `get_video_encoder_options_normalized`, `media2_get_masks`, `media2_delete_mask`,
  `get_endpoint_reference`, `get_storage_configurations`, `imaging_get_move_options`,
  `get_recording_options`, `start_firmware_upgrade`, `start_system_restore`. Together these
  close the gap where you could add a configuration to a profile but had no way to discover
  its token.
- **WS-Discovery hardening**: probes every local interface by default (a single `0.0.0.0`
  bind finds nothing on a multi-homed host), retransmits 3 probes across the listening
  window because UDP multicast is lossy, tolerates a mid-sweep receive error instead of
  truncating, and adds `probe_device()` for unicast, `ipv6=True`, and
  `local_ipv4_addresses()`.
- `__repr__` on both clients (password never shown) and `local_address()`.

### Changed
- **`password_text_fallback` now defaults to `False`.** It retried a digest `401` with a
  plaintext password, which on `http://` puts the credential on the wire in the clear.
  Devices that genuinely need it must opt in per client.
- `DEFAULT_USER_AGENT` is derived from the installed package version instead of a hardcoded
  string that drifted every release.
- `create_osd` / `set_osd` have real typed signatures instead of untyped `**kwargs`.
- `parse_profiles` also accepts a single-profile `GetProfile` response.

### Fixed
- **Per-request read timeouts.** `PullMessages` stored its extended read timeout on the
  client for the duration of a long poll. Any call issued concurrently — the normal case for
  `AsyncOnvifClient` — inherited that timeout *and* silently lost its retries. The timeout is
  now a per-request parameter and cannot leak between callers.
- **Lazy discovery is now locked.** `_discover_once` set its "done" flag before performing
  discovery, so a second concurrent thread or task skipped it and got
  `OnvifCapabilityMissingError` for a service the device does advertise. Guarded by a
  `threading.RLock` (sync) and an `asyncio.Lock` (async); clock-skew sync is likewise locked
  in the sync client.
- `breaker.configure()` now affects circuit breakers created afterwards. It rebound module
  globals that were only ever read as `__init__` default arguments, bound at definition
  time, so it silently did nothing except to the process-wide default instance.
- `parse_event_properties` finds topics marked only by the WS-Topics `topic="true"`
  attribute; trimmed firmware that omits `MessageDescription` previously reported no topics.
- Six envelope builders had no client method and were unreachable — including Media2
  privacy masks, which the coverage table advertised. All are now wired up, and a test
  fails the build if any builder or parser becomes orphaned again.

### Removed
- `envelopes.events_get_service_capabilities()`, which duplicated
  `get_service_capabilities("events")`.

## [0.4.1]

### Changed
- Set the package author email in project metadata (now shown on PyPI).
- CI: bumped GitHub Actions to their latest majors (`checkout`, `setup-uv`,
  `upload-artifact`, `download-artifact`).

## [0.4.0]

### Added
- **Simple connection API**: `OnvifClient("192.168.1.64", 80, "admin", "secret")` (and the
  same for `AsyncOnvifClient`) — host/port/user/password with **lazy auto-discovery** of the
  per-service endpoints on first use. The explicit `endpoint=`/`credentials=` form still works.
  New `connect()`, `get_snapshot()`, `for_host()` helpers.
- **Full async parity**: `AsyncOnvifClient` now mirrors every `OnvifClient` operation (~180
  methods) including the complete event pull-point lifecycle (pull/renew/unsubscribe/sync-point).
- **HTTP Digest/Basic auth** on the SOAP endpoint (`http_auth=`), for devices that require it
  alongside WS-Security.
- **Resilience**: bounded retries with backoff for idempotent operations, split
  connect/read/write timeouts (long-poll `PullMessages` extends its own read timeout), a
  per-client circuit breaker with a half-open probe, `OnvifTimeoutError`, and a `retryable`
  flag on transport errors.
- **Typed models** for PTZ presets, recordings, pull-point messages, and imaging settings.
- Docstrings on every public method; `py.typed` marker now ships; module `onveef` logger.

### Fixed
- Analytics service is now discovered (`parse_services` matched the wrong `ver10` namespace
  instead of the real `ver20/analytics`).
- Media2 `GetProfiles` now parses encoders/sources/PTZ/metadata (was Media1-only, silently
  dropping every config); Media2 `SetVideoEncoderConfiguration` now emits Encoding/GovLength/
  Profile and rate limits as **attributes** per the Media2 schema.
- SOAP 1.1 faults are parsed (were reported as a generic "SOAP Fault"); pull-point
  `CurrentTime`/`TerminationTime` are extracted; event topics keep their `tns1:` prefix.
- Clock-skew resync no longer disables itself permanently on a transient failure; a `3xx`
  redirect and a SOAP fault delivered on HTTP `400` are handled correctly.
- WS-Security password is hidden from `OnvifCredentials` repr; snapshot fetch verifies TLS by
  default; WS-Addressing requests include `MessageID`/`ReplyTo`.

## [0.3.0]

### Added
- **Async transport** (`AsyncOnvifClient`, `onveef.aclient`): full async auth/transport
  core on `httpx.AsyncClient` (clock-skew resync, password-text fallback, breaker,
  streamed size cap), a generic `await call(...)` escape hatch, and typed async helpers
  for common operations. Async WS-Discovery via `wsdiscovery.discover_async()`.
- **Typed response models** (`onveef.models`): dataclasses with `from_dict()` for
  `DeviceInformation`, `Profile`/`VideoEncoder`, `PTZStatus`, `SystemDateTime`,
  `NetworkInterface` — real typed access, not just signature hints.
- **Device/Imaging/PTZ extras**: `GetSystemUris`, `GetGeoLocation`/`SetGeoLocation`,
  `GetWsdlUrl`, `GetZeroConfiguration`; imaging presets (get/current/set); PTZ
  `GetCompatibleConfigurations`, `GetConfigurationOptions`, preset tours
  (`GetPresetTours`, `OperatePresetTour`).
- **Recorded-fixture vendor test harness** (`tests/fixtures/` + `test_fixtures.py`)
  with seed Hikvision/Dahua/Axis/Reolink captures and a capture guide + coverage matrix.

### Fixed
- `parse_profiles` now extracts GOP and profile from **H265** encoders (not only H264)
  — caught by the Dahua H265 fixture.

## [0.2.0]

### Added
- **WS-Discovery** module (`onveef.wsdiscovery`): multicast `Probe`, `ProbeMatch`
  parsing, and a `discover()` helper returning `DiscoveredDevice` objects.
- **Physical Access Control** domain (`onveef.pacs`, Profile A/C): access points,
  areas, doors (access/lock/unlock/double-lock/block/lockdown/lock-open),
  credentials (list/state/enable/disable/delete), with paged list support.
- **Media2 completion**: `CreateProfile`, `DeleteProfile`, `GetProfiles(type)`,
  `AddConfiguration`, `RemoveConfiguration`, `SetSynchronizationPoint`, masks.
- **Events push**: WS-BaseNotification `Subscribe`, plus `SetSynchronizationPoint`
  and a topic `Filter` on pull-point subscriptions.
- **WS-Security options**: `PasswordText` mode, optional `<wsu:Timestamp>`, and
  transparent digest→text fallback on `401`.
- Per-service `GetServiceCapabilities`, `GetStreamUri` transport/protocol options,
  DeviceIO `GetRelayOutputOptions`/`GetSerialPorts`, and IPv6 network parsing.

### Changed
- `verify_tls` now defaults to **`True`** (secure by default). Pass
  `verify_tls=False` for cameras with self-signed certificates.

## [0.1.0]

### Added
- Initial extraction of the synchronous ONVIF engine: `OnvifClient`,
  `envelopes`, `parsers`, plain-exception hierarchy, and an in-memory circuit
  breaker. Depends only on `httpx` + `defusedxml`.
