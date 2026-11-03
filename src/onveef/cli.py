"""Command-line interface for poking at ONVIF devices and capturing test fixtures.

Run ``onveef --help`` (or ``python -m onveef --help``) for the full command list. Every
device command shares the same connection flags, and ``--json`` makes any command emit
machine-readable output.
"""

from __future__ import annotations

import argparse
import dataclasses
import ipaddress
import json
import logging
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from onveef import envelopes, parsers, wsdiscovery
from onveef.client import DEFAULT_TIMEOUT_S, OnvifClient
from onveef.exceptions import OnvifAuthError, OnvifError

_FIXTURE_OPERATIONS: tuple[tuple[str, str, str], ...] = (
    ("device", "GetDeviceInformation", "device_get_information"),
    ("device", "GetServices", "device_get_services"),
    ("device", "GetCapabilities", "device_get_capabilities"),
    ("device", "GetSystemDateAndTime", "device_get_system_date_time"),
    ("device", "GetNetworkInterfaces", "device_get_network_interfaces"),
    ("device", "GetScopes", "device_get_scopes"),
    ("media", "GetProfiles", "media_get_profiles"),
    ("media", "GetVideoSources", "media_get_video_sources"),
    ("ptz", "GetNodes", "ptz_get_nodes"),
    ("ptz", "GetConfigurations", "ptz_get_configurations"),
    ("events", "GetEventProperties", "events_get_event_properties"),
)


_SECRET_TEXT = re.compile(r"(<(?:[\w-]+:)?(?:SerialNumber|HardwareId)>)[^<]*(</)")
_MAC = re.compile(r"\b[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}\b")
_IPV4 = r"\d{1,3}(?:\.\d{1,3}){3}"
_URL_HOST = re.compile(rf"(://)({_IPV4})")
_ADDRESS_TEXT = re.compile(r"(<(?:[\w-]+:)?\w*Address>)([^<]+)(</)")
_SCOPE_TEXT = re.compile(r"(onvif://www\.onvif\.org/(?:name|location)/)[^\s<]+")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def _documentation_ip(value: str) -> str:
    """Map a unicast address onto a documentation range; keep anything else as it is."""
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return value
    if address.is_multicast or address.is_unspecified or address.is_loopback:
        return value
    if address.version == 6:
        return "2001:db8::1"
    return f"192.0.2.{int(address) % 254 + 1}"


def scrub(xml: str) -> str:
    """Replace what identifies a camera in a captured response with documentation values.

    Serial numbers and hardware ids become ``REDACTED``, MAC addresses
    ``00:00:5E:00:53:01``, unicast IPv4 addresses in URLs and ``*Address`` elements a
    stand-in in 192.0.2.0/24 (the same address always gets the same one) and IPv6 ones
    ``2001:db8::1``, and the ``name``/``location`` scopes ``REDACTED``. Multicast, loopback
    and unspecified addresses identify nothing and are kept, as is every setting.
    """
    xml = _SECRET_TEXT.sub(r"\1REDACTED\2", xml)
    xml = _MAC.sub("00:00:5E:00:53:01", xml)
    xml = _URL_HOST.sub(lambda match: match.group(1) + _documentation_ip(match.group(2)), xml)
    xml = _ADDRESS_TEXT.sub(
        lambda match: match.group(1) + _documentation_ip(match.group(2)) + match.group(3), xml
    )
    return _SCOPE_TEXT.sub(r"\1REDACTED", xml)


def _emit(data: Any, as_json: bool) -> None:
    """Print a result either as JSON or as readable indented text."""
    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return
    if isinstance(data, str):
        print(data)
    elif isinstance(data, dict):
        for key, value in data.items():
            print(f"{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                print("  ".join(f"{k}={v}" for k, v in item.items()))
            else:
                print(item)
    else:
        print(data)


def _client(args: argparse.Namespace) -> OnvifClient:
    return OnvifClient(
        args.host,
        args.port,
        args.username,
        args.password,
        use_https=args.https,
        verify_tls=not args.no_verify,
        timeout_s=args.timeout,
        rewrite_host=not args.no_rewrite_host,
        password_text_fallback=args.password_text_fallback,
    )


def _cmd_discover(args: argparse.Namespace) -> int:
    if args.address:
        devices = wsdiscovery.probe_device(args.address, timeout_s=args.timeout)
    else:
        devices = wsdiscovery.discover(
            timeout_s=args.timeout,
            interface_ip=args.interface,
            probes=args.probes,
            ipv6=args.ipv6,
        )
    if args.json:
        _emit([dataclasses.asdict(d) for d in devices], True)
    elif not devices:
        print("No ONVIF devices answered.", file=sys.stderr)
    else:
        for device in devices:
            print(f"{device.device_service}\t{device.name or '?'}\t{device.hardware or '?'}")
    return 0 if devices else 1


def _cmd_locate(args: argparse.Namespace) -> int:
    url = wsdiscovery.find_device_service(
        args.host, timeout_s=args.timeout, verify_tls=not args.no_verify
    )
    if url is None:
        print(f"No ONVIF device service answered on {args.host}.", file=sys.stderr)
        return 1
    _emit({"device_service": url} if args.json else url, args.json)
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    with _client(args) as cam:
        _emit(cam.get_device_information(), args.json)
    return 0


def _cmd_services(args: argparse.Namespace) -> int:
    with _client(args) as cam:
        _emit(cam.discover_services(), args.json)
    return 0


def _cmd_capabilities(args: argparse.Namespace) -> int:
    with _client(args) as cam:
        _emit(cam.get_service_capabilities(args.service), args.json)
    return 0


def _cmd_profiles(args: argparse.Namespace) -> int:
    with _client(args) as cam:
        _emit(cam.get_profiles(), args.json)
    return 0


def _first_profile(cam: OnvifClient, token: str) -> str:
    if token:
        return token
    profiles = cam.get_profiles()
    if not profiles:
        raise OnvifError("Device reports no media profiles.")
    return str(profiles[0]["token"])


def _cmd_stream_uri(args: argparse.Namespace) -> int:
    with _client(args) as cam:
        uri = cam.get_stream_uri(
            profile_token=_first_profile(cam, args.profile),
            with_credentials=args.with_credentials,
        )
        _emit(uri, args.json)
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    with _client(args) as cam:
        token = _first_profile(cam, args.profile)
        if args.uri_only:
            _emit(
                cam.get_snapshot_uri(profile_token=token, with_credentials=args.with_credentials),
                args.json,
            )
            return 0
        image, content_type = cam.get_snapshot(profile_token=token)
    Path(args.output).write_bytes(image)
    print(f"Wrote {len(image)} bytes ({content_type}) to {args.output}", file=sys.stderr)
    return 0


def _cmd_ptz(args: argparse.Namespace) -> int:
    with _client(args) as cam:
        token = _first_profile(cam, args.profile)
        if args.ptz_command == "presets":
            _emit(cam.ptz_get_presets(profile_token=token), args.json)
        elif args.ptz_command == "status":
            _emit(cam.ptz_get_status(profile_token=token), args.json)
        elif args.ptz_command == "goto":
            cam.ptz_goto_preset(profile_token=token, preset_token=args.preset)
        elif args.ptz_command == "move":
            cam.ptz_continuous_move(
                profile_token=token, pan=args.pan, tilt=args.tilt, zoom=args.zoom
            )
        elif args.ptz_command == "stop":
            cam.ptz_stop(profile_token=token)
    return 0


def _cmd_events(args: argparse.Namespace) -> int:
    with _client(args) as cam, cam.pull_point(topic_filter=args.topic) as subscription:
        for seen, message in enumerate(subscription, start=1):
            _emit(message, args.json)
            if args.count and seen >= args.count:
                break
    return 0


def _cmd_raw(args: argparse.Namespace) -> int:
    body = args.body
    if not body:
        builder = getattr(envelopes, args.builder or "", None)
        if builder is None:
            print(
                "Pass --body '<tds:GetHostname/>' or --builder device_get_hostname",
                file=sys.stderr,
            )
            return 2
        body = builder()
    with _client(args) as cam:
        print(cam.call(service=args.service, operation=args.operation, body_inner=body))
    return 0


class _Capture:
    """Sends read-only requests and writes each reply to ``<name>.xml``."""

    def __init__(self, cam: OnvifClient, out_dir: Path, *, scrubbed: bool) -> None:
        self.cam = cam
        self.out_dir = out_dir
        self.scrubbed = scrubbed
        self.written: list[str] = []

    def take(
        self, service: str, operation: str, body: str, *, prefix: str = "", token: str = ""
    ) -> str:
        """Capture one reply; return its (unscrubbed) XML, or ``""`` if the device refused."""
        name = prefix + operation + (f"-{_UNSAFE_NAME.sub('_', token)}" if token else "")
        try:
            xml = self.cam.call(service=service, operation=operation, body_inner=body)
        except OnvifAuthError:
            raise  # never keep trying a refused login: many cameras lock the account
        except OnvifError as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)
            return ""
        text = scrub(xml) if self.scrubbed else xml
        (self.out_dir / f"{name}.xml").write_text(text, encoding="utf-8")
        self.written.append(name)
        print(f"wrote {name}.xml", file=sys.stderr)
        return xml


def _record(capture: _Capture) -> dict[str, Any]:
    """Capture the fixture set; return the manifest describing the camera."""
    cam = capture.cam
    replies: dict[str, str] = {}
    for service, operation, builder_name in _FIXTURE_OPERATIONS:
        builder = getattr(envelopes, builder_name)
        body = (
            builder(use_media2=False) if "use_media2" in builder.__code__.co_varnames else builder()
        )
        replies[operation] = capture.take(service, operation, body)
    source_tokens: set[str] = set()
    for service in ("media", "media2"):
        if not cam.endpoint.has(service):
            continue
        media2 = service == "media2"
        prefix = "Media2-" if media2 else ""
        if media2:
            capture.take(
                service, "GetProfiles", envelopes.media_get_profiles(use_media2=True), prefix=prefix
            )
        sources = parsers.parse_video_source_configurations(
            capture.take(
                service,
                "GetVideoSourceConfigurations",
                envelopes.media_get_video_source_configurations(use_media2=media2),
                prefix=prefix,
            )
        )
        for config in sources:
            source_tokens.add(str(config.get("source_token") or ""))
            capture.take(
                service,
                "GetVideoSourceConfigurationOptions",
                envelopes.media_get_video_source_configuration_options(
                    use_media2=media2, configuration_token=str(config["token"])
                ),
                prefix=prefix,
                token=str(config["token"]),
            )
        for encoder in parsers.parse_video_encoder_configurations(
            capture.take(
                service,
                "GetVideoEncoderConfigurations",
                envelopes.media_get_video_encoder_configurations(use_media2=media2),
                prefix=prefix,
            )
        ):
            token = str(encoder["token"])
            body = (
                envelopes.media2_get_video_encoder_options(configuration_token=token)
                if media2
                else envelopes.media_get_video_encoder_options(configuration_token=token)
            )
            capture.take(
                service, "GetVideoEncoderConfigurationOptions", body, prefix=prefix, token=token
            )
        for encoder in parsers.parse_audio_encoder_configurations(
            capture.take(
                service,
                "GetAudioEncoderConfigurations",
                envelopes.media_get_audio_encoder_configurations(use_media2=media2),
                prefix=prefix,
            )
        ):
            token = str(encoder["token"])
            capture.take(
                service,
                "GetAudioEncoderConfigurationOptions",
                envelopes.media_get_audio_encoder_configuration_options(
                    use_media2=media2, configuration_token=token
                ),
                prefix=prefix,
                token=token,
            )
    if cam.endpoint.has("imaging"):
        for token in sorted(source_tokens - {""}):
            for operation, builder in (
                ("GetImagingSettings", envelopes.imaging_get_settings),
                ("GetOptions", envelopes.imaging_get_options),
                ("GetMoveOptions", envelopes.imaging_get_move_options),
            ):
                capture.take("imaging", operation, builder(video_source_token=token), token=token)
    info = parsers.parse_device_information(replies.get("GetDeviceInformation", ""))
    return {
        "manufacturer": info.get("Manufacturer") or "unknown",
        "model": info.get("Model") or "unknown",
        "firmware": info.get("FirmwareVersion") or "",
        "services": sorted(name for name, url in cam.endpoint.services.items() if url),
        "recorded_at": date.today().isoformat(),
        "scrubbed": capture.scrubbed,
    }


def _cmd_dump(args: argparse.Namespace) -> int:
    """Capture read-only responses as XML fixtures for the vendor test matrix."""
    out_dir = Path(args.directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    with _client(args) as cam:
        capture = _Capture(cam, out_dir, scrubbed=not args.no_scrub)
        try:
            cam.connect()
            manifest = _record(capture)
        except OnvifAuthError as exc:
            print(
                f"stopped: the device refused the login ({exc}). Not retrying, so as not to "
                "lock the account.",
                file=sys.stderr,
            )
            return 1
    (out_dir / "camera.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    note = (
        "Redacted serial numbers, hardware ids, MAC and IP addresses and name/location\n"
        "scopes; review the files"
        if capture.scrubbed
        else "Redact serials, MACs, hostnames and any credentials"
    )
    print(
        f"\n{len(capture.written)} fixtures in {out_dir}. {note} before committing them —\n"
        "see CONTRIBUTING.md.",
        file=sys.stderr,
    )
    return 0 if capture.written else 1


def _add_device_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("host", help="Device IP, host:port, or full http(s)://.../device_service")
    parser.add_argument("-u", "--username", default="", help="ONVIF account username")
    parser.add_argument("-p", "--password", default="", help="ONVIF account password")
    parser.add_argument("--port", type=int, default=80, help="Device port (default: 80)")
    parser.add_argument("--https", action="store_true", help="Build an https:// device URL")
    parser.add_argument(
        "--no-verify", action="store_true", help="Skip TLS verification (self-signed certs)"
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="Per-request timeout in seconds"
    )
    parser.add_argument(
        "--no-rewrite-host",
        action="store_true",
        help="Trust the addresses the device reports about itself verbatim",
    )
    parser.add_argument(
        "--password-text-fallback",
        action="store_true",
        help="On a digest 401, retry with a PLAINTEXT password (insecure over http)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="onveef", description="Talk to ONVIF cameras, NVRs and access-control devices."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log onveef debug output")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="Find devices on the LAN via WS-Discovery")
    discover.add_argument("--timeout", type=float, default=3.0, help="Listen duration in seconds")
    discover.add_argument("--interface", default=None, help="Probe from this local IP only")
    discover.add_argument("--probes", type=int, default=3, help="Probes per interface")
    discover.add_argument("--ipv6", action="store_true", help="Also probe ff02::c")
    discover.add_argument("--address", default="", help="Unicast-probe one known address")
    discover.set_defaults(func=_cmd_discover)

    locate = sub.add_parser(
        "locate", help="Find a host's ONVIF device-service URL by trying common ports/paths"
    )
    locate.add_argument("host", help="Device IP or hostname")
    locate.add_argument("--timeout", type=float, default=2.0, help="Per-attempt timeout (s)")
    locate.add_argument("--no-verify", action="store_true", help="Skip TLS verification")
    locate.set_defaults(func=_cmd_locate)

    info = sub.add_parser("info", help="Show manufacturer/model/firmware/serial")
    _add_device_args(info)
    info.set_defaults(func=_cmd_info)

    services = sub.add_parser("services", help="Show the discovered service XAddr map")
    _add_device_args(services)
    services.set_defaults(func=_cmd_services)

    caps = sub.add_parser("capabilities", help="Show one service's capabilities")
    _add_device_args(caps)
    caps.add_argument("--service", default="device", help="Service key (device, media, ptz, ...)")
    caps.set_defaults(func=_cmd_capabilities)

    profiles = sub.add_parser("profiles", help="List media profiles")
    _add_device_args(profiles)
    profiles.set_defaults(func=_cmd_profiles)

    stream = sub.add_parser("stream-uri", help="Resolve a profile's RTSP URI")
    _add_device_args(stream)
    stream.add_argument("--profile", default="", help="Profile token (default: the first)")
    stream.add_argument(
        "--with-credentials", action="store_true", help="Embed credentials in the URI"
    )
    stream.set_defaults(func=_cmd_stream_uri)

    snapshot = sub.add_parser("snapshot", help="Download a JPEG snapshot")
    _add_device_args(snapshot)
    snapshot.add_argument("--profile", default="", help="Profile token (default: the first)")
    snapshot.add_argument("-o", "--output", default="snapshot.jpg", help="Output file path")
    snapshot.add_argument("--uri-only", action="store_true", help="Print the URI, do not download")
    snapshot.add_argument(
        "--with-credentials", action="store_true", help="Embed credentials in the printed URI"
    )
    snapshot.set_defaults(func=_cmd_snapshot)

    ptz = sub.add_parser("ptz", help="Query or drive the PTZ service")
    _add_device_args(ptz)
    ptz.add_argument(
        "ptz_command", choices=("presets", "status", "goto", "move", "stop"), help="PTZ action"
    )
    ptz.add_argument("--profile", default="", help="Profile token (default: the first)")
    ptz.add_argument("--preset", default="", help="Preset token for 'goto'")
    ptz.add_argument("--pan", type=float, default=0.0, help="Pan velocity for 'move' (-1..1)")
    ptz.add_argument("--tilt", type=float, default=0.0, help="Tilt velocity for 'move' (-1..1)")
    ptz.add_argument("--zoom", type=float, default=0.0, help="Zoom velocity for 'move' (-1..1)")
    ptz.set_defaults(func=_cmd_ptz)

    events = sub.add_parser("events", help="Stream events from a managed pull-point")
    _add_device_args(events)
    events.add_argument("--topic", default="", help="Topic filter, e.g. 'tns1:RuleEngine//.'")
    events.add_argument("--count", type=int, default=0, help="Stop after N messages (0 = forever)")
    events.set_defaults(func=_cmd_events)

    raw = sub.add_parser("raw", help="Send an arbitrary operation and print the response XML")
    _add_device_args(raw)
    raw.add_argument("--service", default="device", help="Service key")
    raw.add_argument("--operation", required=True, help="ONVIF operation name")
    raw.add_argument("--body", default="", help="SOAP body inner XML")
    raw.add_argument("--builder", default="", help="Name of an onveef.envelopes builder to call")
    raw.set_defaults(func=_cmd_raw)

    dump = sub.add_parser("dump", help="Capture raw XML responses as test fixtures")
    _add_device_args(dump)
    dump.add_argument("-d", "--directory", default="fixtures", help="Directory to write into")
    dump.add_argument(
        "--no-scrub",
        action="store_true",
        help="Keep serial numbers, MACs and IP addresses (scrubbed by default)",
    )
    dump.set_defaults(func=_cmd_dump)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``onveef`` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    try:
        result = args.func(args)
        return int(result)
    except OnvifError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
