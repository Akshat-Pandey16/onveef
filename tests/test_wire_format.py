"""Tests for defects where the code was syntactically fine but wrong on the wire.

These are the failures a type checker cannot see: an element parsed by the wrong name
(silently empty), a value emitted as an attribute where the schema wants a child element
(silently rejected), a builder with no caller (silently unreachable).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from conftest import make_client, stub
from onveef import envelopes, pacs, parsers

_SUPPORTED_MODULES = """
<GetSupportedAnalyticsModulesResponse>
  <SupportedAnalyticsModules>
    <AnalyticsModuleContentSchemaLocation>http://cam/schema</AnalyticsModuleContentSchemaLocation>
    <AnalyticsModuleDescription Name="tt:CellMotionEngine" fixed="true" maxInstances="1">
      <Parameters>
        <SimpleItemDescription Name="Sensitivity" Type="xs:int"/>
        <ElementItemDescription Name="Layout" Type="tt:CellLayout"/>
      </Parameters>
      <Messages IsProperty="true">
        <Source><SimpleItemDescription Name="VideoSourceConfigurationToken" Type="tt:ReferenceToken"/></Source>
        <Data><SimpleItemDescription Name="IsMotion" Type="xs:boolean"/></Data>
        <ParentTopic>tns1:RuleEngine/CellMotionDetector/Motion</ParentTopic>
      </Messages>
    </AnalyticsModuleDescription>
  </SupportedAnalyticsModules>
</GetSupportedAnalyticsModulesResponse>
"""

_SUPPORTED_RULES = """
<GetSupportedRulesResponse>
  <SupportedRules>
    <RuleDescription Name="tt:LineDetector">
      <Parameters><SimpleItemDescription Name="Direction" Type="tt:Direction"/></Parameters>
      <Messages IsProperty="false">
        <Data><SimpleItemDescription Name="ObjectId" Type="xs:int"/></Data>
        <ParentTopic>tns1:RuleEngine/LineDetector/Crossed</ParentTopic>
      </Messages>
    </RuleDescription>
  </SupportedRules>
</GetSupportedRulesResponse>
"""


def test_supported_analytics_modules_are_not_silently_empty() -> None:
    """The response holds AnalyticsModuleDescription, not AnalyticsModule.

    Parsing it with the configured-module parser returned ``[]`` with no error, which
    reads as "this camera supports no analytics" rather than as a bug.
    """
    client = make_client()
    stub(client, _SUPPORTED_MODULES)
    modules = client.analytics_get_supported_modules(configuration_token="VAC0")
    assert len(modules) == 1
    assert modules[0]["name"] == "tt:CellMotionEngine"
    assert modules[0]["fixed"] is True
    assert modules[0]["max_instances"] == 1
    assert modules[0]["parameters"] == {"Sensitivity": "xs:int", "Layout": "tt:CellLayout"}
    assert modules[0]["messages"][0]["is_property"] is True
    assert modules[0]["messages"][0]["data"] == {"IsMotion": "xs:boolean"}
    assert modules[0]["messages"][0]["parent_topic"].endswith("CellMotionDetector/Motion")


def test_supported_rules_are_not_silently_empty() -> None:
    """GetSupportedRules has the same trap: RuleDescription, not Rule."""
    client = make_client()
    stub(client, _SUPPORTED_RULES)
    rules = client.analytics_get_supported_rules(configuration_token="VAC0")
    assert len(rules) == 1
    assert rules[0]["name"] == "tt:LineDetector"
    assert rules[0]["parameters"] == {"Direction": "tt:Direction"}
    assert rules[0]["messages"][0]["is_property"] is False


def test_configured_modules_and_rules_still_parse_their_own_shape() -> None:
    """The description parsers must not have been swapped in for the configured ones."""
    modules = parsers.parse_analytics_modules(
        "<GetAnalyticsModulesResponse>"
        '<AnalyticsModule Name="M1" Type="tt:CellMotionEngine">'
        '<Parameters><SimpleItem Name="Sensitivity" Value="50"/></Parameters>'
        "</AnalyticsModule></GetAnalyticsModulesResponse>"
    )
    assert modules[0] == {
        "name": "M1",
        "type": "tt:CellMotionEngine",
        "parameters": {"Sensitivity": "50"},
    }
    assert parsers.parse_supported_analytics_modules("<GetAnalyticsModulesResponse/>") == []


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"focus_continuous": 0.5}, "<tt:Continuous><tt:Speed>0.5</tt:Speed></tt:Continuous>"),
        (
            {"focus_absolute": 1.0, "speed": 0.5},
            "<tt:Absolute><tt:Position>1.0</tt:Position><tt:Speed>0.5</tt:Speed></tt:Absolute>",
        ),
        (
            {"focus_relative": -0.2, "speed": 0.5},
            "<tt:Relative><tt:Distance>-0.2</tt:Distance><tt:Speed>0.5</tt:Speed></tt:Relative>",
        ),
        ({"focus_absolute": 1.0}, "<tt:Absolute><tt:Position>1.0</tt:Position></tt:Absolute>"),
    ],
)
def test_focus_values_are_child_elements_not_vector_attributes(
    kwargs: dict[str, float], expected: str
) -> None:
    """Focus is not a PTZ Vector: AbsoluteFocus/RelativeFocus/ContinuousFocus take floats
    as child elements. Emitting ``x=`` attributes made devices reject the request."""
    body = envelopes.imaging_move(video_source_token="VS0", **kwargs)
    assert expected in body
    assert ' x="' not in body


def test_imaging_move_with_no_focus_argument_sends_an_empty_focus() -> None:
    body = envelopes.imaging_move(video_source_token="VS0")
    assert "<timg:Focus></timg:Focus>" in body


def test_ptz_vectors_keep_their_attribute_form() -> None:
    """The fix above must not have been applied to PTZ, where attributes are correct."""
    body = envelopes.ptz_continuous_move(profile_token="P0", pan=0.5, tilt=-0.5, zoom=None)
    assert '<tt:PanTilt x="0.5" y="-0.5"/>' in body


def test_ptz_configuration_options_have_a_stable_shape() -> None:
    """The generic element-to-dict fallback changed shape with the number of children."""
    client = make_client()
    stub(
        client,
        "<GetConfigurationOptionsResponse><PTZConfigurationOptions><Spaces>"
        "<AbsolutePanTiltPositionSpace><URI>http://onvif.org/pt</URI>"
        "<XRange><Min>-1.0</Min><Max>1.0</Max></XRange>"
        "<YRange><Min>-1.0</Min><Max>1.0</Max></YRange></AbsolutePanTiltPositionSpace>"
        "<ZoomSpeedSpace><URI>http://onvif.org/zs</URI>"
        "<XRange><Min>0.0</Min><Max>1.0</Max></XRange></ZoomSpeedSpace>"
        "</Spaces><PTZTimeout><Min>PT0S</Min><Max>PT10S</Max></PTZTimeout>"
        "</PTZConfigurationOptions></GetConfigurationOptionsResponse>",
    )
    options = client.ptz_get_configuration_options(configuration_token="PTZC0")
    assert options["spaces"]["absolute_pan_tilt"]["x"] == {"min": -1.0, "max": 1.0}
    assert options["spaces"]["zoom_speed"]["uri"] == "http://onvif.org/zs"
    assert options["ptz_timeout"] == {"min": "PT0S", "max": "PT10S"}


def test_zero_configuration_addresses_are_always_a_list() -> None:
    """One address used to come back as a string and two as a list."""
    client = make_client()
    stub(
        client,
        "<GetZeroConfigurationResponse><ZeroConfiguration>"
        "<InterfaceToken>eth0</InterfaceToken><Enabled>true</Enabled>"
        "<Addresses>169.254.1.1</Addresses>"
        "</ZeroConfiguration></GetZeroConfigurationResponse>",
    )
    single = client.get_zero_configuration()
    assert single == {
        "interface_token": "eth0",
        "enabled": True,
        "addresses": ["169.254.1.1"],
    }

    stub(
        client,
        "<GetZeroConfigurationResponse><ZeroConfiguration>"
        "<InterfaceToken>eth0</InterfaceToken><Enabled>true</Enabled>"
        "<Addresses>169.254.1.1</Addresses><Addresses>169.254.1.2</Addresses>"
        "</ZeroConfiguration></GetZeroConfigurationResponse>",
    )
    assert client.get_zero_configuration()["addresses"] == ["169.254.1.1", "169.254.1.2"]


_SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "onveef"

# Helpers the library exports for its *users*, which therefore have no internal caller.
_NOT_DISPATCHED = {
    "build_envelope",
    "parse_notification",  # decodes a POST *to* you; no client call produces it
}


def _public_functions(module_path: pathlib.Path) -> list[str]:
    tree = ast.parse(module_path.read_text())
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]


def _callers_of(module: str) -> str:
    """Every source file that could call into ``module`` — i.e. all the others."""
    return "\n".join(path.read_text() for path in _SRC.rglob("*.py") if path.name != module)


@pytest.mark.parametrize("module", ["envelopes.py", "parsers.py", "pacs.py"])
def test_no_builder_or_parser_is_unreachable(module: str) -> None:
    """Every sans-IO function must have a caller — an orphan is a silent coverage gap.

    Six builders once shipped with no client method at all, including the Media2 privacy
    masks the README advertised, and ``ptz_get_preset_tour`` was still orphaned after
    that. This is the test that stops it recurring.
    """
    callers = _callers_of(module)
    orphans = [
        name
        for name in _public_functions(_SRC / module)
        if name not in _NOT_DISPATCHED and f"{name}(" not in callers
    ]
    assert orphans == [], f"{module} exports functions nothing calls: {orphans}"


def test_the_reachability_check_is_actually_looking_at_something() -> None:
    """Guard against the corpus or the function list silently coming back empty."""
    assert len(_public_functions(_SRC / "envelopes.py")) > 150
    assert "get_stream_uri" in _callers_of("envelopes.py")
    assert len(pacs.DOOR_ACTIONS) == 9
