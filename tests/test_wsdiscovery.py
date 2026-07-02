from __future__ import annotations

from onveef import wsdiscovery


def test_build_probe_is_well_formed() -> None:
    probe = wsdiscovery.build_probe(message_id="urn:uuid:abc")
    assert "<d:Probe" in probe
    assert "urn:uuid:abc" in probe
    assert "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe" in probe
    assert "dn:NetworkVideoTransmitter" in probe
    assert "http://schemas.xmlsoap.org/ws/2004/08/addressing" in probe


def test_parse_probe_matches_extracts_xaddrs_and_scopes() -> None:
    xml = """
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
                xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
      <s:Body>
        <d:ProbeMatches>
          <d:ProbeMatch>
            <a:EndpointReference><a:Address>urn:uuid:dev-1</a:Address></a:EndpointReference>
            <d:Types>dn:NetworkVideoTransmitter</d:Types>
            <d:Scopes>onvif://www.onvif.org/name/Lobby%20Cam onvif://www.onvif.org/hardware/DS-2CD onvif://www.onvif.org/location/floor1 onvif://www.onvif.org/type/video_encoder</d:Scopes>
            <d:XAddrs>http://192.168.1.64/onvif/device_service http://[fe80::1]/onvif/device_service</d:XAddrs>
            <d:MetadataVersion>1</d:MetadataVersion>
          </d:ProbeMatch>
        </d:ProbeMatches>
      </s:Body>
    </s:Envelope>
    """
    devices = wsdiscovery.parse_probe_matches(xml)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.endpoint_reference == "urn:uuid:dev-1"
    assert dev.device_service == "http://192.168.1.64/onvif/device_service"
    assert len(dev.xaddrs) == 2
    assert dev.name == "Lobby%20Cam"
    assert dev.hardware == "DS-2CD"
    assert dev.location == "floor1"
    assert dev.metadata_version == "1"


def test_parse_probe_matches_tolerates_garbage() -> None:
    assert wsdiscovery.parse_probe_matches("not xml") == []
    assert wsdiscovery.parse_probe_matches("<empty/>") == []
