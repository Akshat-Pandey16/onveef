"""Tests for the operations that closed the Profile T/G/A coverage gaps.

Each of these existed as a hole where a related operation was already present: you could
add an audio source configuration but not list one, subscribe for push events but not
decode them, run a preset tour but not create one.
"""

from __future__ import annotations

import pytest

from conftest import make_async_client, make_client, stub, stub_async
from onveef import envelopes, pacs, parsers

_NOTIFY = """
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2">
  <s:Body>
    <wsnt:Notify>
      <wsnt:NotificationMessage>
        <wsnt:Topic>tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic>
        <wsnt:Message>
          <Message UtcTime="2026-08-04T10:11:12Z" PropertyOperation="Changed">
            <Source><SimpleItem Name="VideoSourceConfigurationToken" Value="VSC0"/></Source>
            <Data><SimpleItem Name="IsMotion" Value="true"/></Data>
          </Message>
        </wsnt:Message>
      </wsnt:NotificationMessage>
    </wsnt:Notify>
  </s:Body>
</s:Envelope>
"""

_SUBSCRIBE = """
<SubscribeResponse>
  <SubscriptionReference>
    <Address>http://192.168.9.9/onvif/sub?id=7</Address>
    <ReferenceParameters><SubscriptionId>7</SubscriptionId></ReferenceParameters>
  </SubscriptionReference>
  <CurrentTime>2026-08-04T10:11:12Z</CurrentTime>
  <TerminationTime>2026-08-04T10:12:12Z</TerminationTime>
</SubscribeResponse>
"""


def test_a_pushed_notify_envelope_decodes_like_a_pulled_one() -> None:
    """The device POSTs this to a consumer; without a parser the push path is unusable."""
    messages = parsers.parse_notification(_NOTIFY)
    assert len(messages) == 1
    assert messages[0]["topic"] == "tns1:RuleEngine/CellMotionDetector/Motion"
    assert messages[0]["utc_time"] == "2026-08-04T10:11:12Z"
    assert messages[0]["property_operation"] == "Changed"
    assert messages[0]["source"] == {"VideoSourceConfigurationToken": "VSC0"}
    assert messages[0]["data"] == {"IsMotion": "true"}


@pytest.mark.parametrize("junk", ["", "<not-xml", "<html>404</html>", "<s:Envelope/>"])
def test_notification_parsing_never_raises_on_junk(junk: str) -> None:
    """A consumer is exposed to the network; a malformed POST must not take it down."""
    assert parsers.parse_notification(junk) == []


def test_subscribe_is_parsed_as_a_subscription_not_a_pull_point() -> None:
    result = parsers.parse_subscribe(_SUBSCRIBE)
    assert result["subscription_url"] == "http://192.168.9.9/onvif/sub?id=7"
    assert result["termination_time"] == "2026-08-04T10:12:12Z"
    assert result["reference_parameters"]["SubscriptionId"] == "7"


def test_events_subscribe_rewrites_the_manager_url() -> None:
    """The manager URL is a device-reported address like any other."""
    client = make_client()
    sent = stub(client, _SUBSCRIBE)
    result = client.events_subscribe(consumer_address="http://consumer:9000/events")
    assert "<wsnt:Subscribe>" in sent[0]
    assert "http://consumer:9000/events" in sent[0]
    assert result["subscription_url"] == "http://cam/onvif/sub?id=7"


def test_audio_source_configurations_round_trip() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetAudioSourceConfigurationsResponse>"
        '<Configurations token="ASC0"><Name>audio</Name><UseCount>1</UseCount>'
        "<SourceToken>AS0</SourceToken></Configurations>"
        "</GetAudioSourceConfigurationsResponse>",
    )
    configs = client.get_audio_source_configurations()
    assert "<trt:GetAudioSourceConfigurations/>" in sent[0]
    assert configs[0] == {"token": "ASC0", "name": "audio", "use_count": 1, "source_token": "AS0"}

    sent = stub(
        client,
        "<GetAudioSourceConfigurationOptionsResponse><Options>"
        "<InputTokensAvailable>AS0</InputTokensAvailable>"
        "<InputTokensAvailable>AS1</InputTokensAvailable>"
        "</Options></GetAudioSourceConfigurationOptionsResponse>",
    )
    options = client.get_audio_source_configuration_options(configuration_token="ASC0")
    assert "<trt:ConfigurationToken>ASC0</trt:ConfigurationToken>" in sent[0]
    assert options["input_tokens"] == ["AS0", "AS1"]

    sent = stub(client, "<SetAudioSourceConfigurationResponse/>")
    client.set_audio_source_configuration(token="ASC0", name="audio", source_token="AS1")
    assert "<tt:SourceToken>AS1</tt:SourceToken>" in sent[0]
    assert "<trt:ForcePersistence>true</trt:ForcePersistence>" in sent[0]


def test_audio_output_configuration_options() -> None:
    client = make_client()
    stub(
        client,
        "<GetAudioOutputConfigurationOptionsResponse><Options>"
        "<OutputTokensAvailable>AO0</OutputTokensAvailable>"
        "<SendPrimacyOptions>www.onvif.org/ver20/HalfDuplex/Server</SendPrimacyOptions>"
        "<OutputLevelRange><Min>0</Min><Max>100</Max></OutputLevelRange>"
        "</Options></GetAudioOutputConfigurationOptionsResponse>",
    )
    options = client.get_audio_output_configuration_options()
    assert options["output_tokens"] == ["AO0"]
    assert options["output_level_range"] == {"min": 0, "max": 100}
    assert options["send_primacy_options"][0].endswith("HalfDuplex/Server")


def test_video_source_modes_expose_the_resolutions_a_mode_gates() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetVideoSourceModesResponse>"
        '<VideoSourceModes token="M0" Enabled="true">'
        "<MaxFramerate>30</MaxFramerate>"
        "<MaxResolution><Width>2688</Width><Height>1520</Height></MaxResolution>"
        "<Encodings>H264 H265</Encodings><Reboot>false</Reboot>"
        "<Description>16:9</Description>"
        "</VideoSourceModes>"
        '<VideoSourceModes token="M1" Enabled="false">'
        "<MaxResolution><Width>2048</Width><Height>1536</Height></MaxResolution>"
        "<Reboot>true</Reboot><Description>4:3</Description>"
        "</VideoSourceModes>"
        "</GetVideoSourceModesResponse>",
    )
    modes = client.get_video_source_modes(video_source_token="VS0")
    assert "<trt:VideoSourceToken>VS0</trt:VideoSourceToken>" in sent[0]
    assert modes[0]["token"] == "M0"
    assert modes[0]["enabled"] is True
    assert modes[0]["max_resolution"] == {"width": 2688, "height": 1520}
    assert modes[0]["encodings"] == ["H264", "H265"]
    assert modes[1]["enabled"] is False
    assert modes[1]["reboot"] is True


def test_set_video_source_mode_reports_whether_the_device_reboots() -> None:
    client = make_client()
    sent = stub(
        client, "<SetVideoSourceModeResponse><Reboot>true</Reboot></SetVideoSourceModeResponse>"
    )
    assert client.set_video_source_mode(video_source_token="VS0", mode_token="M1") is True
    assert "<trt:VideoSourceModeToken>M1</trt:VideoSourceModeToken>" in sent[0]

    stub(client, "<SetVideoSourceModeResponse><Reboot>false</Reboot></SetVideoSourceModeResponse>")
    assert client.set_video_source_mode(video_source_token="VS0", mode_token="M0") is False


def test_audio_decoder_configurations_enable_the_backchannel() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetAudioDecoderConfigurationsResponse>"
        '<Configurations token="ADC0"><Name>talkback</Name><UseCount>0</UseCount></Configurations>'
        "</GetAudioDecoderConfigurationsResponse>",
    )
    configs = client.get_audio_decoder_configurations()
    assert "<trt:GetAudioDecoderConfigurations/>" in sent[0]
    assert configs[0] == {"token": "ADC0", "name": "talkback", "use_count": 0}

    sent = stub(
        client,
        "<GetAudioDecoderConfigurationOptionsResponse><Options>"
        "<G711DecOptions>"
        "<Bitrate><Items>64</Items></Bitrate>"
        "<SampleRateRange><Items>8</Items></SampleRateRange>"
        "</G711DecOptions>"
        "<AACDecOptions>"
        "<Bitrate><Items>64</Items><Items>128</Items></Bitrate>"
        "<SampleRateRange><Items>16</Items></SampleRateRange>"
        "</AACDecOptions>"
        "</Options></GetAudioDecoderConfigurationOptionsResponse>",
    )
    options = client.get_audio_decoder_configuration_options(profile_token="P0")
    assert "<trt:ProfileToken>P0</trt:ProfileToken>" in sent[0]
    assert options["g711"] == {"bitrate_list": [64], "sample_rate_list": [8]}
    assert options["aac"]["bitrate_list"] == [64, 128]

    sent = stub(client, "<AddAudioDecoderConfigurationResponse/>")
    client.add_audio_decoder_configuration(profile_token="P0", configuration_token="ADC0")
    assert "<trt:AddAudioDecoderConfiguration>" in sent[0]

    sent = stub(client, "<RemoveAudioDecoderConfigurationResponse/>")
    client.remove_audio_decoder_configuration(profile_token="P0")
    assert "<trt:RemoveAudioDecoderConfiguration>" in sent[0]


def test_analytics_configuration_can_be_attached_to_a_profile() -> None:
    """Rule CRUD only helps once a configuration is actually on a profile."""
    client = make_client()
    sent = stub(client, "<AddVideoAnalyticsConfigurationResponse/>")
    client.add_video_analytics_configuration(profile_token="P0", configuration_token="VAC0")
    assert "<trt:ProfileToken>P0</trt:ProfileToken>" in sent[0]
    assert "<trt:ConfigurationToken>VAC0</trt:ConfigurationToken>" in sent[0]

    sent = stub(client, "<RemoveVideoAnalyticsConfigurationResponse/>")
    client.remove_video_analytics_configuration(profile_token="P0")
    assert "<trt:RemoveVideoAnalyticsConfiguration>" in sent[0]

    sent = stub(client, "<SetVideoAnalyticsConfigurationResponse/>")
    client.set_video_analytics_configuration(
        token="VAC0",
        name="analytics",
        modules=[
            {"name": "M1", "type": "tt:CellMotionEngine", "parameters": {"Sensitivity": "50"}}
        ],
        rules=[{"name": "R1", "type": "tt:CellMotionDetector", "parameters": {"MinCount": "5"}}],
    )
    assert "<tt:AnalyticsEngineConfiguration>" in sent[0]
    assert '<tt:AnalyticsModule Name="M1" Type="tt:CellMotionEngine">' in sent[0]
    assert '<tt:Rule Name="R1" Type="tt:CellMotionDetector">' in sent[0]
    assert '<tt:SimpleItem Name="MinCount" Value="5"/>' in sent[0]


def test_recording_tracks_can_be_created_and_configured() -> None:
    client = make_client()
    sent = stub(client, "<CreateTrackResponse><TrackToken>T1</TrackToken></CreateTrackResponse>")
    assert client.create_track(recording_token="R0", track_type="Video") == "T1"
    assert "<tt:TrackType>Video</tt:TrackType>" in sent[0]

    sent = stub(
        client,
        "<GetTrackConfigurationResponse><TrackConfiguration>"
        "<TrackType>Audio</TrackType><Description>mic</Description>"
        "</TrackConfiguration></GetTrackConfigurationResponse>",
    )
    config = client.get_track_configuration(recording_token="R0", track_token="T1")
    assert config == {"track_type": "Audio", "description": "mic"}

    sent = stub(client, "<SetTrackConfigurationResponse/>")
    client.set_track_configuration(
        recording_token="R0", track_token="T1", track_type="Audio", description="mic"
    )
    assert "<trc:TrackToken>T1</trc:TrackToken>" in sent[0]

    sent = stub(client, "<DeleteTrackResponse/>")
    client.delete_track(recording_token="R0", track_token="T1")
    assert "<trc:DeleteTrack>" in sent[0]


def test_recording_job_state_distinguishes_configured_from_recording() -> None:
    client = make_client()
    stub(
        client,
        "<GetRecordingJobStateResponse><State>"
        "<RecordingToken>R0</RecordingToken><State>Active</State>"
        "<Sources><SourceToken><Token>VS0</Token></SourceToken><State>Recording</State>"
        "<Tracks><SourceTag>VIDEO</SourceTag><Destination>T0</Destination>"
        "<State>Recording</State></Tracks>"
        "</Sources></State></GetRecordingJobStateResponse>",
    )
    state = client.get_recording_job_state(job_token="J0")
    assert state["state"] == "Active"
    assert state["sources"][0]["state"] == "Recording"
    assert state["sources"][0]["tracks"][0]["destination"] == "T0"


def test_media_attributes_report_the_span_a_replay_can_seek_within() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetMediaAttributesResponse><MediaAttributes>"
        "<RecordingToken>R0</RecordingToken>"
        "<TrackAttributes>"
        "<TrackInformation><TrackToken>T0</TrackToken><TrackType>Video</TrackType>"
        "<DataFrom>2026-08-01T00:00:00Z</DataFrom><DataTo>2026-08-04T00:00:00Z</DataTo>"
        "</TrackInformation>"
        "<VideoAttributes><Encoding>H264</Encoding><Width>1920</Width><Height>1080</Height>"
        "<Bitrate>4096</Bitrate><Framerate>25</Framerate></VideoAttributes>"
        "</TrackAttributes>"
        "<From>2026-08-01T00:00:00Z</From><Until>2026-08-04T00:00:00Z</Until>"
        "</MediaAttributes></GetMediaAttributesResponse>",
    )
    attributes = client.get_media_attributes(recording_tokens=["R0"], time="2026-08-04T00:00:00Z")
    assert "<tse:RecordingTokens>R0</tse:RecordingTokens>" in sent[0]
    assert attributes[0]["recording_token"] == "R0"
    assert attributes[0]["from"] == "2026-08-01T00:00:00Z"
    assert attributes[0]["tracks"][0]["type"] == "Video"
    assert attributes[0]["tracks"][0]["video"]["width"] == 1920
    assert attributes[0]["tracks"][0]["video"]["framerate"] == 25.0


def test_search_state() -> None:
    client = make_client()
    sent = stub(client, "<GetSearchStateResponse><State>Completed</State></GetSearchStateResponse>")
    assert client.get_search_state(search_token="S0") == "Completed"
    assert "<tse:SearchToken>S0</tse:SearchToken>" in sent[0]


def test_preset_tours_can_be_created_and_defined() -> None:
    client = make_client()
    sent = stub(
        client,
        "<CreatePresetTourResponse><PresetTourToken>PT0</PresetTourToken>"
        "</CreatePresetTourResponse>",
    )
    assert client.ptz_create_preset_tour(profile_token="P0") == "PT0"
    assert "<tptz:CreatePresetTour>" in sent[0]

    sent = stub(client, "<ModifyPresetTourResponse/>")
    client.ptz_modify_preset_tour(
        profile_token="P0",
        preset_tour_token="PT0",
        name="Perimeter",
        auto_start=True,
        recurring_time=2,
        direction="Forward",
        tour_spots=[
            {"preset_token": "1", "stay_time": "PT10S", "pan": 0.5, "tilt": 0.5},
            {"home": True, "stay_time": "PT5S"},
        ],
    )
    assert '<tptz:PresetTour token="PT0">' in sent[0]
    assert "<tt:Name>Perimeter</tt:Name>" in sent[0]
    assert "<tt:AutoStart>true</tt:AutoStart>" in sent[0]
    assert "<tt:RecurringTime>2</tt:RecurringTime>" in sent[0]
    assert "<tt:PresetToken>1</tt:PresetToken>" in sent[0]
    assert '<tt:PanTilt x="0.5" y="0.5"/>' in sent[0]
    assert "<tt:Home/>" in sent[0]

    sent = stub(client, "<RemovePresetTourResponse/>")
    client.ptz_remove_preset_tour(profile_token="P0", preset_tour_token="PT0")
    assert "<tptz:PresetTourToken>PT0</tptz:PresetTourToken>" in sent[0]


def test_preset_tour_read_back_includes_its_spots() -> None:
    client = make_client()
    stub(
        client,
        "<GetPresetTourResponse>"
        '<PresetTour token="PT0"><Name>Perimeter</Name>'
        "<Status><State>Touring</State></Status><AutoStart>true</AutoStart>"
        '<StartingCondition RandomPresetOrder="false"><RecurringTime>2</RecurringTime>'
        "<Direction>Forward</Direction></StartingCondition>"
        "<TourSpot><PresetDetail><PresetToken>1</PresetToken></PresetDetail>"
        "<StayTime>PT10S</StayTime></TourSpot>"
        "</PresetTour></GetPresetTourResponse>",
    )
    tour = client.ptz_get_preset_tour(profile_token="P0", preset_tour_token="PT0")
    assert tour["state"] == "Touring"
    assert tour["starting_condition"]["direction"] == "Forward"
    assert tour["tour_spots"][0] == {"stay_time": "PT10S", "preset_token": "1", "home": False}


def test_preset_tour_options() -> None:
    client = make_client()
    stub(
        client,
        "<GetPresetTourOptionsResponse><Options>"
        "<AutoStart>true</AutoStart><AutoStart>false</AutoStart>"
        "<TourSpot><PresetDetail><PresetToken>1</PresetToken><PresetToken>2</PresetToken>"
        "</PresetDetail></TourSpot>"
        "</Options></GetPresetTourOptionsResponse>",
    )
    options = client.ptz_get_preset_tour_options(profile_token="P0")
    assert options["auto_start"] == ["true", "false"]
    assert options["preset_tokens"] == ["1", "2"]


def test_geo_move_targets_a_coordinate() -> None:
    client = make_client()
    sent = stub(client, "<GeoMoveResponse/>")
    client.ptz_geo_move(
        profile_token="P0", lat=52.5, lon=13.4, elevation=34.0, pan_speed=0.5, area_width=20.0
    )
    assert '<tptz:Target lon="13.4" lat="52.5" elevation="34.0"/>' in sent[0]
    assert '<tt:PanTilt x="0.5" y="0.0"/>' in sent[0]
    assert "<tptz:AreaWidth>20.0</tptz:AreaWidth>" in sent[0]


def test_credentials_can_be_issued_and_amended() -> None:
    client = make_client()
    sent = stub(client, "<CreateCredentialResponse><Token>C1</Token></CreateCredentialResponse>")
    token = client.create_credential(
        description="Night shift",
        holder_reference="staff/42",
        identifiers=[{"type": "Card", "format_type": "Wiegand26", "value": "1234"}],
        access_profiles=[{"token": "AP0"}],
    )
    assert token == "C1"
    assert "<pt:Name>Card</pt:Name>" in sent[0]
    assert "<pt:FormatType>Wiegand26</pt:FormatType>" in sent[0]
    assert "<pt:AccessProfileToken>AP0</pt:AccessProfileToken>" in sent[0]
    assert "<pt:Enabled>true</pt:Enabled>" in sent[0]

    sent = stub(client, "<ModifyCredentialResponse/>")
    client.modify_credential(token="C1", description="Day shift")
    assert '<tcr:Credential token="C1">' in sent[0]

    stub(
        client,
        "<GetCredentialsResponse>"
        '<Credential token="C1"><Description>Night shift</Description>'
        "<CredentialHolderReference>staff/42</CredentialHolderReference>"
        "<CredentialIdentifier><Type><Name>Card</Name><FormatType>Wiegand26</FormatType></Type>"
        "<Value>1234</Value></CredentialIdentifier>"
        "<CredentialAccessProfile><AccessProfileToken>AP0</AccessProfileToken>"
        "</CredentialAccessProfile>"
        "</Credential></GetCredentialsResponse>",
    )
    credentials = client.get_credentials(tokens=["C1"])
    assert credentials[0]["identifiers"][0] == {
        "type": "Card",
        "format_type": "Wiegand26",
        "value": "1234",
    }
    assert credentials[0]["access_profiles"][0]["token"] == "AP0"


def test_schedules_round_trip() -> None:
    client = make_client()
    sent = stub(client, "<CreateScheduleResponse><Token>S1</Token></CreateScheduleResponse>")
    token = client.create_schedule(
        name="Office hours",
        standard={"Monday": [{"from": "08:00:00", "until": "17:00:00"}]},
        special_days=[{"group_token": "SD0", "time_ranges": [{"from": "10:00:00"}]}],
    )
    assert token == "S1"
    assert "<tsc:Monday><tsc:TimePeriod><tsc:From>08:00:00</tsc:From>" in sent[0]
    assert "<tsc:GroupToken>SD0</tsc:GroupToken>" in sent[0]

    stub(
        client,
        "<GetSchedulesResponse>"
        '<Schedule token="S1"><Name>Office hours</Name><Description/>'
        "<Standard><Monday><TimePeriod><From>08:00:00</From><Until>17:00:00</Until>"
        "</TimePeriod></Monday></Standard>"
        "</Schedule></GetSchedulesResponse>",
    )
    schedules = client.get_schedules(tokens=["S1"])
    assert schedules[0]["standard"]["Monday"] == [{"from": "08:00:00", "until": "17:00:00"}]

    stub(
        client,
        "<GetScheduleStateResponse><ScheduleState><Active>true</Active>"
        "<SpecialDay>false</SpecialDay></ScheduleState></GetScheduleStateResponse>",
    )
    assert client.get_schedule_state(token="S1") == {"active": True, "special_day": False}

    sent = stub(client, "<DeleteScheduleResponse/>")
    client.delete_schedule(token="S1")
    assert "<tsc:DeleteSchedule>" in sent[0]


def test_special_day_groups_round_trip() -> None:
    client = make_client()
    sent = stub(
        client, "<CreateSpecialDayGroupResponse><Token>SD0</Token></CreateSpecialDayGroupResponse>"
    )
    assert client.create_special_day_group(name="Holidays", days=["20261225"]) == "SD0"
    assert "<tsc:Days>20261225</tsc:Days>" in sent[0]

    stub(
        client,
        "<GetSpecialDayGroupsResponse>"
        '<SpecialDayGroup token="SD0"><Name>Holidays</Name><Description/>'
        "<Days>20261225</Days><Days>20270101</Days></SpecialDayGroup>"
        "</GetSpecialDayGroupsResponse>",
    )
    groups = client.get_special_day_groups(tokens=["SD0"])
    assert groups[0]["days"] == ["20261225", "20270101"]


def test_access_profiles_round_trip() -> None:
    client = make_client()
    sent = stub(
        client, "<CreateAccessProfileResponse><Token>AP0</Token></CreateAccessProfileResponse>"
    )
    token = client.create_access_profile(
        name="Night staff",
        policies=[{"schedule_token": "S1", "entity": "AP_1", "entity_type": "tdc:Door"}],
    )
    assert token == "AP0"
    assert "<tar:ScheduleToken>S1</tar:ScheduleToken>" in sent[0]
    assert '<tar:Entity EntityType="tdc:Door">AP_1</tar:Entity>' in sent[0]

    stub(
        client,
        "<GetAccessProfilesResponse>"
        '<AccessProfile token="AP0"><Name>Night staff</Name><Description/>'
        "<AccessPolicy><ScheduleToken>S1</ScheduleToken>"
        '<Entity EntityType="tdc:Door">AP_1</Entity></AccessPolicy>'
        "</AccessProfile></GetAccessProfilesResponse>",
    )
    profiles = client.get_access_profiles(tokens=["AP0"])
    assert profiles[0]["policies"][0] == {
        "schedule_token": "S1",
        "entity": "AP_1",
        "entity_type": "tdc:Door",
    }

    sent = stub(client, "<DeleteAccessProfileResponse/>")
    client.delete_access_profile(token="AP0")
    assert "<tar:DeleteAccessProfile>" in sent[0]


def test_media2_variants_use_the_media2_namespace() -> None:
    """Every new media builder must honour the Media2 prefix, not silently emit Media1."""
    assert "trt2:" in envelopes.media_get_audio_source_configurations(use_media2=True)
    assert "trt2:" in envelopes.media_get_audio_decoder_configurations(use_media2=True)
    assert "trt2:" in envelopes.media_get_video_source_modes(
        video_source_token="VS0", use_media2=True
    )
    body = envelopes.media_set_audio_source_configuration(
        token="T", name="n", source_token="S", use_media2=True
    )
    assert "ForcePersistence" not in body


def test_new_pacs_builders_escape_their_values() -> None:
    body = pacs.credential_create(description="a&b", holder_reference="<x>")
    assert "a&amp;b" in body
    assert "&lt;x&gt;" in body
    assert "<x>" not in body


def test_new_parsers_tolerate_missing_elements() -> None:
    assert parsers.parse_audio_source_configurations("<nope/>") == []
    assert parsers.parse_audio_source_configuration_options("<nope/>") == {}
    assert parsers.parse_audio_output_configuration_options("<nope/>") == {}
    assert parsers.parse_video_source_modes("<nope/>") == []
    assert parsers.parse_audio_decoder_configurations("<nope/>") == []
    assert parsers.parse_audio_decoder_configuration_options("<nope/>") == {}
    assert parsers.parse_track_configuration("<nope/>") == {}
    assert parsers.parse_recording_job_state("<nope/>") == {}
    assert parsers.parse_media_attributes("<nope/>") == []
    assert parsers.parse_preset_tour("<nope/>") == {}
    assert parsers.parse_preset_tour_options("<nope/>") == {}
    assert parsers.parse_subscribe("<nope/>") == {}
    assert pacs.parse_schedules("<nope/>") == []
    assert pacs.parse_schedule_state("<nope/>") == {}
    assert pacs.parse_special_day_groups("<nope/>") == []
    assert pacs.parse_access_profiles("<nope/>") == []
    assert pacs.parse_credentials("<nope/>") == []


async def test_async_parity_for_the_new_operations() -> None:
    client = make_async_client()

    sent = stub_async(client, _SUBSCRIBE)
    result = await client.events_subscribe(consumer_address="http://consumer:9000/events")
    assert result["subscription_url"] == "http://cam/onvif/sub?id=7"

    stub_async(
        client,
        "<GetAudioDecoderConfigurationsResponse>"
        '<Configurations token="ADC0"><Name>talkback</Name></Configurations>'
        "</GetAudioDecoderConfigurationsResponse>",
    )
    assert (await client.get_audio_decoder_configurations())[0]["token"] == "ADC0"

    sent = stub_async(client, "<GeoMoveResponse/>")
    await client.ptz_geo_move(profile_token="P0", lat=1.0, lon=2.0)
    assert "<tptz:GeoMove>" in sent[0]

    stub_async(
        client, "<CreateAccessProfileResponse><Token>AP0</Token></CreateAccessProfileResponse>"
    )
    assert await client.create_access_profile(name="n") == "AP0"
