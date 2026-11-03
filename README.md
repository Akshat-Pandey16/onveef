# onveef — a fast, zeep-free ONVIF client for Python

**onveef** is a Python ONVIF library for IP cameras, NVRs and video management systems.
No runtime WSDL parsing, near-instant import, a sans-IO core, and only two runtime
dependencies (`httpx` + `defusedxml`). It talks to ONVIF **Profile S / T / G / M / A / C**
devices — device management, media & media2, PTZ, imaging, events, analytics, recording,
replay, search, DeviceIO, physical access control, and WS-Discovery — synchronously or on
asyncio, with a CLI for everything.

> This is a client library **compatible with** ONVIF devices. It is **not** ONVIF-certified
> and is not affiliated with or endorsed by the ONVIF trademark holder.

[![PyPI](https://img.shields.io/pypi/v/onveef.svg)](https://pypi.org/project/onveef/)
[![Python](https://img.shields.io/pypi/pyversions/onveef.svg)](https://pypi.org/project/onveef/)
[![License](https://img.shields.io/pypi/l/onveef.svg)](LICENSE)

---

## Why another ONVIF library?

Every mainstream Python ONVIF library is built on [`zeep`](https://pypi.org/project/zeep/),
which downloads and parses the ONVIF WSDL/XSD **at runtime**: slow import, heavy
memory, and a long tail of camera-compatibility bugs (unparsed `GetCapabilities`
extensions, mangled `PullMessages`, `xsd:any` breakage). `onveef` hand-builds SOAP
envelopes and parses responses with the standard library, so it:

- **imports instantly** — no WSDL to load, no `lxml`/`zeep` startup cost;
- **avoids zeep's ONVIF quirks** entirely;
- is **sans-IO at the core** — request builders (`onveef.envelopes`) and response
  parsers (`onveef.parsers`) are pure functions over strings/XML, so behaviour is
  verifiable from recorded fixtures without hardware;
- parses XML with **`defusedxml`** (XXE-safe) and escapes every value it emits.

Runtime dependencies: **`httpx`** and **`defusedxml`**. That's it.

---

## Install

```bash
pip install onveef
```

Requires **Python 3.10+**.

---

## Quickstart

Just pass the camera's IP, port, and credentials — the per-service endpoints are
discovered automatically on first use (no manual `discover_services()` dance):

```python
from onveef import OnvifClient

with OnvifClient("192.168.1.64", 80, "admin", "secret", verify_tls=False) as cam:
    print(cam.get_device_information())
    for profile in cam.get_profiles():
        token = profile["token"]
        print(token, cam.get_stream_uri(profile_token=token))
        print("snapshot:", cam.get_snapshot_uri(profile_token=token))
        image, content_type = cam.get_snapshot(profile_token=token)
```

### Command line

Every device operation is reachable without writing code:

```bash
onveef discover                                    # WS-Discovery sweep of every interface
onveef locate 192.168.1.64                         # find the ONVIF URL when WS-Discovery is off
onveef info 192.168.1.64 -u admin -p secret        # manufacturer / model / firmware
onveef profiles 192.168.1.64 -u admin -p secret --json
onveef stream-uri 192.168.1.64 -u admin -p secret --with-credentials
onveef snapshot 192.168.1.64 -u admin -p secret -o frame.jpg
onveef events 192.168.1.64 -u admin -p secret --topic 'tns1:RuleEngine//.' --count 5
onveef raw 192.168.1.64 --operation GetHostname --builder device_get_hostname
onveef dump 192.168.1.64 -u admin -p secret -d fixtures/mycam   # capture scrubbed test fixtures
```

`python -m onveef` works too. Add `--json` to any command for machine-readable output.

### Addresses the device reports are repaired

Cameras habitually advertise their *own* idea of their address — an internal DHCP lease,
`0.0.0.0`, or `http://` when you connected over HTTPS. Behind NAT, a port forward, or a
Docker bridge that address is unreachable, and every call after discovery fails.

`onveef` re-points every device-reported address (service XAddrs, subscription references,
stream and snapshot URIs) at the host you actually connected to:

```python
cam = OnvifClient("203.0.113.9:8000", username="admin", password="secret")
cam.get_stream_uri(profile_token=token)
# device said  rtsp://192.168.1.64:554/Streaming/101
# you get      rtsp://203.0.113.9:554/Streaming/101
```

HTTP(S) endpoints take the scheme, host *and* port you connected on; RTSP keeps its own
port and only has the host corrected. Pass `rewrite_host=False` to trust the device
verbatim, or use `onveef.urls` directly.

`GetStreamUri` never includes credentials, which is what ffmpeg, OpenCV, GStreamer and
go2rtc all want. Ask for them and they are percent-encoded correctly, even when the
password contains `@`, `:` or `/`:

```python
cam.get_stream_uri(profile_token=token, with_credentials=True)
# rtsp://admin:p%40ss@203.0.113.9:554/Streaming/101
```

`use_https=True` builds an `https://` device URL; a full
`http(s)://host/onvif/device_service` string is also accepted as the first
argument. For full manual control you can still pass a pre-built
`endpoint=OnvifEndpoint(...)` and `credentials=OnvifCredentials(...)` (in that
mode auto-discovery stays off and you manage the service map yourself).

### Async

`AsyncOnvifClient` has the **same constructor and full method parity** with the sync
client (same auth, clock-skew recovery, retries, circuit breaker, and lazy
auto-discovery):

```python
import asyncio
from onveef import AsyncOnvifClient

async def main() -> None:
    async with AsyncOnvifClient("192.168.1.64", 80, "admin", "secret", verify_tls=False) as cam:
        print(await cam.get_device_information())
        for p in await cam.get_profiles():
            print(await cam.get_stream_uri(profile_token=p["token"]))

asyncio.run(main())
```

`wsdiscovery.discover_async()` provides the same LAN discovery on an asyncio loop.

### Typed models (optional)

Parsers return plain dicts; `onveef.models` wraps the common ones in dataclasses
for real IDE autocomplete and `mypy` checking:

```python
from onveef import models

info = models.DeviceInformation.from_dict(client.get_device_information())
profile = models.Profile.from_dict(client.get_profiles()[0])
print(info.manufacturer, profile.video_encoder.encoding)
```

### Discover devices on the LAN (WS-Discovery)

```python
from onveef import wsdiscovery

for dev in wsdiscovery.discover(timeout_s=3.0):
    print(dev.name, dev.device_service, dev.hardware, dev.scopes)
```

By default this probes **every local interface** (a single `0.0.0.0` bind egresses one
kernel-chosen NIC, which finds nothing on a multi-homed host — and any machine running
Docker is multi-homed) and sends **three probes** spread across the listening window, since
UDP multicast is lossy and one dropped probe is indistinguishable from an empty network. A
receive error on one interface no longer truncates the sweep.

```python
wsdiscovery.discover(interface_ip="192.168.1.10")        # pin one NIC
wsdiscovery.discover(interface_ip=["10.0.0.2", "10.1.0.2"])
wsdiscovery.discover(probes=5, timeout_s=6.0)            # slow or noisy network
wsdiscovery.discover(ipv6=True)                          # also probe ff02::c
wsdiscovery.probe_device("192.168.1.64")                 # unicast, when multicast is filtered
wsdiscovery.local_ipv4_addresses()                       # what would be probed
```

`wsdiscovery.build_probe()` / `wsdiscovery.parse_probe_matches()` are exposed
separately so you can drive the multicast yourself or unit-test against captures.

Some cameras do not answer WS-Discovery at all, and their ONVIF port is anyone's guess
(8000 on Reolink, 2020 on Tapo, 8899 on many OEM boards). `find_device_service()` tries the
common ports and paths with an unauthenticated `GetSystemDateAndTime` — no credentials leave
your machine — and returns the URL that answered:

```python
url = wsdiscovery.find_device_service("192.168.1.64")   # or `onveef locate 192.168.1.64`
cam = OnvifClient(url, username="admin", password="secret")
```

### Changing settings without resetting the rest

ONVIF `Set*Configuration` operations replace a configuration as a whole: to change the bit
rate you must send the resolution, frame rate, GOP, profile, rate-control mode and multicast
setup back exactly as they were, or the camera resets them. The `update_*` helpers read the
configuration, overlay your change, check it against the camera's own options and write it
back — over Media2 when the camera has it, falling back to Media1 (except for H.265, which
Media1 cannot express):

```python
from onveef import OnvifValidationError

cam.update_video_encoder_configuration(configuration_token="VE0", bitrate_kbps=2048)
try:
    cam.update_video_encoder_configuration(configuration_token="VE0", frame_rate=27.5)
except OnvifValidationError as exc:
    print(exc.errors)   # {'frame_rate': ['27.5 fps is not offered; choose one of 1, 2, …, 25.']}

cam.get_video_encoder_options_merged(configuration_token="VE0")  # what the encoder accepts
```

Imaging works the same way. The schema makes each block's mode mandatory, so
`imaging_update_settings()` fills it in from the current settings — changing one exposure
limit no longer needs you to know the exposure mode:

```python
cam.imaging_update_settings(video_source_token="VS0", exposure_max_time=33333, brightness=55)
cam.imaging_get_options_normalized(video_source_token="VS0")   # ranges and modes on offer
```

The plain setters keep what they are not told, too: `set_video_encoder_configuration`,
`set_audio_encoder_configuration` and `set_metadata_configuration` read back the multicast
setup, session timeout and (for metadata) the event filter instead of resetting them, and
`set_video_source_rotation()` rotates the picture without touching its crop.
`change_password(new_password=...)` changes an account's password under its existing user
level — and, for the client's own account, keeps the client signed in.

### PTZ

```python
client.ptz_continuous_move(profile_token=token, pan=0.5, tilt=0.0, zoom=0.0)
client.ptz_stop(profile_token=token)
client.ptz_goto_preset(profile_token=token, preset_token="1")
```

Preset tours are fully writable — create the tour, then define it:

```python
tour = client.ptz_create_preset_tour(profile_token=token)
client.ptz_modify_preset_tour(
    profile_token=token,
    preset_tour_token=tour,
    name="Perimeter",
    auto_start=True,
    tour_spots=[
        {"preset_token": "1", "stay_time": "PT10S"},
        {"preset_token": "2", "stay_time": "PT10S"},
        {"home": True, "stay_time": "PT30S"},
    ],
)
client.ptz_operate_preset_tour(profile_token=token, preset_tour_token=tour, operation="Start")
```

On cameras that report a geo-location, `ptz_geo_move(profile_token=..., lat=..., lon=...)`
aims at a coordinate rather than a pan/tilt position.

Click-to-center moves the camera so that a point on the picture becomes its centre. Give the
point as fractions of the image (0..1 from the left and from the top); the camera moves in its
`TranslationSpaceFov`:

```python
caps = client.ptz_capabilities(profile_token=token)
if caps["click_to_center"]:
    client.ptz_center(profile_token=token, x=0.8, y=0.3, pan_tilt_space=caps["fov_space"])
```

`ptz_capabilities()` condenses the profile's PTZ node and lens into booleans and ranges —
continuous/relative/absolute axes, presets, preset tours, home, focus and iris control, speed
ranges — for gating a control panel. Every move also takes `pan_tilt_space=`/`zoom_space=`,
to address a node's other coordinate spaces (degrees, FOV) instead of the default.

### Events: pull-point *and* push

A pull-point expires unless it is renewed. `pull_point()` hands back a managed
subscription that renews at half the termination interval, re-creates itself if the device
forgets it, and unsubscribes on exit:

```python
with client.pull_point(topic_filter="tns1:RuleEngine//.") as sub:
    for message in sub:                      # blocks in the device's long poll
        print(message["topic"], message["data"])
```

```python
async with client.pull_point(topic_filter="tns1:RuleEngine//.") as sub:
    async for message in sub:
        print(message["topic"], message["data"])
```

For **push** delivery the device POSTs a WS-BaseNotification `Notify` envelope to a
consumer address you host. `events_subscribe()` sets it up and
`parsers.parse_notification()` decodes what arrives — the whole consumer is about twenty
lines of ASGI:

```python
from onveef import OnvifClient, parsers

async def consumer(scope, receive, send):
    """Mount at http://<your-host>:9000/onvif-events."""
    body = b""
    while True:
        event = await receive()
        body += event.get("body", b"")
        if not event.get("more_body"):
            break
    for message in parsers.parse_notification(body.decode("utf-8", "replace")):
        print(message["topic"], message["utc_time"], message["data"])
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/xml")]})
    await send({"type": "http.response.body", "body": b""})

cam = OnvifClient("192.168.1.64", 80, "admin", "secret")
sub = cam.events_subscribe(
    consumer_address="http://192.0.2.10:9000/onvif-events",
    topic_filter="tns1:RuleEngine//.",
    termination_time="PT60S",
)
# ...renew before termination_time, or the device drops the subscription:
cam.events_renew(subscription_url=sub["subscription_url"], termination_time="PT60S")
cam.events_unsubscribe(subscription_url=sub["subscription_url"])
```

Push messages come back in exactly the shape `pull_point` yields (`topic`, `utc_time`,
`property_operation`, `source`, `data`), so the same handler serves both. `parse_notification`
never raises on malformed input — a consumer is exposed to the network.

The unmanaged pull operations are still there if you want to drive that lifecycle yourself:

```python
sub = client.events_create_pull_point(topic_filter="tns1:RuleEngine//.")
msgs = client.events_pull_messages(subscription_url=sub["subscription_url"])
client.events_renew(subscription_url=sub["subscription_url"])
```

Devices often grant a shorter lifetime than the one asked for. `lifetime_s` in the create and
renew results is what was actually granted (measured on the device's own clock), and
`pull_point()` schedules from it: it renews at half the granted lifetime and keeps each long
poll within a third of it, so the subscription cannot lapse mid-poll.

### Two-way audio (backchannel)

Profile T's talk-down path needs a decoder configuration on the profile. Discover what the
camera accepts, then wire it up:

```python
options = client.get_audio_decoder_configuration_options()   # {'g711': {...}, 'aac': {...}}
decoder = client.get_audio_decoder_configurations()[0]
client.add_audio_decoder_configuration(profile_token=token, configuration_token=decoder["token"])
```

The audio itself then travels over RTSP; ONVIF's job is only to enable the path.

### Recording and replay (Profile G)

```python
recording = client.create_recording(source_id="cam1", source_name="Front door")
track = client.create_track(recording_token=recording, track_type="Video")
job = client.create_recording_job(recording_token=recording)
print(client.get_recording_job_state(job_token=job))   # configured vs actually recording

for attrs in client.get_media_attributes(recording_tokens=[recording]):
    print(attrs["from"], attrs["until"], attrs["tracks"])   # what a timeline can seek within
print(client.get_replay_uri(recording_token=recording))
```

Playing a recording back is RTSP with ONVIF extensions. `onveef.replay` supplies the ONVIF
part for whichever RTSP client you use: the headers that turn a `PLAY` into a replay of a
time range, and the RTP header extension that stamps each frame with when it was captured:

```python
from onveef import replay

headers = replay.replay_headers(start, end)   # Require: onvif-replay, Range: clock=…, Rate-Control: no
mark = replay.parse_replay_extension(rtp_packet)
if mark is not None:
    print(mark.time, mark.clean_point, mark.end_of_section)
```

Search-result calls (`get_recording_search_results` and friends) widen their read timeout
to their `wait_time`, since a camera may legitimately hold the request that long.

### Physical Access Control (Profile A/C)

Read state, command doors, and write the configuration behind them:

```python
doors = client.get_door_info_list()          # paged; pass start_reference to page
client.unlock_door(token="Door_1")
print(client.get_door_state(token="Door_1"))

schedule = client.create_schedule(
    name="Office hours",
    standard={"Monday": [{"from": "08:00:00", "until": "17:00:00"}]},
)
profile = client.create_access_profile(
    name="Day staff",
    policies=[{"schedule_token": schedule, "entity": "AP_1"}],
)
client.create_credential(
    holder_reference="staff/42",
    identifiers=[{"type": "Card", "format_type": "Wiegand26", "value": "1234"}],
    access_profiles=[{"token": profile}],
)
```

### Capabilities gating

```python
caps = client.get_service_capabilities("ptz")   # any service
if client.endpoint.has("deviceio"):
    client.get_relay_output_options()
```

---

## Authentication

`onveef` implements **WS-Security `UsernameToken` PasswordDigest** by default and
automatically re-signs with a device-derived clock offset when a request is rejected
for time skew (a common cause of `401`s on cameras with wrong clocks). The device's clock is
read with an *unauthenticated* `GetSystemDateAndTime`, since a strict camera refuses a
clock read stamped with the very clock being corrected, and a refusal is recognised however
the camera words it (`ter:NotAuthorized`, `wsse:FailedAuthentication`,
`wsse:InvalidSecurity`, HTTP 400 or 401). A long-lived client re-measures the clock at most
once a minute, so it follows a camera whose clock jumps after an NTP sync, and only retries a
refused login when the offset actually moved — wrong credentials are not retried.

Read the measured offset from `client.clock_offset_s` (or receive it through
`on_clock_resync=`) and pass it to the next client for the same device, which then signs on
the right clock from its first request:

```python
cam = OnvifClient(host, 80, user, password, clock_offset_s=saved_offset,
                  on_clock_resync=lambda offset: store(device_id, offset))
```

Options:

| Constructor arg | Default | Meaning |
|---|---|---|
| `verify_tls` | `True` | TLS verification. Accepts `False`, a CA-bundle path, or an `ssl.SSLContext` — prefer pinning a self-signed cert over disabling verification. |
| `rewrite_host` | `True` | Re-point every address the device reports about itself at the host you connected to. Turn off to trust the device verbatim. |
| `http_auth` | `"auto"` | HTTP transport auth to try when a device answers `401` with a `WWW-Authenticate` challenge — `"auto"` (Digest→Basic), `"digest"`, `"basic"`, or `"none"`. Works **alongside** WS-Security, for cameras that require HTTP Digest on the SOAP endpoint. Once a device has asked, later requests answer it up front (reusing the Digest challenge), instead of collecting a `401` each time. |
| `password_text` | `False` | Force WS-Security `PasswordText` (plaintext) instead of digest. |
| `password_text_fallback` | `False` | On a refused digest login, retry with `PasswordText` — and keep using it for that client once it works, rather than handing the device a failed login on every call. Some cheap firmware only accepts plaintext, but this sends **the password in the clear** on non-HTTPS transports, so you must opt in per device. |
| `clock_offset_s` | `0.0` | Seconds the device clock is ahead of this host's, e.g. a `clock_offset_s` saved from an earlier client — saves the refused login it takes to measure it. |
| `on_clock_resync` | `None` | Called with the new offset whenever the client re-measures the device clock. |
| `ws_timestamp` | `False` | Add a `<wsu:Timestamp>`/`Expires` to the security header (required by some strict devices). |
| `retries` | `2` | Automatic retries (jittered backoff) for transient failures on idempotent (read) operations only. |
| `breaker_key` | `None` | Enable a per-client circuit breaker keyed by this id (e.g. device id). Omit to disable. Tune with `breaker_window_s` / `breaker_threshold` / `breaker_open_s`. |
| `timeout_s` | `5.0` | Default timeout (connect/read/write/pool). Split with `connect_timeout_s` / `read_timeout_s`; long-poll `PullMessages` automatically extends its read timeout to the pull duration. |
| `auto_discover` | host-form: `True` | Discover per-service endpoints lazily on first use. |
| `transport` / `proxy` / `http_client` | `None` | Inject an `httpx` transport (e.g. `httpx.MockTransport` in your tests), a proxy, or a pre-built `httpx.Client` whose pool you share and whose lifetime you own. |

Snapshot fetches use HTTP Digest with a Basic fallback (`get_snapshot(...)` /
`fetch_snapshot_bytes(...)`, TLS verified by default). The library logs to the
`onveef` logger — enable `logging.getLogger("onveef")` at `DEBUG`/`WARNING` to see
retries, auth fallbacks, clock resync, and breaker events.

---

## ONVIF coverage

| Service | Coverage | Notes |
|---|---|---|
| Device Management | ✅ full | info, services/capabilities discovery, datetime (+clock-skew), hostname, users (+ `change_password`), scopes, network, DNS/NTP, log, certs, dot1x, storage, zero-config, endpoint reference, geo-location, firmware upgrade & system restore |
| Media (Profile S) | ✅ full | profiles (incl. single `GetProfile`), stream/snapshot URI, video **and audio** encoder/source configurations — get, options **and** set, with read-modify-write `update_video_encoder_configuration` validated against the options — video source **modes** and rotation, compatible configurations, encoder-instance guarantees, analytics-configuration attach, OSD, metadata (+ event filter), multicast |
| Media2 (Profile T) | ✅ strong | profiles + create/delete, `AddConfiguration`/`RemoveConfiguration`, encoder options, audio decoder (backchannel) configurations, privacy masks (get/delete — create/modify pending), sync point |
| PTZ | ✅ full | continuous/absolute/relative (in any advertised coordinate space), click-to-center (`ptz_center`), `ptz_capabilities`, presets, home, aux, nodes, status, configurations + options, preset tours (full CRUD + options), `GeoMove` |
| Imaging | ✅ full | settings (incl. image stabilization, IR-cut auto adjustment, tone compensation, defogging, noise reduction) / normalized options / status, read-modify-write `imaging_update_settings`, focus move/stop + move options, imaging presets |
| Events | ✅ full | pull-point (managed, +topic filter, sync point, scheduled from the granted lifetime) **and** WS-BaseNotification push — `Subscribe`, renew, unsubscribe, and `parse_notification()` for the `Notify` your consumer receives |
| Analytics | ✅ strong | rules & modules CRUD (SimpleItem + ElementItem params), supported-rule/module **descriptions**, configuration attach/detach/set |
| Recording / Replay / Search (Profile G) | ✅ strong | recordings/jobs CRUD, job **state**, track CRUD + configuration, recording options, `GetMediaAttributes`, replay URI/config, RTSP replay headers + RTP replay-extension decoding (`onveef.replay`), find sessions + search state |
| DeviceIO | ✅ strong | relays (DeviceIO-aware), relay output options, digital inputs, serial ports |
| Access Control / Door / Credential (Profile A/C) | ✅ strong | access points, areas, doors (+lock/unlock/block/lockdown), credentials **incl. create/modify**, schedules and special-day groups, access profiles |
| WS-Discovery | ✅ full | multi-interface multicast Probe with retransmits, unicast probe, optional IPv6, ProbeMatch parsing, HTTP fallback `find_device_service` for devices that ignore WS-Discovery |
| Network | ✅ full | interfaces (IPv4 **and** IPv6), protocols, gateway, DNS, NTP |

Not covered yet: Media2 mask create/modify, receivers, and the authentication-behavior /
credential-identifier-type corners of Profile A. See `CHANGELOG.md` for what changed per
release.

---

## Design notes

- **Sans-IO core.** `onveef.envelopes` and `onveef.parsers` never touch the
  network. All I/O is in the transport (`onveef.transport` / `onveef.atransport`). This
  makes the codec fully testable from recorded XML.
- **One file per service.** `OnvifClient` is composed from the transport core plus a mixin
  per ONVIF service (`onveef.ops.media`, `onveef.ops.ptz`, …), with `onveef.aops` mirroring
  them for asyncio — so operations are where you would look for them, not in one
  3000-line class.
- **Capability gating.** `OnvifEndpoint.has()/url()` and the client's service
  resolution raise a clean `OnvifCapabilityMissingError` instead of a device fault
  when a service is not advertised.
- **DeviceIO aware.** Relay and digital-input calls route to the DeviceIO service
  when advertised, falling back to the legacy device service.
- **Pluggable resilience.** Optional in-memory circuit breaker; bounded (8 MiB)
  streamed responses; content-type negotiation (`application/soap+xml` → `text/xml`).
- **Writes keep what they do not change.** A `Set*Configuration` replaces the whole
  configuration, so every setter echoes back what it was not asked to change (multicast,
  session timeout, rate-control mode, event filter, crop bounds) and the `update_*` helpers
  merge a partial change into what the device reports — validated against its own options
  before anything is sent (`onveef.updates`).
- **Nothing the device says about its address is trusted.** Reported XAddrs, subscription
  references and media URIs are re-pointed at the host you reached the device on
  (`onveef.urls`), which is what makes NAT, port forwards and Docker bridges work.
- **Safe under concurrency.** No request's timeout or retry policy is stored on the client,
  so a 60-second `PullMessages` long poll cannot bleed its read timeout — or its
  retries-disabled flag — into calls made concurrently on the same client. Lazy service
  discovery is guarded by a lock in both clients.
- **Testable from the outside.** `transport=` accepts any `httpx` transport, so downstream
  projects can drive the full request path with `httpx.MockTransport` instead of
  monkeypatching internals.
- **No silent empties.** A parser aimed at the wrong element returns `[]`, which reads as
  "the camera supports nothing" rather than as a bug. The suite pins the wire format of
  every response shape and fails the build if a builder or parser has no caller.

---

## Roadmap

- Grow the **vendor fixture matrix** with real captures (Hikvision / Dahua / Axis /
  Bosch / Reolink / Uniview / Amcrest). `onveef dump` captures a set in one command —
  see [`CONTRIBUTING.md`](CONTRIBUTING.md) for what to redact before opening a PR.
- Media2 mask **create/modify** (get and delete are covered).
- ONVIF **receivers** (`GetReceivers`, `CreateReceiver`) for NVR-side ingest.
- A published API-reference site from the existing docstrings.

---

## Contributing

Bug reports, fixtures from real hardware, and PRs are all welcome — start with
[`CONTRIBUTING.md`](CONTRIBUTING.md). Security issues go through
[`SECURITY.md`](SECURITY.md), not a public issue.

---

## License

Apache-2.0. See [`LICENSE`](LICENSE).
