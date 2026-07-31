"""Tests for the ``onveef`` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import ALL_SERVICES, make_client, stub
from onveef import cli, wsdiscovery

_PROFILES = (
    '<GetProfilesResponse><Profiles token="P0"><Name>main</Name></Profiles></GetProfilesResponse>'
)
_INFO = (
    "<GetDeviceInformationResponse><Manufacturer>ACME</Manufacturer>"
    "<Model>Cam9</Model><SerialNumber>SN1</SerialNumber></GetDeviceInformationResponse>"
)


def _patch_client(monkeypatch: pytest.MonkeyPatch, responder: Any) -> list[str]:
    """Make every CLI command talk to an offline stubbed client."""
    client = make_client(credentials=None)
    captured = stub(client, responder)

    def factory(_args: Any) -> Any:
        return client

    monkeypatch.setattr(cli, "_client", factory)
    return captured


def test_help_lists_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for command in ("discover", "info", "profiles", "stream-uri", "snapshot", "raw", "dump"):
        assert command in out


def test_info_plain_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_client(monkeypatch, _INFO)
    assert cli.main(["info", "10.0.0.9", "-u", "admin", "-p", "pw"]) == 0
    assert "Manufacturer: ACME" in capsys.readouterr().out


def test_info_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_client(monkeypatch, _INFO)
    assert cli.main(["--json", "info", "10.0.0.9"]) == 0
    assert json.loads(capsys.readouterr().out)["Model"] == "Cam9"


def test_profiles(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_client(monkeypatch, _PROFILES)
    assert cli.main(["--json", "profiles", "10.0.0.9"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["token"] == "P0"


def test_stream_uri_defaults_to_the_first_profile(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def responder(envelope: str) -> tuple[int, str]:
        if "GetProfiles" in envelope:
            return 200, _PROFILES
        return 200, (
            "<GetStreamUriResponse><MediaUri><Uri>rtsp://192.168.1.5:554/live</Uri>"
            "</MediaUri></GetStreamUriResponse>"
        )

    _patch_client(monkeypatch, responder)
    assert cli.main(["stream-uri", "10.0.0.9"]) == 0
    assert capsys.readouterr().out.strip() == "rtsp://cam:554/live"


def test_stream_uri_with_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from onveef.client import OnvifCredentials

    client = make_client(credentials=OnvifCredentials("admin", "p@ss"))

    def responder(envelope: str) -> tuple[int, str]:
        if "GetProfiles" in envelope:
            return 200, _PROFILES
        return 200, (
            "<GetStreamUriResponse><MediaUri><Uri>rtsp://192.168.1.5:554/live</Uri>"
            "</MediaUri></GetStreamUriResponse>"
        )

    stub(client, responder)
    monkeypatch.setattr(cli, "_client", lambda _args: client)
    assert cli.main(["stream-uri", "10.0.0.9", "--with-credentials"]) == 0
    assert capsys.readouterr().out.strip() == "rtsp://admin:p%40ss@cam:554/live"


def test_snapshot_uri_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def responder(envelope: str) -> tuple[int, str]:
        if "GetProfiles" in envelope:
            return 200, _PROFILES
        return 200, (
            "<GetSnapshotUriResponse><MediaUri><Uri>http://192.168.1.5/snap</Uri>"
            "</MediaUri></GetSnapshotUriResponse>"
        )

    _patch_client(monkeypatch, responder)
    assert cli.main(["snapshot", "10.0.0.9", "--uri-only"]) == 0
    assert capsys.readouterr().out.strip() == "http://cam/snap"


def test_services(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_client(
        monkeypatch,
        "<GetServicesResponse><Service>"
        "<Namespace>http://www.onvif.org/ver10/media/wsdl</Namespace>"
        "<XAddr>http://192.168.1.5/onvif/media</XAddr></Service></GetServicesResponse>",
    )
    assert cli.main(["--json", "services", "10.0.0.9"]) == 0
    assert json.loads(capsys.readouterr().out)["media"] == "http://cam/onvif/media"


def test_raw_with_builder(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent = _patch_client(monkeypatch, "<GetHostnameResponse><Name>cam</Name></GetHostnameResponse>")
    assert (
        cli.main(
            ["raw", "10.0.0.9", "--operation", "GetHostname", "--builder", "device_get_hostname"]
        )
        == 0
    )
    assert "GetHostname" in capsys.readouterr().out
    assert any("GetHostname" in e for e in sent)


def test_raw_without_a_body_or_builder_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_client(monkeypatch, "<x/>")
    assert cli.main(["raw", "10.0.0.9", "--operation", "GetHostname"]) == 2
    assert "--body" in capsys.readouterr().err


def test_ptz_presets(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def responder(envelope: str) -> tuple[int, str]:
        if "GetProfiles" in envelope:
            return 200, _PROFILES
        return 200, (
            '<GetPresetsResponse><Preset token="1"><Name>Gate</Name></Preset></GetPresetsResponse>'
        )

    _patch_client(monkeypatch, responder)
    assert cli.main(["--json", "ptz", "10.0.0.9", "presets"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["name"] == "Gate"


def test_events_stops_after_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    create = (
        "<CreatePullPointSubscriptionResponse><SubscriptionReference>"
        "<Address>http://cam/onvif/sub</Address></SubscriptionReference>"
        "</CreatePullPointSubscriptionResponse>"
    )
    messages = (
        "<PullMessagesResponse><NotificationMessage><Topic>tns1:Device/Trigger</Topic>"
        '<Message><Message UtcTime="t"><Data>'
        '<SimpleItem Name="State" Value="true"/></Data></Message></Message>'
        "</NotificationMessage></PullMessagesResponse>"
    )

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, create
        if "PullMessages" in envelope:
            return 200, messages
        return 200, "<UnsubscribeResponse/>"

    _patch_client(monkeypatch, responder)
    assert cli.main(["events", "10.0.0.9", "--count", "2"]) == 0
    assert capsys.readouterr().out.count("tns1:Device/Trigger") == 2


def test_dump_writes_fixtures_and_warns_about_redaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def responder(envelope: str) -> tuple[int, str]:
        if "GetDeviceInformation" in envelope:
            return 200, _INFO
        return 200, "<Response/>"

    _patch_client(monkeypatch, responder)
    assert cli.main(["dump", "10.0.0.9", "-d", str(tmp_path)]) == 0
    written = {p.name for p in tmp_path.iterdir()}
    assert "GetDeviceInformation.xml" in written
    assert "ACME" in (tmp_path / "GetDeviceInformation.xml").read_text()
    assert "Redact" in capsys.readouterr().err


def test_discover_reports_nothing_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(wsdiscovery, "discover", lambda **_k: [])
    assert cli.main(["discover", "--timeout", "0.1"]) == 1
    assert "No ONVIF devices" in capsys.readouterr().err


def test_discover_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    device = wsdiscovery.DiscoveredDevice(
        address="10.0.0.4",
        xaddrs=["http://10.0.0.4/onvif/device_service"],
        name="Lobby",
    )
    monkeypatch.setattr(wsdiscovery, "discover", lambda **_k: [device])
    assert cli.main(["--json", "discover"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["name"] == "Lobby"


def test_discover_unicast_uses_probe_device(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_probe(address: str, **_k: Any) -> list[wsdiscovery.DiscoveredDevice]:
        seen.append(address)
        return []

    monkeypatch.setattr(wsdiscovery, "probe_device", fake_probe)
    assert cli.main(["discover", "--address", "10.0.0.4"]) == 1
    assert seen == ["10.0.0.4"]


def test_errors_exit_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_client(monkeypatch, lambda _e: (500, "boom"))
    assert cli.main(["info", "10.0.0.9"]) == 1
    assert "error:" in capsys.readouterr().err


def test_client_factory_maps_flags() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["info", "10.0.0.9", "-u", "a", "-p", "b", "--no-verify", "--no-rewrite-host"]
    )
    client = cli._client(args)
    assert client.credentials.username == "a"
    assert client._verify_tls is False
    assert client._rewrite_host is False
    assert client._password_text_fallback is False
    assert set(ALL_SERVICES) >= {"device"}
    client.close()
