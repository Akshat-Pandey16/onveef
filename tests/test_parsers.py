from __future__ import annotations

from onveef import parsers


def test_parse_recordings() -> None:
    xml = """
    <GetRecordingsResponse>
      <RecordingItem>
        <RecordingToken>REC_0</RecordingToken>
        <Configuration>
          <Source><SourceId>src1</SourceId><Name>Cam</Name></Source>
          <Content>desc</Content>
          <MaximumRetentionTime>PT0S</MaximumRetentionTime>
        </Configuration>
        <Tracks>
          <Track>
            <TrackToken>VIDEO_0</TrackToken>
            <Configuration><TrackType>Video</TrackType></Configuration>
          </Track>
        </Tracks>
      </RecordingItem>
    </GetRecordingsResponse>
    """
    recs = parsers.parse_recordings(xml)
    assert len(recs) == 1
    assert recs[0]["token"] == "REC_0"
    assert recs[0]["tracks"][0]["token"] == "VIDEO_0"
    assert isinstance(recs[0]["configuration"], dict)


def test_parse_recording_jobs() -> None:
    xml = """
    <GetRecordingJobsResponse>
      <JobItem>
        <JobToken>JOB_0</JobToken>
        <JobConfiguration><RecordingToken>REC_0</RecordingToken><Mode>Active</Mode></JobConfiguration>
      </JobItem>
    </GetRecordingJobsResponse>
    """
    jobs = parsers.parse_recording_jobs(xml)
    assert jobs[0]["token"] == "JOB_0"
    assert isinstance(jobs[0]["configuration"], dict)


def test_parse_created_token() -> None:
    assert (
        parsers.parse_created_token(
            "<CreateRecordingResponse><RecordingToken>REC_9</RecordingToken>"
            "</CreateRecordingResponse>",
            tag="RecordingToken",
        )
        == "REC_9"
    )
    assert (
        parsers.parse_created_token(
            "<FindRecordingsResponse><SearchToken>S1</SearchToken></FindRecordingsResponse>",
            tag="SearchToken",
        )
        == "S1"
    )
    assert parsers.parse_created_token("<Empty/>", tag="JobToken") == ""


def test_parse_recording_summary() -> None:
    xml = """
    <GetRecordingSummaryResponse>
      <Summary>
        <DataFrom>2026-01-01T00:00:00Z</DataFrom>
        <DataUntil>2026-06-01T00:00:00Z</DataUntil>
        <NumberRecordings>3</NumberRecordings>
      </Summary>
    </GetRecordingSummaryResponse>
    """
    summary = parsers.parse_recording_summary(xml)
    assert summary["NumberRecordings"] == "3"
    assert summary["DataFrom"] == "2026-01-01T00:00:00Z"


def test_parse_recording_search_results() -> None:
    xml = """
    <GetRecordingSearchResultsResponse>
      <ResultList>
        <SearchState>Completed</SearchState>
        <RecordingInformation>
          <RecordingToken>REC_0</RecordingToken>
          <EarliestRecording>2026-01-01T00:00:00Z</EarliestRecording>
        </RecordingInformation>
      </ResultList>
    </GetRecordingSearchResultsResponse>
    """
    out = parsers.parse_recording_search_results(xml)
    assert out["state"] == "Completed"
    assert len(out["results"]) == 1
    assert out["results"][0]["RecordingToken"] == "REC_0"


def test_parse_event_search_results() -> None:
    xml = """
    <GetEventSearchResultsResponse>
      <ResultList>
        <SearchState>Completed</SearchState>
        <Result><RecordingToken>REC_0</RecordingToken><Time>2026-01-01T00:00:01Z</Time></Result>
        <Result><RecordingToken>REC_1</RecordingToken></Result>
      </ResultList>
    </GetEventSearchResultsResponse>
    """
    out = parsers.parse_event_search_results(xml)
    assert out["state"] == "Completed"
    assert len(out["results"]) == 2


def test_parse_replay_configuration() -> None:
    xml = (
        "<GetReplayConfigurationResponse><Configuration>"
        "<SessionTimeout>PT60S</SessionTimeout></Configuration></GetReplayConfigurationResponse>"
    )
    assert parsers.parse_replay_configuration(xml) == {"session_timeout": "PT60S"}


def test_parse_replay_uri_reuses_stream_parser() -> None:
    xml = "<GetReplayUriResponse><Uri>rtsp://cam/replay</Uri></GetReplayUriResponse>"
    assert parsers.parse_stream_uri(xml) == "rtsp://cam/replay"


def test_parse_osds() -> None:
    xml = """
    <GetOSDsResponse>
      <OSDs token="OSD_0">
        <VideoSourceConfigurationToken>VSC0</VideoSourceConfigurationToken>
        <Type>Text</Type>
        <Position><Type>UpperRight</Type></Position>
        <TextString>
          <Type>Plain</Type>
          <FontSize>30</FontSize>
          <PlainText>Hello</PlainText>
          <FontColor><Color X="0.0" Y="0.0" Z="0.0" Colorspace="ycbcr"/></FontColor>
        </TextString>
      </OSDs>
    </GetOSDsResponse>
    """
    osd = parsers.parse_osds(xml)[0]
    assert osd["token"] == "OSD_0"
    assert osd["osd_type"] == "Text"
    assert osd["position_type"] == "UpperRight"
    assert osd["text_type"] == "Plain"
    assert osd["font_size"] == 30
    assert osd["plain_text"] == "Hello"
    assert osd["font_color"]["X"] == "0.0"


def test_parse_osd_custom_position_keeps_coordinates() -> None:
    xml = """
    <GetOSDResponse>
      <OSD token="OSD_1">
        <Type>Text</Type>
        <Position><Type>Custom</Type><Pos x="-0.5" y="0.8"/></Position>
        <TextString><Type>DateAndTime</Type><FontSize>24</FontSize></TextString>
      </OSD>
    </GetOSDResponse>
    """
    osd = parsers.parse_osd(xml)
    assert osd["position_type"] == "Custom"
    assert osd["pos_x"] == -0.5
    assert osd["pos_y"] == 0.8
    assert osd["text_type"] == "DateAndTime"
    assert osd["font_size"] == 24


def test_parse_osd_options_exposes_position_and_font_options() -> None:
    xml = """
    <GetOSDOptionsResponse>
      <OSDOptions>
        <MaximumNumberOfOSDs Total="4" PlainText="2"/>
        <Type>Text</Type>
        <Type>Image</Type>
        <PositionOption>UpperLeft</PositionOption>
        <PositionOption>UpperRight</PositionOption>
        <PositionOption>LowerLeft</PositionOption>
        <PositionOption>LowerRight</PositionOption>
        <PositionOption>Custom</PositionOption>
        <TextOption>
          <Type>Plain</Type>
          <Type>Date</Type>
          <FontSizeRange><Min>8</Min><Max>64</Max></FontSizeRange>
        </TextOption>
      </OSDOptions>
    </GetOSDOptionsResponse>
    """
    options = parsers.parse_osd_options(xml)
    assert options["position_options"] == [
        "UpperLeft",
        "UpperRight",
        "LowerLeft",
        "LowerRight",
        "Custom",
    ]
    assert options["osd_types"] == ["Text", "Image"]
    assert options["text_types"] == ["Plain", "Date"]
    assert options["font_size_range"] == {"min": 8, "max": 64}
    assert options["maximum_number_of_osds"]["Total"] == 4


def test_parse_metadata_configurations() -> None:
    xml = """
    <GetMetadataConfigurationsResponse>
      <Configurations token="MD0">
        <Name>meta</Name>
        <UseCount>1</UseCount>
        <Analytics>true</Analytics>
        <PTZStatus><Status>true</Status><Position>false</Position></PTZStatus>
      </Configurations>
    </GetMetadataConfigurationsResponse>
    """
    out = parsers.parse_metadata_configurations(xml)
    assert out[0]["token"] == "MD0"
    assert out[0]["analytics"] is True
    assert out[0]["ptz_status"] == {"status": True, "position": False}


def test_parse_digital_inputs() -> None:
    xml = '<GetDigitalInputsResponse><DigitalInputs token="DI0" IdleState="closed"/></GetDigitalInputsResponse>'
    out = parsers.parse_digital_inputs(xml)
    assert out == [{"token": "DI0", "idle_state": "closed"}]


def test_parse_scopes() -> None:
    xml = """
    <GetScopesResponse>
      <Scopes><ScopeDef>Fixed</ScopeDef><ScopeItem>onvif://www.onvif.org/type/video_encoder</ScopeItem></Scopes>
      <Scopes><ScopeDef>Configurable</ScopeDef><ScopeItem>onvif://www.onvif.org/name/Cam</ScopeItem></Scopes>
    </GetScopesResponse>
    """
    out = parsers.parse_scopes(xml)
    assert len(out) == 2
    assert out[1]["scope_def"] == "Configurable"
    assert out[1]["scope_item"].endswith("/name/Cam")


def test_parse_system_log_and_support() -> None:
    log = "<GetSystemLogResponse><SystemLog><String>boot ok</String></SystemLog></GetSystemLogResponse>"
    assert parsers.parse_system_log(log) == {"string": "boot ok"}
    support = (
        "<GetSystemSupportInformationResponse><SupportInformation><String>diag</String>"
        "</SupportInformation></GetSystemSupportInformationResponse>"
    )
    assert parsers.parse_support_information(support) == {"string": "diag"}


def test_parse_certificates_and_dot1x() -> None:
    certs = (
        "<GetCertificatesResponse><NvtCertificate><CertificateID>C1</CertificateID>"
        "</NvtCertificate></GetCertificatesResponse>"
    )
    assert parsers.parse_certificates(certs) == [{"certificate_id": "C1"}]
    dot1x = (
        "<GetDot1XConfigurationsResponse><Dot1XConfiguration>"
        "<Dot1XConfigurationToken>D1</Dot1XConfigurationToken><Identity>user</Identity>"
        "<EAPMethod>13</EAPMethod></Dot1XConfiguration></GetDot1XConfigurationsResponse>"
    )
    out = parsers.parse_dot1x_configurations(dot1x)
    assert out == [{"token": "D1", "identity": "user", "eap_method": "13"}]


def test_parsers_tolerate_garbage() -> None:
    assert parsers.parse_recordings("not xml") == []
    assert parsers.parse_scopes("<bad>") == []
    assert parsers.parse_recording_summary("") == {}


def test_boolean_coercion_accepts_numeric_one_and_zero() -> None:
    xml = """
    <GetMetadataConfigurationsResponse>
      <Configurations token="MD0">
        <Analytics>1</Analytics>
        <PTZStatus><Status>1</Status><Position>0</Position></PTZStatus>
      </Configurations>
    </GetMetadataConfigurationsResponse>
    """
    out = parsers.parse_metadata_configurations(xml)
    assert out[0]["analytics"] is True
    assert out[0]["ptz_status"] == {"status": True, "position": False}


def test_parse_services_detects_deviceio_without_clobbering_device() -> None:
    xml = """
    <GetServicesResponse>
      <Service><Namespace>http://www.onvif.org/ver10/device/wsdl</Namespace>
        <XAddr>http://cam/onvif/device_service</XAddr></Service>
      <Service><Namespace>http://www.onvif.org/ver10/deviceIO/wsdl</Namespace>
        <XAddr>http://cam/onvif/deviceio</XAddr></Service>
    </GetServicesResponse>
    """
    services = parsers.parse_services(xml)
    assert services["device"] == "http://cam/onvif/device_service"
    assert services["deviceio"] == "http://cam/onvif/deviceio"


def test_encoder_config_preserves_zero_and_absent() -> None:
    xml = """
    <GetVideoEncoderConfigurationsResponse>
      <Configurations token="VE0">
        <Encoding>H264</Encoding>
        <RateControl><FrameRateLimit>0</FrameRateLimit><BitrateLimit>2048</BitrateLimit></RateControl>
      </Configurations>
    </GetVideoEncoderConfigurationsResponse>
    """
    out = parsers.parse_video_encoder_configurations(xml)
    assert out[0]["fps_limit"] == 0
    assert out[0]["bitrate_kbps"] == 2048
    assert out[0]["encoding_interval"] is None


def test_analytics_rules_capture_element_item_params() -> None:
    xml = """
    <GetRulesResponse xmlns:tt="http://www.onvif.org/ver10/schema">
      <Rule Name="Line" Type="tt:LineDetector">
        <Parameters>
          <SimpleItem Name="Direction" Value="Any"/>
          <ElementItem Name="Segments">
            <tt:Polyline><tt:Point x="1" y="2"/></tt:Polyline>
          </ElementItem>
        </Parameters>
      </Rule>
    </GetRulesResponse>
    """
    out = parsers.parse_rules(xml)
    assert out[0]["parameters"]["Direction"] == "Any"
    assert "Segments" in out[0]["parameters"]
