# Vendor response fixtures

Real (or realistic) captured ONVIF SOAP **responses**, one file per
`<vendor>/<Operation>.xml`, replayed against the parsers by
[`../test_fixtures.py`](../test_fixtures.py). This is how we prove parsing
behaviour against real-world vendor quirks **without hardware in CI**.

Each file is a full `<Envelope>` (with the vendor's real namespace prefixes and
casing), so the fixtures also exercise `onveef`'s namespace-agnostic parsing.

## Why this matters

The hardest part of an ONVIF library is not the SOAP plumbing — it's the tail of
per-vendor divergence (namespace prefixes, `1`/`0` vs `true`/`false` booleans,
`H265` vs `HEVC`, media1 vs media2 shapes, extra/missing fields). A parser that
passes on idealised XML can still return plausible-but-wrong data on a real
Hikvision or Dahua response. These fixtures are the regression net for that.

## Vendor coverage matrix

Legend: ✅ present · ⬚ wanted (contributions welcome)

| Operation | Hikvision | Dahua | CP Plus | Axis | Reolink | Bosch | Uniview | Amcrest |
|---|---|---|---|---|---|---|---|---|
| GetDeviceInformation | ✅ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetProfiles | ✅ | ✅ (H265) | ✅ (Media1 + Media2) | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetSystemDateAndTime | ⬚ | ⬚ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetStreamUri | ⬚ | ⬚ | ⬚ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ |
| GetNetworkInterfaces | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| PullMessages | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetDoorState (Profile C) | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| Video encoder configurations + options | ⬚ | ⬚ | ✅ (Media1 + Media2) | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| Video source configuration options | ⬚ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| Imaging settings + options | ⬚ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| Audio encoder configurations + options | ⬚ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |

> The `cpplus/` set is a real capture (a CP-UNP-D2521L10-DAQ PTZ, Dahua OEM firmware,
> recorded read-only and scrubbed); note how its H.265 main stream comes back from Media1 as
> a stub, because Media1 cannot express H.265. The other seed fixtures are schema-accurate
> but hand-built. **Replace/augment them with real captures** from devices you own — that is
> what turns this from a template into a real compatibility guarantee.

## How to capture a real response

Pick whichever is easiest for the device you have:

1. **`onveef dump`** — the cheapest option. It sends only read requests, records the
   per-configuration option sets as `<Operation>-<token>.xml` (Media2 replies prefixed
   `Media2-`), writes a `camera.json`, and scrubs serials, MACs, IPs and name/location
   scopes:
   ```bash
   onveef dump 192.168.1.64 -u admin -p secret -d tests/fixtures/<vendor>
   ```
   Or capture a single reply yourself:
   ```python
   client = OnvifClient(endpoint=..., credentials=...)
   xml = client.call(service="device", operation="GetDeviceInformation",
                     body_inner=envelopes.device_get_information())
   pathlib.Path("tests/fixtures/<vendor>/GetDeviceInformation.xml").write_text(xml)
   ```
2. **tcpdump / Wireshark** — capture port 80/8000 traffic and copy the SOAP body of
   the response (`tcp.port == 80 && http`).
3. **The ONVIF Device Manager / `onvif-cli`** — enable request logging and copy the
   response envelope.

**Before committing:** review what `dump` scrubbed (or scrub serial numbers, MAC
addresses, IPs and any credentials yourself for hand captures — `onveef.cli.scrub()` does
the common cases). Keep the structure/namespaces exactly as the device sent them — that
fidelity is the whole point.

## Adding a fixture to the harness

Drop the file at `tests/fixtures/<vendor>/<Operation>.xml`, then add a case to
`test_fixtures.py` mapping it to the parser and the invariants you expect. Keep
assertions about *shape* (keys present, types correct), not exact serial numbers.
