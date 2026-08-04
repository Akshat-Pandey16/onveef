# onveef

A fast, zeep-free ONVIF client for IP cameras — no runtime WSDL parsing, a sans-IO core,
and two runtime dependencies (`httpx`, `defusedxml`).

```bash
pip install onveef
```

```python
from onveef import OnvifClient

with OnvifClient("192.168.1.64", 80, "admin", "secret", verify_tls=False) as cam:
    print(cam.get_device_information())
    for profile in cam.get_profiles():
        print(cam.get_stream_uri(profile_token=profile["token"], with_credentials=True))
```

The [project README](https://github.com/Akshat-Pandey16/onveef#readme) is the narrative
introduction: quickstart, async, authentication options, ONVIF coverage table and design
notes. These pages are the generated API reference and the CLI manual.

## Three things worth knowing

**Addresses the device reports are repaired.** Cameras advertise their own idea of their
address, which is wrong behind NAT, a port forward or a Docker bridge. Every reported
address is re-pointed at the host you connected to — see [`onveef.urls`](api/helpers.md).

**Long polls do not leak.** `PullMessages` extends its read timeout per request, never on
the client, so a 60-second poll cannot affect calls running concurrently beside it.

**The core never touches the network.** `onveef.envelopes` builds request strings and
`onveef.parsers` reads response strings; all I/O lives in the transport. That is what makes
device behaviour verifiable from recorded XML.

## How the package is laid out

| Module | Holds |
|---|---|
| `onveef.client` / `onveef.aclient` | `OnvifClient` / `AsyncOnvifClient` — the classes you import |
| `onveef.transport` / `onveef.atransport` | Endpoints, credentials, auth, retries, breaker, fault handling |
| `onveef.ops.*` / `onveef.aops.*` | One mixin per ONVIF service: `device`, `media`, `ptz`, `imaging`, `events`, `analytics`, `recording`, `accesscontrol` |
| `onveef.envelopes` / `onveef.parsers` / `onveef.pacs` | The sans-IO codec |
| `onveef.urls`, `onveef.wsdiscovery`, `onveef.models`, `onveef.breaker` | Helpers |

The mixins are an implementation detail of how the source is organised — every operation
is reachable on the client itself, and every import path is the one it has always been.
