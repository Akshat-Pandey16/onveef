"""Exercise every public client method once, in both the sync and async clients.

These are thin dispatch wrappers — build a body, send it, parse the reply — and the way
they break is a typo in a service key or operation name, which no other test would catch.
This introspects the signatures, synthesises plausible arguments, and asserts each method
actually puts a request on the wire and survives parsing a minimal response.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from conftest import make_async_client, make_client, stub, stub_async
from onveef.aclient import AsyncOnvifClient
from onveef.client import OnvifClient

_SKIP = {
    "call",
    "close",
    "aclose",
    "connect",
    "credentials",
    "endpoint",
    "get_snapshot",
    "local_address",
    "pull_point",
    "require",
    "set_endpoint",
}

_BY_NAME: dict[str, Any] = {
    "command": "LockDoor",
    "encoding": "H264",
    "log_type": "System",
    "logical_state": "active",
    "mode": "Idle",
    "operation": "Start",
    "rotate": "OFF",
    "service": "device",
    "user_level": "User",
    "usernames": ["admin"],
    "protocols": [{"name": "HTTP", "enabled": True, "port": 80}],
    "rules": [{"name": "R1", "type": "tt:Motion", "parameters": {"Sensitivity": "50"}}],
    "modules": [{"name": "M1", "type": "tt:Module", "parameters": {}}],
    "names": ["R1"],
    "scopes": ["onvif://www.onvif.org/name/Cam"],
    "ipv4_addresses": ["10.0.0.1"],
    "ipv4_servers": ["10.0.0.1"],
    "search_domains": ["lan"],
    "configurations": [{"type": "VideoSource", "token": "VS0"}],
    "types": ["All"],
    "sources": [{"token": "VS0"}],
    "tracks": [{"token": "T0"}],
}

_BY_TYPE: dict[Any, Any] = {
    str: "X",
    int: 1,
    float: 0.5,
    bool: True,
}

_RESPONSE = (
    "<Response>"
    '<Profiles token="P0"><Name>main</Name></Profiles>'
    "<MediaUri><Uri>rtsp://192.168.1.5:554/live</Uri></MediaUri>"
    "<Token>T0</Token><Name>n</Name><GUID>g</GUID>"
    "<UTCDateTime><Date><Year>2026</Year><Month>1</Month><Day>1</Day></Date>"
    "<Time><Hour>0</Hour><Minute>0</Minute><Second>0</Second></Time></UTCDateTime>"
    "</Response>"
)


def _argument_for(name: str, annotation: Any) -> Any:
    if name in _BY_NAME:
        return _BY_NAME[name]
    text = str(annotation)
    if "list[dict" in text:
        return [{"name": "n", "token": "T0"}]
    if "list[str]" in text:
        return ["X"]
    if "dict[" in text:
        return {"name": "n"}
    for kind, value in _BY_TYPE.items():
        if text == kind.__name__ or text.startswith(f"{kind.__name__} |"):
            return value
    return "X"


def _kwargs_for(method: Any) -> dict[str, Any]:
    """Synthesise a plausible argument for every required parameter of ``method``."""
    signature = inspect.signature(method)
    kwargs: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == "self" or parameter.default is not inspect.Parameter.empty:
            continue
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        kwargs[name] = _argument_for(name, parameter.annotation)
    return kwargs


def _public_methods(cls: type) -> list[str]:
    return sorted(
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_") and name not in _SKIP and not isinstance(member, property)
    )


SYNC_METHODS = _public_methods(OnvifClient)
ASYNC_METHODS = _public_methods(AsyncOnvifClient)


def test_the_two_clients_expose_the_same_operations() -> None:
    assert SYNC_METHODS == ASYNC_METHODS


def test_a_meaningful_number_of_methods_is_covered() -> None:
    """Guard against the introspection silently matching nothing."""
    assert len(SYNC_METHODS) > 150


@pytest.mark.parametrize("name", SYNC_METHODS)
def test_sync_method_dispatches(name: str) -> None:
    client = make_client()
    sent = stub(client, _RESPONSE)
    method = getattr(client, name)
    method(**_kwargs_for(method))
    assert sent, f"{name} sent no request"
    assert "<s:Envelope" in sent[0]
    assert "<s:Body>" in sent[0]


@pytest.mark.parametrize("name", ASYNC_METHODS)
async def test_async_method_dispatches(name: str) -> None:
    client = make_async_client()
    sent = stub_async(client, _RESPONSE)
    method = getattr(client, name)
    await method(**_kwargs_for(method))
    assert sent, f"{name} sent no request"
    assert "<s:Envelope" in sent[0]
