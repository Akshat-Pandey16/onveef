# onveef

**A fast, zeep-free ONVIF client for IP cameras.** No runtime WSDL parsing,
near-instant import, sans-IO core, and only two runtime dependencies
(`httpx` + `defusedxml`). Talks to ONVIF **Profile S / T / G / M / A / C** devices —
device management, media & media2, PTZ, imaging, events, analytics, recording,
replay, search, DeviceIO, physical access control, and WS-Discovery.

> `onveef` is a working name — rename freely (see [Renaming](#renaming)). This is a
> client library **compatible with** ONVIF devices; it is **not** ONVIF-certified and
> is not affiliated with or endorsed by the ONVIF trademark holder.

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

Requires **Python 3.11+**.

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

`wsdiscovery.build_probe()` / `wsdiscovery.parse_probe_matches()` are exposed
separately so you can drive the multicast yourself or unit-test against captures.

### PTZ

```python
client.ptz_continuous_move(profile_token=token, pan=0.5, tilt=0.0, zoom=0.0)
client.ptz_stop(profile_token=token)
client.ptz_goto_preset(profile_token=token, preset_token="1")
```

### Events (pull-point and push)

```python
# Pull-point (client-polled), optionally scoped to a topic:
sub = client.events_create_pull_point(topic_filter="tns1:RuleEngine//.")
msgs = client.events_pull_messages(subscription_url=sub["subscription_url"])

# Base-notification push subscription (device POSTs to your consumer URL):
sub = client.events_subscribe(consumer_address="http://my-host:9000/onvif-events")
```

### Physical Access Control (Profile A/C)

```python
doors = client.get_door_info_list()          # paged; pass start_reference to page
client.unlock_door(token="Door_1")
print(client.get_door_state(token="Door_1"))
print(client.get_access_point_state(token="AP_1"))
client.enable_credential(token="Cred_1", reason="reinstated")
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
for time skew (a common cause of `401`s on cameras with wrong clocks). Options:

| Constructor arg | Default | Meaning |
|---|---|---|
| `verify_tls` | `True` | TLS certificate verification. **Set `False` for cameras with self-signed certs.** |
| `http_auth` | `"auto"` | HTTP transport auth to try when a device answers `401` with a `WWW-Authenticate` challenge — `"auto"` (Digest→Basic), `"digest"`, `"basic"`, or `"none"`. Works **alongside** WS-Security, for cameras that require HTTP Digest on the SOAP endpoint. |
| `password_text` | `False` | Force WS-Security `PasswordText` (plaintext) instead of digest. |
| `password_text_fallback` | `True` | On digest `401`, retry once with `PasswordText` (some cheap firmware only accepts plaintext). A warning is logged when it triggers — it is plaintext over the wire on non-HTTPS transports. |
| `ws_timestamp` | `False` | Add a `<wsu:Timestamp>`/`Expires` to the security header (required by some strict devices). |
| `retries` | `2` | Automatic retries (jittered backoff) for transient failures on idempotent (read) operations only. |
| `breaker_key` | `None` | Enable a per-client circuit breaker keyed by this id (e.g. device id). Omit to disable. Tune with `breaker_window_s` / `breaker_threshold` / `breaker_open_s`. |
| `timeout_s` | `5.0` | Default timeout (connect/read/write/pool). Split with `connect_timeout_s` / `read_timeout_s`; long-poll `PullMessages` automatically extends its read timeout to the pull duration. |
| `auto_discover` | host-form: `True` | Discover per-service endpoints lazily on first use. |

Snapshot fetches use HTTP Digest with a Basic fallback (`get_snapshot(...)` /
`fetch_snapshot_bytes(...)`, TLS verified by default). The library logs to the
`onveef` logger — enable `logging.getLogger("onveef")` at `DEBUG`/`WARNING` to see
retries, auth fallbacks, clock resync, and breaker events.

---

## ONVIF coverage

| Service | Coverage | Notes |
|---|---|---|
| Device Management | ✅ full | info, services/capabilities discovery, datetime (+clock-skew), hostname, users, scopes, network, DNS/NTP, log, certs, dot1x |
| Media (Profile S) | ✅ full | profiles, stream/snapshot URI (transport options), video/audio encoder get+set, OSD, metadata, multicast |
| Media2 (Profile T) | ✅ strong | profiles + create/delete, `AddConfiguration`/`RemoveConfiguration`, encoder options, masks, sync point |
| PTZ | ✅ strong | continuous/absolute/relative, presets, home, aux, nodes, status, configurations |
| Imaging | ✅ strong | settings/options/status, focus move/stop |
| Events | ✅ strong | pull-point (+topic filter, sync point) **and** WS-BaseNotification `Subscribe` push |
| Analytics | ✅ strong | rules & modules CRUD (SimpleItem + ElementItem params) |
| Recording / Replay / Search (Profile G) | ✅ strong | recordings/jobs CRUD, replay URI/config, find sessions |
| DeviceIO | ✅ strong | relays (DeviceIO-aware), relay output options, digital inputs, serial ports |
| Access Control / Door / Credential (Profile A/C) | ✅ strong | access points, areas, doors (+lock/unlock/block/lockdown), credentials |
| WS-Discovery | ✅ full | multicast Probe + ProbeMatch parsing |
| Network | ✅ full | interfaces (IPv4 **and** IPv6), protocols, gateway, DNS, NTP |

See `CHANGELOG.md` for what changed per release.

---

## Design notes

- **Sans-IO core.** `onveef.envelopes` and `onveef.parsers` never touch the
  network. All I/O is in `onveef.client` (sync `httpx`). This makes the codec
  fully testable from recorded XML.
- **Capability gating.** `OnvifEndpoint.has()/url()` and the client's service
  resolution raise a clean `OnvifCapabilityMissingError` instead of a device fault
  when a service is not advertised.
- **DeviceIO aware.** Relay and digital-input calls route to the DeviceIO service
  when advertised, falling back to the legacy device service.
- **Pluggable resilience.** Optional in-memory circuit breaker; bounded (8 MiB)
  streamed responses; content-type negotiation (`application/soap+xml` → `text/xml`).

---

## Publishing

Build and release instructions (build, TestPyPI rehearsal, PyPI upload, GitHub
Actions trusted publishing, renaming) live in [`PUBLISHING.md`](PUBLISHING.md). TL;DR:

```bash
uv sync --extra dev
uv run ruff check src tests && uv run mypy && uv run pytest -q
uv build
uv run twine check dist/*
uv run twine upload --repository testpypi dist/*   # rehearse
uv run twine upload dist/*                          # release
```

---

## Roadmap

Delivered in 0.3: async client, typed models, WS-Discovery (sync + async),
device/imaging/PTZ extras, and a recorded-fixture vendor harness. Next:

- Grow the **vendor fixture matrix** with real captures (Hikvision / Dahua / Axis /
  Bosch / Reolink / Uniview / Amcrest).
- Full async **method parity** with the sync client (the generic `await call()`
  already reaches every operation today).
- Access Control **write** ops (create/modify credentials, schedules, access profiles).

---

## Renaming

`onveef` is a placeholder. To rename to `<newname>`:

```bash
git grep -l onveef | xargs sed -i 's/onveef/<newname>/g'
git mv src/onveef src/<newname>
```

---

## License

Apache-2.0. See [`LICENSE`](LICENSE).
