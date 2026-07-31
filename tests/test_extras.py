from __future__ import annotations

from onveef import envelopes, parsers
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint

_SERVICES = {
    "device": "http://cam/onvif/device_service",
    "imaging": "http://cam/onvif/imaging",
    "ptz": "http://cam/onvif/ptz",
}


def _client() -> OnvifClient:
    return OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr="http://cam/onvif/device_service", services=_SERVICES),
        credentials=OnvifCredentials(),
    )


def _stub(client: OnvifClient, xml: str) -> list[str]:
    captured: list[str] = []

    def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        captured.append(envelope)
        return 200, xml

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def test_geo_location_builder_and_parser() -> None:
    body = envelopes.device_set_geo_location(lon=13.4, lat=52.5, elevation=34.0)
    assert 'lon="13.4"' in body
    assert 'lat="52.5"' in body
    out = parsers.parse_geo_location(
        '<GetGeoLocationResponse><Location lon="13.4" lat="52.5" elevation="34"/>'
        "</GetGeoLocationResponse>"
    )
    assert out == [{"lon": 13.4, "lat": 52.5, "elevation": 34.0}]


def test_parse_imaging_presets() -> None:
    xml = (
        "<GetPresetsResponse>"
        '<Preset token="P0" type="Manual"><Name>Indoor</Name></Preset>'
        '<Preset token="P1" type="Manual"><Name>Outdoor</Name></Preset>'
        "</GetPresetsResponse>"
    )
    out = parsers.parse_imaging_presets(xml)
    assert out[0] == {"token": "P0", "type": "Manual", "name": "Indoor"}
    assert out[1]["name"] == "Outdoor"


def test_parse_preset_tours() -> None:
    xml = (
        "<GetPresetToursResponse>"
        '<PresetTour token="T0"><Name>Patrol</Name><AutoStart>true</AutoStart>'
        "<Status><State>Idle</State></Status></PresetTour>"
        "</GetPresetToursResponse>"
    )
    out = parsers.parse_preset_tours(xml)
    assert out[0]["token"] == "T0"
    assert out[0]["auto_start"] is True
    assert out[0]["state"] == "Idle"


def test_parse_system_uris() -> None:
    xml = (
        "<GetSystemUrisResponse>"
        "<SystemLogUris><SystemLogUri><Type>System</Type>"
        "<Uri>http://cam/logs/system</Uri></SystemLogUri></SystemLogUris>"
        "<SupportInfoUri>http://cam/support</SupportInfoUri>"
        "</GetSystemUrisResponse>"
    )
    out = parsers.parse_system_uris(xml)
    assert out["support_info_uri"] == "http://cam/support"


def test_client_imaging_and_ptz_dispatch() -> None:
    client = _client()
    sent = _stub(
        client,
        '<GetPresetsResponse><Preset token="P0"><Name>X</Name></Preset></GetPresetsResponse>',
    )
    presets = client.imaging_get_presets(video_source_token="VS0")
    assert presets[0]["token"] == "P0"
    assert "<timg:GetPresets>" in sent[0]

    sent = _stub(client, "<OperatePresetTourResponse/>")
    client.ptz_operate_preset_tour(profile_token="P0", preset_tour_token="T0", operation="Start")
    assert "<tptz:Operation>Start</tptz:Operation>" in sent[0]

    sent = _stub(client, "<SetGeoLocationResponse/>")
    client.set_geo_location(lon=1.0, lat=2.0)
    assert "<tds:SetGeoLocation>" in sent[0]


def test_breaker_configure_affects_new_instances() -> None:
    """Module-level configure() used to be a no-op for instances created afterwards."""
    from onveef import breaker as breaker_module

    original = (breaker_module._WINDOW_S, breaker_module._THRESHOLD, breaker_module._OPEN_S)
    try:
        breaker_module.configure(window_s=11.0, threshold=7, open_s=13.0)
        fresh = breaker_module.CircuitBreaker()
        assert (fresh.window_s, fresh.threshold, fresh.open_s) == (11.0, 7, 13.0)
        explicit = breaker_module.CircuitBreaker(threshold=2)
        assert explicit.threshold == 2
        assert explicit.window_s == 11.0
    finally:
        breaker_module.configure(window_s=original[0], threshold=original[1], open_s=original[2])
        breaker_module.reset()


def test_default_user_agent_tracks_the_package_version() -> None:
    """A hardcoded string drifts from __version__ on every release."""
    import onveef
    from onveef.client import DEFAULT_USER_AGENT

    assert f"onveef/{onveef.__version__}" == DEFAULT_USER_AGENT
