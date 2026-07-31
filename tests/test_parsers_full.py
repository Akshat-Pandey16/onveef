"""Parser tests using full, realistically-shaped device responses.

The existing parser tests use minimal XML that exercises the happy path. These feed the
large parsers the kind of response cameras actually send — every optional block populated
— which is where the per-vendor branching lives.
"""

from __future__ import annotations

from onveef import parsers

IMAGING_SETTINGS = """
<GetImagingSettingsResponse><ImagingSettings>
  <BacklightCompensation><Mode>ON</Mode><Level>50</Level></BacklightCompensation>
  <Brightness>60.5</Brightness>
  <ColorSaturation>55</ColorSaturation>
  <Contrast>50</Contrast>
  <Exposure>
    <Mode>AUTO</Mode><Priority>LowNoise</Priority>
    <Window bottom="1.0" top="-1.0" right="1.0" left="-1.0"/>
    <MinExposureTime>10</MinExposureTime><MaxExposureTime>40000</MaxExposureTime>
    <MinGain>0</MinGain><MaxGain>100</MaxGain>
    <MinIris>0</MinIris><MaxIris>10</MaxIris>
    <ExposureTime>20000</ExposureTime><Gain>30</Gain><Iris>5</Iris>
  </Exposure>
  <Focus><AutoFocusMode>AUTO</AutoFocusMode><DefaultSpeed>1.0</DefaultSpeed>
    <NearLimit>0.1</NearLimit><FarLimit>100.0</FarLimit></Focus>
  <IrCutFilter>AUTO</IrCutFilter>
  <Sharpness>45</Sharpness>
  <WideDynamicRange><Mode>OFF</Mode><Level>0</Level></WideDynamicRange>
  <WhiteBalance><Mode>AUTO</Mode><CrGain>50</CrGain><CbGain>50</CbGain></WhiteBalance>
</ImagingSettings></GetImagingSettingsResponse>
"""

PTZ_NODES = """
<GetNodesResponse><PTZNode token="N0" FixedHomePosition="true" GeoMove="false">
  <Name>MainNode</Name>
  <SupportedPTZSpaces>
    <AbsolutePanTiltPositionSpace>
      <URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace</URI>
      <XRange><Min>-1.0</Min><Max>1.0</Max></XRange>
      <YRange><Min>-1.0</Min><Max>1.0</Max></YRange>
    </AbsolutePanTiltPositionSpace>
    <AbsoluteZoomPositionSpace>
      <URI>http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace</URI>
      <XRange><Min>0.0</Min><Max>1.0</Max></XRange>
    </AbsoluteZoomPositionSpace>
    <ContinuousPanTiltVelocitySpace>
      <URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</URI>
      <XRange><Min>-1.0</Min><Max>1.0</Max></XRange>
      <YRange><Min>-1.0</Min><Max>1.0</Max></YRange>
    </ContinuousPanTiltVelocitySpace>
  </SupportedPTZSpaces>
  <MaximumNumberOfPresets>300</MaximumNumberOfPresets>
  <HomeSupported>true</HomeSupported>
  <AuxiliaryCommands>tt:Wiper|On</AuxiliaryCommands>
  <AuxiliaryCommands>tt:Wiper|Off</AuxiliaryCommands>
</PTZNode></GetNodesResponse>
"""

PTZ_STATUS = """
<GetStatusResponse><PTZStatus>
  <Position>
    <PanTilt x="0.25" y="-0.5"
      space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace"/>
    <Zoom x="0.75" space="http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace"/>
  </Position>
  <MoveStatus><PanTilt>IDLE</PanTilt><Zoom>MOVING</Zoom></MoveStatus>
  <UtcTime>2026-01-01T12:00:00Z</UtcTime>
</PTZStatus></GetStatusResponse>
"""

ENCODER_OPTIONS = """
<GetVideoEncoderConfigurationOptionsResponse><Options>
  <QualityRange><Min>1</Min><Max>6</Max></QualityRange>
  <JPEG>
    <ResolutionsAvailable><Width>1920</Width><Height>1080</Height></ResolutionsAvailable>
    <ResolutionsAvailable><Width>640</Width><Height>480</Height></ResolutionsAvailable>
    <FrameRateRange><Min>1</Min><Max>25</Max></FrameRateRange>
    <EncodingIntervalRange><Min>1</Min><Max>10</Max></EncodingIntervalRange>
  </JPEG>
  <H264>
    <ResolutionsAvailable><Width>2688</Width><Height>1520</Height></ResolutionsAvailable>
    <GovLengthRange><Min>1</Min><Max>150</Max></GovLengthRange>
    <FrameRateRange><Min>1</Min><Max>30</Max></FrameRateRange>
    <EncodingIntervalRange><Min>1</Min><Max>10</Max></EncodingIntervalRange>
    <H264ProfilesSupported>Baseline</H264ProfilesSupported>
    <H264ProfilesSupported>Main</H264ProfilesSupported>
    <H264ProfilesSupported>High</H264ProfilesSupported>
  </H264>
  <Extension><H265>
    <ResolutionsAvailable><Width>3840</Width><Height>2160</Height></ResolutionsAvailable>
    <GovLengthRange><Min>1</Min><Max>150</Max></GovLengthRange>
    <FrameRateRange><Min>1</Min><Max>20</Max></FrameRateRange>
    <H265ProfilesSupported>Main</H265ProfilesSupported>
  </H265></Extension>
</Options></GetVideoEncoderConfigurationOptionsResponse>
"""

EVENT_PROPERTIES = """
<GetEventPropertiesResponse>
  <TopicNamespaceLocation>http://www.onvif.org/onvif/ver10/topics/topicns.xml</TopicNamespaceLocation>
  <FixedTopicSet>true</FixedTopicSet>
  <TopicSet xmlns:tns1="http://www.onvif.org/ver10/topics"
            xmlns:tnsaxis="http://www.axis.com/2009/event/topics">
    <tns1:RuleEngine>
      <CellMotionDetector><Motion topic="true"/></CellMotionDetector>
      <TamperDetector><Tamper topic="true"/></TamperDetector>
    </tns1:RuleEngine>
    <tns1:Device><Trigger><Relay topic="true"/></Trigger></tns1:Device>
  </TopicSet>
  <TopicExpressionDialect>http://docs.oasis-open.org/wsn/t-1/TopicExpression/Concrete</TopicExpressionDialect>
  <MessageContentFilterDialect>http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter</MessageContentFilterDialect>
</GetEventPropertiesResponse>
"""

OSD = """
<GetOSDsResponse><OSDs token="OSD0">
  <VideoSourceConfigurationToken>VSC0</VideoSourceConfigurationToken>
  <Type>Text</Type>
  <Position><Type>Custom</Type><Pos x="-0.9" y="0.9"/></Position>
  <TextString>
    <Type>DateAndTime</Type>
    <DateFormat>YYYY-MM-DD</DateFormat><TimeFormat>HH:mm:ss</TimeFormat>
    <FontSize>32</FontSize>
    <FontColor><Color X="0" Y="0" Z="0" Colorspace="ycbcr"/></FontColor>
  </TextString>
</OSDs></GetOSDsResponse>
"""

RECORDINGS = """
<GetRecordingsResponse><RecordingItem>
  <RecordingToken>R0</RecordingToken>
  <Configuration>
    <Source>
      <SourceId>urn:uuid:1</SourceId><Name>Cam</Name>
      <Location>Lobby</Location><Description>front</Description><Address>10.0.0.5</Address>
    </Source>
    <Content>Recording of Lobby</Content>
    <MaximumRetentionTime>P30D</MaximumRetentionTime>
  </Configuration>
  <Tracks><Track>
    <TrackToken>T0</TrackToken>
    <Configuration><TrackType>Video</TrackType><Description>h264</Description></Configuration>
  </Track></Tracks>
</RecordingItem></GetRecordingsResponse>
"""


def test_imaging_settings_full() -> None:
    settings = parsers.parse_imaging_settings(IMAGING_SETTINGS)
    assert settings["Brightness"] == 60.5
    assert settings["IrCutFilter"] == "AUTO"
    assert settings["BacklightCompensation"]["mode"] == "ON"
    assert settings["Exposure"]["mode"] == "AUTO"
    assert settings["Exposure"]["MaxExposureTime"] == 40000
    assert settings["Focus"]["auto_focus_mode"] == "AUTO"
    assert settings["WhiteBalance"]["crgain"] == 50
    assert settings["WideDynamicRange"]["mode"] == "OFF"


def test_imaging_settings_model_wrapper() -> None:
    from onveef import models

    settings = models.ImagingSettings.from_dict(parsers.parse_imaging_settings(IMAGING_SETTINGS))
    assert settings.brightness == 60.5
    assert settings.ir_cut_filter == "AUTO"
    assert settings.exposure["priority"] == "LowNoise"


def test_ptz_nodes_full() -> None:
    node = parsers.parse_ptz_nodes(PTZ_NODES)[0]
    assert node["token"] == "N0"
    assert node["name"] == "MainNode"
    assert node["max_presets"] == "300"
    assert node["home_supported"] == "true"
    assert node["ranges"]["absolute_pan_tilt"]["x"] == {"min": -1.0, "max": 1.0}
    assert node["ranges"]["absolute_zoom"]["x"] == {"min": 0.0, "max": 1.0}
    assert node["ranges"]["continuous_pan_tilt"]["y"] == {"min": -1.0, "max": 1.0}


def test_ptz_status_full() -> None:
    status = parsers.parse_ptz_status(PTZ_STATUS)
    assert status["pan"] == 0.25
    assert status["tilt"] == -0.5
    assert status["zoom"] == 0.75
    assert status["move_status"] == {"pan_tilt": "IDLE", "zoom": "MOVING"}
    assert status["utc_time"] == "2026-01-01T12:00:00Z"

    from onveef import models

    model = models.PTZStatus.from_dict(status)
    assert model.move_status_zoom == "MOVING"


def test_encoder_options_normalized_across_codecs() -> None:
    options = parsers.parse_video_encoder_options_normalized(ENCODER_OPTIONS)
    by_encoding = {item["encoding"]: item for item in options}
    assert {"JPEG", "H264", "H265"} <= set(by_encoding)
    assert {"width": 2688, "height": 1520} in by_encoding["H264"]["resolutions"]
    assert by_encoding["H264"]["gop"] == {"min": 1.0, "max": 150.0}
    assert by_encoding["H264"]["profiles"] == ["Baseline", "Main", "High"]
    assert by_encoding["H265"]["fps"] == {"min": 1.0, "max": 20.0}
    assert len(by_encoding["JPEG"]["resolutions"]) == 2


def test_encoder_options_legacy_shape() -> None:
    """The legacy parser preserves the device tree verbatim, keys and all."""
    options = parsers.parse_video_encoder_options(ENCODER_OPTIONS)
    assert options["QualityRange"] == {"Min": "1", "Max": "6"}
    assert options["H264"]["H264ProfilesSupported"] == ["Baseline", "Main", "High"]


def test_event_properties_finds_topics_marked_only_by_attribute() -> None:
    """Trimmed firmware omits MessageDescription and marks leaves with topic="true"."""
    properties = parsers.parse_event_properties(EVENT_PROPERTIES)
    topics = properties["topics"]
    assert "tns1:RuleEngine/CellMotionDetector/Motion" in topics
    assert "tns1:RuleEngine/TamperDetector/Tamper" in topics
    assert "tns1:Device/Trigger/Relay" in topics


def test_event_properties_still_finds_message_description_topics() -> None:
    xml = (
        "<GetEventPropertiesResponse><TopicSet "
        "xmlns:tns1='http://www.onvif.org/ver10/topics'>"
        "<tns1:VideoSource><MotionAlarm><MessageDescription IsProperty='true'/>"
        "</MotionAlarm></tns1:VideoSource></TopicSet></GetEventPropertiesResponse>"
    )
    assert parsers.parse_event_properties(xml)["topics"] == ["tns1:VideoSource/MotionAlarm"]


def test_osd_full() -> None:
    osd = parsers.parse_osds(OSD)[0]
    assert osd["token"] == "OSD0"
    assert osd["video_source_configuration_token"] == "VSC0"
    assert osd["position_type"] == "Custom"
    assert osd["pos_x"] == -0.9
    assert osd["pos_y"] == 0.9
    assert osd["text_type"] == "DateAndTime"
    assert osd["date_format"] == "YYYY-MM-DD"
    assert osd["font_size"] == 32


def test_recordings_full() -> None:
    recording = parsers.parse_recordings(RECORDINGS)[0]
    assert recording["token"] == "R0"
    assert recording["configuration"]["Source"]["Name"] == "Cam"
    assert recording["configuration"]["MaximumRetentionTime"] == "P30D"
    assert recording["tracks"][0]["token"] == "T0"

    from onveef import models

    model = models.Recording.from_dict(recording)
    assert model.tracks[0].configuration["TrackType"] == "Video"


def test_every_parser_tolerates_junk_input() -> None:
    """No parser may raise on an empty, malformed or unexpected document."""
    import inspect

    junk = ["", "<not-xml", "<Envelope/>", "<html><body>404</body></html>"]
    skipped = {"parse_xml", "parse_named_element", "parse_text_element", "parse_created_token"}
    checked = 0
    for name, function in inspect.getmembers(parsers, inspect.isfunction):
        if not name.startswith("parse_") or name in skipped:
            continue
        for document in junk:
            function(document)
        checked += 1
    assert checked > 40


def test_named_and_text_element_helpers_tolerate_junk() -> None:
    assert parsers.parse_named_element("<not-xml", "Options") == {}
    assert parsers.parse_text_element("<not-xml", "Name") == ""
    assert parsers.parse_created_token("<not-xml", tag="Token") == ""
