"""Builders and parsers for ONVIF Physical Access Control (Profile A/C) messages."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from onveef.parsers import (
    _local,
    _to_bool,
    child_local,
    child_text,
    find_all_local,
    find_local,
    parse_xml,
)

DOOR_ACTIONS = (
    "AccessDoor",
    "LockDoor",
    "UnlockDoor",
    "DoubleLockDoor",
    "BlockDoor",
    "LockDownDoor",
    "LockDownReleaseDoor",
    "LockOpenDoor",
    "LockOpenReleaseDoor",
)


def _paged_body(prefix: str, op: str, *, limit: int | None, start_reference: str) -> str:
    inner = ""
    if limit is not None:
        inner += f"<{prefix}:Limit>{int(limit)}</{prefix}:Limit>"
    if start_reference:
        inner += f"<{prefix}:StartReference>{escape(start_reference)}</{prefix}:StartReference>"
    if not inner:
        return f"<{prefix}:{op}/>"
    return f"<{prefix}:{op}>{inner}</{prefix}:{op}>"


def _token_body(prefix: str, op: str, token: str, *, tag: str = "Token") -> str:
    return f"<{prefix}:{op}><{prefix}:{tag}>{escape(token)}</{prefix}:{tag}></{prefix}:{op}>"


def _tokens_body(prefix: str, op: str, tokens: list[str], *, tag: str = "Token") -> str:
    inner = "".join(f"<{prefix}:{tag}>{escape(t)}</{prefix}:{tag}>" for t in tokens)
    return f"<{prefix}:{op}>{inner}</{prefix}:{op}>"


def access_point_info_list(*, limit: int | None = None, start_reference: str = "") -> str:
    """Build a ``tac:GetAccessPointInfoList`` body, optionally paged by limit and start reference."""
    return _paged_body(
        "tac", "GetAccessPointInfoList", limit=limit, start_reference=start_reference
    )


def access_points(*, tokens: list[str]) -> str:
    """Build a ``tac:GetAccessPoints`` body requesting the given access point tokens."""
    return _tokens_body("tac", "GetAccessPoints", tokens)


def access_point_state(*, token: str) -> str:
    """Build a ``tac:GetAccessPointState`` body for a single access point token."""
    return _token_body("tac", "GetAccessPointState", token)


def enable_access_point(*, token: str) -> str:
    """Build a ``tac:EnableAccessPoint`` body for a single access point token."""
    return _token_body("tac", "EnableAccessPoint", token)


def disable_access_point(*, token: str) -> str:
    """Build a ``tac:DisableAccessPoint`` body for a single access point token."""
    return _token_body("tac", "DisableAccessPoint", token)


def area_info_list(*, limit: int | None = None, start_reference: str = "") -> str:
    """Build a ``tac:GetAreaInfoList`` body, optionally paged by limit and start reference."""
    return _paged_body("tac", "GetAreaInfoList", limit=limit, start_reference=start_reference)


def door_info_list(*, limit: int | None = None, start_reference: str = "") -> str:
    """Build a ``tdc:GetDoorInfoList`` body, optionally paged by limit and start reference."""
    return _paged_body("tdc", "GetDoorInfoList", limit=limit, start_reference=start_reference)


def doors(*, tokens: list[str]) -> str:
    """Build a ``tdc:GetDoors`` body requesting the given door tokens."""
    return _tokens_body("tdc", "GetDoors", tokens)


def door_state(*, token: str) -> str:
    """Build a ``tdc:GetDoorState`` body for a single door token."""
    return _token_body("tdc", "GetDoorState", token)


def door_action(op: str, *, token: str) -> str:
    """Build a ``tdc`` door-control body for the given door token.

    Args:
        op: One of ``DOOR_ACTIONS`` (e.g. ``AccessDoor``, ``LockDoor``); used as the operation name.
        token: The door token the action targets.

    Raises:
        ValueError: If ``op`` is not a recognized door action.
    """
    if op not in DOOR_ACTIONS:
        raise ValueError(f"Unknown door action: {op}")
    return _token_body("tdc", op, token)


def credential_info_list(*, limit: int | None = None, start_reference: str = "") -> str:
    """Build a ``tcr:GetCredentialInfoList`` body, optionally paged by limit and start reference."""
    return _paged_body("tcr", "GetCredentialInfoList", limit=limit, start_reference=start_reference)


def credentials(*, tokens: list[str]) -> str:
    """Build a ``tcr:GetCredentials`` body requesting the given credential tokens."""
    return _tokens_body("tcr", "GetCredentials", tokens)


def credential_state(*, token: str) -> str:
    """Build a ``tcr:GetCredentialState`` body for a single credential token."""
    return _token_body("tcr", "GetCredentialState", token)


def enable_credential(*, token: str, reason: str = "") -> str:
    """Build a ``tcr:EnableCredential`` body, including a ``Reason`` element when provided."""
    reason_xml = f"<tcr:Reason>{escape(reason)}</tcr:Reason>" if reason else ""
    return f"<tcr:EnableCredential><tcr:Token>{escape(token)}</tcr:Token>{reason_xml}</tcr:EnableCredential>"


def disable_credential(*, token: str, reason: str = "") -> str:
    """Build a ``tcr:DisableCredential`` body, including a ``Reason`` element when provided."""
    reason_xml = f"<tcr:Reason>{escape(reason)}</tcr:Reason>" if reason else ""
    return f"<tcr:DisableCredential><tcr:Token>{escape(token)}</tcr:Token>{reason_xml}</tcr:DisableCredential>"


def delete_credential(*, token: str) -> str:
    """Build a ``tcr:DeleteCredential`` body for a single credential token."""
    return _token_body("tcr", "DeleteCredential", token)


def _parse_list(xml: str, item_element: str, fields: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    root = parse_xml(xml)
    if root is None:
        return {"items": [], "next_start_reference": ""}
    items: list[dict[str, Any]] = []
    for el in find_all_local(root, item_element):
        item: dict[str, Any] = {"token": el.attrib.get("token", "")}
        for element_name, out_key in fields:
            item[out_key] = child_text(el, element_name)
        caps = child_local(el, "Capabilities")
        if caps is not None:
            item["capabilities"] = {_local(k): v for k, v in caps.attrib.items()}
        items.append(item)
    nsr = find_local(root, "NextStartReference")
    return {
        "items": items,
        "next_start_reference": nsr.text.strip() if nsr is not None and nsr.text else "",
    }


def parse_access_point_info_list(xml: str) -> dict[str, Any]:
    """Parse a GetAccessPointInfoList response.

    Returns:
        A dict with ``items`` (each carrying ``token``, ``name``, ``description``, ``area_from``,
        ``area_to``, ``entity_type``, ``entity`` and optional ``capabilities``) and
        ``next_start_reference``.
    """
    return _parse_list(
        xml,
        "AccessPointInfo",
        (
            ("Name", "name"),
            ("Description", "description"),
            ("AreaFrom", "area_from"),
            ("AreaTo", "area_to"),
            ("EntityType", "entity_type"),
            ("Entity", "entity"),
        ),
    )


def parse_area_info_list(xml: str) -> dict[str, Any]:
    """Parse a GetAreaInfoList response.

    Returns:
        A dict with ``items`` (each carrying ``token``, ``name``, ``description`` and optional
        ``capabilities``) and ``next_start_reference``.
    """
    return _parse_list(xml, "AreaInfo", (("Name", "name"), ("Description", "description")))


def parse_access_point_state(xml: str) -> dict[str, Any]:
    """Parse a GetAccessPointState response into ``{"enabled": bool}`` (empty dict if absent)."""
    root = parse_xml(xml)
    if root is None:
        return {}
    state = find_local(root, "AccessPointState")
    if state is None:
        return {}
    return {"enabled": _to_bool(child_text(state, "Enabled"))}


def parse_door_info_list(xml: str) -> dict[str, Any]:
    """Parse a GetDoorInfoList response.

    Returns:
        A dict with ``items`` (each carrying ``token``, ``name``, ``description``, ``door_type`` and
        optional ``capabilities``) and ``next_start_reference``.
    """
    return _parse_list(
        xml,
        "DoorInfo",
        (("Name", "name"), ("Description", "description"), ("DoorType", "door_type")),
    )


def parse_door_state(xml: str) -> dict[str, Any]:
    """Parse a GetDoorState response.

    Returns:
        A dict with ``door_physical_state``, ``lock_physical_state`` and ``door_mode``, plus an
        ``alarm`` key when present; empty dict if no state element is found.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    state = find_local(root, "DoorState")
    if state is None:
        return {}
    out: dict[str, Any] = {
        "door_physical_state": child_text(state, "DoorPhysicalState"),
        "lock_physical_state": child_text(state, "LockPhysicalState"),
        "door_mode": child_text(state, "DoorMode"),
    }
    alarm = child_text(state, "Alarm")
    if alarm:
        out["alarm"] = alarm
    return out


def parse_credential_info_list(xml: str) -> dict[str, Any]:
    """Parse a GetCredentialInfoList response.

    Returns:
        A dict with ``items`` (each carrying ``token``, ``description``,
        ``credential_holder_reference``, ``valid_from``, ``valid_to`` and optional ``capabilities``)
        and ``next_start_reference``.
    """
    return _parse_list(
        xml,
        "CredentialInfo",
        (
            ("Description", "description"),
            ("CredentialHolderReference", "credential_holder_reference"),
            ("ValidFrom", "valid_from"),
            ("ValidTo", "valid_to"),
        ),
    )


def parse_credential_state(xml: str) -> dict[str, Any]:
    """Parse a GetCredentialState response.

    Returns:
        A dict with ``enabled`` (bool), plus a ``reason`` key when present; empty dict if no state
        element is found.
    """
    root = parse_xml(xml)
    if root is None:
        return {}
    state = find_local(root, "State") or find_local(root, "CredentialState")
    if state is None:
        return {}
    out: dict[str, Any] = {"enabled": _to_bool(child_text(state, "Enabled"))}
    reason = child_text(state, "Reason")
    if reason:
        out["reason"] = reason
    return out
