from __future__ import annotations

import pytest

from onveef import envelopes, pacs
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint

_PACS_SERVICES = {
    "device": "http://cam/onvif/device_service",
    "accesscontrol": "http://cam/onvif/accesscontrol",
    "doorcontrol": "http://cam/onvif/doorcontrol",
    "credential": "http://cam/onvif/credential",
}


def _client() -> OnvifClient:
    return OnvifClient(
        endpoint=OnvifEndpoint(
            device_xaddr="http://cam/onvif/device_service", services=_PACS_SERVICES
        ),
        credentials=OnvifCredentials(),
    )


def _stub(client: OnvifClient, xml: str) -> list[str]:
    captured: list[str] = []

    def fake_post_soap(*, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        captured.append(envelope)
        return 200, xml

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def test_pacs_namespaces_declared() -> None:
    assert "ver10/accesscontrol/wsdl" in envelopes.NS_DECL
    assert "ver10/doorcontrol/wsdl" in envelopes.NS_DECL
    assert "ver10/credential/wsdl" in envelopes.NS_DECL
    assert "ver10/pacs" in envelopes.NS_DECL


def test_paged_list_omits_params_on_first_page() -> None:
    assert pacs.access_point_info_list() == "<tac:GetAccessPointInfoList/>"
    body = pacs.access_point_info_list(limit=50, start_reference="cursor-9")
    assert "<tac:Limit>50</tac:Limit>" in body
    assert "<tac:StartReference>cursor-9</tac:StartReference>" in body


def test_door_action_builders_and_guard() -> None:
    assert pacs.door_action("UnlockDoor", token="D0") == (
        "<tdc:UnlockDoor><tdc:Token>D0</tdc:Token></tdc:UnlockDoor>"
    )
    with pytest.raises(ValueError):
        pacs.door_action("MeltDoor", token="D0")


def test_credential_enable_with_reason() -> None:
    body = pacs.enable_credential(token="C1", reason="lost card recovered")
    assert "<tcr:Token>C1</tcr:Token>" in body
    assert "<tcr:Reason>lost card recovered</tcr:Reason>" in body
    assert "<tcr:Reason>" not in pacs.enable_credential(token="C1")


def test_parse_access_point_info_list_paging() -> None:
    xml = """
    <tac:GetAccessPointInfoListResponse xmlns:tac="http://www.onvif.org/ver10/accesscontrol/wsdl">
      <tac:AccessPointInfo token="AP0">
        <Name>Front</Name><Entity>D0</Entity><EntityType>tdc:Door</EntityType>
        <Capabilities DisableAccessPoint="true"/>
      </tac:AccessPointInfo>
      <tac:NextStartReference>next-cursor</tac:NextStartReference>
    </tac:GetAccessPointInfoListResponse>
    """
    out = pacs.parse_access_point_info_list(xml)
    assert out["items"][0]["token"] == "AP0"
    assert out["items"][0]["name"] == "Front"
    assert out["items"][0]["capabilities"]["DisableAccessPoint"] == "true"
    assert out["next_start_reference"] == "next-cursor"


def test_parse_door_state() -> None:
    xml = (
        "<GetDoorStateResponse><DoorState>"
        "<DoorPhysicalState>Closed</DoorPhysicalState>"
        "<LockPhysicalState>Locked</LockPhysicalState>"
        "<DoorMode>Locked</DoorMode>"
        "</DoorState></GetDoorStateResponse>"
    )
    state = pacs.parse_door_state(xml)
    assert state == {
        "door_physical_state": "Closed",
        "lock_physical_state": "Locked",
        "door_mode": "Locked",
    }


def test_client_routes_access_control_and_door() -> None:
    client = _client()
    sent = _stub(
        client,
        "<GetAccessPointStateResponse><AccessPointState><Enabled>true</Enabled></AccessPointState></GetAccessPointStateResponse>",
    )
    state = client.get_access_point_state(token="AP0")
    assert state == {"enabled": True}
    assert "<tac:GetAccessPointState>" in sent[0]

    sent = _stub(client, "<UnlockDoorResponse/>")
    client.unlock_door(token="D0")
    assert "<tdc:UnlockDoor>" in sent[0]

    sent = _stub(client, "<EnableCredentialResponse/>")
    client.enable_credential(token="C1")
    assert "<tcr:EnableCredential>" in sent[0]


def test_client_access_control_requires_service() -> None:
    client = OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr="http://cam/onvif/device_service"),
        credentials=OnvifCredentials(),
    )
    from onveef.exceptions import OnvifCapabilityMissingError

    with pytest.raises(OnvifCapabilityMissingError):
        client.get_door_state(token="D0")
