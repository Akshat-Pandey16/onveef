# Command line

Installing the package provides an `onveef` console script; `python -m onveef` is
equivalent. Every device command shares the same connection flags, and `--json` makes any
command emit machine-readable output.

```bash
onveef --help
onveef <command> --help
```

## Connection flags

| Flag | Meaning |
|---|---|
| `-u`, `--username` / `-p`, `--password` | ONVIF account credentials |
| `--port` | Device port (default 80) |
| `--https` | Build an `https://` device URL |
| `--no-verify` | Skip TLS verification (self-signed certs) |
| `--timeout` | Per-request timeout in seconds |
| `--no-rewrite-host` | Trust the addresses the device reports verbatim |
| `--password-text-fallback` | On a digest 401, retry with a **plaintext** password |

!!! warning
    `-p` puts the password in your shell history and in the process list. Use an account
    with restricted rights for interactive poking.

## Commands

```bash
onveef discover                                  # sweep every local interface
onveef discover --address 192.168.1.64           # unicast probe one known device
onveef discover --interface 10.0.0.2 --probes 5 --ipv6

onveef info 192.168.1.64 -u admin -p secret      # manufacturer / model / firmware
onveef services 192.168.1.64 -u admin -p secret  # the discovered XAddr map
onveef capabilities 192.168.1.64 --service ptz -u admin -p secret
onveef profiles 192.168.1.64 -u admin -p secret --json

onveef stream-uri 192.168.1.64 -u admin -p secret --with-credentials
onveef snapshot 192.168.1.64 -u admin -p secret -o frame.jpg
onveef snapshot 192.168.1.64 -u admin -p secret --uri-only

onveef ptz 192.168.1.64 presets -u admin -p secret --json
onveef ptz 192.168.1.64 goto --preset 1 -u admin -p secret
onveef ptz 192.168.1.64 move --pan 0.5 -u admin -p secret
onveef ptz 192.168.1.64 stop -u admin -p secret

onveef events 192.168.1.64 -u admin -p secret --topic 'tns1:RuleEngine//.' --count 5
```

## Escape hatch

`raw` sends any operation and prints the response XML — either an inline body or the name
of a builder in `onveef.envelopes`:

```bash
onveef raw 192.168.1.64 --operation GetHostname --builder device_get_hostname
onveef raw 192.168.1.64 --operation GetHostname --body '<tds:GetHostname/>'
```

## Capturing fixtures

`dump` records a device's raw responses so they can become regression tests:

```bash
onveef dump 192.168.1.64 -u admin -p secret -d tests/fixtures/mycam
```

Redact serials, MACs, hostnames and credentials before committing — see
[Contributing](contributing.md).
