"""Builders for ONVIF SOAP request bodies and the enclosing SOAP envelope."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape, quoteattr

WSA_ANONYMOUS = "http://www.w3.org/2005/08/addressing/anonymous"

NS_DECL = (
    'xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
    'xmlns:tmd="http://www.onvif.org/ver10/deviceIO/wsdl" '
    'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
    'xmlns:trt2="http://www.onvif.org/ver20/media/wsdl" '
    'xmlns:tt="http://www.onvif.org/ver10/schema" '
    'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" '
    'xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl" '
    'xmlns:tev="http://www.onvif.org/ver10/events/wsdl" '
    'xmlns:tan="http://www.onvif.org/ver20/analytics/wsdl" '
    'xmlns:trc="http://www.onvif.org/ver10/recording/wsdl" '
    'xmlns:tse="http://www.onvif.org/ver10/search/wsdl" '
    'xmlns:trp="http://www.onvif.org/ver10/replay/wsdl" '
    'xmlns:tac="http://www.onvif.org/ver10/accesscontrol/wsdl" '
    'xmlns:tdc="http://www.onvif.org/ver10/doorcontrol/wsdl" '
    'xmlns:tcr="http://www.onvif.org/ver10/credential/wsdl" '
    'xmlns:pt="http://www.onvif.org/ver10/pacs" '
    'xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" '
    'xmlns:tns1="http://www.onvif.org/ver10/topics" '
    'xmlns:wsa="http://www.w3.org/2005/08/addressing"'
)

XML_PROLOG = '<?xml version="1.0" encoding="UTF-8"?>'


def _ws_security_header(
    username: str,
    password: str,
    clock_offset_s: float = 0.0,
    *,
    use_password_text: bool = False,
    add_timestamp: bool = False,
) -> str:
    now = datetime.now(UTC) + timedelta(seconds=clock_offset_s)
    created = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if use_password_text:
        password_xml = (
            '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-username-token-profile-1.0#PasswordText">'
            f"{escape(password)}</wsse:Password>"
        )
        nonce_xml = ""
    else:
        nonce = secrets.token_bytes(16)
        digest = base64.b64encode(
            hashlib.sha1(
                nonce + created.encode() + password.encode(), usedforsecurity=False
            ).digest()
        ).decode()
        nonce_b64 = base64.b64encode(nonce).decode()
        password_xml = (
            '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
            f"{digest}</wsse:Password>"
        )
        nonce_xml = (
            '<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
            f"{nonce_b64}</wsse:Nonce>"
        )
    timestamp_xml = ""
    if add_timestamp:
        expires = (now + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        timestamp_xml = (
            '<wsu:Timestamp wsu:Id="TS-1">'
            f"<wsu:Created>{created}</wsu:Created><wsu:Expires>{expires}</wsu:Expires>"
            "</wsu:Timestamp>"
        )
    return (
        '<wsse:Security s:mustUnderstand="1" '
        'xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
        'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
        f"{timestamp_xml}"
        f"<wsse:UsernameToken><wsse:Username>{escape(username)}</wsse:Username>"
        f"{password_xml}{nonce_xml}"
        f"<wsu:Created>{created}</wsu:Created>"
        "</wsse:UsernameToken></wsse:Security>"
    )


def build_envelope(
    body_inner: str,
    *,
    username: str = "",
    password: str = "",
    wsa_action: str = "",
    wsa_to: str = "",
    clock_offset_s: float = 0.0,
    use_password_text: bool = False,
    add_timestamp: bool = False,
) -> str:
    """Wrap a SOAP body fragment in a full ONVIF SOAP 1.2 envelope.

    Builds the ``s:Envelope`` with namespace declarations and an ``s:Header``.
    WS-Addressing ``Action``/``MessageID``/``ReplyTo`` are added when ``wsa_action``
    is set, ``To`` when ``wsa_to`` is set, and a WS-Security UsernameToken header
    when ``username`` is provided (digest auth by default, plain text when
    ``use_password_text`` is true). Returns the complete request XML string.
    """
    parts: list[str] = []
    if wsa_action:
        parts.append(f'<wsa:Action s:mustUnderstand="1">{escape(wsa_action)}</wsa:Action>')
        parts.append(f"<wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>")
        parts.append(f"<wsa:ReplyTo><wsa:Address>{WSA_ANONYMOUS}</wsa:Address></wsa:ReplyTo>")
    if wsa_to:
        parts.append(f'<wsa:To s:mustUnderstand="1">{escape(wsa_to)}</wsa:To>')
    if username:
        parts.append(
            _ws_security_header(
                username,
                password,
                clock_offset_s,
                use_password_text=use_password_text,
                add_timestamp=add_timestamp,
            )
        )
    header = f"<s:Header>{''.join(parts)}</s:Header>" if parts else "<s:Header/>"
    return f"{XML_PROLOG}<s:Envelope {NS_DECL}>{header}<s:Body>{body_inner}</s:Body></s:Envelope>"


def device_get_information() -> str:
    """Build a ``GetDeviceInformation`` request for the device service."""
    return "<tds:GetDeviceInformation/>"


def device_get_capabilities() -> str:
    """Build a ``GetCapabilities`` request for all capability categories."""
    return "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>"


def device_get_services(include_capability: bool = False) -> str:
    """Build a ``GetServices`` request; ``include_capability`` toggles per-service capabilities."""
    inc = "true" if include_capability else "false"
    return (
        f"<tds:GetServices><tds:IncludeCapability>{inc}</tds:IncludeCapability></tds:GetServices>"
    )


def device_get_system_date_time() -> str:
    """Build a ``GetSystemDateAndTime`` request for the device service."""
    return "<tds:GetSystemDateAndTime/>"


def device_set_system_date_time(
    *,
    date_time_type: str,
    daylight_savings: bool,
    timezone: str,
    utc_datetime: datetime | None,
) -> str:
    """Build a ``SetSystemDateAndTime`` request.

    ``date_time_type`` is ``Manual`` or ``NTP``; when ``Manual`` and ``utc_datetime``
    is given, the time is emitted as a UTC date/time block. ``daylight_savings`` and
    ``timezone`` (POSIX TZ string) configure the clock.
    """
    tz_inner = f"<tt:TZ>{escape(timezone)}</tt:TZ>" if timezone else "<tt:TZ/>"
    dt_block = ""
    if date_time_type == "Manual" and utc_datetime is not None:
        dt = utc_datetime.astimezone(UTC)
        dt_block = (
            "<tds:UTCDateTime>"
            "<tt:Time>"
            f"<tt:Hour>{dt.hour}</tt:Hour>"
            f"<tt:Minute>{dt.minute}</tt:Minute>"
            f"<tt:Second>{dt.second}</tt:Second>"
            "</tt:Time>"
            "<tt:Date>"
            f"<tt:Year>{dt.year}</tt:Year>"
            f"<tt:Month>{dt.month}</tt:Month>"
            f"<tt:Day>{dt.day}</tt:Day>"
            "</tt:Date>"
            "</tds:UTCDateTime>"
        )
    return (
        "<tds:SetSystemDateAndTime>"
        f"<tds:DateTimeType>{escape(date_time_type)}</tds:DateTimeType>"
        f"<tds:DaylightSavings>{'true' if daylight_savings else 'false'}</tds:DaylightSavings>"
        f"<tds:TimeZone>{tz_inner}</tds:TimeZone>"
        f"{dt_block}"
        "</tds:SetSystemDateAndTime>"
    )


def device_get_hostname() -> str:
    """Build a ``GetHostname`` request for the device service."""
    return "<tds:GetHostname/>"


def device_set_hostname(name: str) -> str:
    """Build a ``SetHostname`` request setting the device hostname to ``name``."""
    return f"<tds:SetHostname><tds:Name>{escape(name)}</tds:Name></tds:SetHostname>"


def device_get_network_interfaces() -> str:
    """Build a ``GetNetworkInterfaces`` request for the device service."""
    return "<tds:GetNetworkInterfaces/>"


def device_get_users() -> str:
    """Build a ``GetUsers`` request for the device service."""
    return "<tds:GetUsers/>"


def device_system_reboot() -> str:
    """Build a ``SystemReboot`` request for the device service."""
    return "<tds:SystemReboot/>"


def media_get_profiles(*, use_media2: bool) -> str:
    """Build a ``GetProfiles`` request using the Media2 or legacy Media service."""
    return (
        "<trt2:GetProfiles><trt2:Type>All</trt2:Type></trt2:GetProfiles>"
        if use_media2
        else "<trt:GetProfiles/>"
    )


def media_get_video_sources(*, use_media2: bool) -> str:
    """Build a ``GetVideoSources`` request using the Media2 or legacy Media service."""
    return "<trt2:GetVideoSources/>" if use_media2 else "<trt:GetVideoSources/>"


def media_get_video_encoder_configurations(*, use_media2: bool) -> str:
    """Build a ``GetVideoEncoderConfigurations`` request (Media2 or legacy Media)."""
    return (
        "<trt2:GetVideoEncoderConfigurations/>"
        if use_media2
        else "<trt:GetVideoEncoderConfigurations/>"
    )


def media_get_audio_encoder_configurations(*, use_media2: bool) -> str:
    """Build a ``GetAudioEncoderConfigurations`` request (Media2 or legacy Media)."""
    return (
        "<trt2:GetAudioEncoderConfigurations/>"
        if use_media2
        else "<trt:GetAudioEncoderConfigurations/>"
    )


def media_get_stream_uri(
    *,
    profile_token: str,
    use_media2: bool,
    stream: str = "RTP-Unicast",
    protocol: str = "RTSP",
    protocol2: str = "RtspUnicast",
) -> str:
    """Build a ``GetStreamUri`` request for a media profile's live stream.

    For Media2 the ``protocol2`` transport (e.g. ``RtspUnicast``) is used; for legacy
    Media the ``stream`` setup and ``protocol`` transport are emitted. ``profile_token``
    selects the profile.
    """
    if use_media2:
        return (
            "<trt2:GetStreamUri>"
            f"<trt2:Protocol>{escape(protocol2)}</trt2:Protocol>"
            f"<trt2:ProfileToken>{escape(profile_token)}</trt2:ProfileToken>"
            "</trt2:GetStreamUri>"
        )
    return (
        "<trt:GetStreamUri>"
        "<trt:StreamSetup>"
        f"<tt:Stream>{escape(stream)}</tt:Stream>"
        f"<tt:Transport><tt:Protocol>{escape(protocol)}</tt:Protocol></tt:Transport>"
        "</trt:StreamSetup>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:GetStreamUri>"
    )


def media_get_snapshot_uri(*, profile_token: str, use_media2: bool) -> str:
    """Build a ``GetSnapshotUri`` request for a profile (Media2 or legacy Media)."""
    if use_media2:
        return (
            "<trt2:GetSnapshotUri>"
            f"<trt2:ProfileToken>{escape(profile_token)}</trt2:ProfileToken>"
            "</trt2:GetSnapshotUri>"
        )
    return (
        "<trt:GetSnapshotUri>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:GetSnapshotUri>"
    )


def media2_get_video_encoder_options(
    *, configuration_token: str = "", profile_token: str = ""
) -> str:
    """Build a Media2 ``GetVideoEncoderConfigurationOptions`` request.

    Either ``configuration_token`` or ``profile_token`` (or both) may be supplied to
    scope the returned options; empty values are omitted.
    """
    parts: list[str] = []
    if configuration_token:
        parts.append(
            f"<trt2:ConfigurationToken>{escape(configuration_token)}</trt2:ConfigurationToken>"
        )
    if profile_token:
        parts.append(f"<trt2:ProfileToken>{escape(profile_token)}</trt2:ProfileToken>")
    return f"<trt2:GetVideoEncoderConfigurationOptions>{''.join(parts)}</trt2:GetVideoEncoderConfigurationOptions>"


def media2_set_video_encoder_configuration(
    *,
    token: str,
    name: str,
    encoding: str,
    width: int,
    height: int,
    quality: float | None,
    fps: int | None,
    bitrate_kbps: int | None,
    gop: int | None,
    h264_profile: str = "",
    h265_profile: str = "",
    use_count: int = 0,
) -> str:
    """Build a Media2 ``SetVideoEncoderConfiguration`` request.

    Emits a configuration identified by ``token`` with the given ``encoding``,
    ``width``/``height`` resolution, and optional ``quality``, ``fps``/``bitrate_kbps``
    rate control, and ``gop`` (GovLength). The H.264/H.265 ``Profile`` attribute is
    chosen from ``h264_profile`` or ``h265_profile`` based on ``encoding``.
    """
    enc_upper = encoding.upper()
    profile = ""
    if enc_upper == "H264":
        profile = h264_profile
    elif enc_upper in ("H265", "HEVC"):
        profile = h265_profile
    config_attrs = f" token={quoteattr(token)} Encoding={quoteattr(encoding)}"
    if gop is not None:
        config_attrs += f' GovLength="{gop}"'
    if profile:
        config_attrs += f" Profile={quoteattr(profile)}"

    parts: list[str] = [
        f"<tt:Name>{escape(name)}</tt:Name>",
        f"<tt:UseCount>{use_count}</tt:UseCount>",
        f"<tt:Resolution><tt:Width>{width}</tt:Width><tt:Height>{height}</tt:Height></tt:Resolution>",
    ]
    if quality is not None:
        parts.append(f"<tt:Quality>{quality}</tt:Quality>")
    rc_attrs = ' ConstantBitRate="false"'
    if fps is not None:
        rc_attrs += f' FrameRateLimit="{fps}"'
    if bitrate_kbps is not None:
        rc_attrs += f' BitrateLimit="{bitrate_kbps}"'
    if fps is not None or bitrate_kbps is not None:
        parts.append(f"<tt:RateControl{rc_attrs}/>")
    return (
        "<trt2:SetVideoEncoderConfiguration>"
        f"<trt2:Configuration{config_attrs}>"
        f"{''.join(parts)}"
        "</trt2:Configuration>"
        "</trt2:SetVideoEncoderConfiguration>"
    )


def media_get_video_encoder_options(*, configuration_token: str, profile_token: str = "") -> str:
    """Build a legacy Media ``GetVideoEncoderConfigurationOptions`` request.

    ``configuration_token`` is required; ``profile_token`` further scopes the options
    when provided.
    """
    parts = [f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"]
    if profile_token:
        parts.append(f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>")
    return f"<trt:GetVideoEncoderConfigurationOptions>{''.join(parts)}</trt:GetVideoEncoderConfigurationOptions>"


def media_set_video_encoder_configuration(
    *,
    token: str,
    name: str,
    encoding: str,
    width: int,
    height: int,
    quality: float,
    fps: int,
    bitrate_kbps: int,
    gop: int,
    h264_profile: str = "",
    use_count: int = 0,
    session_timeout: str = "PT60S",
    force_persistence: bool = True,
) -> str:
    """Build a legacy Media ``SetVideoEncoderConfiguration`` request.

    Emits the configuration named ``name`` (token ``token``) with ``encoding``,
    ``width``/``height`` resolution, ``quality``, rate control (``fps``,
    ``bitrate_kbps``), and ``gop``. An H.264 block with ``h264_profile`` is added for
    H.264 encoding. ``force_persistence`` maps to the ``ForcePersistence`` flag.
    """
    resolution = (
        f"<tt:Resolution>"
        f"<tt:Width>{width}</tt:Width>"
        f"<tt:Height>{height}</tt:Height>"
        f"</tt:Resolution>"
    )
    h264_block = (
        f"<tt:H264><tt:GovLength>{gop}</tt:GovLength>"
        f"<tt:H264Profile>{escape(h264_profile or 'Main')}</tt:H264Profile></tt:H264>"
        if encoding.upper() == "H264"
        else ""
    )
    rate_control = (
        f"<tt:RateControl>"
        f"<tt:FrameRateLimit>{fps}</tt:FrameRateLimit>"
        f"<tt:EncodingInterval>1</tt:EncodingInterval>"
        f"<tt:BitrateLimit>{bitrate_kbps}</tt:BitrateLimit>"
        f"</tt:RateControl>"
    )
    return (
        "<trt:SetVideoEncoderConfiguration>"
        f"<trt:Configuration token={quoteattr(token)}>"
        f"<tt:Name>{escape(name)}</tt:Name>"
        f"<tt:UseCount>{use_count}</tt:UseCount>"
        f"<tt:Encoding>{escape(encoding)}</tt:Encoding>"
        f"{resolution}"
        f"<tt:Quality>{quality}</tt:Quality>"
        f"{rate_control}"
        f"{h264_block}"
        "<tt:Multicast>"
        "<tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>"
        "<tt:Port>0</tt:Port><tt:TTL>0</tt:TTL><tt:AutoStart>false</tt:AutoStart>"
        "</tt:Multicast>"
        f"<tt:SessionTimeout>{session_timeout}</tt:SessionTimeout>"
        "</trt:Configuration>"
        f"<trt:ForcePersistence>{'true' if force_persistence else 'false'}</trt:ForcePersistence>"
        "</trt:SetVideoEncoderConfiguration>"
    )


def ptz_get_nodes() -> str:
    """Build a ``GetNodes`` request for the PTZ service."""
    return "<tptz:GetNodes/>"


def ptz_get_configurations() -> str:
    """Build a ``GetConfigurations`` request for the PTZ service."""
    return "<tptz:GetConfigurations/>"


def ptz_get_status(*, profile_token: str) -> str:
    """Build a ``GetStatus`` request for the PTZ state of ``profile_token``."""
    return (
        "<tptz:GetStatus>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        "</tptz:GetStatus>"
    )


def _vector(pan: float | None, tilt: float | None, zoom: float | None) -> str:
    parts: list[str] = []
    if pan is not None or tilt is not None:
        pan_v = pan if pan is not None else 0.0
        tilt_v = tilt if tilt is not None else 0.0
        parts.append(f'<tt:PanTilt x="{pan_v}" y="{tilt_v}"/>')
    if zoom is not None:
        parts.append(f'<tt:Zoom x="{zoom}"/>')
    return "".join(parts)


def ptz_continuous_move(
    *,
    profile_token: str,
    pan: float | None,
    tilt: float | None,
    zoom: float | None,
    timeout: str = "",
) -> str:
    """Build a ``ContinuousMove`` request driving pan/tilt/zoom at the given velocities.

    ``pan``/``tilt``/``zoom`` are velocity components (omitted axes are left out);
    ``timeout`` is an optional ISO-8601 duration after which the device stops.
    """
    velocity = _vector(pan, tilt, zoom)
    timeout_block = f"<tptz:Timeout>{escape(timeout)}</tptz:Timeout>" if timeout else ""
    return (
        "<tptz:ContinuousMove>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:Velocity>{velocity}</tptz:Velocity>"
        f"{timeout_block}"
        "</tptz:ContinuousMove>"
    )


def ptz_absolute_move(
    *,
    profile_token: str,
    pan: float | None,
    tilt: float | None,
    zoom: float | None,
    speed_pan: float | None = None,
    speed_tilt: float | None = None,
    speed_zoom: float | None = None,
) -> str:
    """Build an ``AbsoluteMove`` request to an absolute pan/tilt/zoom position.

    ``pan``/``tilt``/``zoom`` give the target position; the optional ``speed_*``
    components form an accompanying speed vector when any are set.
    """
    position = _vector(pan, tilt, zoom)
    speed = _vector(speed_pan, speed_tilt, speed_zoom)
    speed_block = f"<tptz:Speed>{speed}</tptz:Speed>" if speed else ""
    return (
        "<tptz:AbsoluteMove>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:Position>{position}</tptz:Position>"
        f"{speed_block}"
        "</tptz:AbsoluteMove>"
    )


def ptz_relative_move(
    *,
    profile_token: str,
    pan: float | None,
    tilt: float | None,
    zoom: float | None,
    speed_pan: float | None = None,
    speed_tilt: float | None = None,
    speed_zoom: float | None = None,
) -> str:
    """Build a ``RelativeMove`` request by a pan/tilt/zoom translation.

    ``pan``/``tilt``/``zoom`` give the relative translation; the optional ``speed_*``
    components form an accompanying speed vector when any are set.
    """
    translation = _vector(pan, tilt, zoom)
    speed = _vector(speed_pan, speed_tilt, speed_zoom)
    speed_block = f"<tptz:Speed>{speed}</tptz:Speed>" if speed else ""
    return (
        "<tptz:RelativeMove>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:Translation>{translation}</tptz:Translation>"
        f"{speed_block}"
        "</tptz:RelativeMove>"
    )


def ptz_stop(*, profile_token: str, pan_tilt: bool, zoom: bool) -> str:
    """Build a ``Stop`` request halting the ``pan_tilt`` and/or ``zoom`` movement."""
    return (
        "<tptz:Stop>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:PanTilt>{'true' if pan_tilt else 'false'}</tptz:PanTilt>"
        f"<tptz:Zoom>{'true' if zoom else 'false'}</tptz:Zoom>"
        "</tptz:Stop>"
    )


def ptz_get_presets(*, profile_token: str) -> str:
    """Build a ``GetPresets`` request listing PTZ presets for ``profile_token``."""
    return (
        "<tptz:GetPresets>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        "</tptz:GetPresets>"
    )


def ptz_set_preset(
    *,
    profile_token: str,
    preset_name: str = "",
    preset_token: str = "",
) -> str:
    """Build a ``SetPreset`` request storing the current position as a preset.

    ``preset_name`` names a new preset; ``preset_token`` targets an existing preset to
    overwrite. Each is omitted when empty.
    """
    name_block = f"<tptz:PresetName>{escape(preset_name)}</tptz:PresetName>" if preset_name else ""
    token_block = (
        f"<tptz:PresetToken>{escape(preset_token)}</tptz:PresetToken>" if preset_token else ""
    )
    return (
        "<tptz:SetPreset>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"{name_block}"
        f"{token_block}"
        "</tptz:SetPreset>"
    )


def ptz_remove_preset(*, profile_token: str, preset_token: str) -> str:
    """Build a ``RemovePreset`` request deleting ``preset_token`` from the profile."""
    return (
        "<tptz:RemovePreset>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:PresetToken>{escape(preset_token)}</tptz:PresetToken>"
        "</tptz:RemovePreset>"
    )


def ptz_goto_preset(
    *,
    profile_token: str,
    preset_token: str,
    speed_pan: float | None = None,
    speed_tilt: float | None = None,
    speed_zoom: float | None = None,
) -> str:
    """Build a ``GotoPreset`` request moving to ``preset_token``.

    The optional ``speed_*`` components form a speed vector when any are set.
    """
    speed = _vector(speed_pan, speed_tilt, speed_zoom)
    speed_block = f"<tptz:Speed>{speed}</tptz:Speed>" if speed else ""
    return (
        "<tptz:GotoPreset>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:PresetToken>{escape(preset_token)}</tptz:PresetToken>"
        f"{speed_block}"
        "</tptz:GotoPreset>"
    )


def ptz_set_home_position(*, profile_token: str) -> str:
    """Build a ``SetHomePosition`` request saving the current position as home."""
    return (
        "<tptz:SetHomePosition>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        "</tptz:SetHomePosition>"
    )


def ptz_goto_home_position(
    *,
    profile_token: str,
    speed_pan: float | None = None,
    speed_tilt: float | None = None,
    speed_zoom: float | None = None,
) -> str:
    """Build a ``GotoHomePosition`` request moving to the stored home position.

    The optional ``speed_*`` components form a speed vector when any are set.
    """
    speed = _vector(speed_pan, speed_tilt, speed_zoom)
    speed_block = f"<tptz:Speed>{speed}</tptz:Speed>" if speed else ""
    return (
        "<tptz:GotoHomePosition>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"{speed_block}"
        "</tptz:GotoHomePosition>"
    )


def imaging_get_settings(*, video_source_token: str) -> str:
    """Build a ``GetImagingSettings`` request for the given video source."""
    return (
        "<timg:GetImagingSettings>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        "</timg:GetImagingSettings>"
    )


def imaging_get_options(*, video_source_token: str) -> str:
    """Build a ``GetOptions`` request for the imaging settings ranges of a video source."""
    return (
        "<timg:GetOptions>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        "</timg:GetOptions>"
    )


def imaging_get_status(*, video_source_token: str) -> str:
    """Build a ``GetStatus`` request for the imaging (focus) status of a video source."""
    return (
        "<timg:GetStatus>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        "</timg:GetStatus>"
    )


def imaging_get_move_options(*, video_source_token: str) -> str:
    """Build a ``GetMoveOptions`` request for the focus move ranges of a video source."""
    return (
        "<timg:GetMoveOptions>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        "</timg:GetMoveOptions>"
    )


def imaging_set_settings(
    *,
    video_source_token: str,
    brightness: float | None = None,
    contrast: float | None = None,
    color_saturation: float | None = None,
    sharpness: float | None = None,
    backlight_compensation_mode: str = "",
    backlight_compensation_level: float | None = None,
    wide_dynamic_range_mode: str = "",
    wide_dynamic_range_level: float | None = None,
    white_balance_mode: str = "",
    white_balance_cr_gain: float | None = None,
    white_balance_cb_gain: float | None = None,
    exposure_mode: str = "",
    exposure_priority: str = "",
    exposure_min_time: int | None = None,
    exposure_max_time: int | None = None,
    exposure_min_gain: float | None = None,
    exposure_max_gain: float | None = None,
    exposure_iris: float | None = None,
    focus_auto_mode: str = "",
    ir_cut_filter: str = "",
    force_persistence: bool = True,
) -> str:
    """Build a ``SetImagingSettings`` request for a video source.

    Only the parameters that are set are emitted, each in the ONVIF schema order:
    backlight compensation, brightness, colour saturation, contrast, exposure,
    focus auto mode, IR cut filter, sharpness, wide dynamic range, and white balance.
    ``force_persistence`` maps to the ``ForcePersistence`` flag.
    """
    fragments: list[str] = []
    if backlight_compensation_mode or backlight_compensation_level is not None:
        bl_parts: list[str] = []
        if backlight_compensation_mode:
            bl_parts.append(f"<tt:Mode>{escape(backlight_compensation_mode)}</tt:Mode>")
        if backlight_compensation_level is not None:
            bl_parts.append(f"<tt:Level>{backlight_compensation_level}</tt:Level>")
        fragments.append(
            f"<tt:BacklightCompensation>{''.join(bl_parts)}</tt:BacklightCompensation>"
        )
    if brightness is not None:
        fragments.append(f"<tt:Brightness>{brightness}</tt:Brightness>")
    if color_saturation is not None:
        fragments.append(f"<tt:ColorSaturation>{color_saturation}</tt:ColorSaturation>")
    if contrast is not None:
        fragments.append(f"<tt:Contrast>{contrast}</tt:Contrast>")
    if (
        exposure_mode
        or exposure_priority
        or any(
            v is not None
            for v in (
                exposure_min_time,
                exposure_max_time,
                exposure_min_gain,
                exposure_max_gain,
                exposure_iris,
            )
        )
    ):
        exp_parts: list[str] = []
        if exposure_mode:
            exp_parts.append(f"<tt:Mode>{escape(exposure_mode)}</tt:Mode>")
        if exposure_priority:
            exp_parts.append(f"<tt:Priority>{escape(exposure_priority)}</tt:Priority>")
        if exposure_min_time is not None:
            exp_parts.append(f"<tt:MinExposureTime>{exposure_min_time}</tt:MinExposureTime>")
        if exposure_max_time is not None:
            exp_parts.append(f"<tt:MaxExposureTime>{exposure_max_time}</tt:MaxExposureTime>")
        if exposure_min_gain is not None:
            exp_parts.append(f"<tt:MinGain>{exposure_min_gain}</tt:MinGain>")
        if exposure_max_gain is not None:
            exp_parts.append(f"<tt:MaxGain>{exposure_max_gain}</tt:MaxGain>")
        if exposure_iris is not None:
            exp_parts.append(f"<tt:Iris>{exposure_iris}</tt:Iris>")
        fragments.append(f"<tt:Exposure>{''.join(exp_parts)}</tt:Exposure>")
    if focus_auto_mode:
        fragments.append(
            f"<tt:Focus><tt:AutoFocusMode>{escape(focus_auto_mode)}</tt:AutoFocusMode></tt:Focus>"
        )
    if ir_cut_filter:
        fragments.append(f"<tt:IrCutFilter>{escape(ir_cut_filter)}</tt:IrCutFilter>")
    if sharpness is not None:
        fragments.append(f"<tt:Sharpness>{sharpness}</tt:Sharpness>")
    if wide_dynamic_range_mode or wide_dynamic_range_level is not None:
        wdr_parts: list[str] = []
        if wide_dynamic_range_mode:
            wdr_parts.append(f"<tt:Mode>{escape(wide_dynamic_range_mode)}</tt:Mode>")
        if wide_dynamic_range_level is not None:
            wdr_parts.append(f"<tt:Level>{wide_dynamic_range_level}</tt:Level>")
        fragments.append(f"<tt:WideDynamicRange>{''.join(wdr_parts)}</tt:WideDynamicRange>")
    if white_balance_mode or white_balance_cr_gain is not None or white_balance_cb_gain is not None:
        wb_parts: list[str] = []
        if white_balance_mode:
            wb_parts.append(f"<tt:Mode>{escape(white_balance_mode)}</tt:Mode>")
        if white_balance_cr_gain is not None:
            wb_parts.append(f"<tt:CrGain>{white_balance_cr_gain}</tt:CrGain>")
        if white_balance_cb_gain is not None:
            wb_parts.append(f"<tt:CbGain>{white_balance_cb_gain}</tt:CbGain>")
        fragments.append(f"<tt:WhiteBalance>{''.join(wb_parts)}</tt:WhiteBalance>")

    body = "".join(fragments)
    return (
        "<timg:SetImagingSettings>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        f"<timg:ImagingSettings>{body}</timg:ImagingSettings>"
        f"<timg:ForcePersistence>{'true' if force_persistence else 'false'}</timg:ForcePersistence>"
        "</timg:SetImagingSettings>"
    )


def imaging_move(
    *,
    video_source_token: str,
    focus_continuous: float | None = None,
    focus_absolute: float | None = None,
    focus_relative: float | None = None,
    speed: float | None = None,
) -> str:
    """Build an imaging ``Move`` request driving the focus of a video source.

    Exactly one focus mode is emitted based on which argument is set:
    ``focus_continuous`` (continuous at that speed), ``focus_absolute`` (to a position),
    or ``focus_relative`` (by a distance); ``speed`` applies to the absolute/relative
    modes.
    """
    if focus_continuous is not None:
        speed_attr = f' x="{focus_continuous}"'
        focus_block = f"<tt:Continuous{speed_attr}/>"
    elif focus_absolute is not None:
        speed_block = f'<tt:Speed x="{speed}"/>' if speed is not None else ""
        focus_block = f'<tt:Absolute><tt:Position x="{focus_absolute}"/>{speed_block}</tt:Absolute>'
    elif focus_relative is not None:
        speed_block = f'<tt:Speed x="{speed}"/>' if speed is not None else ""
        focus_block = f'<tt:Relative><tt:Distance x="{focus_relative}"/>{speed_block}</tt:Relative>'
    else:
        focus_block = ""
    return (
        "<timg:Move>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        f"<timg:Focus>{focus_block}</timg:Focus>"
        "</timg:Move>"
    )


def imaging_stop(*, video_source_token: str) -> str:
    """Build an imaging ``Stop`` request halting focus movement on a video source."""
    return (
        "<timg:Stop>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        "</timg:Stop>"
    )


def device_get_dns() -> str:
    """Build a ``GetDNS`` request for the device service."""
    return "<tds:GetDNS/>"


def device_set_dns(*, from_dhcp: bool, ipv4_servers: list[str], search_domains: list[str]) -> str:
    """Build a ``SetDNS`` request.

    ``from_dhcp`` selects DHCP-provided DNS; otherwise ``ipv4_servers`` are emitted as
    manual IPv4 DNS servers. ``search_domains`` sets the DNS search list.
    """
    servers = "".join(
        f"<tt:DNSManual><tt:Type>IPv4</tt:Type><tt:IPv4Address>{escape(s)}</tt:IPv4Address></tt:DNSManual>"
        for s in ipv4_servers
    )
    domains = "".join(f"<tt:SearchDomain>{escape(d)}</tt:SearchDomain>" for d in search_domains)
    return (
        "<tds:SetDNS>"
        f"<tds:FromDHCP>{'true' if from_dhcp else 'false'}</tds:FromDHCP>"
        f"{domains}"
        f"{servers}"
        "</tds:SetDNS>"
    )


def device_get_ntp() -> str:
    """Build a ``GetNTP`` request for the device service."""
    return "<tds:GetNTP/>"


def device_set_ntp(*, from_dhcp: bool, ipv4_servers: list[str]) -> str:
    """Build a ``SetNTP`` request.

    ``from_dhcp`` uses DHCP-provided NTP servers; otherwise ``ipv4_servers`` are
    emitted as manual IPv4 NTP servers.
    """
    servers = "".join(
        f"<tt:NTPManual><tt:Type>IPv4</tt:Type><tt:IPv4Address>{escape(s)}</tt:IPv4Address></tt:NTPManual>"
        for s in ipv4_servers
    )
    return (
        "<tds:SetNTP>"
        f"<tds:FromDHCP>{'true' if from_dhcp else 'false'}</tds:FromDHCP>"
        f"{servers}"
        "</tds:SetNTP>"
    )


def device_create_users(*, username: str, password: str, user_level: str = "User") -> str:
    """Build a ``CreateUsers`` request adding one user with ``username``, ``password`` and ``user_level``."""
    return (
        "<tds:CreateUsers>"
        "<tds:User>"
        f"<tt:Username>{escape(username)}</tt:Username>"
        f"<tt:Password>{escape(password)}</tt:Password>"
        f"<tt:UserLevel>{escape(user_level)}</tt:UserLevel>"
        "</tds:User>"
        "</tds:CreateUsers>"
    )


def device_set_user(*, username: str, password: str, user_level: str = "User") -> str:
    """Build a ``SetUser`` request updating ``username`` and ``user_level``.

    The password element is omitted when ``password`` is empty.
    """
    pwd = f"<tt:Password>{escape(password)}</tt:Password>" if password else ""
    return (
        "<tds:SetUser>"
        "<tds:User>"
        f"<tt:Username>{escape(username)}</tt:Username>"
        f"{pwd}"
        f"<tt:UserLevel>{escape(user_level)}</tt:UserLevel>"
        "</tds:User>"
        "</tds:SetUser>"
    )


def device_delete_users(*, usernames: list[str]) -> str:
    """Build a ``DeleteUsers`` request removing every account named in ``usernames``."""
    names = "".join(f"<tds:Username>{escape(n)}</tds:Username>" for n in usernames)
    return f"<tds:DeleteUsers>{names}</tds:DeleteUsers>"


def device_set_network_interface(
    *,
    token: str,
    enabled: bool,
    dhcp: bool,
    ipv4_address: str = "",
    prefix_length: int = 24,
    mtu: int | None = None,
) -> str:
    """Build a ``SetNetworkInterfaces`` request for ``token``.

    Enables/disables the interface, selects DHCP or a manual ``ipv4_address`` with
    ``prefix_length``, and sets the ``mtu`` when provided.
    """
    ipv4_parts: list[str] = [f"<tt:Enabled>{'true' if enabled else 'false'}</tt:Enabled>"]
    if dhcp:
        ipv4_parts.append("<tt:DHCP>true</tt:DHCP>")
    else:
        ipv4_parts.append("<tt:DHCP>false</tt:DHCP>")
        if ipv4_address:
            ipv4_parts.append(
                "<tt:Manual>"
                f"<tt:Address>{escape(ipv4_address)}</tt:Address>"
                f"<tt:PrefixLength>{int(prefix_length)}</tt:PrefixLength>"
                "</tt:Manual>"
            )
    info_block = ""
    if mtu is not None:
        info_block = f"<tt:Info><tt:MTU>{int(mtu)}</tt:MTU></tt:Info>"
    return (
        "<tds:SetNetworkInterfaces>"
        f"<tds:InterfaceToken>{escape(token)}</tds:InterfaceToken>"
        "<tds:NetworkInterface>"
        f"<tt:Enabled>{'true' if enabled else 'false'}</tt:Enabled>"
        f"{info_block}"
        "<tt:IPv4>"
        f"{''.join(ipv4_parts)}"
        "</tt:IPv4>"
        "</tds:NetworkInterface>"
        "</tds:SetNetworkInterfaces>"
    )


def device_get_network_protocols() -> str:
    """Build a ``GetNetworkProtocols`` request for the device service."""
    return "<tds:GetNetworkProtocols/>"


def device_set_network_protocols(*, protocols: list[dict[str, object]]) -> str:
    """Build a ``SetNetworkProtocols`` request.

    Each dict in ``protocols`` may hold ``name`` (required), ``enabled`` and an optional
    ``port``; entries without a name are skipped.
    """
    parts: list[str] = []
    for p in protocols:
        name = str(p.get("name", ""))
        if not name:
            continue
        enabled = bool(p.get("enabled"))
        port = p.get("port")
        port_xml = f"<tt:Port>{int(port)}</tt:Port>" if isinstance(port, (int, float, str)) else ""
        parts.append(
            "<tds:NetworkProtocols>"
            f"<tt:Name>{escape(name)}</tt:Name>"
            f"<tt:Enabled>{'true' if enabled else 'false'}</tt:Enabled>"
            f"{port_xml}"
            "</tds:NetworkProtocols>"
        )
    return f"<tds:SetNetworkProtocols>{''.join(parts)}</tds:SetNetworkProtocols>"


def device_get_network_default_gateway() -> str:
    """Build a ``GetNetworkDefaultGateway`` request for the device service."""
    return "<tds:GetNetworkDefaultGateway/>"


def device_set_network_default_gateway(*, ipv4_addresses: list[str]) -> str:
    """Build a ``SetNetworkDefaultGateway`` request setting the IPv4 gateways to ``ipv4_addresses``."""
    addrs = "".join(f"<tds:IPv4Address>{escape(a)}</tds:IPv4Address>" for a in ipv4_addresses)
    return f"<tds:SetNetworkDefaultGateway>{addrs}</tds:SetNetworkDefaultGateway>"


def device_set_system_factory_default(*, hard: bool = False) -> str:
    """Build a ``SetSystemFactoryDefault`` request; ``hard`` selects a ``Hard`` reset, else ``Soft``."""
    mode = "Hard" if hard else "Soft"
    return (
        "<tds:SetSystemFactoryDefault>"
        f"<tds:FactoryDefault>{mode}</tds:FactoryDefault>"
        "</tds:SetSystemFactoryDefault>"
    )


def media_create_profile(*, name: str, token: str = "") -> str:
    """Build a legacy Media ``CreateProfile`` request named ``name``; ``token`` sets the profile token when given."""
    token_attr = f" token={quoteattr(token)}" if token else ""
    return f"<trt:CreateProfile{token_attr}><trt:Name>{escape(name)}</trt:Name></trt:CreateProfile>"


def media_delete_profile(*, profile_token: str) -> str:
    """Build a legacy Media ``DeleteProfile`` request removing ``profile_token``."""
    return (
        "<trt:DeleteProfile>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:DeleteProfile>"
    )


def media_add_video_source_configuration(*, profile_token: str, configuration_token: str) -> str:
    """Build an ``AddVideoSourceConfiguration`` request adding ``configuration_token`` to ``profile_token``."""
    return (
        "<trt:AddVideoSourceConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:AddVideoSourceConfiguration>"
    )


def media_add_video_encoder_configuration(*, profile_token: str, configuration_token: str) -> str:
    """Build an ``AddVideoEncoderConfiguration`` request adding ``configuration_token`` to ``profile_token``."""
    return (
        "<trt:AddVideoEncoderConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:AddVideoEncoderConfiguration>"
    )


def media_remove_video_encoder_configuration(*, profile_token: str) -> str:
    """Build a ``RemoveVideoEncoderConfiguration`` request removing the video encoder config from ``profile_token``."""
    return (
        "<trt:RemoveVideoEncoderConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:RemoveVideoEncoderConfiguration>"
    )


def media_add_ptz_configuration(*, profile_token: str, configuration_token: str) -> str:
    """Build an ``AddPTZConfiguration`` request adding ``configuration_token`` to ``profile_token``."""
    return (
        "<trt:AddPTZConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:AddPTZConfiguration>"
    )


def media_remove_ptz_configuration(*, profile_token: str) -> str:
    """Build a ``RemovePTZConfiguration`` request removing the PTZ config from ``profile_token``."""
    return (
        "<trt:RemovePTZConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:RemovePTZConfiguration>"
    )


def media_set_audio_encoder_configuration(
    *,
    token: str,
    name: str,
    encoding: str,
    bitrate_kbps: int,
    sample_rate: int,
    use_count: int = 0,
    session_timeout: str = "PT60S",
    force_persistence: bool = True,
) -> str:
    """Build a legacy Media ``SetAudioEncoderConfiguration`` request.

    Emits configuration ``token`` with ``encoding``, ``bitrate_kbps`` and ``sample_rate``;
    ``force_persistence`` maps to the ``ForcePersistence`` flag.
    """
    return (
        "<trt:SetAudioEncoderConfiguration>"
        f"<trt:Configuration token={quoteattr(token)}>"
        f"<tt:Name>{escape(name)}</tt:Name>"
        f"<tt:UseCount>{use_count}</tt:UseCount>"
        f"<tt:Encoding>{escape(encoding)}</tt:Encoding>"
        f"<tt:Bitrate>{bitrate_kbps}</tt:Bitrate>"
        f"<tt:SampleRate>{sample_rate}</tt:SampleRate>"
        "<tt:Multicast>"
        "<tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>"
        "<tt:Port>0</tt:Port><tt:TTL>0</tt:TTL><tt:AutoStart>false</tt:AutoStart>"
        "</tt:Multicast>"
        f"<tt:SessionTimeout>{session_timeout}</tt:SessionTimeout>"
        "</trt:Configuration>"
        f"<trt:ForcePersistence>{'true' if force_persistence else 'false'}</trt:ForcePersistence>"
        "</trt:SetAudioEncoderConfiguration>"
    )


def media_get_audio_sources() -> str:
    """Build a ``GetAudioSources`` request for the legacy Media service."""
    return "<trt:GetAudioSources/>"


def media_get_audio_outputs() -> str:
    """Build a ``GetAudioOutputs`` request for the legacy Media service."""
    return "<trt:GetAudioOutputs/>"


def media_get_audio_output_configurations() -> str:
    """Build a ``GetAudioOutputConfigurations`` request for the legacy Media service."""
    return "<trt:GetAudioOutputConfigurations/>"


def media_set_audio_output_configuration(
    *,
    token: str,
    name: str,
    output_token: str,
    output_level: int,
    send_primacy: str = "",
    use_count: int = 0,
    force_persistence: bool = True,
) -> str:
    """Build a ``SetAudioOutputConfiguration`` request for ``token`` targeting ``output_token`` at ``output_level``.

    ``send_primacy`` is emitted only when set.
    """
    primacy_xml = f"<tt:SendPrimacy>{escape(send_primacy)}</tt:SendPrimacy>" if send_primacy else ""
    return (
        "<trt:SetAudioOutputConfiguration>"
        f"<trt:Configuration token={quoteattr(token)}>"
        f"<tt:Name>{escape(name)}</tt:Name>"
        f"<tt:UseCount>{use_count}</tt:UseCount>"
        f"<tt:OutputToken>{escape(output_token)}</tt:OutputToken>"
        f"{primacy_xml}"
        f"<tt:OutputLevel>{int(output_level)}</tt:OutputLevel>"
        "</trt:Configuration>"
        f"<trt:ForcePersistence>{'true' if force_persistence else 'false'}</trt:ForcePersistence>"
        "</trt:SetAudioOutputConfiguration>"
    )


def device_get_relay_outputs(*, use_deviceio: bool = False) -> str:
    """Build a ``GetRelayOutputs`` request on the DeviceIO (``tmd``) or Device (``tds``) service per ``use_deviceio``."""
    ns = "tmd" if use_deviceio else "tds"
    return f"<{ns}:GetRelayOutputs/>"


def device_set_relay_output_state(
    *, token: str, logical_state: str, use_deviceio: bool = False
) -> str:
    """Build a ``SetRelayOutputState`` request setting ``token`` to ``logical_state``, via DeviceIO or Device service."""
    ns = "tmd" if use_deviceio else "tds"
    return (
        f"<{ns}:SetRelayOutputState>"
        f"<{ns}:RelayOutputToken>{escape(token)}</{ns}:RelayOutputToken>"
        f"<{ns}:LogicalState>{escape(logical_state)}</{ns}:LogicalState>"
        f"</{ns}:SetRelayOutputState>"
    )


def device_set_relay_output_settings(
    *,
    token: str,
    mode: str,
    delay_time: str = "PT1S",
    idle_state: str = "open",
    use_deviceio: bool = False,
) -> str:
    """Build a ``SetRelayOutputSettings`` request configuring ``token`` with ``mode``, ``delay_time`` and ``idle_state``, via DeviceIO or Device service."""
    settings = (
        f"<tt:Mode>{escape(mode)}</tt:Mode>"
        f"<tt:DelayTime>{escape(delay_time)}</tt:DelayTime>"
        f"<tt:IdleState>{escape(idle_state)}</tt:IdleState>"
    )
    if use_deviceio:
        return (
            "<tmd:SetRelayOutputSettings>"
            f"<tmd:RelayOutput token={quoteattr(token)}>"
            f"<tt:Properties>{settings}</tt:Properties>"
            "</tmd:RelayOutput>"
            "</tmd:SetRelayOutputSettings>"
        )
    return (
        "<tds:SetRelayOutputSettings>"
        f"<tds:RelayOutputToken>{escape(token)}</tds:RelayOutputToken>"
        f"<tds:Properties>{settings}</tds:Properties>"
        "</tds:SetRelayOutputSettings>"
    )


def media_get_video_analytics_configurations(*, use_media2: bool) -> str:
    """Build a ``GetVideoAnalyticsConfigurations`` request (Media2 or legacy Media)."""
    return (
        "<trt2:GetVideoAnalyticsConfigurations/>"
        if use_media2
        else "<trt:GetVideoAnalyticsConfigurations/>"
    )


def analytics_get_supported_rules(*, configuration_token: str) -> str:
    """Build a ``GetSupportedRules`` request for the analytics ``configuration_token``."""
    return (
        "<tan:GetSupportedRules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        "</tan:GetSupportedRules>"
    )


def analytics_get_rules(*, configuration_token: str) -> str:
    """Build a ``GetRules`` request for the analytics ``configuration_token``."""
    return (
        "<tan:GetRules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        "</tan:GetRules>"
    )


def analytics_get_supported_analytics_modules(*, configuration_token: str) -> str:
    """Build a ``GetSupportedAnalyticsModules`` request for the analytics ``configuration_token``."""
    return (
        "<tan:GetSupportedAnalyticsModules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        "</tan:GetSupportedAnalyticsModules>"
    )


def analytics_get_analytics_modules(*, configuration_token: str) -> str:
    """Build a ``GetAnalyticsModules`` request for the analytics ``configuration_token``."""
    return (
        "<tan:GetAnalyticsModules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        "</tan:GetAnalyticsModules>"
    )


def events_get_service_capabilities() -> str:
    """Build a ``GetServiceCapabilities`` request for the events service."""
    return "<tev:GetServiceCapabilities/>"


def events_get_event_properties() -> str:
    """Build a ``GetEventProperties`` request listing the event topics the device supports."""
    return "<tev:GetEventProperties/>"


def events_create_pull_point_subscription(
    *, termination_time: str = "PT60S", topic_filter: str = ""
) -> str:
    """Build a ``CreatePullPointSubscription`` request.

    Sets ``InitialTerminationTime`` to ``termination_time`` and, when ``topic_filter``
    is given, adds a concrete-set topic filter.
    """
    filter_xml = ""
    if topic_filter:
        filter_xml = (
            "<tev:Filter>"
            '<wsnt:TopicExpression Dialect="http://www.onvif.org/ver10/tev/'
            'topicExpression/ConcreteSet">'
            f"{escape(topic_filter)}</wsnt:TopicExpression>"
            "</tev:Filter>"
        )
    return (
        "<tev:CreatePullPointSubscription>"
        f"{filter_xml}"
        f"<tev:InitialTerminationTime>{escape(termination_time)}</tev:InitialTerminationTime>"
        "</tev:CreatePullPointSubscription>"
    )


def events_pull_messages(*, timeout: str = "PT5S", message_limit: int = 20) -> str:
    """Build a ``PullMessages`` request waiting up to ``timeout`` for at most ``message_limit`` messages."""
    return (
        "<tev:PullMessages>"
        f"<tev:Timeout>{escape(timeout)}</tev:Timeout>"
        f"<tev:MessageLimit>{int(message_limit)}</tev:MessageLimit>"
        "</tev:PullMessages>"
    )


def events_renew(*, termination_time: str = "PT60S") -> str:
    """Build a WS-Notification ``Renew`` request extending the subscription to ``termination_time``."""
    return (
        "<wsnt:Renew>"
        f"<wsnt:TerminationTime>{escape(termination_time)}</wsnt:TerminationTime>"
        "</wsnt:Renew>"
    )


def events_unsubscribe() -> str:
    """Build a WS-Notification ``Unsubscribe`` request ending the current subscription."""
    return "<wsnt:Unsubscribe/>"


def _simple_items_xml(parameters: dict[str, object]) -> str:
    return "".join(
        f"<tt:SimpleItem Name={quoteattr(str(name))} Value={quoteattr(str(value))}/>"
        for name, value in parameters.items()
    )


def _config_items_xml(items: list[dict[str, object]], *, wrapper_tag: str) -> str:
    parts: list[str] = []
    for item in items:
        name = str(item.get("name", ""))
        type_ = str(item.get("type", ""))
        params = item.get("parameters") or {}
        params_xml = _simple_items_xml(params) if isinstance(params, dict) else ""
        type_attr = f" Type={quoteattr(type_)}" if type_ else ""
        parts.append(
            f"<{wrapper_tag} Name={quoteattr(name)}{type_attr}>"
            f"<tt:Parameters>{params_xml}</tt:Parameters>"
            f"</{wrapper_tag}>"
        )
    return "".join(parts)


def _recording_configuration_xml(
    *,
    source_id: str,
    source_name: str,
    source_location: str = "",
    source_description: str = "",
    source_address: str = "",
    content: str = "",
    max_retention: str = "PT0S",
) -> str:
    return (
        "<tt:Source>"
        f"<tt:SourceId>{escape(source_id)}</tt:SourceId>"
        f"<tt:Name>{escape(source_name)}</tt:Name>"
        f"<tt:Location>{escape(source_location)}</tt:Location>"
        f"<tt:Description>{escape(source_description)}</tt:Description>"
        f"<tt:Address>{escape(source_address)}</tt:Address>"
        "</tt:Source>"
        f"<tt:Content>{escape(content)}</tt:Content>"
        f"<tt:MaximumRetentionTime>{escape(max_retention)}</tt:MaximumRetentionTime>"
    )


def recording_get_recordings() -> str:
    """Build a ``GetRecordings`` request for the recording service."""
    return "<trc:GetRecordings/>"


def recording_create_recording(
    *,
    source_id: str,
    source_name: str,
    source_location: str = "",
    source_description: str = "",
    source_address: str = "",
    content: str = "",
    max_retention: str = "PT0S",
) -> str:
    """Build a ``CreateRecording`` request.

    Builds the recording configuration from the ``source_*`` fields, ``content`` and
    ``max_retention`` (ISO-8601 duration).
    """
    config = _recording_configuration_xml(
        source_id=source_id,
        source_name=source_name,
        source_location=source_location,
        source_description=source_description,
        source_address=source_address,
        content=content,
        max_retention=max_retention,
    )
    return (
        "<trc:CreateRecording>"
        f"<trc:RecordingConfiguration>{config}</trc:RecordingConfiguration>"
        "</trc:CreateRecording>"
    )


def recording_delete_recording(*, recording_token: str) -> str:
    """Build a ``DeleteRecording`` request removing ``recording_token``."""
    return (
        "<trc:DeleteRecording>"
        f"<trc:RecordingToken>{escape(recording_token)}</trc:RecordingToken>"
        "</trc:DeleteRecording>"
    )


def recording_get_recording_configuration(*, recording_token: str) -> str:
    """Build a ``GetRecordingConfiguration`` request for ``recording_token``."""
    return (
        "<trc:GetRecordingConfiguration>"
        f"<trc:RecordingToken>{escape(recording_token)}</trc:RecordingToken>"
        "</trc:GetRecordingConfiguration>"
    )


def recording_set_recording_configuration(
    *,
    recording_token: str,
    source_id: str,
    source_name: str,
    source_location: str = "",
    source_description: str = "",
    source_address: str = "",
    content: str = "",
    max_retention: str = "PT0S",
) -> str:
    """Build a ``SetRecordingConfiguration`` request updating ``recording_token``.

    Rebuilds the recording configuration from the ``source_*`` fields, ``content`` and
    ``max_retention``.
    """
    config = _recording_configuration_xml(
        source_id=source_id,
        source_name=source_name,
        source_location=source_location,
        source_description=source_description,
        source_address=source_address,
        content=content,
        max_retention=max_retention,
    )
    return (
        "<trc:SetRecordingConfiguration>"
        f"<trc:RecordingToken>{escape(recording_token)}</trc:RecordingToken>"
        f"<trc:RecordingConfiguration>{config}</trc:RecordingConfiguration>"
        "</trc:SetRecordingConfiguration>"
    )


def recording_get_recording_options(*, recording_token: str) -> str:
    """Build a ``GetRecordingOptions`` request for ``recording_token``."""
    return (
        "<trc:GetRecordingOptions>"
        f"<trc:RecordingToken>{escape(recording_token)}</trc:RecordingToken>"
        "</trc:GetRecordingOptions>"
    )


def recording_get_recording_jobs() -> str:
    """Build a ``GetRecordingJobs`` request for the recording service."""
    return "<trc:GetRecordingJobs/>"


def recording_create_recording_job(
    *,
    recording_token: str,
    mode: str = "Active",
    priority: int = 10,
    source_token: str = "",
    source_type: str = "",
    auto_create_receiver: bool = True,
) -> str:
    """Build a ``CreateRecordingJob`` request for ``recording_token``.

    Sets the job ``mode`` and ``priority``; when ``source_token`` is given a source block
    is added (with optional ``source_type`` and the ``auto_create_receiver`` flag).
    """
    source_block = ""
    if source_token:
        type_block = f"<tt:Type>{escape(source_type)}</tt:Type>" if source_type else ""
        source_block = (
            "<tt:Source>"
            "<tt:SourceToken>"
            f"{type_block}"
            f"<tt:Token>{escape(source_token)}</tt:Token>"
            "</tt:SourceToken>"
            f"<tt:AutoCreateReceiver>{'true' if auto_create_receiver else 'false'}"
            "</tt:AutoCreateReceiver>"
            "<tt:Tracks/>"
            "</tt:Source>"
        )
    return (
        "<trc:CreateRecordingJob>"
        "<trc:JobConfiguration>"
        f"<tt:RecordingToken>{escape(recording_token)}</tt:RecordingToken>"
        f"<tt:Mode>{escape(mode)}</tt:Mode>"
        f"<tt:Priority>{int(priority)}</tt:Priority>"
        f"{source_block}"
        "</trc:JobConfiguration>"
        "</trc:CreateRecordingJob>"
    )


def recording_delete_recording_job(*, job_token: str) -> str:
    """Build a ``DeleteRecordingJob`` request removing ``job_token``."""
    return (
        "<trc:DeleteRecordingJob>"
        f"<trc:JobToken>{escape(job_token)}</trc:JobToken>"
        "</trc:DeleteRecordingJob>"
    )


def recording_set_recording_job_mode(*, job_token: str, mode: str) -> str:
    """Build a ``SetRecordingJobMode`` request setting ``job_token`` to ``mode`` (e.g. Active/Idle)."""
    return (
        "<trc:SetRecordingJobMode>"
        f"<trc:JobToken>{escape(job_token)}</trc:JobToken>"
        f"<trc:Mode>{escape(mode)}</trc:Mode>"
        "</trc:SetRecordingJobMode>"
    )


def _search_scope_xml(*, included_sources: list[str], included_recordings: list[str]) -> str:
    parts: list[str] = []
    for src in included_sources:
        parts.append(f"<tt:IncludedSources Token={quoteattr(src)}/>")
    for rec in included_recordings:
        parts.append(f"<tt:IncludedRecordings>{escape(rec)}</tt:IncludedRecordings>")
    return f"<tse:Scope>{''.join(parts)}</tse:Scope>"


def search_get_recording_summary() -> str:
    """Build a ``GetRecordingSummary`` request for the search service."""
    return "<tse:GetRecordingSummary/>"


def search_find_recordings(
    *,
    included_sources: list[str] | None = None,
    included_recordings: list[str] | None = None,
    max_matches: int | None = None,
    keep_alive: str = "PT60S",
) -> str:
    """Build a ``FindRecordings`` request.

    Scoped by ``included_sources`` and ``included_recordings``, capped at ``max_matches``
    matches, with ``keep_alive`` (ISO-8601 duration) as the search session lifetime.
    """
    scope = _search_scope_xml(
        included_sources=included_sources or [],
        included_recordings=included_recordings or [],
    )
    max_block = f"<tse:MaxMatches>{int(max_matches)}</tse:MaxMatches>" if max_matches else ""
    return (
        "<tse:FindRecordings>"
        f"{scope}"
        f"{max_block}"
        f"<tse:KeepAliveTime>{escape(keep_alive)}</tse:KeepAliveTime>"
        "</tse:FindRecordings>"
    )


def search_get_recording_search_results(
    *,
    search_token: str,
    min_results: int | None = None,
    max_results: int | None = None,
    wait_time: str = "PT5S",
) -> str:
    """Build a ``GetRecordingSearchResults`` request for ``search_token``.

    Bounded by ``min_results``/``max_results`` and waiting up to ``wait_time`` for
    matches.
    """
    min_block = f"<tse:MinResults>{int(min_results)}</tse:MinResults>" if min_results else ""
    max_block = f"<tse:MaxResults>{int(max_results)}</tse:MaxResults>" if max_results else ""
    return (
        "<tse:GetRecordingSearchResults>"
        f"<tse:SearchToken>{escape(search_token)}</tse:SearchToken>"
        f"{min_block}"
        f"{max_block}"
        f"<tse:WaitTime>{escape(wait_time)}</tse:WaitTime>"
        "</tse:GetRecordingSearchResults>"
    )


def _find_time_window_body(
    *,
    operation: str,
    start_point: str,
    end_point: str,
    included_sources: list[str],
    included_recordings: list[str],
    filter_tag: str,
    filter_expression: str,
    max_matches: int | None,
    keep_alive: str,
    extra: str = "",
) -> str:
    scope = _search_scope_xml(
        included_sources=included_sources, included_recordings=included_recordings
    )
    end_block = f"<tse:EndPoint>{escape(end_point)}</tse:EndPoint>" if end_point else ""
    filter_block = (
        f"<tse:{filter_tag}>{escape(filter_expression)}</tse:{filter_tag}>"
        if filter_expression
        else ""
    )
    max_block = f"<tse:MaxMatches>{int(max_matches)}</tse:MaxMatches>" if max_matches else ""
    return (
        f"<tse:{operation}>"
        f"<tse:StartPoint>{escape(start_point)}</tse:StartPoint>"
        f"{end_block}"
        f"{scope}"
        f"{filter_block}"
        f"{extra}"
        f"{max_block}"
        f"<tse:KeepAliveTime>{escape(keep_alive)}</tse:KeepAliveTime>"
        f"</tse:{operation}>"
    )


def search_find_events(
    *,
    start_point: str,
    end_point: str = "",
    included_sources: list[str] | None = None,
    included_recordings: list[str] | None = None,
    filter_expression: str = "",
    include_start_state: bool = False,
    max_matches: int | None = None,
    keep_alive: str = "PT60S",
) -> str:
    """Build a ``FindEvents`` request over the ``start_point`` to ``end_point`` window.

    Scoped by ``included_sources``/``included_recordings`` and filtered by
    ``filter_expression``; ``include_start_state`` sets the IncludeStartState flag.
    """
    return _find_time_window_body(
        operation="FindEvents",
        start_point=start_point,
        end_point=end_point,
        included_sources=included_sources or [],
        included_recordings=included_recordings or [],
        filter_tag="SearchFilter",
        filter_expression=filter_expression,
        max_matches=max_matches,
        keep_alive=keep_alive,
        extra=(
            f"<tse:IncludeStartState>{'true' if include_start_state else 'false'}"
            "</tse:IncludeStartState>"
        ),
    )


def search_get_event_search_results(
    *,
    search_token: str,
    min_results: int | None = None,
    max_results: int | None = None,
    wait_time: str = "PT5S",
) -> str:
    """Build a ``GetEventSearchResults`` request for ``search_token``.

    Bounded by ``min_results``/``max_results`` and waiting up to ``wait_time`` for
    matches.
    """
    min_block = f"<tse:MinResults>{int(min_results)}</tse:MinResults>" if min_results else ""
    max_block = f"<tse:MaxResults>{int(max_results)}</tse:MaxResults>" if max_results else ""
    return (
        "<tse:GetEventSearchResults>"
        f"<tse:SearchToken>{escape(search_token)}</tse:SearchToken>"
        f"{min_block}"
        f"{max_block}"
        f"<tse:WaitTime>{escape(wait_time)}</tse:WaitTime>"
        "</tse:GetEventSearchResults>"
    )


def search_find_ptz_position(
    *,
    start_point: str,
    end_point: str = "",
    included_sources: list[str] | None = None,
    included_recordings: list[str] | None = None,
    filter_expression: str = "",
    max_matches: int | None = None,
    keep_alive: str = "PT60S",
) -> str:
    """Build a ``FindPTZPosition`` request over the ``start_point`` to ``end_point`` window.

    Scoped by ``included_sources``/``included_recordings`` and filtered by
    ``filter_expression``.
    """
    return _find_time_window_body(
        operation="FindPTZPosition",
        start_point=start_point,
        end_point=end_point,
        included_sources=included_sources or [],
        included_recordings=included_recordings or [],
        filter_tag="SearchFilter",
        filter_expression=filter_expression,
        max_matches=max_matches,
        keep_alive=keep_alive,
    )


def search_get_ptz_position_search_results(
    *,
    search_token: str,
    min_results: int | None = None,
    max_results: int | None = None,
    wait_time: str = "PT5S",
) -> str:
    """Build a ``GetPTZPositionSearchResults`` request for ``search_token``.

    Bounded by ``min_results``/``max_results`` and waiting up to ``wait_time`` for
    matches.
    """
    min_block = f"<tse:MinResults>{int(min_results)}</tse:MinResults>" if min_results else ""
    max_block = f"<tse:MaxResults>{int(max_results)}</tse:MaxResults>" if max_results else ""
    return (
        "<tse:GetPTZPositionSearchResults>"
        f"<tse:SearchToken>{escape(search_token)}</tse:SearchToken>"
        f"{min_block}"
        f"{max_block}"
        f"<tse:WaitTime>{escape(wait_time)}</tse:WaitTime>"
        "</tse:GetPTZPositionSearchResults>"
    )


def search_find_metadata(
    *,
    start_point: str,
    end_point: str = "",
    included_sources: list[str] | None = None,
    included_recordings: list[str] | None = None,
    filter_expression: str = "",
    max_matches: int | None = None,
    keep_alive: str = "PT60S",
) -> str:
    """Build a ``FindMetadata`` request over the ``start_point`` to ``end_point`` window.

    Scoped by ``included_sources``/``included_recordings`` and filtered by the
    ``filter_expression`` metadata filter.
    """
    return _find_time_window_body(
        operation="FindMetadata",
        start_point=start_point,
        end_point=end_point,
        included_sources=included_sources or [],
        included_recordings=included_recordings or [],
        filter_tag="MetadataFilter",
        filter_expression=filter_expression,
        max_matches=max_matches,
        keep_alive=keep_alive,
    )


def search_get_metadata_search_results(
    *,
    search_token: str,
    min_results: int | None = None,
    max_results: int | None = None,
    wait_time: str = "PT5S",
) -> str:
    """Build a ``GetMetadataSearchResults`` request for ``search_token``.

    Bounded by ``min_results``/``max_results`` and waiting up to ``wait_time`` for
    matches.
    """
    min_block = f"<tse:MinResults>{int(min_results)}</tse:MinResults>" if min_results else ""
    max_block = f"<tse:MaxResults>{int(max_results)}</tse:MaxResults>" if max_results else ""
    return (
        "<tse:GetMetadataSearchResults>"
        f"<tse:SearchToken>{escape(search_token)}</tse:SearchToken>"
        f"{min_block}"
        f"{max_block}"
        f"<tse:WaitTime>{escape(wait_time)}</tse:WaitTime>"
        "</tse:GetMetadataSearchResults>"
    )


def search_end_search(*, search_token: str) -> str:
    """Build an ``EndSearch`` request terminating the search session ``search_token``."""
    return (
        f"<tse:EndSearch><tse:SearchToken>{escape(search_token)}</tse:SearchToken></tse:EndSearch>"
    )


def replay_get_replay_uri(
    *,
    recording_token: str,
    stream: str = "RTP-Unicast",
    protocol: str = "RTSP",
) -> str:
    """Build a ``GetReplayUri`` request for ``recording_token`` using the ``stream`` setup and ``protocol`` transport."""
    return (
        "<trp:GetReplayUri>"
        "<trp:StreamSetup>"
        f"<tt:Stream>{escape(stream)}</tt:Stream>"
        f"<tt:Transport><tt:Protocol>{escape(protocol)}</tt:Protocol></tt:Transport>"
        "</trp:StreamSetup>"
        f"<trp:RecordingToken>{escape(recording_token)}</trp:RecordingToken>"
        "</trp:GetReplayUri>"
    )


def replay_get_replay_configuration() -> str:
    """Build a ``GetReplayConfiguration`` request for the replay service."""
    return "<trp:GetReplayConfiguration/>"


def replay_set_replay_configuration(*, session_timeout: str = "PT60S") -> str:
    """Build a ``SetReplayConfiguration`` request setting the replay ``session_timeout``."""
    return (
        "<trp:SetReplayConfiguration>"
        "<trp:Configuration>"
        f"<tt:SessionTimeout>{escape(session_timeout)}</tt:SessionTimeout>"
        "</trp:Configuration>"
        "</trp:SetReplayConfiguration>"
    )


def media_get_osds(*, configuration_token: str = "") -> str:
    """Build a ``GetOSDs`` request, optionally scoped to ``configuration_token``."""
    inner = (
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        if configuration_token
        else ""
    )
    return f"<trt:GetOSDs>{inner}</trt:GetOSDs>"


def media_get_osd(*, osd_token: str) -> str:
    """Build a ``GetOSD`` request for the single OSD ``osd_token``."""
    return f"<trt:GetOSD><trt:OSDToken>{escape(osd_token)}</trt:OSDToken></trt:GetOSD>"


def media_get_osd_options(*, configuration_token: str) -> str:
    """Build a ``GetOSDOptions`` request for the OSD ``configuration_token``."""
    return (
        "<trt:GetOSDOptions>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:GetOSDOptions>"
    )


def _osd_body_xml(
    *,
    video_source_configuration_token: str,
    osd_type: str,
    position_type: str,
    pos_x: float | None,
    pos_y: float | None,
    text_type: str,
    plain_text: str,
    font_size: int | None,
    date_format: str,
    time_format: str,
) -> str:
    pos_block = ""
    if position_type.lower() == "custom" and pos_x is not None and pos_y is not None:
        pos_block = f'<tt:Pos x="{pos_x}" y="{pos_y}"/>'
    position = f"<tt:Position><tt:Type>{escape(position_type)}</tt:Type>{pos_block}</tt:Position>"
    text_parts: list[str] = [f"<tt:Type>{escape(text_type)}</tt:Type>"]
    if text_type in ("Date", "DateAndTime") and date_format:
        text_parts.append(f"<tt:DateFormat>{escape(date_format)}</tt:DateFormat>")
    if text_type in ("Time", "DateAndTime") and time_format:
        text_parts.append(f"<tt:TimeFormat>{escape(time_format)}</tt:TimeFormat>")
    if font_size is not None:
        text_parts.append(f"<tt:FontSize>{int(font_size)}</tt:FontSize>")
    if text_type == "Plain":
        text_parts.append(f"<tt:PlainText>{escape(plain_text)}</tt:PlainText>")
    text_string = f"<tt:TextString>{''.join(text_parts)}</tt:TextString>"
    return (
        f"<tt:VideoSourceConfigurationToken>{escape(video_source_configuration_token)}"
        "</tt:VideoSourceConfigurationToken>"
        f"<tt:Type>{escape(osd_type)}</tt:Type>"
        f"{position}"
        f"{text_string}"
    )


def media_create_osd(
    *,
    video_source_configuration_token: str,
    osd_type: str = "Text",
    position_type: str = "UpperLeft",
    pos_x: float | None = None,
    pos_y: float | None = None,
    text_type: str = "Plain",
    plain_text: str = "",
    font_size: int | None = None,
    date_format: str = "",
    time_format: str = "",
) -> str:
    """Build a ``CreateOSD`` request placing an OSD on ``video_source_configuration_token``.

    ``text_type`` selects plain/date/time content and the remaining args set the
    position, custom ``pos_x``/``pos_y``, font and date/time formats.
    """
    body = _osd_body_xml(
        video_source_configuration_token=video_source_configuration_token,
        osd_type=osd_type,
        position_type=position_type,
        pos_x=pos_x,
        pos_y=pos_y,
        text_type=text_type,
        plain_text=plain_text,
        font_size=font_size,
        date_format=date_format,
        time_format=time_format,
    )
    return f"<trt:CreateOSD><trt:OSD>{body}</trt:OSD></trt:CreateOSD>"


def media_set_osd(
    *,
    osd_token: str,
    video_source_configuration_token: str,
    osd_type: str = "Text",
    position_type: str = "UpperLeft",
    pos_x: float | None = None,
    pos_y: float | None = None,
    text_type: str = "Plain",
    plain_text: str = "",
    font_size: int | None = None,
    date_format: str = "",
    time_format: str = "",
) -> str:
    """Build a ``SetOSD`` request updating ``osd_token`` on ``video_source_configuration_token``.

    ``text_type`` selects plain/date/time content and the remaining args set the
    position, custom ``pos_x``/``pos_y``, font and date/time formats.
    """
    body = _osd_body_xml(
        video_source_configuration_token=video_source_configuration_token,
        osd_type=osd_type,
        position_type=position_type,
        pos_x=pos_x,
        pos_y=pos_y,
        text_type=text_type,
        plain_text=plain_text,
        font_size=font_size,
        date_format=date_format,
        time_format=time_format,
    )
    return f"<trt:SetOSD><trt:OSD token={quoteattr(osd_token)}>{body}</trt:OSD></trt:SetOSD>"


def media_delete_osd(*, osd_token: str) -> str:
    """Build a ``DeleteOSD`` request removing ``osd_token``."""
    return f"<trt:DeleteOSD><trt:OSDToken>{escape(osd_token)}</trt:OSDToken></trt:DeleteOSD>"


def media_get_metadata_configurations() -> str:
    """Build a ``GetMetadataConfigurations`` request for the legacy Media service."""
    return "<trt:GetMetadataConfigurations/>"


def media_get_metadata_configuration(*, configuration_token: str) -> str:
    """Build a ``GetMetadataConfiguration`` request for ``configuration_token``."""
    return (
        "<trt:GetMetadataConfiguration>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:GetMetadataConfiguration>"
    )


def media_get_metadata_configuration_options(
    *, configuration_token: str = "", profile_token: str = ""
) -> str:
    """Build a ``GetMetadataConfigurationOptions`` request, scoped by ``configuration_token`` and/or ``profile_token`` when set."""
    parts: list[str] = []
    if configuration_token:
        parts.append(
            f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        )
    if profile_token:
        parts.append(f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>")
    return (
        f"<trt:GetMetadataConfigurationOptions>{''.join(parts)}"
        "</trt:GetMetadataConfigurationOptions>"
    )


def media_set_metadata_configuration(
    *,
    token: str,
    name: str,
    analytics: bool = True,
    ptz_status: bool = False,
    ptz_position: bool = False,
    use_count: int = 0,
    session_timeout: str = "PT60S",
    force_persistence: bool = True,
) -> str:
    """Build a ``SetMetadataConfiguration`` request for ``token``.

    Toggles the ``analytics`` metadata flag and, when ``ptz_status`` or ``ptz_position``
    is set, a PTZ status/position block; ``force_persistence`` maps to the
    ``ForcePersistence`` flag.
    """
    ptz_block = ""
    if ptz_status or ptz_position:
        ptz_block = (
            "<tt:PTZStatus>"
            f"<tt:Status>{'true' if ptz_status else 'false'}</tt:Status>"
            f"<tt:Position>{'true' if ptz_position else 'false'}</tt:Position>"
            "</tt:PTZStatus>"
        )
    return (
        "<trt:SetMetadataConfiguration>"
        f"<trt:Configuration token={quoteattr(token)}>"
        f"<tt:Name>{escape(name)}</tt:Name>"
        f"<tt:UseCount>{int(use_count)}</tt:UseCount>"
        f"{ptz_block}"
        f"<tt:Analytics>{'true' if analytics else 'false'}</tt:Analytics>"
        "<tt:Multicast>"
        "<tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>"
        "<tt:Port>0</tt:Port><tt:TTL>0</tt:TTL><tt:AutoStart>false</tt:AutoStart>"
        "</tt:Multicast>"
        f"<tt:SessionTimeout>{escape(session_timeout)}</tt:SessionTimeout>"
        "</trt:Configuration>"
        f"<trt:ForcePersistence>{'true' if force_persistence else 'false'}</trt:ForcePersistence>"
        "</trt:SetMetadataConfiguration>"
    )


def media_add_metadata_configuration(*, profile_token: str, configuration_token: str) -> str:
    """Build an ``AddMetadataConfiguration`` request adding ``configuration_token`` to ``profile_token``."""
    return (
        "<trt:AddMetadataConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:AddMetadataConfiguration>"
    )


def media_remove_metadata_configuration(*, profile_token: str) -> str:
    """Build a ``RemoveMetadataConfiguration`` request removing the metadata config from ``profile_token``."""
    return (
        "<trt:RemoveMetadataConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:RemoveMetadataConfiguration>"
    )


def analytics_create_analytics_modules(
    *, configuration_token: str, modules: list[dict[str, object]]
) -> str:
    """Build a ``CreateAnalyticsModules`` request adding ``modules`` to ``configuration_token``.

    Each dict in ``modules`` provides ``name``, ``type`` and a ``parameters`` mapping.
    """
    return (
        "<tan:CreateAnalyticsModules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        f"{_config_items_xml(modules, wrapper_tag='tan:AnalyticsModule')}"
        "</tan:CreateAnalyticsModules>"
    )


def analytics_modify_analytics_modules(
    *, configuration_token: str, modules: list[dict[str, object]]
) -> str:
    """Build a ``ModifyAnalyticsModules`` request updating ``modules`` on ``configuration_token``.

    Each dict in ``modules`` provides ``name``, ``type`` and a ``parameters`` mapping.
    """
    return (
        "<tan:ModifyAnalyticsModules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        f"{_config_items_xml(modules, wrapper_tag='tan:AnalyticsModule')}"
        "</tan:ModifyAnalyticsModules>"
    )


def analytics_delete_analytics_modules(*, configuration_token: str, names: list[str]) -> str:
    """Build a ``DeleteAnalyticsModules`` request removing the modules named in ``names`` from ``configuration_token``."""
    name_xml = "".join(
        f"<tan:AnalyticsModuleName>{escape(n)}</tan:AnalyticsModuleName>" for n in names
    )
    return (
        "<tan:DeleteAnalyticsModules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        f"{name_xml}"
        "</tan:DeleteAnalyticsModules>"
    )


def analytics_create_rules(*, configuration_token: str, rules: list[dict[str, object]]) -> str:
    """Build a ``CreateRules`` request adding ``rules`` (each with ``name``, ``type`` and ``parameters``) to ``configuration_token``."""
    return (
        "<tan:CreateRules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        f"{_config_items_xml(rules, wrapper_tag='tan:Rule')}"
        "</tan:CreateRules>"
    )


def analytics_modify_rules(*, configuration_token: str, rules: list[dict[str, object]]) -> str:
    """Build a ``ModifyRules`` request updating ``rules`` (each with ``name``, ``type`` and ``parameters``) on ``configuration_token``."""
    return (
        "<tan:ModifyRules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        f"{_config_items_xml(rules, wrapper_tag='tan:Rule')}"
        "</tan:ModifyRules>"
    )


def analytics_delete_rules(*, configuration_token: str, names: list[str]) -> str:
    """Build a ``DeleteRules`` request removing the rules named in ``names`` from ``configuration_token``."""
    name_xml = "".join(f"<tan:RuleName>{escape(n)}</tan:RuleName>" for n in names)
    return (
        "<tan:DeleteRules>"
        f"<tan:ConfigurationToken>{escape(configuration_token)}</tan:ConfigurationToken>"
        f"{name_xml}"
        "</tan:DeleteRules>"
    )


def media_add_audio_source_configuration(*, profile_token: str, configuration_token: str) -> str:
    """Build an ``AddAudioSourceConfiguration`` request adding ``configuration_token`` to ``profile_token``."""
    return (
        "<trt:AddAudioSourceConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:AddAudioSourceConfiguration>"
    )


def media_add_audio_encoder_configuration(*, profile_token: str, configuration_token: str) -> str:
    """Build an ``AddAudioEncoderConfiguration`` request adding ``configuration_token`` to ``profile_token``."""
    return (
        "<trt:AddAudioEncoderConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        f"<trt:ConfigurationToken>{escape(configuration_token)}</trt:ConfigurationToken>"
        "</trt:AddAudioEncoderConfiguration>"
    )


def media_remove_audio_encoder_configuration(*, profile_token: str) -> str:
    """Build a ``RemoveAudioEncoderConfiguration`` request removing the audio encoder config from ``profile_token``."""
    return (
        "<trt:RemoveAudioEncoderConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:RemoveAudioEncoderConfiguration>"
    )


def media_remove_audio_source_configuration(*, profile_token: str) -> str:
    """Build a ``RemoveAudioSourceConfiguration`` request removing the audio source config from ``profile_token``."""
    return (
        "<trt:RemoveAudioSourceConfiguration>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:RemoveAudioSourceConfiguration>"
    )


def media_start_multicast_streaming(*, profile_token: str) -> str:
    """Build a ``StartMulticastStreaming`` request for ``profile_token``."""
    return (
        "<trt:StartMulticastStreaming>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:StartMulticastStreaming>"
    )


def media_stop_multicast_streaming(*, profile_token: str) -> str:
    """Build a ``StopMulticastStreaming`` request for ``profile_token``."""
    return (
        "<trt:StopMulticastStreaming>"
        f"<trt:ProfileToken>{escape(profile_token)}</trt:ProfileToken>"
        "</trt:StopMulticastStreaming>"
    )


def ptz_send_auxiliary_command(*, profile_token: str, auxiliary_data: str) -> str:
    """Build a ``SendAuxiliaryCommand`` request sending ``auxiliary_data`` to ``profile_token``."""
    return (
        "<tptz:SendAuxiliaryCommand>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:AuxiliaryData>{escape(auxiliary_data)}</tptz:AuxiliaryData>"
        "</tptz:SendAuxiliaryCommand>"
    )


def device_get_digital_inputs(*, use_deviceio: bool = False) -> str:
    """Build a ``GetDigitalInputs`` request on the DeviceIO (``tmd``) or Device (``tds``) service per ``use_deviceio``."""
    ns = "tmd" if use_deviceio else "tds"
    return f"<{ns}:GetDigitalInputs/>"


def device_get_scopes() -> str:
    """Build a ``GetScopes`` request for the device service."""
    return "<tds:GetScopes/>"


def device_set_scopes(*, scopes: list[str]) -> str:
    """Build a ``SetScopes`` request replacing the configurable scopes with ``scopes``."""
    items = "".join(f"<tds:Scopes>{escape(s)}</tds:Scopes>" for s in scopes)
    return f"<tds:SetScopes>{items}</tds:SetScopes>"


def device_add_scopes(*, scopes: list[str]) -> str:
    """Build an ``AddScopes`` request adding ``scopes`` to the device's scope list."""
    items = "".join(f"<tds:ScopeItem>{escape(s)}</tds:ScopeItem>" for s in scopes)
    return f"<tds:AddScopes>{items}</tds:AddScopes>"


def device_remove_scopes(*, scopes: list[str]) -> str:
    """Build a ``RemoveScopes`` request removing ``scopes`` from the device's scope list."""
    items = "".join(f"<tds:ScopeItem>{escape(s)}</tds:ScopeItem>" for s in scopes)
    return f"<tds:RemoveScopes>{items}</tds:RemoveScopes>"


def device_get_system_log(*, log_type: str = "System") -> str:
    """Build a ``GetSystemLog`` request for the given ``log_type`` (``System`` or ``Access``)."""
    return f"<tds:GetSystemLog><tds:LogType>{escape(log_type)}</tds:LogType></tds:GetSystemLog>"


def device_get_system_support_information() -> str:
    """Build a ``GetSystemSupportInformation`` request for the device service."""
    return "<tds:GetSystemSupportInformation/>"


def device_get_certificates() -> str:
    """Build a ``GetCertificates`` request for the device service."""
    return "<tds:GetCertificates/>"


def device_get_dot1x_configurations() -> str:
    """Build a ``GetDot1XConfigurations`` request for the device service."""
    return "<tds:GetDot1XConfigurations/>"


_SERVICE_CAPABILITY_PREFIX = {
    "device": "tds",
    "media": "trt",
    "media2": "trt2",
    "ptz": "tptz",
    "imaging": "timg",
    "events": "tev",
    "analytics": "tan",
    "recording": "trc",
    "replay": "trp",
    "search": "tse",
    "deviceio": "tmd",
}


def get_service_capabilities(service: str) -> str:
    """Build a ``GetServiceCapabilities`` request for ``service``.

    ``service`` (e.g. ``device``, ``media``, ``ptz``) selects the matching namespace
    prefix, defaulting to ``tds`` when unknown.
    """
    prefix = _SERVICE_CAPABILITY_PREFIX.get(service, "tds")
    return f"<{prefix}:GetServiceCapabilities/>"


def events_set_synchronization_point() -> str:
    """Build a ``SetSynchronizationPoint`` request asking the events service to refire current-state notifications."""
    return "<tev:SetSynchronizationPoint/>"


def device_get_relay_output_options(*, token: str = "") -> str:
    """Build a DeviceIO ``GetRelayOutputOptions`` request, optionally scoped to relay ``token``."""
    if not token:
        return "<tmd:GetRelayOutputOptions/>"
    return (
        "<tmd:GetRelayOutputOptions>"
        f"<tmd:RelayOutputToken>{escape(token)}</tmd:RelayOutputToken>"
        "</tmd:GetRelayOutputOptions>"
    )


def device_get_serial_ports() -> str:
    """Build a DeviceIO ``GetSerialPorts`` request."""
    return "<tmd:GetSerialPorts/>"


def _media2_configurations(configurations: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for cfg in configurations:
        token_xml = f"<trt2:Token>{escape(cfg['token'])}</trt2:Token>" if cfg.get("token") else ""
        parts.append(
            f"<trt2:Configuration><trt2:Type>{escape(cfg['type'])}</trt2:Type>"
            f"{token_xml}</trt2:Configuration>"
        )
    return "".join(parts)


def media2_create_profile(*, name: str, configurations: list[dict[str, str]] | None = None) -> str:
    """Build a Media2 ``CreateProfile`` request named ``name`` with the given ``configurations`` (each a ``type``/``token`` dict)."""
    return (
        "<trt2:CreateProfile>"
        f"<trt2:Name>{escape(name)}</trt2:Name>"
        f"{_media2_configurations(configurations or [])}"
        "</trt2:CreateProfile>"
    )


def media2_delete_profile(*, token: str) -> str:
    """Build a Media2 ``DeleteProfile`` request removing ``token``."""
    return f"<trt2:DeleteProfile><trt2:Token>{escape(token)}</trt2:Token></trt2:DeleteProfile>"


def media2_get_profiles(*, types: list[str] | None = None) -> str:
    """Build a Media2 ``GetProfiles`` request, optionally restricted to the configuration ``types``."""
    type_xml = "".join(f"<trt2:Type>{escape(t)}</trt2:Type>" for t in (types or []))
    if not type_xml:
        return "<trt2:GetProfiles/>"
    return f"<trt2:GetProfiles>{type_xml}</trt2:GetProfiles>"


def media2_add_configuration(
    *, profile_token: str, configurations: list[dict[str, str]], name: str = ""
) -> str:
    """Build a Media2 ``AddConfiguration`` request adding ``configurations`` to ``profile_token``.

    ``name`` optionally renames the profile.
    """
    name_xml = f"<trt2:Name>{escape(name)}</trt2:Name>" if name else ""
    return (
        "<trt2:AddConfiguration>"
        f"<trt2:ProfileToken>{escape(profile_token)}</trt2:ProfileToken>"
        f"{name_xml}{_media2_configurations(configurations)}"
        "</trt2:AddConfiguration>"
    )


def media2_remove_configuration(*, profile_token: str, configurations: list[dict[str, str]]) -> str:
    """Build a Media2 ``RemoveConfiguration`` request removing ``configurations`` from ``profile_token``."""
    return (
        "<trt2:RemoveConfiguration>"
        f"<trt2:ProfileToken>{escape(profile_token)}</trt2:ProfileToken>"
        f"{_media2_configurations(configurations)}"
        "</trt2:RemoveConfiguration>"
    )


def media2_set_synchronization_point(*, profile_token: str) -> str:
    """Build a Media2 ``SetSynchronizationPoint`` request for ``profile_token``."""
    return (
        "<trt2:SetSynchronizationPoint>"
        f"<trt2:ProfileToken>{escape(profile_token)}</trt2:ProfileToken>"
        "</trt2:SetSynchronizationPoint>"
    )


def media2_get_masks(*, configuration_token: str = "") -> str:
    """Build a Media2 ``GetMasks`` request, optionally scoped to ``configuration_token``."""
    if not configuration_token:
        return "<trt2:GetMasks/>"
    return (
        "<trt2:GetMasks>"
        f"<trt2:ConfigurationToken>{escape(configuration_token)}</trt2:ConfigurationToken>"
        "</trt2:GetMasks>"
    )


def media2_delete_mask(*, token: str) -> str:
    """Build a Media2 ``DeleteMask`` request removing the mask ``token``."""
    return f"<trt2:DeleteMask><trt2:Token>{escape(token)}</trt2:Token></trt2:DeleteMask>"


def events_subscribe(
    *, consumer_address: str, topic_filter: str = "", termination_time: str = "PT60S"
) -> str:
    """Build a WS-Notification ``Subscribe`` request.

    Delivers notifications to ``consumer_address`` until ``termination_time``, with an
    optional concrete-set ``topic_filter``.
    """
    filter_xml = ""
    if topic_filter:
        filter_xml = (
            "<wsnt:Filter>"
            '<wsnt:TopicExpression Dialect="http://www.onvif.org/ver10/tev/'
            'topicExpression/ConcreteSet">'
            f"{escape(topic_filter)}</wsnt:TopicExpression>"
            "</wsnt:Filter>"
        )
    return (
        "<wsnt:Subscribe>"
        "<wsnt:ConsumerReference>"
        f"<wsa:Address>{escape(consumer_address)}</wsa:Address>"
        "</wsnt:ConsumerReference>"
        f"{filter_xml}"
        f"<wsnt:InitialTerminationTime>{escape(termination_time)}</wsnt:InitialTerminationTime>"
        "</wsnt:Subscribe>"
    )


def device_get_system_uris() -> str:
    """Build a ``GetSystemUris`` request for the device service."""
    return "<tds:GetSystemUris/>"


def device_get_storage_configurations() -> str:
    """Build a ``GetStorageConfigurations`` request for the device service."""
    return "<tds:GetStorageConfigurations/>"


def device_get_geo_location() -> str:
    """Build a ``GetGeoLocation`` request for the device service."""
    return "<tds:GetGeoLocation/>"


def device_set_geo_location(*, lon: float, lat: float, elevation: float = 0.0) -> str:
    """Build a ``SetGeoLocation`` request setting the device ``lon``, ``lat`` and ``elevation``."""
    return (
        "<tds:SetGeoLocation>"
        f'<tds:Location lon="{lon}" lat="{lat}" elevation="{elevation}"/>'
        "</tds:SetGeoLocation>"
    )


def device_get_wsdl_url() -> str:
    """Build a ``GetWsdlUrl`` request for the device service."""
    return "<tds:GetWsdlUrl/>"


def device_get_endpoint_reference() -> str:
    """Build a ``GetEndpointReference`` request for the device service."""
    return "<tds:GetEndpointReference/>"


def device_get_zero_configuration() -> str:
    """Build a ``GetZeroConfiguration`` request for the device service."""
    return "<tds:GetZeroConfiguration/>"


def imaging_get_presets(*, video_source_token: str) -> str:
    """Build an imaging ``GetPresets`` request listing imaging presets for ``video_source_token``."""
    return (
        "<timg:GetPresets>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        "</timg:GetPresets>"
    )


def imaging_get_current_preset(*, video_source_token: str) -> str:
    """Build an imaging ``GetCurrentPreset`` request for ``video_source_token``."""
    return (
        "<timg:GetCurrentPreset>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        "</timg:GetCurrentPreset>"
    )


def imaging_set_current_preset(*, video_source_token: str, preset_token: str) -> str:
    """Build an imaging ``SetCurrentPreset`` request applying ``preset_token`` to ``video_source_token``."""
    return (
        "<timg:SetCurrentPreset>"
        f"<timg:VideoSourceToken>{escape(video_source_token)}</timg:VideoSourceToken>"
        f"<timg:PresetToken>{escape(preset_token)}</timg:PresetToken>"
        "</timg:SetCurrentPreset>"
    )


def ptz_get_compatible_configurations(*, profile_token: str) -> str:
    """Build a ``GetCompatibleConfigurations`` request listing PTZ configs usable with ``profile_token``."""
    return (
        "<tptz:GetCompatibleConfigurations>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        "</tptz:GetCompatibleConfigurations>"
    )


def ptz_get_configuration_options(*, configuration_token: str) -> str:
    """Build a ``GetConfigurationOptions`` request for the PTZ ``configuration_token``."""
    return (
        "<tptz:GetConfigurationOptions>"
        f"<tptz:ConfigurationToken>{escape(configuration_token)}</tptz:ConfigurationToken>"
        "</tptz:GetConfigurationOptions>"
    )


def ptz_get_preset_tours(*, profile_token: str) -> str:
    """Build a ``GetPresetTours`` request listing preset tours for ``profile_token``."""
    return (
        "<tptz:GetPresetTours>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        "</tptz:GetPresetTours>"
    )


def ptz_get_preset_tour(*, profile_token: str, preset_tour_token: str) -> str:
    """Build a ``GetPresetTour`` request for ``preset_tour_token`` on ``profile_token``."""
    return (
        "<tptz:GetPresetTour>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:PresetTourToken>{escape(preset_tour_token)}</tptz:PresetTourToken>"
        "</tptz:GetPresetTour>"
    )


def ptz_operate_preset_tour(*, profile_token: str, preset_tour_token: str, operation: str) -> str:
    """Build an ``OperatePresetTour`` request applying ``operation`` (e.g. Start/Stop/Pause) to ``preset_tour_token`` on ``profile_token``."""
    return (
        "<tptz:OperatePresetTour>"
        f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:PresetTourToken>{escape(preset_tour_token)}</tptz:PresetTourToken>"
        f"<tptz:Operation>{escape(operation)}</tptz:Operation>"
        "</tptz:OperatePresetTour>"
    )
