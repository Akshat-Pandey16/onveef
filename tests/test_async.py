from __future__ import annotations

import asyncio
import inspect

from onveef import wsdiscovery
from onveef.aclient import AsyncOnvifClient
from onveef.client import OnvifCredentials, OnvifEndpoint

_SERVICES = {
    "device": "http://cam/onvif/device_service",
    "media": "http://cam/onvif/media",
    "ptz": "http://cam/onvif/ptz",
    "doorcontrol": "http://cam/onvif/doorcontrol",
}


def _async_client() -> AsyncOnvifClient:
    return AsyncOnvifClient(
        endpoint=OnvifEndpoint(device_xaddr="http://cam/onvif/device_service", services=_SERVICES),
        credentials=OnvifCredentials(),
    )


def _astub(client: AsyncOnvifClient, xml: str) -> list[str]:
    captured: list[str] = []

    async def fake_post_soap(*, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        captured.append(envelope)
        return 200, xml

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def test_async_get_device_information() -> None:
    client = _async_client()
    _astub(
        client,
        "<GetDeviceInformationResponse><Manufacturer>ACME</Manufacturer>"
        "<Model>X1</Model></GetDeviceInformationResponse>",
    )

    async def run() -> dict[str, str]:
        async with client:
            return await client.get_device_information()

    info = asyncio.run(run())
    assert info["Manufacturer"] == "ACME"
    assert info["Model"] == "X1"


def test_async_generic_call_and_ptz() -> None:
    client = _async_client()
    sent = _astub(client, "<ContinuousMoveResponse/>")

    async def run() -> None:
        async with client:
            await client.ptz_continuous_move(profile_token="P0", pan=0.5, tilt=0.0, zoom=0.0)

    asyncio.run(run())
    assert "<tptz:ContinuousMove>" in sent[0]


def test_async_door_control() -> None:
    client = _async_client()
    sent = _astub(client, "<UnlockDoorResponse/>")

    async def run() -> None:
        async with client:
            await client.unlock_door(token="D0")

    asyncio.run(run())
    assert "<tdc:UnlockDoor>" in sent[0]


def test_discover_async_is_coroutine() -> None:
    assert inspect.iscoroutinefunction(wsdiscovery.discover_async)
