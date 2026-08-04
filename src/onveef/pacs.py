"""Builders and parsers for ONVIF Physical Access Control (Profile A/C) messages."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape, quoteattr

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


def _optional(prefix: str, tag: str, value: str) -> str:
    return f"<{prefix}:{tag}>{escape(value)}</{prefix}:{tag}>" if value else ""


def _credential_xml(
    *,
    token: str,
    description: str,
    holder_reference: str,
    valid_from: str,
    valid_to: str,
    identifiers: list[dict[str, str]] | None,
    access_profiles: list[dict[str, str]] | None,
) -> str:
    identifier_xml = ""
    for identifier in identifiers or []:
        format_type = identifier.get("format_type", "")
        format_xml = f"<pt:FormatType>{escape(format_type)}</pt:FormatType>" if format_type else ""
        identifier_xml += (
            "<pt:CredentialIdentifier>"
            "<pt:Type>"
            f"<pt:Name>{escape(identifier.get('type', ''))}</pt:Name>"
            f"{format_xml}"
            "</pt:Type>"
            f"<pt:Value>{escape(identifier.get('value', ''))}</pt:Value>"
            "</pt:CredentialIdentifier>"
        )
    profile_xml = ""
    for profile in access_profiles or []:
        profile_xml += (
            "<pt:CredentialAccessProfile>"
            f"<pt:AccessProfileToken>{escape(profile.get('token', ''))}</pt:AccessProfileToken>"
            f"{_optional('pt', 'ValidFrom', profile.get('valid_from', ''))}"
            f"{_optional('pt', 'ValidTo', profile.get('valid_to', ''))}"
            "</pt:CredentialAccessProfile>"
        )
    token_attr = f" token={quoteattr(token)}" if token else ""
    return (
        f"<tcr:Credential{token_attr}>"
        f"<pt:Description>{escape(description)}</pt:Description>"
        f"<pt:CredentialHolderReference>{escape(holder_reference)}</pt:CredentialHolderReference>"
        f"{_optional('pt', 'ValidFrom', valid_from)}"
        f"{_optional('pt', 'ValidTo', valid_to)}"
        f"{identifier_xml}{profile_xml}"
        "</tcr:Credential>"
    )


def credential_create(
    *,
    description: str = "",
    holder_reference: str = "",
    valid_from: str = "",
    valid_to: str = "",
    identifiers: list[dict[str, str]] | None = None,
    access_profiles: list[dict[str, str]] | None = None,
    enabled: bool = True,
    reason: str = "",
) -> str:
    """Build a ``tcr:CreateCredential`` body; the device replies with the new token.

    Args:
        description: Free-text label for the credential.
        holder_reference: Identifier of the person the credential belongs to.
        valid_from: ISO-8601 timestamp the credential becomes usable (optional).
        valid_to: ISO-8601 timestamp it expires (optional).
        identifiers: The physical credentials themselves — each a dict of ``type``
            (e.g. ``Card``, ``PIN``), optional ``format_type`` (e.g. ``Wiegand26``) and
            ``value``.
        access_profiles: Access profiles to grant, each a dict of ``token`` plus optional
            ``valid_from``/``valid_to``.
        enabled: Initial state of the credential.
        reason: Why it starts in that state (recorded by the device).
    """
    credential = _credential_xml(
        token="",
        description=description,
        holder_reference=holder_reference,
        valid_from=valid_from,
        valid_to=valid_to,
        identifiers=identifiers,
        access_profiles=access_profiles,
    )
    return (
        "<tcr:CreateCredential>"
        f"{credential}"
        "<tcr:State>"
        f"<pt:Enabled>{'true' if enabled else 'false'}</pt:Enabled>"
        f"{_optional('pt', 'Reason', reason)}"
        "</tcr:State>"
        "</tcr:CreateCredential>"
    )


def credential_modify(
    *,
    token: str,
    description: str = "",
    holder_reference: str = "",
    valid_from: str = "",
    valid_to: str = "",
    identifiers: list[dict[str, str]] | None = None,
    access_profiles: list[dict[str, str]] | None = None,
) -> str:
    """Build a ``tcr:ModifyCredential`` body replacing credential ``token``.

    ONVIF has no partial update here: the credential you send replaces the stored one, so
    pass every field you want kept. Same argument shapes as :func:`credential_create`.
    """
    credential = _credential_xml(
        token=token,
        description=description,
        holder_reference=holder_reference,
        valid_from=valid_from,
        valid_to=valid_to,
        identifiers=identifiers,
        access_profiles=access_profiles,
    )
    return f"<tcr:ModifyCredential>{credential}</tcr:ModifyCredential>"


def _time_periods_xml(periods: list[dict[str, str]] | None) -> str:
    out = ""
    for period in periods or []:
        out += (
            "<tsc:TimePeriod>"
            f"<tsc:From>{escape(period.get('from', ''))}</tsc:From>"
            f"{_optional('tsc', 'Until', period.get('until', ''))}"
            "</tsc:TimePeriod>"
        )
    return out


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _schedule_xml(
    *,
    token: str,
    name: str,
    description: str,
    standard: dict[str, list[dict[str, str]]] | None,
    special_days: list[dict[str, Any]] | None,
) -> str:
    week = ""
    for day in _WEEKDAYS:
        periods = (standard or {}).get(day)
        if periods:
            week += f"<tsc:{day}>{_time_periods_xml(periods)}</tsc:{day}>"
    standard_xml = f"<tsc:Standard>{week}</tsc:Standard>" if week else ""
    special_xml = ""
    for entry in special_days or []:
        ranges = entry.get("time_ranges")
        periods = ranges if isinstance(ranges, list) else []
        special_xml += (
            "<tsc:SpecialDays>"
            f"<tsc:GroupToken>{escape(str(entry.get('group_token', '')))}</tsc:GroupToken>"
            f"{_time_periods_xml(periods)}"
            "</tsc:SpecialDays>"
        )
    token_attr = f" token={quoteattr(token)}" if token else ""
    return (
        f"<tsc:Schedule{token_attr}>"
        f"<tsc:Name>{escape(name)}</tsc:Name>"
        f"<tsc:Description>{escape(description)}</tsc:Description>"
        f"{standard_xml}{special_xml}"
        f"</tsc:Schedule>"
    )


def schedule_info_list(*, limit: int | None = None, start_reference: str = "") -> str:
    """Build a ``tsc:GetScheduleInfoList`` body, optionally paged by limit and start reference."""
    return _paged_body("tsc", "GetScheduleInfoList", limit=limit, start_reference=start_reference)


def schedules(*, tokens: list[str]) -> str:
    """Build a ``tsc:GetSchedules`` body requesting the given schedule tokens."""
    return _tokens_body("tsc", "GetSchedules", tokens)


def schedule_state(*, token: str) -> str:
    """Build a ``tsc:GetScheduleState`` body asking whether a schedule is currently active."""
    return _token_body("tsc", "GetScheduleState", token)


def schedule_create(
    *,
    name: str,
    description: str = "",
    standard: dict[str, list[dict[str, str]]] | None = None,
    special_days: list[dict[str, Any]] | None = None,
) -> str:
    """Build a ``tsc:CreateSchedule`` body; the device replies with the new token.

    Args:
        name: Schedule name.
        description: Free-text description.
        standard: The recurring week, mapping weekday names (``"Monday"`` …) to a list of
            ``{"from": "08:00:00", "until": "17:00:00"}`` periods. Days you omit are closed.
        special_days: Overrides, each a dict of ``group_token`` (from
            :func:`special_day_group_info_list`) and its own ``time_ranges`` list.
    """
    return (
        "<tsc:CreateSchedule>"
        f"{_schedule_xml(token='', name=name, description=description, standard=standard, special_days=special_days)}"
        "</tsc:CreateSchedule>"
    )


def schedule_modify(
    *,
    token: str,
    name: str,
    description: str = "",
    standard: dict[str, list[dict[str, str]]] | None = None,
    special_days: list[dict[str, Any]] | None = None,
) -> str:
    """Build a ``tsc:ModifySchedule`` body replacing schedule ``token`` wholesale."""
    return (
        "<tsc:ModifySchedule>"
        f"{_schedule_xml(token=token, name=name, description=description, standard=standard, special_days=special_days)}"
        "</tsc:ModifySchedule>"
    )


def schedule_delete(*, token: str) -> str:
    """Build a ``tsc:DeleteSchedule`` body removing schedule ``token``."""
    return _token_body("tsc", "DeleteSchedule", token)


def special_day_group_info_list(*, limit: int | None = None, start_reference: str = "") -> str:
    """Build a ``tsc:GetSpecialDayGroupInfoList`` body, optionally paged.

    Special day groups are the holidays and exceptions a schedule refers to by token —
    this is how you discover those tokens.
    """
    return _paged_body(
        "tsc", "GetSpecialDayGroupInfoList", limit=limit, start_reference=start_reference
    )


def special_day_groups(*, tokens: list[str]) -> str:
    """Build a ``tsc:GetSpecialDayGroups`` body requesting the given group tokens."""
    return _tokens_body("tsc", "GetSpecialDayGroups", tokens)


def _special_day_group_xml(*, token: str, name: str, description: str, days: list[str]) -> str:
    days_xml = "".join(f"<tsc:Days>{escape(day)}</tsc:Days>" for day in days)
    token_attr = f" token={quoteattr(token)}" if token else ""
    return (
        f"<tsc:SpecialDayGroup{token_attr}>"
        f"<tsc:Name>{escape(name)}</tsc:Name>"
        f"<tsc:Description>{escape(description)}</tsc:Description>"
        f"{days_xml}"
        "</tsc:SpecialDayGroup>"
    )


def special_day_group_create(
    *, name: str, description: str = "", days: list[str] | None = None
) -> str:
    """Build a ``tsc:CreateSpecialDayGroup`` body from a list of iCalendar ``days`` strings."""
    return (
        "<tsc:CreateSpecialDayGroup>"
        f"{_special_day_group_xml(token='', name=name, description=description, days=days or [])}"
        "</tsc:CreateSpecialDayGroup>"
    )


def special_day_group_modify(
    *, token: str, name: str, description: str = "", days: list[str] | None = None
) -> str:
    """Build a ``tsc:ModifySpecialDayGroup`` body replacing group ``token``."""
    return (
        "<tsc:ModifySpecialDayGroup>"
        f"{_special_day_group_xml(token=token, name=name, description=description, days=days or [])}"
        "</tsc:ModifySpecialDayGroup>"
    )


def special_day_group_delete(*, token: str) -> str:
    """Build a ``tsc:DeleteSpecialDayGroup`` body removing group ``token``."""
    return _token_body("tsc", "DeleteSpecialDayGroup", token)


def _access_profile_xml(
    *, token: str, name: str, description: str, policies: list[dict[str, str]] | None
) -> str:
    policy_xml = ""
    for policy in policies or []:
        entity_type = policy.get("entity_type", "")
        type_attr = f" EntityType={quoteattr(entity_type)}" if entity_type else ""
        policy_xml += (
            "<tar:AccessPolicy>"
            f"<tar:ScheduleToken>{escape(policy.get('schedule_token', ''))}</tar:ScheduleToken>"
            f"<tar:Entity{type_attr}>{escape(policy.get('entity', ''))}</tar:Entity>"
            "</tar:AccessPolicy>"
        )
    token_attr = f" token={quoteattr(token)}" if token else ""
    return (
        f"<tar:AccessProfile{token_attr}>"
        f"<tar:Name>{escape(name)}</tar:Name>"
        f"<tar:Description>{escape(description)}</tar:Description>"
        f"{policy_xml}"
        "</tar:AccessProfile>"
    )


def access_profile_info_list(*, limit: int | None = None, start_reference: str = "") -> str:
    """Build a ``tar:GetAccessProfileInfoList`` body, optionally paged by limit and start reference."""
    return _paged_body(
        "tar", "GetAccessProfileInfoList", limit=limit, start_reference=start_reference
    )


def access_profiles(*, tokens: list[str]) -> str:
    """Build a ``tar:GetAccessProfiles`` body requesting the given access profile tokens."""
    return _tokens_body("tar", "GetAccessProfiles", tokens)


def access_profile_create(
    *, name: str, description: str = "", policies: list[dict[str, str]] | None = None
) -> str:
    """Build a ``tar:CreateAccessProfile`` body; the device replies with the new token.

    Each entry in ``policies`` grants one access point (or area) during one schedule:
    a dict of ``schedule_token``, ``entity`` (the access point/area token) and an optional
    ``entity_type``.
    """
    return (
        "<tar:CreateAccessProfile>"
        f"{_access_profile_xml(token='', name=name, description=description, policies=policies)}"
        "</tar:CreateAccessProfile>"
    )


def access_profile_modify(
    *, token: str, name: str, description: str = "", policies: list[dict[str, str]] | None = None
) -> str:
    """Build a ``tar:ModifyAccessProfile`` body replacing access profile ``token`` wholesale."""
    return (
        "<tar:ModifyAccessProfile>"
        f"{_access_profile_xml(token=token, name=name, description=description, policies=policies)}"
        "</tar:ModifyAccessProfile>"
    )


def access_profile_delete(*, token: str) -> str:
    """Build a ``tar:DeleteAccessProfile`` body removing access profile ``token``."""
    return _token_body("tar", "DeleteAccessProfile", token)


def parse_schedule_info_list(xml: str) -> dict[str, Any]:
    """Parse a GetScheduleInfoList response.

    Returns:
        A dict with ``items`` (each carrying ``token``, ``name``, ``description`` and
        optional ``capabilities``) and ``next_start_reference``.
    """
    return _parse_list(xml, "ScheduleInfo", (("Name", "name"), ("Description", "description")))


def parse_schedules(xml: str) -> list[dict[str, Any]]:
    """Parse a GetSchedules response.

    Returns:
        One dict per schedule with ``token``, ``name``, ``description``, ``standard`` (a
        weekday-keyed map of ``{"from", "until"}`` periods) and ``special_days``.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for schedule in find_all_local(root, "Schedule"):
        standard: dict[str, list[dict[str, str]]] = {}
        week = child_local(schedule, "Standard")
        if week is not None:
            for day in _WEEKDAYS:
                day_el = child_local(week, day)
                if day_el is not None:
                    standard[day] = _parse_time_periods(day_el)
        special = [
            {
                "group_token": child_text(entry, "GroupToken"),
                "time_ranges": _parse_time_periods(entry),
            }
            for entry in find_all_local(schedule, "SpecialDays")
        ]
        out.append(
            {
                "token": schedule.attrib.get("token", ""),
                "name": child_text(schedule, "Name"),
                "description": child_text(schedule, "Description"),
                "standard": standard,
                "special_days": special,
            }
        )
    return out


def _parse_time_periods(parent: Any) -> list[dict[str, str]]:
    return [
        {"from": child_text(period, "From"), "until": child_text(period, "Until")}
        for period in find_all_local(parent, "TimePeriod")
    ]


def parse_schedule_state(xml: str) -> dict[str, Any]:
    """Parse a GetScheduleState response into ``{"active": bool, "special_day": bool}``."""
    root = parse_xml(xml)
    if root is None:
        return {}
    state = find_local(root, "ScheduleState")
    if state is None:
        return {}
    return {
        "active": _to_bool(child_text(state, "Active")),
        "special_day": _to_bool(child_text(state, "SpecialDay")),
    }


def parse_special_day_group_info_list(xml: str) -> dict[str, Any]:
    """Parse a GetSpecialDayGroupInfoList response into ``items`` plus ``next_start_reference``."""
    return _parse_list(
        xml, "SpecialDayGroupInfo", (("Name", "name"), ("Description", "description"))
    )


def parse_access_profile_info_list(xml: str) -> dict[str, Any]:
    """Parse a GetAccessProfileInfoList response into ``items`` plus ``next_start_reference``."""
    return _parse_list(xml, "AccessProfileInfo", (("Name", "name"), ("Description", "description")))


def parse_access_profiles(xml: str) -> list[dict[str, Any]]:
    """Parse a GetAccessProfiles response.

    Returns:
        One dict per profile with ``token``, ``name``, ``description`` and ``policies`` —
        each policy a ``schedule_token``/``entity``/``entity_type`` triple.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for profile in find_all_local(root, "AccessProfile"):
        policies = []
        for policy in find_all_local(profile, "AccessPolicy"):
            entity = child_local(policy, "Entity")
            policies.append(
                {
                    "schedule_token": child_text(policy, "ScheduleToken"),
                    "entity": (entity.text or "").strip() if entity is not None else "",
                    "entity_type": entity.attrib.get("EntityType", "")
                    if entity is not None
                    else "",
                }
            )
        out.append(
            {
                "token": profile.attrib.get("token", ""),
                "name": child_text(profile, "Name"),
                "description": child_text(profile, "Description"),
                "policies": policies,
            }
        )
    return out


def parse_credentials(xml: str) -> list[dict[str, Any]]:
    """Parse a GetCredentials response.

    Returns:
        One dict per credential with ``token``, ``description``,
        ``credential_holder_reference``, ``valid_from``, ``valid_to``, ``identifiers``
        (``type``/``format_type``/``value``) and ``access_profiles``.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for credential in find_all_local(root, "Credential"):
        identifiers = []
        for identifier in find_all_local(credential, "CredentialIdentifier"):
            type_el = child_local(identifier, "Type")
            identifiers.append(
                {
                    "type": child_text(type_el, "Name") if type_el is not None else "",
                    "format_type": child_text(type_el, "FormatType") if type_el is not None else "",
                    "value": child_text(identifier, "Value"),
                }
            )
        profiles = [
            {
                "token": child_text(profile, "AccessProfileToken"),
                "valid_from": child_text(profile, "ValidFrom"),
                "valid_to": child_text(profile, "ValidTo"),
            }
            for profile in find_all_local(credential, "CredentialAccessProfile")
        ]
        out.append(
            {
                "token": credential.attrib.get("token", ""),
                "description": child_text(credential, "Description"),
                "credential_holder_reference": child_text(credential, "CredentialHolderReference"),
                "valid_from": child_text(credential, "ValidFrom"),
                "valid_to": child_text(credential, "ValidTo"),
                "identifiers": identifiers,
                "access_profiles": profiles,
            }
        )
    return out


def parse_access_points(xml: str) -> dict[str, Any]:
    """Parse a GetAccessPoints response into ``items`` plus ``next_start_reference``.

    Same fields as :func:`parse_access_point_info_list` plus ``authentication_profile``.
    """
    return _parse_list(
        xml,
        "AccessPoint",
        (
            ("Name", "name"),
            ("Description", "description"),
            ("AreaFrom", "area_from"),
            ("AreaTo", "area_to"),
            ("EntityType", "entity_type"),
            ("Entity", "entity"),
            ("AuthenticationProfileToken", "authentication_profile"),
        ),
    )


def parse_doors(xml: str) -> dict[str, Any]:
    """Parse a GetDoors response into ``items`` plus ``next_start_reference``."""
    return _parse_list(
        xml,
        "Door",
        (("Name", "name"), ("Description", "description"), ("DoorType", "door_type")),
    )


def parse_special_day_groups(xml: str) -> list[dict[str, Any]]:
    """Parse a GetSpecialDayGroups response.

    Returns:
        One dict per group with ``token``, ``name``, ``description`` and ``days`` — the
        iCalendar strings naming the dates the group covers.
    """
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[dict[str, Any]] = []
    for group in find_all_local(root, "SpecialDayGroup"):
        days = [
            (el.text or "").strip()
            for el in group
            if _local(el.tag) == "Days" and el.text and el.text.strip()
        ]
        out.append(
            {
                "token": group.attrib.get("token", ""),
                "name": child_text(group, "Name"),
                "description": child_text(group, "Description"),
                "days": days,
            }
        )
    return out
