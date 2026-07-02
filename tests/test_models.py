from __future__ import annotations

from datetime import UTC, datetime

from onveef import models, parsers


def test_device_information_from_parser() -> None:
    xml = (
        "<GetDeviceInformationResponse><Manufacturer>ACME</Manufacturer>"
        "<Model>X1</Model><FirmwareVersion>1.2</FirmwareVersion>"
        "<SerialNumber>SN9</SerialNumber><HardwareId>HW3</HardwareId>"
        "</GetDeviceInformationResponse>"
    )
    info = models.DeviceInformation.from_dict(parsers.parse_device_information(xml))
    assert info.manufacturer == "ACME"
    assert info.model == "X1"
    assert info.firmware_version == "1.2"
    assert info.serial_number == "SN9"
    assert info.hardware_id == "HW3"


def test_profile_and_video_encoder_from_parser() -> None:
    xml = """
    <GetProfilesResponse>
      <Profiles token="P0">
        <Name>Main</Name>
        <VideoEncoderConfiguration token="VE0">
          <Name>enc</Name><Encoding>H264</Encoding>
          <RateControl><FrameRateLimit>25</FrameRateLimit><BitrateLimit>4096</BitrateLimit></RateControl>
          <H264><GovLength>50</GovLength><H264Profile>High</H264Profile></H264>
        </VideoEncoderConfiguration>
      </Profiles>
    </GetProfilesResponse>
    """
    profile = models.Profile.from_dict(parsers.parse_profiles(xml)[0])
    assert profile.token == "P0"
    assert profile.name == "Main"
    assert profile.video_encoder is not None
    assert profile.video_encoder.encoding == "H264"
    assert profile.video_encoder.fps_limit == 25
    assert profile.video_encoder.bitrate_kbps == 4096
    assert profile.video_encoder.gop == 50
    assert profile.video_encoder.h264_profile == "High"


def test_system_datetime_to_aware_datetime() -> None:
    xml = """
    <GetSystemDateAndTimeResponse><SystemDateAndTime>
      <DateTimeType>NTP</DateTimeType><DaylightSavings>true</DaylightSavings>
      <TimeZone><TZ>CET-1</TZ></TimeZone>
      <UTCDateTime><Date><Year>2026</Year><Month>7</Month><Day>2</Day></Date>
      <Time><Hour>10</Hour><Minute>30</Minute><Second>0</Second></Time></UTCDateTime>
    </SystemDateAndTime></GetSystemDateAndTimeResponse>
    """
    dt = models.SystemDateTime.from_dict(parsers.parse_system_datetime(xml))
    assert dt.date_time_type == "NTP"
    assert dt.daylight_savings is True
    assert dt.timezone == "CET-1"
    assert dt.utc == datetime(2026, 7, 2, 10, 30, 0, tzinfo=UTC)


def test_network_interface_from_parser() -> None:
    xml = """
    <GetNetworkInterfacesResponse>
      <NetworkInterfaces token="eth0"><Enabled>true</Enabled>
        <Info><Name>eth0</Name><HwAddress>00:11:22:33:44:55</HwAddress></Info>
        <IPv4><Enabled>true</Enabled><Config>
          <Manual><Address>192.168.1.64</Address><PrefixLength>24</PrefixLength></Manual></Config></IPv4>
        <IPv6><Enabled>true</Enabled><Config>
          <LinkLocal><Address>fe80::1</Address></LinkLocal></Config></IPv6>
      </NetworkInterfaces>
    </GetNetworkInterfacesResponse>
    """
    iface = models.NetworkInterface.from_dict(parsers.parse_network_interfaces(xml)[0])
    assert iface.token == "eth0"
    assert iface.enabled is True
    assert iface.ipv4_addresses == ["192.168.1.64"]
    assert iface.ipv6_addresses == ["fe80::1"]
