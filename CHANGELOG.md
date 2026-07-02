# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versioning is
[SemVer](https://semver.org/) (0.x while the API stabilises).

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
