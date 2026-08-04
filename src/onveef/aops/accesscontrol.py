"""Access Control, Door and Credential (Profile A/C) operations for the asyncio ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import pacs, parsers
from onveef.atransport import AsyncTransport


class AccessControlOperations(AsyncTransport):
    """Access Control, Door and Credential (Profile A/C) operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def get_access_point_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return access points and a pagination reference (Profile A/C)."""
        xml = await self.call(
            service="accesscontrol",
            operation="GetAccessPointInfoList",
            body_inner=pacs.access_point_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_access_point_info_list(xml)

    async def get_access_point_state(self, *, token: str) -> dict[str, Any]:
        """Return an access point's state (Profile A/C)."""
        xml = await self.call(
            service="accesscontrol",
            operation="GetAccessPointState",
            body_inner=pacs.access_point_state(token=token),
        )
        return pacs.parse_access_point_state(xml)

    async def enable_access_point(self, *, token: str) -> None:
        """Enable an access point (Profile A/C)."""
        await self.call(
            service="accesscontrol",
            operation="EnableAccessPoint",
            body_inner=pacs.enable_access_point(token=token),
        )

    async def disable_access_point(self, *, token: str) -> None:
        """Disable an access point (Profile A/C)."""
        await self.call(
            service="accesscontrol",
            operation="DisableAccessPoint",
            body_inner=pacs.disable_access_point(token=token),
        )

    async def get_area_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return areas and a pagination reference (Profile A/C)."""
        xml = await self.call(
            service="accesscontrol",
            operation="GetAreaInfoList",
            body_inner=pacs.area_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_area_info_list(xml)

    async def get_door_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return doors and a pagination reference (Profile A/C)."""
        xml = await self.call(
            service="doorcontrol",
            operation="GetDoorInfoList",
            body_inner=pacs.door_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_door_info_list(xml)

    async def get_door_state(self, *, token: str) -> dict[str, Any]:
        """Return a door's state (Profile A/C)."""
        xml = await self.call(
            service="doorcontrol",
            operation="GetDoorState",
            body_inner=pacs.door_state(token=token),
        )
        return pacs.parse_door_state(xml)

    async def door_command(self, command: str, *, token: str) -> None:
        """Send an arbitrary door command (e.g. ``AccessDoor``) to a door (Profile A/C)."""
        await self.call(
            service="doorcontrol",
            operation=command,
            body_inner=pacs.door_action(command, token=token),
        )

    async def access_door(self, *, token: str) -> None:
        """Momentarily grant access at a door (Profile A/C)."""
        await self.door_command("AccessDoor", token=token)

    async def lock_door(self, *, token: str) -> None:
        """Lock a door (Profile A/C)."""
        await self.door_command("LockDoor", token=token)

    async def unlock_door(self, *, token: str) -> None:
        """Unlock a door (Profile A/C)."""
        await self.door_command("UnlockDoor", token=token)

    async def get_credential_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return credentials and a pagination reference (Profile C)."""
        xml = await self.call(
            service="credential",
            operation="GetCredentialInfoList",
            body_inner=pacs.credential_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_credential_info_list(xml)

    async def get_credential_state(self, *, token: str) -> dict[str, Any]:
        """Return a credential's state (Profile C)."""
        xml = await self.call(
            service="credential",
            operation="GetCredentialState",
            body_inner=pacs.credential_state(token=token),
        )
        return pacs.parse_credential_state(xml)

    async def enable_credential(self, *, token: str, reason: str = "") -> None:
        """Enable a credential (Profile C)."""
        await self.call(
            service="credential",
            operation="EnableCredential",
            body_inner=pacs.enable_credential(token=token, reason=reason),
        )

    async def disable_credential(self, *, token: str, reason: str = "") -> None:
        """Disable a credential (Profile C)."""
        await self.call(
            service="credential",
            operation="DisableCredential",
            body_inner=pacs.disable_credential(token=token, reason=reason),
        )

    async def delete_credential(self, *, token: str) -> None:
        """Delete a credential (Profile C)."""
        await self.call(
            service="credential",
            operation="DeleteCredential",
            body_inner=pacs.delete_credential(token=token),
        )

    async def get_access_points(self, *, tokens: list[str]) -> dict[str, Any]:
        """Return full access point records for the given tokens."""
        xml = await self.call(
            service="accesscontrol",
            operation="GetAccessPoints",
            body_inner=pacs.access_points(tokens=tokens),
        )
        return pacs.parse_access_points(xml)

    async def get_doors(self, *, tokens: list[str]) -> dict[str, Any]:
        """Return full door records for the given tokens."""
        xml = await self.call(
            service="doorcontrol",
            operation="GetDoors",
            body_inner=pacs.doors(tokens=tokens),
        )
        return pacs.parse_doors(xml)

    async def get_credentials(self, *, tokens: list[str]) -> list[dict[str, Any]]:
        """Return full credential records — identifiers and granted access profiles."""
        xml = await self.call(
            service="credential",
            operation="GetCredentials",
            body_inner=pacs.credentials(tokens=tokens),
        )
        return pacs.parse_credentials(xml)

    async def create_credential(
        self,
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
        """Issue a new credential and return its token (Profile A).

        ``identifiers`` are the physical credentials — each a dict of ``type``
        (``Card``, ``PIN``…), optional ``format_type`` and ``value``. ``access_profiles``
        grant access, each a dict of ``token`` plus optional ``valid_from``/``valid_to``.
        """
        xml = await self.call(
            service="credential",
            operation="CreateCredential",
            body_inner=pacs.credential_create(
                description=description,
                holder_reference=holder_reference,
                valid_from=valid_from,
                valid_to=valid_to,
                identifiers=list(identifiers or []),
                access_profiles=list(access_profiles or []),
                enabled=enabled,
                reason=reason,
            ),
        )
        return parsers.parse_created_token(xml, tag="Token")

    async def modify_credential(
        self,
        *,
        token: str,
        description: str = "",
        holder_reference: str = "",
        valid_from: str = "",
        valid_to: str = "",
        identifiers: list[dict[str, str]] | None = None,
        access_profiles: list[dict[str, str]] | None = None,
    ) -> None:
        """Replace a credential wholesale — read it with :meth:`get_credentials` first."""
        await self.call(
            service="credential",
            operation="ModifyCredential",
            body_inner=pacs.credential_modify(
                token=token,
                description=description,
                holder_reference=holder_reference,
                valid_from=valid_from,
                valid_to=valid_to,
                identifiers=list(identifiers or []),
                access_profiles=list(access_profiles or []),
            ),
        )

    async def get_schedule_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return the device's schedules as paged summaries (Profile A)."""
        xml = await self.call(
            service="schedule",
            operation="GetScheduleInfoList",
            body_inner=pacs.schedule_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_schedule_info_list(xml)

    async def get_schedules(self, *, tokens: list[str]) -> list[dict[str, Any]]:
        """Return full schedules — the recurring week and any special-day overrides."""
        xml = await self.call(
            service="schedule",
            operation="GetSchedules",
            body_inner=pacs.schedules(tokens=tokens),
        )
        return pacs.parse_schedules(xml)

    async def get_schedule_state(self, *, token: str) -> dict[str, Any]:
        """Return whether a schedule is active right now, and whether today is special."""
        xml = await self.call(
            service="schedule",
            operation="GetScheduleState",
            body_inner=pacs.schedule_state(token=token),
        )
        return pacs.parse_schedule_state(xml)

    async def create_schedule(
        self,
        *,
        name: str,
        description: str = "",
        standard: dict[str, list[dict[str, str]]] | None = None,
        special_days: list[dict[str, Any]] | None = None,
    ) -> str:
        """Create a schedule and return its token.

        ``standard`` maps weekday names (``"Monday"`` …) to a list of
        ``{"from": "08:00:00", "until": "17:00:00"}`` periods; days you omit are closed.
        ``special_days`` overrides those, each a dict of ``group_token`` (from
        :meth:`get_special_day_group_info_list`) and its own ``time_ranges``.
        """
        xml = await self.call(
            service="schedule",
            operation="CreateSchedule",
            body_inner=pacs.schedule_create(
                name=name,
                description=description,
                standard=dict(standard or {}),
                special_days=list(special_days or []),
            ),
        )
        return parsers.parse_created_token(xml, tag="Token")

    async def modify_schedule(
        self,
        *,
        token: str,
        name: str,
        description: str = "",
        standard: dict[str, list[dict[str, str]]] | None = None,
        special_days: list[dict[str, Any]] | None = None,
    ) -> None:
        """Replace a schedule wholesale — read it with :meth:`get_schedules` first."""
        await self.call(
            service="schedule",
            operation="ModifySchedule",
            body_inner=pacs.schedule_modify(
                token=token,
                name=name,
                description=description,
                standard=dict(standard or {}),
                special_days=list(special_days or []),
            ),
        )

    async def delete_schedule(self, *, token: str) -> None:
        """Delete a schedule. Access profiles still referencing it will be rejected."""
        await self.call(
            service="schedule",
            operation="DeleteSchedule",
            body_inner=pacs.schedule_delete(token=token),
        )

    async def get_special_day_group_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return the device's special-day groups (holidays, exceptions) as paged summaries."""
        xml = await self.call(
            service="schedule",
            operation="GetSpecialDayGroupInfoList",
            body_inner=pacs.special_day_group_info_list(
                limit=limit, start_reference=start_reference
            ),
        )
        return pacs.parse_special_day_group_info_list(xml)

    async def get_special_day_groups(self, *, tokens: list[str]) -> list[dict[str, Any]]:
        """Return full special-day groups, including the iCalendar day strings they hold."""
        xml = await self.call(
            service="schedule",
            operation="GetSpecialDayGroups",
            body_inner=pacs.special_day_groups(tokens=tokens),
        )
        return pacs.parse_special_day_groups(xml)

    async def create_special_day_group(
        self, *, name: str, description: str = "", days: list[str] | None = None
    ) -> str:
        """Create a special-day group from iCalendar ``days`` strings; returns its token."""
        xml = await self.call(
            service="schedule",
            operation="CreateSpecialDayGroup",
            body_inner=pacs.special_day_group_create(
                name=name, description=description, days=list(days or [])
            ),
        )
        return parsers.parse_created_token(xml, tag="Token")

    async def modify_special_day_group(
        self, *, token: str, name: str, description: str = "", days: list[str] | None = None
    ) -> None:
        """Replace a special-day group wholesale."""
        await self.call(
            service="schedule",
            operation="ModifySpecialDayGroup",
            body_inner=pacs.special_day_group_modify(
                token=token, name=name, description=description, days=list(days or [])
            ),
        )

    async def delete_special_day_group(self, *, token: str) -> None:
        """Delete a special-day group."""
        await self.call(
            service="schedule",
            operation="DeleteSpecialDayGroup",
            body_inner=pacs.special_day_group_delete(token=token),
        )

    async def get_access_profile_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return the device's access profiles as paged summaries (Profile A)."""
        xml = await self.call(
            service="accessrules",
            operation="GetAccessProfileInfoList",
            body_inner=pacs.access_profile_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_access_profile_info_list(xml)

    async def get_access_profiles(self, *, tokens: list[str]) -> list[dict[str, Any]]:
        """Return full access profiles — which schedule opens which access point."""
        xml = await self.call(
            service="accessrules",
            operation="GetAccessProfiles",
            body_inner=pacs.access_profiles(tokens=tokens),
        )
        return pacs.parse_access_profiles(xml)

    async def create_access_profile(
        self, *, name: str, description: str = "", policies: list[dict[str, str]] | None = None
    ) -> str:
        """Create an access profile and return its token.

        Each entry in ``policies`` grants one entity during one schedule: a dict of
        ``schedule_token``, ``entity`` (an access point or area token) and an optional
        ``entity_type``. This is the object a credential is granted.
        """
        xml = await self.call(
            service="accessrules",
            operation="CreateAccessProfile",
            body_inner=pacs.access_profile_create(
                name=name, description=description, policies=list(policies or [])
            ),
        )
        return parsers.parse_created_token(xml, tag="Token")

    async def modify_access_profile(
        self,
        *,
        token: str,
        name: str,
        description: str = "",
        policies: list[dict[str, str]] | None = None,
    ) -> None:
        """Replace an access profile wholesale — read it with :meth:`get_access_profiles` first."""
        await self.call(
            service="accessrules",
            operation="ModifyAccessProfile",
            body_inner=pacs.access_profile_modify(
                token=token, name=name, description=description, policies=list(policies or [])
            ),
        )

    async def delete_access_profile(self, *, token: str) -> None:
        """Delete an access profile, revoking it from every credential holding it."""
        await self.call(
            service="accessrules",
            operation="DeleteAccessProfile",
            body_inner=pacs.access_profile_delete(token=token),
        )
