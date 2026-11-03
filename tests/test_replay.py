"""ONVIF replay (Profile G): PLAY headers and the RTP replay extension."""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone

import pytest

from onveef import replay

_START = datetime(2009, 6, 15, 11, 49, 0, 440000, tzinfo=timezone.utc)
_END = datetime(2009, 6, 15, 11, 50, tzinfo=timezone.utc)


def test_range_follows_the_streaming_specification_examples() -> None:
    assert replay.replay_range(_START) == "clock=20090615T114900.440Z-"
    assert replay.replay_range(_START, _END) == "clock=20090615T114900.440Z-20090615T115000Z"


def test_times_in_other_zones_and_naive_times_are_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    assert replay.utc_clock(datetime(2009, 6, 15, 17, 19, tzinfo=ist)) == "20090615T114900Z"
    assert replay.utc_clock(datetime(2009, 6, 15, 11, 49)) == "20090615T114900Z"


def test_headers_for_downloading_footage() -> None:
    assert replay.replay_headers(_START, _END) == {
        "Require": "onvif-replay",
        "Range": "clock=20090615T114900.440Z-20090615T115000Z",
        "Rate-Control": "no",
        "Immediate": "yes",
    }


def test_headers_for_reverse_key_frame_playback_in_real_time() -> None:
    headers = replay.replay_headers(
        _END, _START, reverse=True, frames="intra/4000", rate_control=True, immediate=False
    )
    assert headers["Scale"] == "-1.0"
    assert headers["Frames"] == "intra/4000"
    assert headers["Rate-Control"] == "yes"
    assert "Immediate" not in headers


def _rtp(*, extension: bytes | None, csrc: int = 0, version: int = 2) -> bytes:
    first = (version << 6) | (0x10 if extension is not None else 0) | csrc
    header = struct.pack(">BBHII", first, 96, 7, 90000, 0x1234) + b"\0\0\0\0" * csrc
    return header + (extension or b"") + b"payload"


def _extension(moment: datetime, flags: int, cseq: int, *, profile: int = 0xABAC) -> bytes:
    unix = (moment - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
    seconds = int(unix) + 2208988800
    fraction = round((unix - int(unix)) * (1 << 32))
    return (
        struct.pack(">HH", profile, 3)
        + struct.pack(">II", seconds & 0xFFFFFFFF, fraction)
        + bytes((flags, cseq, 0, 0))
    )


def test_the_replay_extension_gives_the_capture_time_and_flags() -> None:
    packet = _rtp(extension=_extension(_START, 0x80 | 0x40, 123), csrc=1)
    mark = replay.parse_replay_extension(packet)
    assert mark is not None
    assert abs((mark.time - _START).total_seconds()) < 1e-3
    assert (mark.clean_point, mark.end_of_section, mark.discontinuity, mark.terminal) == (
        True,
        True,
        False,
        False,
    )
    assert mark.cseq == 123


def test_times_after_the_2036_ntp_rollover() -> None:
    later = datetime(2040, 1, 1, tzinfo=timezone.utc)
    mark = replay.parse_replay_extension(_rtp(extension=_extension(later, 0x30, 1)))
    assert mark is not None
    assert abs((mark.time - later).total_seconds()) < 1e-3
    assert mark.discontinuity and mark.terminal


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\x80\x60",
        _rtp(extension=None),
        _rtp(extension=_extension(_START, 0, 0, profile=0xBEDE)),
        _rtp(extension=_extension(_START, 0, 0), version=1),
        _rtp(extension=_extension(_START, 0, 0))[:20],
    ],
)
def test_packets_without_a_usable_replay_extension(packet: bytes) -> None:
    assert replay.parse_replay_extension(packet) is None
