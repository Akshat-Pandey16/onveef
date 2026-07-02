from __future__ import annotations

import pathlib

import pytest

from onveef import parsers

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read(rel: str) -> str:
    return (_FIXTURES / rel).read_text(encoding="utf-8")


def test_hikvision_device_information() -> None:
    info = parsers.parse_device_information(_read("hikvision/GetDeviceInformation.xml"))
    assert info["Manufacturer"] == "HIKVISION"
    assert info["Model"] == "DS-2CD2085FWD-I"
    assert info["FirmwareVersion"].startswith("V5.6.3")


@pytest.mark.parametrize(
    ("fixture", "expected_encoding"),
    [
        ("hikvision/GetProfiles.xml", "H264"),
        ("dahua/GetProfiles.xml", "H265"),
    ],
)
def test_profiles_across_vendors(fixture: str, expected_encoding: str) -> None:
    profiles = parsers.parse_profiles(_read(fixture))
    assert profiles, f"{fixture} produced no profiles"
    profile = profiles[0]
    assert profile["token"]
    encoder = profile["video_encoder"]
    assert encoder["encoding"] == expected_encoding
    assert encoder["width"] and encoder["height"]
    assert encoder["fps_limit"] is not None
    assert encoder["gop"] == 50


def test_axis_system_datetime_parses_to_fields() -> None:
    dt = parsers.parse_system_datetime(_read("axis/GetSystemDateAndTime.xml"))
    assert dt["date_time_type"] == "NTP"
    assert dt["daylight_savings"] is True
    assert dt["UTCDateTime"]["year"] == 2026
    assert dt["UTCDateTime"]["hour"] == 10


def test_reolink_stream_uri() -> None:
    uri = parsers.parse_stream_uri(_read("reolink/GetStreamUri.xml"))
    assert uri == "rtsp://192.168.1.30:554/h264Preview_01_main"
