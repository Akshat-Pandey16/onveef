"""ONVIF replay over RTSP (Profile G): the PLAY headers and the RTP replay extension.

The ONVIF Streaming Specification extends RTSP for playing back recordings: the ``PLAY``
request carries ``Require: onvif-replay`` and an absolute ``Range: clock=…``, and the first
RTP packet of every access unit carries a header extension (``0xABAC``) with the wall-clock
time the frame was captured plus clean-point, gap and end-of-track flags.
:meth:`~onveef.client.OnvifClient.get_replay_uri` gives the RTSP address; these helpers
give whatever RTSP client you use the ONVIF part. They are pure: no sockets.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

__all__ = (
    "REPLAY_EXTENSION_ID",
    "REPLAY_FEATURE",
    "ReplayMark",
    "parse_replay_extension",
    "replay_headers",
    "replay_range",
    "utc_clock",
)

REPLAY_FEATURE = "onvif-replay"
"""The RTSP feature tag a replay server supports and a ``PLAY`` must ``Require``."""

REPLAY_EXTENSION_ID = 0xABAC
"""The RTP header-extension profile carrying the replay timestamp and flags."""

_NTP_UNIX_OFFSET_S = 2208988800
_NTP_ERA_S = 1 << 32
_RTP_HEADER = struct.Struct(">BBHII")
_EXTENSION_HEADER = struct.Struct(">HH")
_NTP = struct.Struct(">II")
_CLEAN_POINT, _END_OF_SECTION, _DISCONTINUITY, _TERMINAL = 0x80, 0x40, 0x20, 0x10

UTC = timezone.utc  # the object datetime.UTC names on Python 3.11+


def utc_clock(moment: datetime) -> str:
    """Format a moment as an RFC 2326 ``utc-time``, e.g. ``20090615T114900.440Z``.

    Naive datetimes are taken to be UTC; fractions are kept to the millisecond.
    """
    utc = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    millis = utc.microsecond // 1000
    return f"{utc:%Y%m%dT%H%M%S}" + (f".{millis:03d}" if millis else "") + "Z"


def replay_range(start: datetime, end: datetime | None = None) -> str:
    """Build the ``Range`` value for a replay: ``clock=<start>-[<end>]``.

    The first time is where playback starts. For reverse playback give ``end`` earlier
    than ``start``; omit it to play to the end of the recording (or its beginning).
    """
    return f"clock={utc_clock(start)}-{utc_clock(end) if end is not None else ''}"


def replay_headers(
    start: datetime,
    end: datetime | None = None,
    *,
    reverse: bool = False,
    frames: str = "",
    rate_control: bool = False,
    immediate: bool = True,
) -> dict[str, str]:
    """The RTSP headers that turn a ``PLAY`` into an ONVIF replay of ``start``..``end``.

    Args:
        reverse: Play backwards (``Scale: -1.0``); the device's ``ReversePlayback``
            replay capability says whether it can.
        frames: ``"intra"`` for key frames only (``"intra/4000"`` for at most one per 4
            seconds of recording), ``"predicted"`` to drop B-frames; ``""`` sends all.
        rate_control: ``False`` (``Rate-Control: no``) has the camera send as fast as the
            connection allows, which is what downloading footage wants; ``True`` paces it
            in real time.
        immediate: Start from the new position at once, cancelling a running ``PLAY``.

    Returns:
        Headers to add to the ``PLAY`` request (``Require``, ``Range``, ``Rate-Control``,
        and ``Immediate``, ``Scale`` and ``Frames`` when they apply).
    """
    headers = {
        "Require": REPLAY_FEATURE,
        "Range": replay_range(start, end),
        "Rate-Control": "yes" if rate_control else "no",
    }
    if immediate:
        headers["Immediate"] = "yes"
    if reverse:
        headers["Scale"] = "-1.0"
    if frames:
        headers["Frames"] = frames
    return headers


@dataclass(frozen=True, slots=True)
class ReplayMark:
    """The replay extension of one RTP packet.

    Attributes:
        time: When the access unit was captured (UTC), on the recording's wall clock.
        clean_point: The access unit is a synchronization point (e.g. a key frame).
        end_of_section: The last access unit before a gap in the recording, or at its end.
        discontinuity: The access unit does not follow on from the previous one (reverse
            playback, or the first packet after an ``Immediate`` re-position).
        terminal: No more data will follow for this track.
        cseq: The low byte of the ``CSeq`` of the ``PLAY`` that started this data, which
            tells consecutive ``PLAY`` requests' data apart.
    """

    time: datetime
    clean_point: bool
    end_of_section: bool
    discontinuity: bool
    terminal: bool
    cseq: int


def _ntp_time(seconds: int, fraction: int) -> datetime:
    if seconds < 1 << 31:  # NTP era 1 began in 2036
        seconds += _NTP_ERA_S
    unix = seconds - _NTP_UNIX_OFFSET_S + fraction / _NTP_ERA_S
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=unix)


def parse_replay_extension(packet: bytes) -> ReplayMark | None:
    """Read the ONVIF replay extension from an RTP packet.

    Returns ``None`` for a packet that is not RTP version 2, is truncated, or carries no
    replay extension (only the first packet of each access unit has one).
    """
    if len(packet) < _RTP_HEADER.size:
        return None
    first = packet[0]
    if first >> 6 != 2 or not first & 0x10:
        return None
    offset = _RTP_HEADER.size + 4 * (first & 0x0F)
    if offset + _EXTENSION_HEADER.size > len(packet):
        return None
    profile, words = _EXTENSION_HEADER.unpack_from(packet, offset)
    body = offset + _EXTENSION_HEADER.size
    if profile != REPLAY_EXTENSION_ID or words < 3 or body + 4 * words > len(packet):
        return None
    seconds, fraction = _NTP.unpack_from(packet, body)
    flags, cseq = packet[body + 8], packet[body + 9]
    return ReplayMark(
        time=_ntp_time(seconds, fraction),
        clean_point=bool(flags & _CLEAN_POINT),
        end_of_section=bool(flags & _END_OF_SECTION),
        discontinuity=bool(flags & _DISCONTINUITY),
        terminal=bool(flags & _TERMINAL),
        cseq=cseq,
    )
