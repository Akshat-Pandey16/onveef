from __future__ import annotations

from onveef import envelopes


def test_namespaces_declared() -> None:
    assert "ver10/recording/wsdl" in envelopes.NS_DECL
    assert "ver10/search/wsdl" in envelopes.NS_DECL
    assert "ver10/replay/wsdl" in envelopes.NS_DECL


def test_recording_create_recording() -> None:
    body = envelopes.recording_create_recording(source_id="src1", source_name="Cam", content="all")
    assert "<trc:CreateRecording>" in body
    assert "<tt:SourceId>src1</tt:SourceId>" in body
    assert "<tt:MaximumRetentionTime>PT0S</tt:MaximumRetentionTime>" in body


def test_recording_create_job_with_source() -> None:
    body = envelopes.recording_create_recording_job(
        recording_token="REC_0", mode="Active", priority=5, source_token="VS0"
    )
    assert "<tt:RecordingToken>REC_0</tt:RecordingToken>" in body
    assert "<tt:Mode>Active</tt:Mode>" in body
    assert "<tt:Token>VS0</tt:Token>" in body


def test_recording_create_job_without_source_omits_block() -> None:
    body = envelopes.recording_create_recording_job(recording_token="REC_0")
    assert "<tt:Source>" not in body


def test_search_find_events_includes_window_and_state() -> None:
    body = envelopes.search_find_events(
        start_point="2026-01-01T00:00:00Z",
        end_point="2026-01-02T00:00:00Z",
        include_start_state=True,
        max_matches=10,
    )
    assert "<tse:StartPoint>2026-01-01T00:00:00Z</tse:StartPoint>" in body
    assert "<tse:EndPoint>2026-01-02T00:00:00Z</tse:EndPoint>" in body
    assert "<tse:IncludeStartState>true</tse:IncludeStartState>" in body
    assert "<tse:MaxMatches>10</tse:MaxMatches>" in body


def test_search_scope_includes_recordings() -> None:
    body = envelopes.search_find_recordings(included_recordings=["REC_0"])
    assert "<tt:IncludedRecordings>REC_0</tt:IncludedRecordings>" in body


def test_replay_get_replay_uri() -> None:
    body = envelopes.replay_get_replay_uri(recording_token="REC_0")
    assert "<trp:RecordingToken>REC_0</trp:RecordingToken>" in body
    assert "<tt:Stream>RTP-Unicast</tt:Stream>" in body


def test_media_create_osd_text() -> None:
    body = envelopes.media_create_osd(
        video_source_configuration_token="VSC0", plain_text="Lobby", font_size=24
    )
    assert "<trt:CreateOSD>" in body
    assert "<tt:PlainText>Lobby</tt:PlainText>" in body
    assert "<tt:FontSize>24</tt:FontSize>" in body
    assert "<tt:VideoSourceConfigurationToken>VSC0</tt:VideoSourceConfigurationToken>" in body


def test_media_set_osd_carries_token() -> None:
    body = envelopes.media_set_osd(osd_token="OSD_1", video_source_configuration_token="VSC0")
    assert 'token="OSD_1"' in body


def test_osd_custom_position_emits_pos() -> None:
    body = envelopes.media_create_osd(
        video_source_configuration_token="VSC0", position_type="Custom", pos_x=0.5, pos_y=-0.5
    )
    assert '<tt:Pos x="0.5" y="-0.5"/>' in body


def test_metadata_configuration_has_analytics_and_token() -> None:
    body = envelopes.media_set_metadata_configuration(
        token="MD0", name="meta", analytics=True, ptz_status=True
    )
    assert 'token="MD0"' in body
    assert "<tt:Analytics>true</tt:Analytics>" in body
    assert "<tt:PTZStatus>" in body
    assert "<tt:Multicast>" in body


def test_analytics_create_rules_structure() -> None:
    body = envelopes.analytics_create_rules(
        configuration_token="CFG0",
        rules=[{"name": "Line", "type": "tt:LineDetector", "parameters": {"Direction": "Any"}}],
    )
    assert "<tan:ConfigurationToken>CFG0</tan:ConfigurationToken>" in body
    assert '<tan:Rule Name="Line" Type="tt:LineDetector">' in body
    assert '<tt:SimpleItem Name="Direction" Value="Any"/>' in body


def test_analytics_delete_modules_lists_names() -> None:
    body = envelopes.analytics_delete_analytics_modules(
        configuration_token="CFG0", names=["A", "B"]
    )
    assert "<tan:AnalyticsModuleName>A</tan:AnalyticsModuleName>" in body
    assert "<tan:AnalyticsModuleName>B</tan:AnalyticsModuleName>" in body


def test_ptz_send_auxiliary_command_escapes() -> None:
    body = envelopes.ptz_send_auxiliary_command(profile_token="P0", auxiliary_data="tt:Wiper|On")
    assert "<tptz:AuxiliaryData>tt:Wiper|On</tptz:AuxiliaryData>" in body


def test_device_scopes_builders() -> None:
    assert "<tds:Scopes>onvif://x</tds:Scopes>" in envelopes.device_set_scopes(scopes=["onvif://x"])
    assert "<tds:ScopeItem>onvif://y</tds:ScopeItem>" in envelopes.device_add_scopes(
        scopes=["onvif://y"]
    )


def test_multicast_builders() -> None:
    assert "<trt:StartMulticastStreaming>" in envelopes.media_start_multicast_streaming(
        profile_token="P0"
    )
    assert "<trt:StopMulticastStreaming>" in envelopes.media_stop_multicast_streaming(
        profile_token="P0"
    )


def test_escaping_of_special_chars() -> None:
    body = envelopes.recording_create_recording(source_id="a&b", source_name="<x>")
    assert "a&amp;b" in body
    assert "&lt;x&gt;" in body


def test_deviceio_and_topics_namespaces_declared() -> None:
    assert "ver10/deviceIO/wsdl" in envelopes.NS_DECL
    assert "ver10/topics" in envelopes.NS_DECL


def test_relay_builders_default_to_device_service() -> None:
    assert envelopes.device_get_relay_outputs() == "<tds:GetRelayOutputs/>"
    assert envelopes.device_get_digital_inputs() == "<tds:GetDigitalInputs/>"
    state = envelopes.device_set_relay_output_state(token="R0", logical_state="active")
    assert "<tds:SetRelayOutputState>" in state
    assert "<tds:RelayOutputToken>R0</tds:RelayOutputToken>" in state


def test_relay_builders_use_deviceio_namespace() -> None:
    assert envelopes.device_get_relay_outputs(use_deviceio=True) == "<tmd:GetRelayOutputs/>"
    assert envelopes.device_get_digital_inputs(use_deviceio=True) == "<tmd:GetDigitalInputs/>"
    state = envelopes.device_set_relay_output_state(
        token="R0", logical_state="active", use_deviceio=True
    )
    assert "<tmd:SetRelayOutputState>" in state
    assert "<tmd:RelayOutputToken>R0</tmd:RelayOutputToken>" in state
    settings = envelopes.device_set_relay_output_settings(
        token="R0", mode="Bistable", use_deviceio=True
    )
    assert '<tmd:RelayOutput token="R0">' in settings
    assert "<tt:Mode>Bistable</tt:Mode>" in settings


def test_create_pull_point_topic_filter_optional() -> None:
    plain = envelopes.events_create_pull_point_subscription()
    assert "<tev:Filter>" not in plain
    filtered = envelopes.events_create_pull_point_subscription(
        topic_filter="tns1:RuleEngine/CellMotionDetector/Motion"
    )
    assert "<tev:Filter>" in filtered
    assert "ConcreteSet" in filtered
    assert "tns1:RuleEngine/CellMotionDetector/Motion" in filtered
