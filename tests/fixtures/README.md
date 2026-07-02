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

| Operation | Hikvision | Dahua | Axis | Reolink | Bosch | Uniview | Amcrest |
|---|---|---|---|---|---|---|---|
| GetDeviceInformation | ✅ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetProfiles | ✅ | ✅ (H265) | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetSystemDateAndTime | ⬚ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetStreamUri | ⬚ | ⬚ | ⬚ | ✅ | ⬚ | ⬚ | ⬚ |
| GetNetworkInterfaces | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| PullMessages | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |
| GetDoorState (Profile C) | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ | ⬚ |

> The seed fixtures here are schema-accurate but hand-built. **Replace/augment them
> with real captures** from devices you own — that is what turns this from a
> template into a real compatibility guarantee.

## How to capture a real response

Pick whichever is easiest for the device you have:

1. **From `onveef` itself** — the cheapest option. Temporarily log the raw XML:
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

**Before committing:** scrub serial numbers, MAC addresses, external IPs, and any
credentials. Keep the structure/namespaces exactly as the device sent them — that
fidelity is the whole point.

## Adding a fixture to the harness

Drop the file at `tests/fixtures/<vendor>/<Operation>.xml`, then add a case to
`test_fixtures.py` mapping it to the parser and the invariants you expect. Keep
assertions about *shape* (keys present, types correct), not exact serial numbers.
