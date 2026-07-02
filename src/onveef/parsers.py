"""Parsers that turn ONVIF SOAP response XML into plain Python dicts and lists."""

from __future__ import annotations

import contextlib
import re
from typing import Any
from xml.etree import ElementTree as ET

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as _safe_fromstring

_LOCAL_TAG = re.compile(r"^\{[^}]*\}")

_NS_PREFIX = {
    "http://www.onvif.org/ver10/topics": "tns1",
    "http://www.onvif.org/ver10/tev/topics": "tns1",
}


def _local(tag: str) -> str:
    return _LOCAL_TAG.sub("", tag)


def _namespace(tag: str) -> str:
    m = _LOCAL_TAG.match(tag)
    return m.group(0)[1:-1] if m else ""


def parse_xml(xml: str | bytes) -> ET.Element | None:
    """Parse an XML document safely (XXE-hardened via defusedxml).

    Accepts ``str`` or raw ``bytes``; passing bytes lets the parser honour the
    ``<?xml ... encoding=?>`` prolog. Returns ``None`` on any parse error so callers
    can degrade gracefully instead of crashing on malformed device output.
    """
    try:
        return _safe_fromstring(xml)
    except (ET.ParseError, DefusedXmlException, ValueError, LookupError):
        return None


def _body(root: ET.Element) -> ET.Element:
    """Return the SOAP ``Body`` element, or ``root`` itself if there is no envelope.

    Searching within the Body avoids matching same-named elements that appear in the
    SOAP/WS-Addressing/WS-Security header (a hazard for local-name-only lookups).
    """
    for el in root.iter():
        if _local(el.tag) == "Body":
            return el
    return root


def _token(el: ET.Element) -> str:
    """Read an object token whether the device spells it ``token``, ``Token``, or a child."""
    return el.attrib.get("token") or el.attrib.get("Token") or child_text(el, "Token")


def _text_of(el: ET.Element | None) -> str:
    """Return the stripped text of an element, or ``""`` if it or its text is absent."""
    return el.text.strip() if el is not None and el.text else ""


def find_local(root: ET.Element, name: str) -> ET.Element | None:
    """Return the first descendant element whose local (namespace-stripped) tag is ``name``, else ``None``."""
    for el in root.iter():
        if _local(el.tag) == name:
            return el
    return None


def find_all_local(root: ET.Element, name: str) -> list[ET.Element]:
    """Return every descendant element whose local (namespace-stripped) tag is ``name``."""
    return [el for el in root.iter() if _local(el.tag) == name]


def child_local(parent: ET.Element, name: str) -> ET.Element | None:
    """Return the first direct child whose local tag is ``name``, else ``None``."""
    for el in parent:
        if _local(el.tag) == name:
            return el
    return None


def child_text(parent: ET.Element, name: str) -> str:
    """Return the stripped text of the first direct child named ``name``, or ``""`` if absent."""
    el = child_local(parent, name)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


_TRUTHY = frozenset({"true", "1", "yes"})


def _to_bool(text: str) -> bool:
    return text.strip().lower() in _TRUTHY


def _opt_int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _opt_float(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_device_information(xml: str) -> dict[str, str]:
    """Parse a ``GetDeviceInformation`` response.

    Returns a dict holding whichever of ``Manufacturer``, ``Model``,
    ``FirmwareVersion``, ``SerialNumber`` and ``HardwareId`` are present, mapped to
    their string values.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    out: dict[str, str] = {}
    for field in (
        "Manufacturer",
        "Model",
        "FirmwareVersion",
        "SerialNumber",
        "HardwareId",
    ):
        el = find_local(root, field)
        if el is not None and el.text:
            out[field] = el.text.strip()
    return out


def parse_services(xml: str) -> dict[str, str]:
    """Parse a ``GetServices`` response.

    Returns a dict mapping a normalized service key (e.g. ``media``, ``media2``,
    ``ptz``, ``events``, ``analytics``, ``imaging``, ``recording``, ``replay``,
    ``search``, ``deviceio``, ``accesscontrol``, ``doorcontrol``, ``credential``,
    ``schedule``, ``accessrules``, ``device``) to that service's ``XAddr`` URL.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    services: dict[str, str] = {}
    for svc in find_all_local(root, "Service"):
        namespace = child_text(svc, "Namespace").lower()
        xaddr = child_text(svc, "XAddr")
        if not xaddr:
            continue
        if "ver10/media" in namespace:
            services["media"] = xaddr
        elif "ver20/media" in namespace:
            services["media2"] = xaddr
        elif "ver20/ptz" in namespace or "ver10/ptz" in namespace:
            services["ptz"] = xaddr
        elif "ver10/events" in namespace:
            services["events"] = xaddr
        elif "ver20/analytics" in namespace or "ver10/analytics" in namespace:
            services["analytics"] = xaddr
        elif "ver20/imaging" in namespace or "ver10/imaging" in namespace:
            services["imaging"] = xaddr
        elif "ver10/recording" in namespace:
            services["recording"] = xaddr
        elif "ver10/replay" in namespace:
            services["replay"] = xaddr
        elif "ver10/search" in namespace:
            services["search"] = xaddr
        elif "ver10/deviceio" in namespace:
            services["deviceio"] = xaddr
        elif "ver10/accesscontrol" in namespace:
            services["accesscontrol"] = xaddr
        elif "ver10/doorcontrol" in namespace:
            services["doorcontrol"] = xaddr
        elif "ver10/credential" in namespace:
            services["credential"] = xaddr
        elif "ver10/schedule" in namespace:
            services["schedule"] = xaddr
        elif "ver10/accessrules" in namespace:
            services["accessrules"] = xaddr
        elif "ver10/device" in namespace:
            services["device"] = xaddr
    return services


def parse_capabilities(xml: str) -> dict[str, str]:
    """Parse a ``GetCapabilities`` response.

    Returns a dict mapping a service key (``device``, ``media``, ``ptz``,
    ``imaging``, ``events``, ``analytics``, ``recording``, ``replay``, ``search``,
    ``deviceio``) to that category's ``XAddr`` URL.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    services: dict[str, str] = {}
    categories = (
        ("Device", "device"),
        ("Media", "media"),
        ("PTZ", "ptz"),
        ("Imaging", "imaging"),
        ("Events", "events"),
        ("Analytics", "analytics"),
        ("Recording", "recording"),
        ("Replay", "replay"),
        ("Search", "search"),
        ("DeviceIO", "deviceio"),
    )
    for label, key in categories:
        cat = find_local(root, label)
        if cat is None:
            continue
        xaddr_el = child_local(cat, "XAddr")
        if xaddr_el is not None and xaddr_el.text:
            services[key] = xaddr_el.text.strip()
    return services


def parse_system_datetime(xml: str) -> dict[str, Any]:
    """Parse a ``GetSystemDateAndTime`` response.

    Returns a dict with optional keys ``date_time_type``, ``daylight_savings``
    (bool), ``timezone`` (POSIX TZ string), and ``UTCDateTime``/``LocalDateTime``,
    each a dict of ``year``/``month``/``day``/``hour``/``minute``/``second`` ints.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    out: dict[str, Any] = {}
    dt_type = find_local(root, "DateTimeType")
    if dt_type is not None and dt_type.text:
        out["date_time_type"] = dt_type.text.strip()
    dst = find_local(root, "DaylightSavings")
    if dst is not None and dst.text:
        out["daylight_savings"] = _to_bool(dst.text)
    tz_el = find_local(root, "TimeZone")
    if tz_el is not None:
        tz_inner = child_text(tz_el, "TZ")
        if tz_inner:
            out["timezone"] = tz_inner
    for variant in ("UTCDateTime", "LocalDateTime"):
        block = find_local(root, variant)
        if block is None:
            continue
        date_el = child_local(block, "Date")
        time_el = child_local(block, "Time")
        if date_el is None and time_el is None:
            continue
        year = _opt_int(child_text(date_el, "Year")) if date_el is not None else None
        month = _opt_int(child_text(date_el, "Month")) if date_el is not None else None
        day = _opt_int(child_text(date_el, "Day")) if date_el is not None else None
        if year is None or month is None or day is None:
            continue
        out[variant] = {
            "year": year,
            "month": month,
            "day": day,
            "hour": _opt_int(child_text(time_el, "Hour")) or 0 if time_el is not None else 0,
            "minute": _opt_int(child_text(time_el, "Minute")) or 0 if time_el is not None else 0,
            "second": _opt_int(child_text(time_el, "Second")) or 0 if time_el is not None else 0,
        }
    return out


def parse_hostname(xml: str) -> str:
    """Parse a ``GetHostname`` response and return the hostname string, or ``""``."""
    root = parse_xml(xml)
    if root is None:
        return ""
    name = find_local(root, "Name")
    return name.text.strip() if name is not None and name.text else ""


def _parse_ip_config(el: ET.Element | None) -> dict[str, Any]:
    if el is None:
        return {"enabled": False, "dhcp": "", "addresses": []}
    config = child_local(el, "Config")
    if config is None:
        config = el
    addresses: list[dict[str, Any]] = []
    for kind in ("Manual", "LinkLocal", "FromDHCP", "FromRA"):
        for entry in find_all_local(config, kind):
            ip = child_text(entry, "Address")
            if ip:
                addresses.append(
                    {
                        "address": ip,
                        "prefix_length": _opt_int(child_text(entry, "PrefixLength")),
                        "source": kind,
                    }
                )
    return {
        "enabled": _to_bool(child_text(el, "Enabled")),
        "dhcp": child_text(config, "DHCP"),
        "addresses": addresses,
    }


def parse_network_interfaces(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetNetworkInterfaces`` response.

    Returns a list of interface dicts, each with ``token``, ``enabled`` (bool),
    ``name``, ``hardware_address``, ``mtu``, ``addresses`` (list of IPv4 address
    strings), and ``ipv4``/``ipv6`` config dicts (each ``enabled``, ``dhcp`` and an
    ``addresses`` list of ``{address, prefix_length, source}`` entries).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for iface in find_all_local(root, "NetworkInterfaces"):
        token = iface.attrib.get("token", "")
        enabled = _to_bool(child_text(iface, "Enabled"))
        hw_el = find_local(iface, "HwAddress")
        info_el = find_local(iface, "Info")
        ipv4 = _parse_ip_config(find_local(iface, "IPv4"))
        ipv6 = _parse_ip_config(find_local(iface, "IPv6"))
        out.append(
            {
                "token": token,
                "enabled": enabled,
                "name": child_text(info_el, "Name") if info_el is not None else "",
                "hardware_address": (
                    hw_el.text.strip() if hw_el is not None and hw_el.text else ""
                ),
                "mtu": child_text(info_el, "MTU") if info_el is not None else "",
                "addresses": [entry["address"] for entry in ipv4["addresses"]],
                "ipv4": ipv4,
                "ipv6": ipv6,
            }
        )
    return out


def parse_users(xml: str) -> list[dict[str, str]]:
    """Parse a ``GetUsers`` response into a list of ``{username, user_level}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, str]] = []
    for user in find_all_local(root, "User"):
        out.append(
            {
                "username": child_text(user, "Username"),
                "user_level": child_text(user, "UserLevel"),
            }
        )
    return out


def parse_stream_uri(xml: str) -> str:
    """Parse a ``GetStreamUri`` response and return the ``Uri``/``MediaUri`` value, or ``""``."""
    root = parse_xml(xml)
    if root is None:
        return ""
    for tag in ("Uri", "MediaUri"):
        el = find_local(root, tag)
        if el is not None and el.text:
            return el.text.strip()
    return ""


def parse_snapshot_uri(xml: str) -> str:
    """Parse a ``GetSnapshotUri`` response and return the snapshot URI string, or ``""``."""
    return parse_stream_uri(xml)


def _parse_resolution(el: ET.Element) -> dict[str, int]:
    res_el = child_local(el, "Resolution")
    if res_el is None:
        return {}
    try:
        return {
            "width": int(child_text(res_el, "Width") or "0"),
            "height": int(child_text(res_el, "Height") or "0"),
        }
    except ValueError:
        return {}


def _find_cfg(profile: ET.Element, *names: str) -> ET.Element | None:
    """Find a configuration element by any of its Media1 or Media2 local names."""
    for name in names:
        el = find_local(profile, name)
        if el is not None:
            return el
    return None


def _parse_video_encoder(video_enc: ET.Element) -> dict[str, Any]:
    """Parse a video encoder config from either the Media1 or Media2 shape.

    Media1 nests GovLength/Profile under ``<H264>``/``<H265>`` and rate limits under
    ``<RateControl>`` child elements; Media2 (VideoEncoder2Configuration) carries
    Encoding/GovLength/Profile as attributes and the rate limits as attributes on
    ``RateControl``. This reads whichever is present.
    """
    enc_info: dict[str, Any] = {
        "token": _token(video_enc),
        "name": child_text(video_enc, "Name"),
        "encoding": child_text(video_enc, "Encoding") or video_enc.attrib.get("Encoding", ""),
        "quality": child_text(video_enc, "Quality"),
    }
    res = _parse_resolution(video_enc)
    if res:
        enc_info.update(res)
    rate = child_local(video_enc, "RateControl")
    if rate is not None:
        enc_info["fps_limit"] = _opt_int(
            child_text(rate, "FrameRateLimit") or rate.attrib.get("FrameRateLimit", "")
        )
        enc_info["bitrate_kbps"] = _opt_int(
            child_text(rate, "BitrateLimit") or rate.attrib.get("BitrateLimit", "")
        )
        enc_info["encoding_interval"] = _opt_int(
            child_text(rate, "EncodingInterval") or rate.attrib.get("EncodingInterval", "")
        )
    if "GovLength" in video_enc.attrib:
        enc_info["gop"] = _opt_int(video_enc.attrib.get("GovLength", ""))
    if "Profile" in video_enc.attrib:
        enc_info["profile"] = video_enc.attrib.get("Profile", "")
    h264 = child_local(video_enc, "H264")
    if h264 is not None:
        enc_info["gop"] = _opt_int(child_text(h264, "GovLength"))
        enc_info["h264_profile"] = child_text(h264, "H264Profile")
    h265 = child_local(video_enc, "H265")
    if h265 is not None:
        enc_info["gop"] = _opt_int(child_text(h265, "GovLength"))
        enc_info["h265_profile"] = child_text(h265, "H265Profile")
    return enc_info


def parse_profiles(xml: str) -> list[dict[str, Any]]:
    """Parse ``GetProfiles`` (Media1 *and* Media2) into a list of profile dicts.

    Each profile has ``token`` and ``name`` plus any present sub-configs
    (``video_source``, ``video_encoder``, ``audio_encoder``, ``ptz``, ``metadata``).
    Both the Media1 element names (e.g. ``VideoEncoderConfiguration``) and the Media2
    names nested under ``<Configurations>`` (e.g. ``VideoEncoder``) are recognised.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    profiles: list[dict[str, Any]] = []
    for profile in find_all_local(root, "Profiles"):
        out: dict[str, Any] = {"token": _token(profile), "name": child_text(profile, "Name")}

        video_src = _find_cfg(profile, "VideoSourceConfiguration", "VideoSource")
        if video_src is not None:
            out["video_source"] = {
                "token": _token(video_src),
                "name": child_text(video_src, "Name"),
                "source_token": child_text(video_src, "SourceToken"),
            }

        video_enc = _find_cfg(profile, "VideoEncoderConfiguration", "VideoEncoder")
        if video_enc is not None:
            out["video_encoder"] = _parse_video_encoder(video_enc)

        audio_enc = _find_cfg(profile, "AudioEncoderConfiguration", "AudioEncoder")
        if audio_enc is not None:
            out["audio_encoder"] = {
                "token": _token(audio_enc),
                "encoding": child_text(audio_enc, "Encoding")
                or audio_enc.attrib.get("Encoding", ""),
                "bitrate": child_text(audio_enc, "Bitrate"),
                "sample_rate": child_text(audio_enc, "SampleRate"),
            }

        ptz = _find_cfg(profile, "PTZConfiguration", "PTZ")
        if ptz is not None:
            out["ptz"] = {
                "token": _token(ptz),
                "name": child_text(ptz, "Name"),
                "node_token": child_text(ptz, "NodeToken"),
            }

        meta = _find_cfg(profile, "MetadataConfiguration", "Metadata")
        if meta is not None:
            out["metadata"] = {
                "token": _token(meta),
                "name": child_text(meta, "Name"),
            }
        profiles.append(out)
    return profiles


def parse_video_sources(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetVideoSources`` response.

    Returns a list of dicts, each with ``token`` and any present of ``framerate``
    (float), ``width``/``height`` (int) and ``imaging_token``.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for src in find_all_local(root, "VideoSources"):
        info: dict[str, Any] = {"token": src.attrib.get("token", "")}
        framerate = child_text(src, "Framerate")
        if framerate:
            with contextlib.suppress(ValueError):
                info["framerate"] = float(framerate)
        res = _parse_resolution(src)
        if res:
            info.update(res)
        imaging = child_local(src, "Imaging")
        if imaging is not None:
            info["imaging_token"] = imaging.attrib.get("token", "")
        out.append(info)
    return out


def parse_video_encoder_configurations(xml: str) -> list[dict[str, Any]]:
    """Parse ``GetVideoEncoderConfigurations`` (Media1 and Media2) responses.

    Returns a list of config dicts, each with ``token``, ``name``, ``use_count``,
    ``encoding``, ``quality``, ``session_timeout`` plus any present of ``width``/
    ``height``, ``fps_limit``, ``bitrate_kbps``, ``encoding_interval``, ``gop`` and
    ``h264_profile``/``h265_profile``.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for cfg in find_all_local(root, "Configurations"):
        encoding = child_text(cfg, "Encoding")
        item: dict[str, Any] = {
            "token": cfg.attrib.get("token", ""),
            "name": child_text(cfg, "Name"),
            "use_count": child_text(cfg, "UseCount"),
            "encoding": encoding,
            "quality": child_text(cfg, "Quality"),
            "session_timeout": child_text(cfg, "SessionTimeout"),
        }
        res = _parse_resolution(cfg)
        if res:
            item.update(res)
        rate = child_local(cfg, "RateControl")
        if rate is not None:
            item["fps_limit"] = _opt_int(child_text(rate, "FrameRateLimit"))
            item["bitrate_kbps"] = _opt_int(child_text(rate, "BitrateLimit"))
            item["encoding_interval"] = _opt_int(child_text(rate, "EncodingInterval"))
        media2_gov = cfg.attrib.get("GovLength") or child_text(cfg, "GovLength")
        if media2_gov:
            item["gop"] = _opt_int(media2_gov)
        media2_profile = cfg.attrib.get("Profile") or child_text(cfg, "Profile")
        if media2_profile:
            enc_upper = encoding.upper()
            if enc_upper == "H264":
                item["h264_profile"] = media2_profile
            elif enc_upper in ("H265", "HEVC"):
                item["h265_profile"] = media2_profile
        h264 = child_local(cfg, "H264")
        if h264 is not None:
            gop = _opt_int(child_text(h264, "GovLength"))
            if gop is not None:
                item["gop"] = gop
            h264_profile = child_text(h264, "H264Profile")
            if h264_profile:
                item["h264_profile"] = h264_profile
        h265 = child_local(cfg, "H265")
        if h265 is not None:
            gop = _opt_int(child_text(h265, "GovLength"))
            if gop is not None:
                item["gop"] = gop
            h265_profile = child_text(h265, "H265Profile")
            if h265_profile:
                item["h265_profile"] = h265_profile
        out.append(item)
    return out


def parse_ptz_status(xml: str) -> dict[str, Any]:
    """Parse a PTZ ``GetStatus`` response.

    Returns a dict with any present of ``pan``/``tilt``/``zoom`` (floats),
    ``move_status`` (``{pan_tilt, zoom}``), ``error`` and ``utc_time``.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    out: dict[str, Any] = {}
    position = find_local(root, "Position")
    if position is not None:
        pan_tilt = child_local(position, "PanTilt")
        if pan_tilt is not None:
            try:
                out["pan"] = float(pan_tilt.attrib.get("x", "0"))
                out["tilt"] = float(pan_tilt.attrib.get("y", "0"))
            except ValueError:
                pass
        zoom = child_local(position, "Zoom")
        if zoom is not None:
            with contextlib.suppress(ValueError):
                out["zoom"] = float(zoom.attrib.get("x", "0"))
    move_status = find_local(root, "MoveStatus")
    if move_status is not None:
        out["move_status"] = {
            "pan_tilt": child_text(move_status, "PanTilt"),
            "zoom": child_text(move_status, "Zoom"),
        }
    err = find_local(root, "Error")
    if err is not None and err.text:
        out["error"] = err.text.strip()
    utc_time = find_local(root, "UtcTime")
    if utc_time is not None and utc_time.text:
        out["utc_time"] = utc_time.text.strip()
    return out


def parse_ptz_nodes(xml: str) -> list[dict[str, Any]]:
    """Parse a PTZ ``GetNodes`` response.

    Returns a list of node dicts, each with ``token``, ``fixed_home_position``,
    ``name``, ``max_presets``, ``home_supported`` and an optional ``ranges`` dict
    mapping space labels (e.g. ``absolute_pan_tilt``, ``continuous_zoom``) to range
    dicts (``uri`` plus ``x``/``y`` ``{min, max}`` entries).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    nodes: list[dict[str, Any]] = []
    for node in find_all_local(root, "PTZNode"):
        info: dict[str, Any] = {
            "token": node.attrib.get("token", ""),
            "fixed_home_position": node.attrib.get("FixedHomePosition", ""),
            "name": child_text(node, "Name"),
            "max_presets": child_text(node, "MaximumNumberOfPresets"),
            "home_supported": child_text(node, "HomeSupported"),
        }
        supported = child_local(node, "SupportedPTZSpaces")
        if supported is not None:
            ranges: dict[str, dict[str, Any]] = {}
            for kind, label in (
                ("AbsolutePanTiltPositionSpace", "absolute_pan_tilt"),
                ("AbsoluteZoomPositionSpace", "absolute_zoom"),
                ("RelativePanTiltTranslationSpace", "relative_pan_tilt"),
                ("RelativeZoomTranslationSpace", "relative_zoom"),
                ("ContinuousPanTiltVelocitySpace", "continuous_pan_tilt"),
                ("ContinuousZoomVelocitySpace", "continuous_zoom"),
            ):
                el = find_local(supported, kind)
                if el is None:
                    continue
                ranges[label] = _parse_space_range(el)
            info["ranges"] = ranges
        nodes.append(info)
    return nodes


def _parse_space_range(el: ET.Element) -> dict[str, Any]:
    out: dict[str, Any] = {"uri": child_text(el, "URI")}
    for axis_label, tag in (("x", "XRange"), ("y", "YRange")):
        rng = find_local(el, tag)
        if rng is None:
            continue
        min_v = _opt_float(child_text(rng, "Min"))
        max_v = _opt_float(child_text(rng, "Max"))
        if min_v is None or max_v is None:
            continue
        out[axis_label] = {"min": min_v, "max": max_v}
    return out


def parse_ptz_presets(xml: str) -> list[dict[str, Any]]:
    """Parse a PTZ ``GetPresets`` response.

    Returns a list of preset dicts, each with ``token`` and ``name`` plus any
    present of ``pan``/``tilt``/``zoom`` (floats).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for preset in find_all_local(root, "Preset"):
        token = preset.attrib.get("token", "")
        name = child_text(preset, "Name")
        item: dict[str, Any] = {"token": token, "name": name}
        position = find_local(preset, "PTZPosition")
        if position is not None:
            pt = child_local(position, "PanTilt")
            if pt is not None:
                try:
                    item["pan"] = float(pt.attrib.get("x", "0"))
                    item["tilt"] = float(pt.attrib.get("y", "0"))
                except ValueError:
                    pass
            zoom = child_local(position, "Zoom")
            if zoom is not None:
                with contextlib.suppress(ValueError):
                    item["zoom"] = float(zoom.attrib.get("x", "0"))
        out.append(item)
    return out


def parse_set_preset_token(xml: str) -> str:
    """Parse a ``SetPreset`` response and return the created ``PresetToken``, or ``""``."""
    root = parse_xml(xml)
    if root is None:
        return ""
    token = find_local(root, "PresetToken")
    if token is not None and token.text:
        return token.text.strip()
    return ""


def parse_imaging_settings(xml: str) -> dict[str, Any]:
    """Parse a ``GetImagingSettings`` response.

    Returns a dict with any present of the scalar keys ``Brightness``,
    ``ColorSaturation``, ``Contrast``, ``Sharpness`` (floats); the nested dicts
    ``BacklightCompensation``, ``WideDynamicRange``, ``WhiteBalance``, ``Exposure``
    and ``Focus``; and the ``IrCutFilter`` mode string.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    settings = find_local(root, "ImagingSettings")
    if settings is None:
        return {}
    out: dict[str, Any] = {}
    for scalar in ("Brightness", "ColorSaturation", "Contrast", "Sharpness"):
        el = child_local(settings, scalar)
        if el is not None and el.text:
            with contextlib.suppress(ValueError):
                out[scalar] = float(el.text.strip())
    bl = child_local(settings, "BacklightCompensation")
    if bl is not None:
        bl_out: dict[str, Any] = {}
        mode = child_text(bl, "Mode")
        if mode:
            bl_out["mode"] = mode
        level = child_text(bl, "Level")
        if level:
            with contextlib.suppress(ValueError):
                bl_out["level"] = float(level)
        if bl_out:
            out["BacklightCompensation"] = bl_out
    wdr = child_local(settings, "WideDynamicRange")
    if wdr is not None:
        wdr_out: dict[str, Any] = {}
        mode = child_text(wdr, "Mode")
        if mode:
            wdr_out["mode"] = mode
        level = child_text(wdr, "Level")
        if level:
            with contextlib.suppress(ValueError):
                wdr_out["level"] = float(level)
        if wdr_out:
            out["WideDynamicRange"] = wdr_out
    wb = child_local(settings, "WhiteBalance")
    if wb is not None:
        wb_out: dict[str, Any] = {}
        mode = child_text(wb, "Mode")
        if mode:
            wb_out["mode"] = mode
        for axis in ("CrGain", "CbGain"):
            txt = child_text(wb, axis)
            if txt:
                with contextlib.suppress(ValueError):
                    wb_out[axis.lower()] = float(txt)
        if wb_out:
            out["WhiteBalance"] = wb_out
    exposure = child_local(settings, "Exposure")
    if exposure is not None:
        exp: dict[str, Any] = {}
        for tag in ("Mode", "Priority"):
            txt = child_text(exposure, tag)
            if txt:
                exp[tag.lower()] = txt
        for tag in (
            "MinExposureTime",
            "MaxExposureTime",
            "MinGain",
            "MaxGain",
            "Iris",
            "ExposureTime",
            "Gain",
        ):
            txt = child_text(exposure, tag)
            if txt:
                with contextlib.suppress(ValueError):
                    exp[tag] = float(txt)
        if exp:
            out["Exposure"] = exp
    focus = child_local(settings, "Focus")
    if focus is not None:
        focus_out: dict[str, Any] = {}
        mode = child_text(focus, "AutoFocusMode")
        if mode:
            focus_out["auto_focus_mode"] = mode
        for tag in ("DefaultSpeed", "NearLimit", "FarLimit"):
            txt = child_text(focus, tag)
            if txt:
                with contextlib.suppress(ValueError):
                    focus_out[tag.lower()] = float(txt)
        if focus_out:
            out["Focus"] = focus_out
    ir = child_local(settings, "IrCutFilter")
    if ir is not None and ir.text:
        out["IrCutFilter"] = ir.text.strip()
    return out


def parse_imaging_status(xml: str) -> dict[str, Any]:
    """Parse an imaging ``GetStatus`` response.

    Returns a dict with an optional ``focus`` dict (``position``, ``move_status``,
    ``error``).
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    out: dict[str, Any] = {}
    focus = find_local(root, "FocusStatus20")
    if focus is None:
        focus = find_local(root, "FocusStatus")
    if focus is not None:
        out["focus"] = {
            "position": child_text(focus, "Position"),
            "move_status": child_text(focus, "MoveStatus"),
            "error": child_text(focus, "Error"),
        }
    return out


def _element_to_dict(el: ET.Element) -> Any:
    children = list(el)
    if not children:
        text = (el.text or "").strip()
        attrs = {f"@{_local(k)}": v for k, v in el.attrib.items()}
        if attrs:
            if text:
                attrs["#text"] = text
            return attrs
        return text
    out: dict[str, Any] = {}
    for k, v in el.attrib.items():
        out[f"@{_local(k)}"] = v
    for child in children:
        key = _local(child.tag)
        value = _element_to_dict(child)
        if key in out:
            if isinstance(out[key], list):
                out[key].append(value)
            else:
                out[key] = [out[key], value]
        else:
            out[key] = value
    return out


def parse_dns(xml: str) -> dict[str, Any]:
    """Parse a ``GetDNS`` response.

    Returns a dict with ``from_dhcp`` (bool), ``search_domains`` (list of str) and
    ``servers`` (list of DNS server IP address strings).
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    info = find_local(root, "DNSInformation")
    if info is None:
        return {}
    out: dict[str, Any] = {
        "from_dhcp": _to_bool(child_text(info, "FromDHCP")),
        "search_domains": [
            (el.text or "").strip() for el in find_all_local(info, "SearchDomain") if el.text
        ],
        "servers": [],
    }
    for entry in find_all_local(info, "DNSManual") + find_all_local(info, "DNSFromDHCP"):
        addr = child_text(entry, "IPv4Address") or child_text(entry, "IPv6Address")
        if addr:
            out["servers"].append(addr)
    return out


def parse_audio_sources(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetAudioSources`` response into a list of dicts with ``token`` and optional ``channels`` (int)."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for src in find_all_local(root, "AudioSources"):
        channels = child_text(src, "Channels")
        item: dict[str, Any] = {"token": src.attrib.get("token", "")}
        if channels:
            with contextlib.suppress(ValueError):
                item["channels"] = int(channels)
        out.append(item)
    return out


def parse_audio_outputs(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetAudioOutputs`` response into a list of ``{token}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    return [{"token": el.attrib.get("token", "")} for el in find_all_local(root, "AudioOutputs")]


def parse_audio_output_configurations(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetAudioOutputConfigurations`` response.

    Returns a list of config dicts, each with ``token``, ``name``, ``use_count``,
    ``output_token``, ``send_primacy`` and an optional ``output_level`` (int).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for cfg in find_all_local(root, "Configurations"):
        item: dict[str, Any] = {
            "token": cfg.attrib.get("token", ""),
            "name": child_text(cfg, "Name"),
            "use_count": child_text(cfg, "UseCount"),
            "output_token": child_text(cfg, "OutputToken"),
            "send_primacy": child_text(cfg, "SendPrimacy"),
        }
        level_text = child_text(cfg, "OutputLevel")
        if level_text:
            with contextlib.suppress(ValueError):
                item["output_level"] = int(float(level_text))
        out.append(item)
    return out


def parse_relay_outputs(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetRelayOutputs`` response.

    Returns a list of relay dicts, each with ``token`` and, when properties are
    present, ``mode``, ``delay_time`` and ``idle_state``.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for relay in find_all_local(root, "RelayOutputs"):
        props = child_local(relay, "Properties")
        item: dict[str, Any] = {"token": relay.attrib.get("token", "")}
        if props is not None:
            item["mode"] = child_text(props, "Mode")
            item["delay_time"] = child_text(props, "DelayTime")
            item["idle_state"] = child_text(props, "IdleState")
        out.append(item)
    return out


def parse_network_protocols(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetNetworkProtocols`` response into a list of ``{name, enabled (bool), port (int|None)}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for proto in find_all_local(root, "NetworkProtocols"):
        name = child_text(proto, "Name")
        enabled = _to_bool(child_text(proto, "Enabled"))
        port_text = child_text(proto, "Port")
        port: int | None
        try:
            port = int(port_text) if port_text else None
        except ValueError:
            port = None
        if not name:
            continue
        out.append({"name": name, "enabled": enabled, "port": port})
    return out


def parse_network_default_gateway(xml: str) -> dict[str, list[str]]:
    """Parse a ``GetNetworkDefaultGateway`` response into ``{"ipv4": [...], "ipv6": [...]}`` gateway address lists."""
    root = parse_xml(xml)
    if root is None:
        return {"ipv4": [], "ipv6": []}
    return {
        "ipv4": [(el.text or "").strip() for el in find_all_local(root, "IPv4Address") if el.text],
        "ipv6": [(el.text or "").strip() for el in find_all_local(root, "IPv6Address") if el.text],
    }


def parse_profile_create(xml: str) -> str:
    """Parse a ``CreateProfile`` response and return the new profile's token, or ``""``."""
    root = parse_xml(xml)
    if root is None:
        return ""
    for el in find_all_local(root, "Profile"):
        token = el.attrib.get("token")
        if token:
            return token
    token_el = find_local(root, "ProfileToken")
    if token_el is not None and token_el.text:
        return token_el.text.strip()
    return ""


def parse_ntp(xml: str) -> dict[str, Any]:
    """Parse a ``GetNTP`` response.

    Returns a dict with ``from_dhcp`` (bool) and ``servers`` (list of NTP server
    IPv4/IPv6 address or DNS-name strings).
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    info = find_local(root, "NTPInformation")
    if info is None:
        return {}
    out: dict[str, Any] = {
        "from_dhcp": _to_bool(child_text(info, "FromDHCP")),
        "servers": [],
    }
    for entry in find_all_local(info, "NTPManual") + find_all_local(info, "NTPFromDHCP"):
        addr = (
            child_text(entry, "IPv4Address")
            or child_text(entry, "IPv6Address")
            or child_text(entry, "DNSname")
        )
        if addr:
            out["servers"].append(addr)
    return out


def parse_audio_encoder_configurations(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetAudioEncoderConfigurations`` response.

    Returns a token-deduped list of config dicts, each with ``token``, ``name``,
    ``encoding``, ``bitrate_kbps`` (int|None), ``sample_rate`` (int|None) and
    ``use_count`` (int|None).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for cfg in find_all_local(root, "Configurations") + find_all_local(root, "Configuration"):
        if _local(cfg.tag) not in ("Configurations", "Configuration"):
            continue
        token = cfg.attrib.get("token") or cfg.attrib.get("Token") or ""
        out.append(
            {
                "token": token,
                "name": child_text(cfg, "Name"),
                "encoding": child_text(cfg, "Encoding"),
                "bitrate_kbps": _to_int(child_text(cfg, "Bitrate")),
                "sample_rate": _to_int(child_text(cfg, "SampleRate")),
                "use_count": _to_int(child_text(cfg, "UseCount")),
            }
        )
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        key = item["token"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _to_int(text: str) -> int | None:
    if not text:
        return None
    with contextlib.suppress(ValueError):
        return int(float(text))
    return None


def parse_imaging_options(xml: str) -> dict[str, Any]:
    """Parse an imaging ``GetOptions`` response.

    Returns the ``ImagingOptions20`` (or ``ImagingOptions``) block converted to a
    nested dict, or ``{}`` when absent.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    options = find_local(root, "ImagingOptions20")
    if options is None:
        options = find_local(root, "ImagingOptions")
    if options is None:
        return {}
    result = _element_to_dict(options)
    return result if isinstance(result, dict) else {}


def parse_video_encoder_options(xml: str) -> dict[str, Any]:
    """Parse a ``GetVideoEncoderConfigurationOptions`` response.

    Returns the raw ``Options`` block converted to a nested dict, or ``{}`` when
    absent. See :func:`parse_video_encoder_options_normalized` for a flattened,
    per-encoding shape.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    options = find_local(root, "Options")
    if options is None:
        return {}
    result = _element_to_dict(options)
    return result if isinstance(result, dict) else {}


_ENCODING_ALIASES: dict[str, str] = {
    "H264": "H264",
    "AVC": "H264",
    "H265": "H265",
    "HEVC": "H265",
    "JPEG": "JPEG",
    "MJPEG": "JPEG",
    "MPEG4": "MPV4-ES",
    "MPV4-ES": "MPV4-ES",
}


def _norm_enc(label: str) -> str:
    if not label:
        return ""
    return _ENCODING_ALIASES.get(label.upper(), label)


def _to_int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _to_float_or_none(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _range_from(el: ET.Element | None) -> dict[str, float] | None:
    if el is None:
        return None
    lo = _to_float_or_none(child_text(el, "Min"))
    hi = _to_float_or_none(child_text(el, "Max"))
    if lo is None and hi is None:
        return None
    return {
        "min": lo if lo is not None else 0.0,
        "max": hi if hi is not None else lo or 0.0,
    }


def _resolutions_from(el: ET.Element, tag: str = "ResolutionsAvailable") -> list[dict[str, int]]:
    out: list[dict[str, int]] = []
    for r in find_all_local(el, tag):
        w = _to_int_or_none(child_text(r, "Width"))
        h = _to_int_or_none(child_text(r, "Height"))
        if w and h:
            out.append({"width": w, "height": h})
    return out


def _profiles_from(el: ET.Element, *tags: str) -> list[str]:
    out: list[str] = []
    for tag in tags:
        for p in find_all_local(el, tag):
            text = (p.text or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def _supported_fps_from(el: ET.Element) -> dict[str, float] | None:
    rng = _range_from(child_local(el, "FrameRateRange"))
    if rng is not None:
        return rng
    values = [_to_float_or_none(node.text) for node in find_all_local(el, "FrameRatesSupported")]
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return {"min": min(nums), "max": max(nums)}


def _merge_encoding(target: dict[str, Any], add: dict[str, Any]) -> None:
    for r in add.get("resolutions", []):
        if r not in target["resolutions"]:
            target["resolutions"].append(r)
    for p in add.get("profiles", []):
        if p not in target["profiles"]:
            target["profiles"].append(p)
    for key in ("fps", "bitrate_kbps", "gop", "quality"):
        new = add.get(key)
        if new is None:
            continue
        cur = target.get(key)
        if cur is None:
            target[key] = new
        else:
            target[key] = {
                "min": min(cur["min"], new["min"]),
                "max": max(cur["max"], new["max"]),
            }


def _range_from_attr(text: str | None) -> dict[str, float] | None:
    if not text:
        return None
    parts = text.replace(",", " ").split()
    nums: list[float] = []
    for p in parts:
        try:
            nums.append(float(p))
        except ValueError:
            continue
    if not nums:
        return None
    return {"min": min(nums), "max": max(nums)}


def _profiles_from_attr(text: str | None) -> list[str]:
    if not text:
        return []
    return [p for p in text.replace(",", " ").split() if p]


def _parse_one_options_block(
    block: ET.Element, *, encoding_hint: str = ""
) -> dict[str, Any] | None:
    encoding = _norm_enc(child_text(block, "Encoding") or encoding_hint)
    if not encoding:
        return None
    fps = _supported_fps_from(block) or _range_from_attr(block.attrib.get("FrameRatesSupported"))
    gop = _range_from(child_local(block, "GovLengthRange")) or _range_from_attr(
        block.attrib.get("GovLengthRange")
    )
    profiles = _profiles_from(block, "ProfilesSupported", "H264ProfilesSupported")
    if not profiles:
        profiles = _profiles_from_attr(
            block.attrib.get("ProfilesSupported") or block.attrib.get("H264ProfilesSupported")
        )
    out: dict[str, Any] = {
        "encoding": encoding,
        "resolutions": _resolutions_from(block),
        "fps": fps,
        "bitrate_kbps": _range_from(child_local(block, "BitrateRange")),
        "gop": gop,
        "quality": _range_from(child_local(block, "QualityRange")),
        "profiles": profiles,
    }
    return out


def parse_video_encoder_options_normalized(
    xml: str, *, encoding_hint: str = ""
) -> list[dict[str, Any]]:
    """Normalize a ``GetVideoEncoderConfigurationOptions`` response across Media1/Media2.

    Args:
        xml: The SOAP response body.
        encoding_hint: Encoding label used when the response carries no explicit
            ``Encoding`` (and to synthesize a bare entry when nothing parses).

    Returns:
        A list of per-encoding dicts, each with ``encoding``, ``resolutions`` (list
        of ``{width, height}``), ``fps``, ``bitrate_kbps``, ``gop`` and ``quality``
        (each a ``{min, max}`` range or ``None``), and ``profiles`` (list of str).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    encodings: dict[str, dict[str, Any]] = {}

    def _accept(block_dict: dict[str, Any] | None) -> None:
        if block_dict is None:
            return
        key = block_dict["encoding"]
        if key not in encodings:
            encodings[key] = {
                "encoding": key,
                "resolutions": [],
                "fps": None,
                "bitrate_kbps": None,
                "gop": None,
                "quality": None,
                "profiles": [],
            }
        _merge_encoding(encodings[key], block_dict)

    options_blocks = find_all_local(root, "Options")
    for block in options_blocks:
        own_enc = child_text(block, "Encoding")
        if own_enc:
            _accept(_parse_one_options_block(block, encoding_hint=own_enc))
            continue
        quality_block = _range_from(child_local(block, "QualityRange"))
        for sub_tag, sub_hint in (
            ("H264", "H264"),
            ("H265", "H265"),
            ("HEVC", "H265"),
            ("JPEG", "JPEG"),
            ("MPEG4", "MPV4-ES"),
        ):
            sub = child_local(block, sub_tag)
            if sub is None:
                continue
            parsed = _parse_one_options_block(sub, encoding_hint=sub_hint)
            if parsed is None:
                continue
            if parsed.get("quality") is None and quality_block is not None:
                parsed["quality"] = quality_block
            _accept(parsed)
        extension = child_local(block, "Extension")
        if extension is not None:
            for sub_tag, sub_hint in (
                ("H264", "H264"),
                ("H265", "H265"),
                ("HEVC", "H265"),
                ("JPEG", "JPEG"),
            ):
                sub = child_local(extension, sub_tag)
                if sub is None:
                    continue
                parsed = _parse_one_options_block(sub, encoding_hint=sub_hint)
                if parsed is None:
                    continue
                if parsed.get("quality") is None and quality_block is not None:
                    parsed["quality"] = quality_block
                _accept(parsed)

    if not encodings and encoding_hint:
        _accept(
            {
                "encoding": _norm_enc(encoding_hint),
                "resolutions": [],
                "fps": None,
                "bitrate_kbps": None,
                "gop": None,
                "quality": None,
                "profiles": [],
            }
        )

    return list(encodings.values())


def parse_ptz_configurations(xml: str) -> list[dict[str, Any]]:
    """Parse a PTZ ``GetConfigurations`` response.

    Returns a list of config dicts, each with ``token``, ``name``, ``use_count``
    (int|None), ``node_token``, ``default_pan_tilt_speed`` (nested dict or ``None``)
    and ``default_timeout``.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for cfg in find_all_local(root, "PTZConfiguration") + find_all_local(root, "Configurations"):
        if _local(cfg.tag) not in ("PTZConfiguration", "Configurations"):
            continue
        speed_el = child_local(cfg, "DefaultPTZSpeed")
        out.append(
            {
                "token": cfg.attrib.get("token", ""),
                "name": child_text(cfg, "Name"),
                "use_count": _to_int(child_text(cfg, "UseCount")),
                "node_token": child_text(cfg, "NodeToken"),
                "default_pan_tilt_speed": (
                    _element_to_dict(speed_el) if speed_el is not None else None
                ),
                "default_timeout": child_text(cfg, "DefaultPTZTimeout"),
            }
        )
    return out


def parse_video_analytics_configurations(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetVideoAnalyticsConfigurations`` response into a token-deduped list of ``{token, name, use_count}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for cfg in find_all_local(root, "Configurations") + find_all_local(root, "Configuration"):
        if _local(cfg.tag) not in ("Configurations", "Configuration"):
            continue
        token = cfg.attrib.get("token") or cfg.attrib.get("Token") or ""
        if not token:
            continue
        out.append(
            {
                "token": token,
                "name": child_text(cfg, "Name"),
                "use_count": _to_int(child_text(cfg, "UseCount")),
            }
        )
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        if item["token"] in seen:
            continue
        seen.add(item["token"])
        deduped.append(item)
    return deduped


def _parse_item_params(params_el: ET.Element) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for item in find_all_local(params_el, "SimpleItem"):
        name = item.attrib.get("Name", "")
        if name:
            params[name] = item.attrib.get("Value", "")
    for item in find_all_local(params_el, "ElementItem"):
        name = item.attrib.get("Name", "")
        if not name:
            continue
        children = list(item)
        params[name] = _element_to_dict(children[0]) if children else ""
    return params


def parse_analytics_modules(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetAnalyticsModules`` response.

    Returns a list of module dicts, each with ``name``, ``type`` and ``parameters``
    (a dict of ``SimpleItem``/``ElementItem`` name to value).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for mod in find_all_local(root, "AnalyticsModule"):
        params_el = child_local(mod, "Parameters")
        out.append(
            {
                "name": mod.attrib.get("Name", ""),
                "type": mod.attrib.get("Type", ""),
                "parameters": _parse_item_params(params_el) if params_el is not None else {},
            }
        )
    return out


def parse_rules(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetRules`` response.

    Returns a list of rule dicts, each with ``name``, ``type`` and ``parameters``
    (a dict of ``SimpleItem``/``ElementItem`` name to value).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for rule in find_all_local(root, "Rule"):
        params_el = child_local(rule, "Parameters")
        out.append(
            {
                "name": rule.attrib.get("Name", ""),
                "type": rule.attrib.get("Type", ""),
                "parameters": _parse_item_params(params_el) if params_el is not None else {},
            }
        )
    return out


def parse_event_properties(xml: str) -> dict[str, Any]:
    """Parse a ``GetEventProperties`` response.

    Walks the ``TopicSet`` tree and returns ``{"topics": [...]}``, a sorted list of
    fully-qualified topic path strings (e.g. ``tns1:VideoSource/MotionAlarm``).
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    topic_set = find_local(root, "TopicSet")
    if topic_set is None:
        return {"topics": []}
    topics: list[str] = []

    def walk(el: ET.Element, prefix: str) -> None:
        for child in el:
            local = _local(child.tag)
            if local in ("MessageDescription", "Message"):
                if prefix:
                    topics.append(prefix)
                continue
            if prefix:
                segment = local
            else:
                ns_prefix = _NS_PREFIX.get(_namespace(child.tag), "")
                segment = f"{ns_prefix}:{local}" if ns_prefix else local
            path = f"{prefix}/{segment}" if prefix else segment
            walk(child, path)

    walk(topic_set, "")
    return {"topics": sorted(set(topics))}


def parse_create_pull_point(xml: str) -> dict[str, Any]:
    """Parse a ``CreatePullPointSubscription`` response.

    Returns a dict with ``subscription_url`` (the subscription reference address),
    ``current_time`` and ``termination_time``, or ``{}`` when no reference is present.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    ref = find_local(root, "SubscriptionReference")
    if ref is None:
        return {}
    address = ""
    addr_el = find_local(ref, "Address")
    if addr_el is not None and addr_el.text:
        address = addr_el.text.strip()
    return {
        "subscription_url": address,
        "current_time": _text_of(find_local(root, "CurrentTime")),
        "termination_time": _text_of(find_local(root, "TerminationTime")),
    }


def parse_pull_messages(xml: str) -> dict[str, Any]:
    """Parse a ``PullMessages`` response.

    Returns a dict with ``messages`` (a list of dicts, each ``topic``, ``utc_time``,
    ``property_operation``, ``source`` and ``data`` — the latter two being dicts of
    ``SimpleItem`` name to value) plus ``current_time`` and ``termination_time``.
    """
    root = parse_xml(xml)
    if root is None:
        return {"messages": []}
    messages: list[dict[str, Any]] = []
    for notif in find_all_local(root, "NotificationMessage"):
        topic_el = find_local(notif, "Topic")
        topic = (topic_el.text or "").strip() if topic_el is not None else ""
        msg_el = find_local(notif, "Message")
        if msg_el is None:
            continue
        msg_body = child_local(msg_el, "Message")
        if msg_body is None:
            msg_body = msg_el
        utc_time = msg_body.attrib.get("UtcTime", "")
        property_op = msg_body.attrib.get("PropertyOperation", "")
        source: dict[str, str] = {}
        source_el = child_local(msg_body, "Source")
        if source_el is not None:
            for item in find_all_local(source_el, "SimpleItem"):
                k = item.attrib.get("Name", "")
                v = item.attrib.get("Value", "")
                if k:
                    source[k] = v
        data: dict[str, str] = {}
        data_el = child_local(msg_body, "Data")
        if data_el is not None:
            for item in find_all_local(data_el, "SimpleItem"):
                k = item.attrib.get("Name", "")
                v = item.attrib.get("Value", "")
                if k:
                    data[k] = v
        messages.append(
            {
                "topic": topic,
                "utc_time": utc_time,
                "property_operation": property_op,
                "source": source,
                "data": data,
            }
        )
    return {
        "messages": messages,
        "current_time": _text_of(find_local(root, "CurrentTime")),
        "termination_time": _text_of(find_local(root, "TerminationTime")),
    }


def has_soap_fault(xml: str | bytes) -> bool:
    """Return ``True`` if the response body contains a SOAP fault (1.1 or 1.2)."""
    root = parse_xml(xml)
    if root is None:
        return False
    return find_local(_body(root), "Fault") is not None


def parse_fault(xml: str | bytes) -> str:
    """Extract a human-readable reason from a SOAP fault (SOAP 1.2 *and* 1.1).

    Prefers the SOAP 1.2 ``Reason/Text`` then ``Code/Subcode/Value``; falls back to the
    SOAP 1.1 ``faultstring``/``faultcode`` so ``fault_is_unsupported()`` still works for
    legacy or proxied stacks. Returns ``""`` when there is no fault.
    """
    root = parse_xml(xml)
    if root is None:
        return ""
    fault = find_local(_body(root), "Fault")
    if fault is None:
        return ""
    reason = find_local(fault, "Text")
    if reason is not None and reason.text and reason.text.strip():
        return reason.text.strip()
    code = find_local(fault, "Subcode")
    if code is not None:
        value = child_text(code, "Value")
        if value:
            return value
    for tag in ("faultstring", "faultcode"):
        el = find_local(fault, tag)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return "SOAP Fault"


_UNSUPPORTED_FAULT_MARKERS = (
    "not implemented",
    "notimplemented",
    "not supported",
    "notsupported",
    "actionnotsupported",
    "optionalaction",
    "method not found",
    "notsupportedfunction",
)


def fault_is_unsupported(fault: str) -> bool:
    """Return ``True`` if a fault reason string signals an unsupported/not-implemented operation."""
    normalized = fault.lower()
    return any(marker in normalized for marker in _UNSUPPORTED_FAULT_MARKERS)


def parse_recordings(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetRecordings`` response.

    Returns a list of recording dicts, each with ``token``, ``configuration`` (a
    nested dict) and ``tracks`` (a list of ``{token, configuration}`` dicts).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for item in find_all_local(root, "RecordingItem"):
        config_el = child_local(item, "Configuration")
        tracks: list[dict[str, Any]] = []
        tracks_el = child_local(item, "Tracks")
        if tracks_el is not None:
            for track in find_all_local(tracks_el, "Track"):
                track_cfg = child_local(track, "Configuration")
                tracks.append(
                    {
                        "token": child_text(track, "TrackToken"),
                        "configuration": (
                            _element_to_dict(track_cfg) if track_cfg is not None else {}
                        ),
                    }
                )
        out.append(
            {
                "token": child_text(item, "RecordingToken"),
                "configuration": _element_to_dict(config_el) if config_el is not None else {},
                "tracks": tracks,
            }
        )
    return out


def parse_recording_configuration(xml: str) -> dict[str, Any]:
    """Parse a ``GetRecordingConfiguration`` response into the ``RecordingConfiguration`` block as a nested dict."""
    root = parse_xml(xml)
    if root is None:
        return {}
    config = find_local(root, "RecordingConfiguration")
    if config is None:
        return {}
    result = _element_to_dict(config)
    return result if isinstance(result, dict) else {}


def parse_recording_jobs(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetRecordingJobs`` response into a list of ``{token, configuration}`` dicts (``configuration`` nested)."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for item in find_all_local(root, "JobItem"):
        config_el = child_local(item, "JobConfiguration")
        out.append(
            {
                "token": child_text(item, "JobToken"),
                "configuration": _element_to_dict(config_el) if config_el is not None else {},
            }
        )
    return out


def parse_created_token(xml: str, *, tag: str) -> str:
    """Return the stripped text of the first element named ``tag`` (a created object token), or ``""``.

    Args:
        xml: The SOAP response body.
        tag: Local element name holding the token (e.g. ``RecordingToken``).
    """
    root = parse_xml(xml)
    if root is None:
        return ""
    el = find_local(root, tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def parse_recording_summary(xml: str) -> dict[str, Any]:
    """Parse a ``GetRecordingSummary`` response into the ``Summary`` block as a nested dict, or ``{}``."""
    root = parse_xml(xml)
    if root is None:
        return {}
    summary = find_local(root, "Summary")
    if summary is None:
        return {}
    result = _element_to_dict(summary)
    return result if isinstance(result, dict) else {}


def _parse_search_results(xml: str, *, item_tag: str) -> dict[str, Any]:
    root = parse_xml(xml)
    if root is None:
        return {"state": "", "results": []}
    result_list = find_local(root, "ResultList")
    scope = result_list if result_list is not None else root
    state = child_text(result_list, "SearchState") if result_list is not None else ""
    results = [_element_to_dict(el) for el in find_all_local(scope, item_tag)]
    return {"state": state, "results": results}


def parse_recording_search_results(xml: str) -> dict[str, Any]:
    """Parse a ``GetRecordingSearchResults`` response.

    Returns ``{"state": <SearchState>, "results": [...]}`` where each result is a
    ``RecordingInformation`` element converted to a nested dict.
    """
    return _parse_search_results(xml, item_tag="RecordingInformation")


def parse_event_search_results(xml: str) -> dict[str, Any]:
    """Parse a ``GetEventSearchResults`` response.

    Returns ``{"state": <SearchState>, "results": [...]}`` where each result is a
    ``Result`` element converted to a nested dict.
    """
    return _parse_search_results(xml, item_tag="Result")


def parse_ptz_position_search_results(xml: str) -> dict[str, Any]:
    """Parse a ``GetPTZPositionSearchResults`` response.

    Returns ``{"state": <SearchState>, "results": [...]}`` where each result is a
    ``Result`` element converted to a nested dict.
    """
    return _parse_search_results(xml, item_tag="Result")


def parse_metadata_search_results(xml: str) -> dict[str, Any]:
    """Parse a ``GetMetadataSearchResults`` response.

    Returns ``{"state": <SearchState>, "results": [...]}`` where each result is a
    ``Result`` element converted to a nested dict.
    """
    return _parse_search_results(xml, item_tag="Result")


def parse_replay_configuration(xml: str) -> dict[str, Any]:
    """Parse a ``GetReplayConfiguration`` response into ``{"session_timeout": <SessionTimeout>}``, or ``{}``."""
    root = parse_xml(xml)
    if root is None:
        return {}
    config = find_local(root, "Configuration")
    if config is None:
        return {}
    return {"session_timeout": child_text(config, "SessionTimeout")}


def _direct_texts(parent: ET.Element, name: str) -> list[str]:
    return [
        (el.text or "").strip()
        for el in parent
        if _local(el.tag) == name and el.text and el.text.strip()
    ]


def _osd_to_dict(osd: ET.Element) -> dict[str, Any]:
    out: dict[str, Any] = {
        "token": osd.attrib.get("token", ""),
        "video_source_configuration_token": child_text(osd, "VideoSourceConfigurationToken"),
        "osd_type": child_text(osd, "Type"),
        "position_type": "",
        "pos_x": None,
        "pos_y": None,
        "text_type": "",
        "plain_text": "",
        "font_size": None,
        "date_format": "",
        "time_format": "",
    }
    position = child_local(osd, "Position")
    if position is not None:
        out["position_type"] = child_text(position, "Type")
        pos = child_local(position, "Pos")
        if pos is not None:
            out["pos_x"] = _to_float_or_none(pos.attrib.get("x"))
            out["pos_y"] = _to_float_or_none(pos.attrib.get("y"))
    text = child_local(osd, "TextString")
    if text is not None:
        out["text_type"] = child_text(text, "Type")
        out["plain_text"] = child_text(text, "PlainText")
        out["date_format"] = child_text(text, "DateFormat")
        out["time_format"] = child_text(text, "TimeFormat")
        out["font_size"] = _to_int(child_text(text, "FontSize"))
        font_color = child_local(text, "FontColor")
        color = child_local(font_color, "Color") if font_color is not None else None
        if color is not None:
            out["font_color"] = {_local(k): v for k, v in color.attrib.items()}
    return out


def parse_osds(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetOSDs`` response.

    Returns a list of OSD dicts, each with ``token``,
    ``video_source_configuration_token``, ``osd_type``, ``position_type``,
    ``pos_x``/``pos_y``, ``text_type``, ``plain_text``, ``font_size``,
    ``date_format``, ``time_format`` and an optional ``font_color`` dict.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    return [_osd_to_dict(osd) for osd in find_all_local(root, "OSDs")]


def parse_osd(xml: str) -> dict[str, Any]:
    """Parse a ``GetOSD`` response into a single OSD dict (see :func:`parse_osds`), or ``{}``."""
    root = parse_xml(xml)
    if root is None:
        return {}
    osd = find_local(root, "OSD")
    return _osd_to_dict(osd) if osd is not None else {}


def parse_osd_options(xml: str) -> dict[str, Any]:
    """Parse a ``GetOSDOptions`` response.

    Returns a dict with ``osd_types`` and ``position_options`` (lists of str),
    ``text_types``, ``date_formats`` and ``time_formats`` (lists of str),
    ``font_size_range`` (``{min, max}`` ints or ``None``) and an optional
    ``maximum_number_of_osds`` dict of attribute name to int.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    options = find_local(root, "OSDOptions")
    if options is None:
        return {}
    out: dict[str, Any] = {
        "osd_types": _direct_texts(options, "Type"),
        "position_options": _direct_texts(options, "PositionOption"),
        "text_types": [],
        "font_size_range": None,
        "date_formats": [],
        "time_formats": [],
    }
    text_option = child_local(options, "TextOption")
    if text_option is not None:
        out["text_types"] = _direct_texts(text_option, "Type")
        out["date_formats"] = _direct_texts(text_option, "DateFormat")
        out["time_formats"] = _direct_texts(text_option, "TimeFormat")
        font_size_range = child_local(text_option, "FontSizeRange")
        if font_size_range is not None:
            out["font_size_range"] = {
                "min": _to_int(child_text(font_size_range, "Min")),
                "max": _to_int(child_text(font_size_range, "Max")),
            }
    maximum = child_local(options, "MaximumNumberOfOSDs")
    if maximum is not None:
        out["maximum_number_of_osds"] = {_local(k): _to_int(v) for k, v in maximum.attrib.items()}
    return out


def parse_metadata_configurations(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetMetadataConfigurations`` response.

    Returns a list of config dicts, each with ``token``, ``name``, ``use_count``
    (int|None), ``analytics`` (bool) and an optional ``ptz_status`` dict
    (``status`` and ``position`` bools).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for cfg in find_all_local(root, "Configurations"):
        item: dict[str, Any] = {
            "token": cfg.attrib.get("token", ""),
            "name": child_text(cfg, "Name"),
            "use_count": _to_int(child_text(cfg, "UseCount")),
            "analytics": _to_bool(child_text(cfg, "Analytics")),
        }
        ptz = child_local(cfg, "PTZStatus")
        if ptz is not None:
            item["ptz_status"] = {
                "status": _to_bool(child_text(ptz, "Status")),
                "position": _to_bool(child_text(ptz, "Position")),
            }
        out.append(item)
    return out


def parse_metadata_configuration(xml: str) -> dict[str, Any]:
    """Parse a ``GetMetadataConfiguration`` response into the ``Configuration`` block as a nested dict.

    The ``token`` key is always populated from the element's ``token`` attribute;
    returns ``{}`` when no configuration is present.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    cfg = find_local(root, "Configuration")
    if cfg is None:
        return {}
    result = _element_to_dict(cfg)
    if isinstance(result, dict):
        result.setdefault("token", cfg.attrib.get("token", ""))
        return result
    return {"token": cfg.attrib.get("token", "")}


def parse_digital_inputs(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetDigitalInputs`` response into a list of dicts with ``token`` and optional ``idle_state``."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for di in find_all_local(root, "DigitalInputs"):
        item: dict[str, Any] = {"token": di.attrib.get("token", "")}
        idle = di.attrib.get("IdleState")
        if idle:
            item["idle_state"] = idle
        out.append(item)
    return out


def parse_scopes(xml: str) -> list[dict[str, str]]:
    """Parse a ``GetScopes`` response into a list of ``{scope_def, scope_item}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, str]] = []
    for scope in find_all_local(root, "Scopes"):
        out.append(
            {
                "scope_def": child_text(scope, "ScopeDef"),
                "scope_item": child_text(scope, "ScopeItem"),
            }
        )
    return out


def parse_system_log(xml: str) -> dict[str, str]:
    """Parse a ``GetSystemLog`` response into ``{"string": <log text>}``, or ``{}`` when absent."""
    root = parse_xml(xml)
    if root is None:
        return {}
    log = find_local(root, "SystemLog")
    if log is None:
        return {}
    return {"string": child_text(log, "String")}


def parse_support_information(xml: str) -> dict[str, str]:
    """Parse a ``GetSystemSupportInformation`` response into ``{"string": <text>}``, or ``{}`` when absent."""
    root = parse_xml(xml)
    if root is None:
        return {}
    info = find_local(root, "SupportInformation")
    if info is None:
        return {}
    return {"string": child_text(info, "String")}


def parse_certificates(xml: str) -> list[dict[str, str]]:
    """Parse a ``GetCertificates`` response into a list of ``{certificate_id}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, str]] = []
    for cert in find_all_local(root, "NvtCertificate"):
        out.append({"certificate_id": child_text(cert, "CertificateID")})
    return out


def parse_dot1x_configurations(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetDot1XConfigurations`` response into a list of ``{token, identity, eap_method}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for cfg in find_all_local(root, "Dot1XConfiguration"):
        out.append(
            {
                "token": child_text(cfg, "Dot1XConfigurationToken"),
                "identity": child_text(cfg, "Identity"),
                "eap_method": child_text(cfg, "EAPMethod"),
            }
        )
    return out


def parse_service_capabilities(xml: str) -> dict[str, Any]:
    """Parse a ``GetServiceCapabilities`` response into the ``Capabilities`` block as a nested dict, or ``{}``."""
    root = parse_xml(xml)
    if root is None:
        return {}
    caps = find_local(root, "Capabilities")
    if caps is None:
        return {}
    result = _element_to_dict(caps)
    return result if isinstance(result, dict) else {}


def parse_relay_output_options(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetRelayOutputOptions`` response.

    Returns a list of option dicts, each with ``token``, ``modes`` (list of str)
    and optional ``delay_times`` (list of str) and ``discrete`` (bool).
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for opt in find_all_local(root, "RelayOutputOptions"):
        item: dict[str, Any] = {"token": opt.attrib.get("token", "")}
        item["modes"] = [(el.text or "").strip() for el in find_all_local(opt, "Mode") if el.text]
        delay = child_local(opt, "DelayTimes")
        if delay is not None and delay.text:
            item["delay_times"] = delay.text.split()
        discrete = child_local(opt, "Discrete")
        if discrete is not None:
            item["discrete"] = _to_bool(discrete.text or "")
        out.append(item)
    return out


def parse_serial_ports(xml: str) -> list[dict[str, str]]:
    """Parse a ``GetSerialPorts`` response into a list of ``{token}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    return [{"token": el.attrib.get("token", "")} for el in find_all_local(root, "SerialPort")]


def parse_named_element(xml: str, name: str) -> dict[str, Any]:
    """Return the first element with local tag ``name`` converted to a nested dict, or ``{}``.

    Args:
        xml: The SOAP response body.
        name: Local element name to locate and convert.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    el = find_local(root, name)
    if el is None:
        return {}
    result = _element_to_dict(el)
    return result if isinstance(result, dict) else {}


def parse_text_element(xml: str, name: str) -> str:
    """Return the stripped text of the first element with local tag ``name``, or ``""``.

    Args:
        xml: The SOAP response body.
        name: Local element name whose text to read.
    """
    root = parse_xml(xml)
    if root is None:
        return ""
    el = find_local(root, name)
    return el.text.strip() if el is not None and el.text else ""


def parse_geo_location(xml: str) -> list[dict[str, float | None]]:
    """Parse a ``GetGeoLocation`` response into a list of ``{lon, lat, elevation}`` dicts (floats or ``None``)."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, float | None]] = []
    for el in find_all_local(root, "Location"):
        out.append(
            {
                "lon": _opt_float(el.attrib.get("lon", "")),
                "lat": _opt_float(el.attrib.get("lat", "")),
                "elevation": _opt_float(el.attrib.get("elevation", "")),
            }
        )
    return out


def parse_imaging_presets(xml: str) -> list[dict[str, str]]:
    """Parse a ``GetCurrentPreset``/``GetPresets`` imaging response into a list of ``{token, type, name}`` dicts."""
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, str]] = []
    for el in find_all_local(root, "Preset"):
        out.append(
            {
                "token": el.attrib.get("token", ""),
                "type": el.attrib.get("type", ""),
                "name": child_text(el, "Name") or el.attrib.get("Name", ""),
            }
        )
    return out


def parse_preset_tours(xml: str) -> list[dict[str, Any]]:
    """Parse a ``GetPresetTours`` response.

    Returns a list of tour dicts, each with ``token``, ``name``, ``auto_start``
    (bool) and an optional ``state`` string from the tour's ``Status``.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for el in find_all_local(root, "PresetTour"):
        item: dict[str, Any] = {
            "token": el.attrib.get("token", ""),
            "name": child_text(el, "Name"),
            "auto_start": _to_bool(child_text(el, "AutoStart")),
        }
        status = child_local(el, "Status")
        if status is not None:
            item["state"] = child_text(status, "State")
        out.append(item)
    return out


def parse_system_uris(xml: str) -> dict[str, Any]:
    """Parse a ``GetSystemUris`` response.

    Returns a dict with any present of ``system_backup_uri``, ``support_info_uri``
    and ``system_log_uris`` (a list of ``{type, uri}`` dicts).
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    out: dict[str, Any] = {}
    for tag, key in (
        ("SystemBackupUri", "system_backup_uri"),
        ("SupportInfoUri", "support_info_uri"),
    ):
        el = find_local(root, tag)
        if el is not None and el.text:
            out[key] = el.text.strip()
    logs = []
    for lu in find_all_local(root, "SystemLogUris"):
        uri = child_text(lu, "Uri")
        if uri:
            logs.append({"type": child_text(lu, "Type"), "uri": uri})
    if logs:
        out["system_log_uris"] = logs
    return out
