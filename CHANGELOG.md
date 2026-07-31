# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versioning is
[SemVer](https://semver.org/) (0.x while the API stabilises).

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
