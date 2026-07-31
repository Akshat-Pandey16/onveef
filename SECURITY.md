# Security Policy

## Reporting a vulnerability

Report security issues privately through
[GitHub Security Advisories](https://github.com/Akshat-Pandey16/onveef/security/advisories/new)
rather than a public issue. Include the version, a description of the impact, and steps to
reproduce. Expect an initial response within a week.

## Supported versions

`onveef` is pre-1.0; only the latest release receives fixes.

## Security-relevant defaults

The defaults below are chosen deliberately. Each can be relaxed, and each carries a cost
when you do.

| Setting | Default | If you change it |
|---|---|---|
| `verify_tls` | `True` | `False` disables certificate verification entirely, so an on-path attacker can read and modify the session. For a camera with a self-signed cert, prefer passing a CA-bundle path or an `ssl.SSLContext` and pinning the certificate. |
| `password_text_fallback` | `False` | `True` retries a digest `401` with a **plaintext** `PasswordText` password. Over `http://` that puts the credential on the wire in the clear. Enable it per device, only for firmware that needs it, and prefer HTTPS when you do. |
| `follow_redirects` | off (not configurable) | A redirect could send credentials to a different host, so a `3xx` is reported as an error instead of followed. Point the endpoint at the final URL yourself. |
| `max_response_bytes` | 8 MiB | Bounds a hostile or malfunctioning device's ability to exhaust memory. Responses are streamed and the cap is enforced mid-stream. |
| XML parsing | `defusedxml` | Blocks XXE, billion-laughs and external-entity attacks. Do not swap in `xml.etree` or `lxml` without equivalent hardening. |
| `rewrite_host` | `True` | Requests go to the host you configured rather than one the device names, so a compromised device cannot redirect your client at a third party. Turning it off makes the device's self-reported addresses authoritative. |

## Handling credentials

- `OnvifCredentials` hides the password from `repr()`, and so do the client `__repr__`s.
  Passwords are still plain attributes — do not log the object's `__dict__`.
- `get_stream_uri(with_credentials=True)` and `onveef.urls.with_credentials()` return URIs
  containing the password. These are convenient for handing to `ffmpeg`, and dangerous to
  log, print, or store — treat the result as a secret.
- WS-Security `PasswordDigest` (the default) never puts the password on the wire, but it is
  SHA-1 based and offers no transport confidentiality. Use HTTPS for anything sensitive.
- The `onveef` CLI takes `-p/--password` on the command line, which is visible in your shell
  history and to other users via the process list. Prefer a device with restricted
  credentials for interactive poking.

## Scope

`onveef` is a client library. It does not listen on any port; the WS-Discovery helpers send
UDP multicast and read replies on an ephemeral socket for the duration of a probe. Reports
about ONVIF device firmware itself belong with the device vendor.
