"""PTZ spaces, click-to-center and capability summaries."""

from __future__ import annotations

import pathlib

import pytest

from conftest import make_async_client, make_client, stub, stub_async
from onveef import envelopes, parsers, ptz
from onveef.exceptions import OnvifCapabilityMissingError

_FOV = ptz.FOV_TRANSLATION_SPACE
_GENERIC = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/TranslationGenericSpace"
_CPPLUS = pathlib.Path(__file__).parent / "fixtures" / "cpplus"
_NS = (
    'xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:tt="http://www.onvif.org/ver10/schema" '
    'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"'
)


def _soap(body: str) -> str:
    return f"<s:Envelope {_NS}><s:Body>{body}</s:Body></s:Envelope>"


_NODES = _soap(
    '<tptz:GetNodesResponse><tptz:PTZNode token="N1" FixedHomePosition="false" GeoMove="true">'
    "<tt:Name>Dome</tt:Name><tt:SupportedPTZSpaces>"
    "<tt:RelativePanTiltTranslationSpace>"
    f"<tt:URI>{_GENERIC}</tt:URI>"
    "<tt:XRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:XRange>"
    "<tt:YRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:YRange>"
    "</tt:RelativePanTiltTranslationSpace>"
    f"<tt:RelativePanTiltTranslationSpace><tt:SpaceURI>{_FOV}</tt:SpaceURI>"
    "<tt:XRange><tt:Min>-INF</tt:Min><tt:Max>INF</tt:Max></tt:XRange>"
    "<tt:YRange><tt:Min>-INF</tt:Min><tt:Max>INF</tt:Max></tt:YRange>"
    "</tt:RelativePanTiltTranslationSpace>"
    "<tt:ContinuousPanTiltVelocitySpace>"
    "<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:URI>"
    "<tt:XRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:XRange>"
    "<tt:YRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:YRange>"
    "</tt:ContinuousPanTiltVelocitySpace>"
    "<tt:ContinuousZoomVelocitySpace>"
    "<tt:URI>http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace</tt:URI>"
    "<tt:XRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:XRange>"
    "</tt:ContinuousZoomVelocitySpace>"
    "<tt:PanTiltSpeedSpace>"
    "<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/GenericSpeedSpace</tt:URI>"
    "<tt:XRange><tt:Min>0</tt:Min><tt:Max>1</tt:Max></tt:XRange></tt:PanTiltSpeedSpace>"
    "</tt:SupportedPTZSpaces>"
    "<tt:MaximumNumberOfPresets>255</tt:MaximumNumberOfPresets>"
    "<tt:HomeSupported>true</tt:HomeSupported>"
    "<tt:AuxiliaryCommands>tt:Wiper|On</tt:AuxiliaryCommands>"
    "<tt:AuxiliaryCommands>tt:Wiper|Off</tt:AuxiliaryCommands>"
    "<tt:Extension><tt:SupportedPresetTour>"
    "<tt:MaximumNumberOfPresetTours>8</tt:MaximumNumberOfPresetTours>"
    "<tt:PTZPresetTourOperation>Start</tt:PTZPresetTourOperation>"
    "<tt:PTZPresetTourOperation>Stop</tt:PTZPresetTourOperation>"
    "</tt:SupportedPresetTour></tt:Extension>"
    "</tptz:PTZNode></tptz:GetNodesResponse>"
)
_PROFILES = (
    '<GetProfilesResponse><Profiles token="P0"><Name>main</Name>'
    '<VideoSourceConfiguration token="VSC0"><Name>v</Name><SourceToken>VS0</SourceToken>'
    '</VideoSourceConfiguration><PTZConfiguration token="PTZ0"><Name>ptz</Name>'
    "<NodeToken>N1</NodeToken></PTZConfiguration></Profiles>"
    '<Profiles token="P1"><Name>sub</Name></Profiles></GetProfilesResponse>'
)


def _device(envelope: str) -> tuple[int, str]:
    if "GetProfiles" in envelope:
        return 200, _PROFILES
    if "GetNodes" in envelope:
        return 200, _NODES
    if "<timg:GetOptions>" in envelope:
        return 200, (_CPPLUS / "GetOptions-00000.xml").read_text()
    if "<timg:GetMoveOptions>" in envelope:
        return 200, (
            "<GetMoveOptionsResponse><MoveOptions><Continuous><Speed><Min>-1</Min><Max>1</Max>"
            "</Speed></Continuous></MoveOptions></GetMoveOptionsResponse>"
        )
    return 200, "<RelativeMoveResponse/>"


def test_every_space_of_a_kind_is_listed_not_just_the_first() -> None:
    """The FOV space usually comes second; keeping only the first hid click-to-center."""
    [node] = parsers.parse_ptz_nodes(_NODES)
    assert [space["uri"] for space in node["spaces"]["relative_pan_tilt"]] == [_GENERIC, _FOV]
    assert node["ranges"]["relative_pan_tilt"]["x"] == {"min": -1.0, "max": 1.0}
    assert node["spaces"]["pan_tilt_speed"][0]["x"] == {"min": 0.0, "max": 1.0}
    assert node["max_presets"] == "255"
    assert node["max_preset_tours"] == 8
    assert node["preset_tour_operations"] == ["Start", "Stop"]
    assert node["auxiliary_commands"] == ["tt:Wiper|On", "tt:Wiper|Off"]
    assert node["geo_move"] is True


def test_a_node_without_spaces_or_tours() -> None:
    [node] = parsers.parse_ptz_nodes(
        _soap(
            '<tptz:GetNodesResponse><tptz:PTZNode token="N1"><tt:Name>Bullet</tt:Name>'
            "<tt:MaximumNumberOfPresets>0</tt:MaximumNumberOfPresets>"
            "<tt:HomeSupported>false</tt:HomeSupported></tptz:PTZNode></tptz:GetNodesResponse>"
        )
    )
    assert node["max_preset_tours"] == 0
    assert node["preset_tour_operations"] == []
    assert node["geo_move"] is False
    assert "spaces" not in node


def test_ptz_status_names_the_space_its_position_is_in() -> None:
    generic = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace"
    named = _soap(
        "<tptz:GetStatusResponse><tptz:PTZStatus><tt:Position>"
        f'<tt:PanTilt x="0.5" y="-0.25" space="{generic}"/><tt:Zoom x="0.1"/>'
        "</tt:Position></tptz:PTZStatus></tptz:GetStatusResponse>"
    )
    status = parsers.parse_ptz_status(named)
    assert status["pan_tilt_space"] == generic
    assert "zoom_space" not in status
    assert "pan_tilt_space" not in parsers.parse_ptz_status(
        named.replace(f' space="{generic}"', "")
    )


@pytest.mark.parametrize(
    "builder",
    [envelopes.ptz_absolute_move, envelopes.ptz_relative_move, envelopes.ptz_continuous_move],
)
def test_every_move_can_name_its_coordinate_spaces(builder: object) -> None:
    body = builder(  # type: ignore[operator]
        profile_token="P0",
        pan=0.5,
        tilt=0.0,
        zoom=0.1,
        pan_tilt_space=_FOV,
        zoom_space="urn:zoom",
    )
    assert f'<tt:PanTilt x="0.5" y="0.0" space="{_FOV}"/>' in body
    assert '<tt:Zoom x="0.1" space="urn:zoom"/>' in body


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (0.5, 0.5, (0.0, 0.0)),
        (1.0, 0.0, (1.0, 1.0)),
        (0.0, 1.0, (-1.0, -1.0)),
        (0.75, 0.25, (0.5, 0.5)),
    ],
)
def test_a_point_on_the_picture_maps_to_the_move_that_centres_it(
    x: float, y: float, expected: tuple[float, float]
) -> None:
    assert ptz.fov_translation(x, y) == expected


@pytest.mark.parametrize(("x", "y"), [(-0.1, 0.5), (0.5, 1.5), (float("nan"), 0.5)])
def test_a_point_off_the_picture_is_refused(x: float, y: float) -> None:
    with pytest.raises(ValueError, match="fraction"):
        ptz.fov_translation(x, y)


def test_ptz_center_moves_in_the_nodes_fov_space() -> None:
    client = make_client()
    sent = stub(client, _device)
    client.ptz_center(profile_token="P0", x=0.75, y=0.25, zoom=0.2)
    move = sent[-1]
    assert "<tptz:RelativeMove>" in move
    assert f'<tt:PanTilt x="0.5" y="0.5" space="{_FOV}"/>' in move
    assert '<tt:Zoom x="0.2"/>' in move


async def test_async_ptz_center_with_a_known_space_skips_the_lookups() -> None:
    client = make_async_client()
    sent = stub_async(client, _device)
    await client.ptz_center(profile_token="P0", x=0.5, y=0.5, pan_tilt_space=_FOV)
    assert len(sent) == 1


def test_ptz_center_needs_a_fov_space() -> None:
    client = make_client()
    stub(client, lambda e: _device(e) if "GetNodes" not in e else (200, _NODES.replace(_FOV, "x")))
    with pytest.raises(OnvifCapabilityMissingError, match="TranslationSpaceFov"):
        client.ptz_center(profile_token="P0", x=0.5, y=0.5)


def test_ptz_center_needs_a_profile_with_ptz() -> None:
    client = make_client()
    stub(client, _device)
    with pytest.raises(OnvifCapabilityMissingError, match="no PTZ configuration"):
        client.ptz_center(profile_token="P1", x=0.5, y=0.5)
    with pytest.raises(OnvifCapabilityMissingError, match="no profile"):
        client.ptz_center(profile_token="P9", x=0.5, y=0.5)


def test_capabilities_summarise_the_node_and_the_lens() -> None:
    client = make_client()
    stub(client, _device)
    caps = client.ptz_capabilities()
    assert caps["profile_token"] == "P0"
    assert caps["node_token"] == "N1"
    assert caps["video_source_token"] == "VS0"
    assert caps["click_to_center"] is True
    assert caps["fov_space"] == _FOV
    assert caps["continuous_pan_tilt"] and caps["continuous_zoom"] and caps["relative_pan_tilt"]
    assert not caps["absolute_pan_tilt"]
    assert caps["presets"] and caps["max_presets"] == 255
    assert caps["home"] and caps["preset_tours"] and caps["geo_move"]
    assert caps["pan_tilt_speed"] == {"min": 0.0, "max": 1.0}
    assert caps["auxiliary_commands"] == ["tt:Wiper|On", "tt:Wiper|Off"]
    # The CP Plus lens: manual focus that can be driven, a manual iris, nothing automatic.
    assert caps["focus"] is True
    assert caps["focus_speed"] == {"min": -1.0, "max": 1.0}
    assert caps["auto_focus"] is False
    assert caps["iris"] is True
    assert caps["iris_range"] == {"min": 0.0, "max": 1.0}
    assert caps["auto_iris"] is False


async def test_async_capabilities_without_an_imaging_service() -> None:
    from conftest import ALL_SERVICES

    services = {key: url for key, url in ALL_SERVICES.items() if key != "imaging"}
    client = make_async_client(services)
    stub_async(client, _device)
    caps = await client.ptz_capabilities(profile_token="P0")
    assert caps["click_to_center"] is True
    assert caps["focus"] is False and caps["iris"] is False


def test_capabilities_need_a_ptz_profile() -> None:
    client = make_client()
    stub(
        client, lambda e: (200, '<GetProfilesResponse><Profiles token="P1"/></GetProfilesResponse>')
    )
    with pytest.raises(OnvifCapabilityMissingError, match="PTZ configuration"):
        client.ptz_capabilities()


def test_infinite_ranges_are_not_reported_as_speeds() -> None:
    node = {
        "token": "N",
        "spaces": {"pan_tilt_speed": [{"uri": "u", "x": {"min": float("-inf"), "max": 1.0}}]},
    }
    caps = ptz.capabilities(profile={"token": "P"}, node=node)
    assert caps["pan_tilt_speed"] is None
    assert caps["fov_space"] == ""
