"""Device Management and DeviceIO operations for the asyncio ONVIF client."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from onveef import envelopes, parsers
from onveef.atransport import AsyncTransport


class DeviceOperations(AsyncTransport):
    """Device Management and DeviceIO operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def get_device_information(self) -> dict[str, str]:
        """Return the device's manufacturer/model/firmware/serial/hardware information."""
        xml = await self.call(
            service="device",
            operation="GetDeviceInformation",
            body_inner=envelopes.device_get_information(),
        )
        return parsers.parse_device_information(xml)

    async def set_system_date_time(
        self,
        *,
        date_time_type: str = "Manual",
        daylight_savings: bool = False,
        timezone: str = "",
        utc_datetime: datetime | None = None,
    ) -> None:
        """Set the device's date/time mode, DST flag, timezone, and optional UTC value."""
        await self.call(
            service="device",
            operation="SetSystemDateAndTime",
            body_inner=envelopes.device_set_system_date_time(
                date_time_type=date_time_type,
                daylight_savings=daylight_savings,
                timezone=timezone,
                utc_datetime=utc_datetime,
            ),
        )

    async def get_hostname(self) -> str:
        """Return the device hostname."""
        xml = await self.call(
            service="device",
            operation="GetHostname",
            body_inner=envelopes.device_get_hostname(),
        )
        return parsers.parse_hostname(xml)

    async def set_hostname(self, name: str) -> None:
        """Set the device hostname to ``name``."""
        await self.call(
            service="device",
            operation="SetHostname",
            body_inner=envelopes.device_set_hostname(name),
        )

    async def get_network_interfaces(self) -> list[dict[str, Any]]:
        """Return the device's network interfaces."""
        xml = await self.call(
            service="device",
            operation="GetNetworkInterfaces",
            body_inner=envelopes.device_get_network_interfaces(),
        )
        return parsers.parse_network_interfaces(xml)

    async def get_users(self) -> list[dict[str, str]]:
        """Return the configured user accounts and their levels."""
        xml = await self.call(
            service="device",
            operation="GetUsers",
            body_inner=envelopes.device_get_users(),
        )
        return parsers.parse_users(xml)

    async def system_reboot(self) -> None:
        """Reboot the device."""
        await self.call(
            service="device",
            operation="SystemReboot",
            body_inner=envelopes.device_system_reboot(),
        )

    async def system_factory_default(self, *, hard: bool = False) -> None:
        """Reset the device to factory defaults (``hard`` for a full reset)."""
        await self.call(
            service="device",
            operation="SetSystemFactoryDefault",
            body_inner=envelopes.device_set_system_factory_default(hard=hard),
        )

    async def create_user(self, *, username: str, password: str, user_level: str) -> None:
        """Create a user account with the given username, password, and level."""
        await self.call(
            service="device",
            operation="CreateUsers",
            body_inner=envelopes.device_create_users(
                username=username, password=password, user_level=user_level
            ),
        )

    async def set_user(self, *, username: str, password: str, user_level: str) -> None:
        """Update an existing user's password and level."""
        await self.call(
            service="device",
            operation="SetUser",
            body_inner=envelopes.device_set_user(
                username=username, password=password, user_level=user_level
            ),
        )

    async def delete_users(self, *, usernames: list[str]) -> None:
        """Delete the named user accounts."""
        await self.call(
            service="device",
            operation="DeleteUsers",
            body_inner=envelopes.device_delete_users(usernames=usernames),
        )

    async def set_network_interface(
        self,
        *,
        token: str,
        enabled: bool,
        dhcp: bool,
        ipv4_address: str = "",
        prefix_length: int = 24,
        mtu: int | None = None,
    ) -> None:
        """Configure a network interface's enable/DHCP/IPv4/MTU settings."""
        await self.call(
            service="device",
            operation="SetNetworkInterfaces",
            body_inner=envelopes.device_set_network_interface(
                token=token,
                enabled=enabled,
                dhcp=dhcp,
                ipv4_address=ipv4_address,
                prefix_length=prefix_length,
                mtu=mtu,
            ),
        )

    async def get_network_protocols(self) -> list[dict[str, Any]]:
        """Return the device's network protocols (HTTP/HTTPS/RTSP ports and enable flags)."""
        xml = await self.call(
            service="device",
            operation="GetNetworkProtocols",
            body_inner=envelopes.device_get_network_protocols(),
        )
        return parsers.parse_network_protocols(xml)

    async def set_network_protocols(self, *, protocols: list[dict[str, Any]]) -> None:
        """Set the device's network protocols."""
        await self.call(
            service="device",
            operation="SetNetworkProtocols",
            body_inner=envelopes.device_set_network_protocols(protocols=protocols),
        )

    async def get_network_default_gateway(self) -> dict[str, list[str]]:
        """Return the device's default gateway addresses."""
        xml = await self.call(
            service="device",
            operation="GetNetworkDefaultGateway",
            body_inner=envelopes.device_get_network_default_gateway(),
        )
        return parsers.parse_network_default_gateway(xml)

    async def set_network_default_gateway(self, *, ipv4_addresses: list[str]) -> None:
        """Set the device's IPv4 default gateway addresses."""
        await self.call(
            service="device",
            operation="SetNetworkDefaultGateway",
            body_inner=envelopes.device_set_network_default_gateway(ipv4_addresses=ipv4_addresses),
        )

    async def get_dns(self) -> dict[str, Any]:
        """Return the device's DNS configuration."""
        xml = await self.call(
            service="device",
            operation="GetDNS",
            body_inner=envelopes.device_get_dns(),
        )
        return parsers.parse_dns(xml)

    async def set_dns(
        self,
        *,
        from_dhcp: bool,
        ipv4_servers: list[str],
        search_domains: list[str],
    ) -> None:
        """Set the device's DNS servers and search domains."""
        await self.call(
            service="device",
            operation="SetDNS",
            body_inner=envelopes.device_set_dns(
                from_dhcp=from_dhcp,
                ipv4_servers=ipv4_servers,
                search_domains=search_domains,
            ),
        )

    async def get_ntp(self) -> dict[str, Any]:
        """Return the device's NTP configuration."""
        xml = await self.call(
            service="device",
            operation="GetNTP",
            body_inner=envelopes.device_get_ntp(),
        )
        return parsers.parse_ntp(xml)

    async def set_ntp(self, *, from_dhcp: bool, ipv4_servers: list[str]) -> None:
        """Set the device's NTP servers."""
        await self.call(
            service="device",
            operation="SetNTP",
            body_inner=envelopes.device_set_ntp(from_dhcp=from_dhcp, ipv4_servers=ipv4_servers),
        )

    async def get_scopes(self) -> list[dict[str, str]]:
        """Return the device's discovery scopes."""
        xml = await self.call(
            service="device",
            operation="GetScopes",
            body_inner=envelopes.device_get_scopes(),
        )
        return parsers.parse_scopes(xml)

    async def set_scopes(self, *, scopes: list[str]) -> None:
        """Replace the device's configurable discovery scopes."""
        await self.call(
            service="device",
            operation="SetScopes",
            body_inner=envelopes.device_set_scopes(scopes=scopes),
        )

    async def add_scopes(self, *, scopes: list[str]) -> None:
        """Add configurable discovery scopes."""
        await self.call(
            service="device",
            operation="AddScopes",
            body_inner=envelopes.device_add_scopes(scopes=scopes),
        )

    async def remove_scopes(self, *, scopes: list[str]) -> None:
        """Remove configurable discovery scopes."""
        await self.call(
            service="device",
            operation="RemoveScopes",
            body_inner=envelopes.device_remove_scopes(scopes=scopes),
        )

    async def get_geo_location(self) -> list[dict[str, float | None]]:
        """Return the device's geographic location entries."""
        xml = await self.call(
            service="device",
            operation="GetGeoLocation",
            body_inner=envelopes.device_get_geo_location(),
        )
        return parsers.parse_geo_location(xml)

    async def set_geo_location(self, *, lon: float, lat: float, elevation: float = 0.0) -> None:
        """Set the device's geographic location."""
        await self.call(
            service="device",
            operation="SetGeoLocation",
            body_inner=envelopes.device_set_geo_location(lon=lon, lat=lat, elevation=elevation),
        )

    async def get_system_log(self, *, log_type: str = "System") -> dict[str, str]:
        """Return a device system or access log."""
        xml = await self.call(
            service="device",
            operation="GetSystemLog",
            body_inner=envelopes.device_get_system_log(log_type=log_type),
        )
        return parsers.parse_system_log(xml)

    async def get_system_support_information(self) -> dict[str, str]:
        """Return the device's support information blob."""
        xml = await self.call(
            service="device",
            operation="GetSystemSupportInformation",
            body_inner=envelopes.device_get_system_support_information(),
        )
        return parsers.parse_support_information(xml)

    async def get_system_uris(self) -> dict[str, Any]:
        """Return the device's system log/support/backup download URIs."""
        xml = await self.call(
            service="device",
            operation="GetSystemUris",
            body_inner=envelopes.device_get_system_uris(),
        )
        return parsers.parse_system_uris(xml)

    async def get_certificates(self) -> list[dict[str, str]]:
        """Return the device's installed TLS certificates."""
        xml = await self.call(
            service="device",
            operation="GetCertificates",
            body_inner=envelopes.device_get_certificates(),
        )
        return parsers.parse_certificates(xml)

    async def get_dot1x_configurations(self) -> list[dict[str, Any]]:
        """Return the device's IEEE 802.1X configurations."""
        xml = await self.call(
            service="device",
            operation="GetDot1XConfigurations",
            body_inner=envelopes.device_get_dot1x_configurations(),
        )
        return parsers.parse_dot1x_configurations(xml)

    async def get_wsdl_url(self) -> str:
        """Return the device's WSDL base URL."""
        xml = await self.call(
            service="device",
            operation="GetWsdlUrl",
            body_inner=envelopes.device_get_wsdl_url(),
        )
        return parsers.parse_text_element(xml, "Url")

    async def get_zero_configuration(self) -> dict[str, Any]:
        """Return the device's zero-configuration (link-local) settings."""
        xml = await self.call(
            service="device",
            operation="GetZeroConfiguration",
            body_inner=envelopes.device_get_zero_configuration(),
        )
        return parsers.parse_zero_configuration(xml)

    async def get_service_capabilities(self, service: str) -> dict[str, Any]:
        """Return a service's capability flags (``media`` resolves to media/media2)."""
        resolved = service
        if service == "media":
            resolved, _ = await self._media_service()
        xml = await self.call(
            service=resolved,
            operation="GetServiceCapabilities",
            body_inner=envelopes.get_service_capabilities(resolved),
        )
        return parsers.parse_service_capabilities(xml)

    async def get_relay_outputs(self) -> list[dict[str, Any]]:
        """Return the device's relay outputs."""
        service, use_deviceio = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetRelayOutputs",
            body_inner=envelopes.device_get_relay_outputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_relay_outputs(xml)

    async def set_relay_output_state(self, *, token: str, logical_state: str) -> None:
        """Set a relay output's logical state (active/inactive)."""
        service, use_deviceio = await self._relay_service()
        await self.call(
            service=service,
            operation="SetRelayOutputState",
            body_inner=envelopes.device_set_relay_output_state(
                token=token, logical_state=logical_state, use_deviceio=use_deviceio
            ),
        )

    async def set_relay_output_settings(
        self,
        *,
        token: str,
        mode: str,
        delay_time: str,
        idle_state: str,
    ) -> None:
        """Set a relay output's mode, delay time, and idle state."""
        service, use_deviceio = await self._relay_service()
        await self.call(
            service=service,
            operation="SetRelayOutputSettings",
            body_inner=envelopes.device_set_relay_output_settings(
                token=token,
                mode=mode,
                delay_time=delay_time,
                idle_state=idle_state,
                use_deviceio=use_deviceio,
            ),
        )

    async def get_relay_output_options(self, *, token: str = "") -> list[dict[str, Any]]:
        """Return the option ranges for relay outputs."""
        service, _ = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetRelayOutputOptions",
            body_inner=envelopes.device_get_relay_output_options(token=token),
        )
        return parsers.parse_relay_output_options(xml)

    async def get_digital_inputs(self) -> list[dict[str, Any]]:
        """Return the device's digital inputs."""
        service, use_deviceio = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetDigitalInputs",
            body_inner=envelopes.device_get_digital_inputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_digital_inputs(xml)

    async def get_serial_ports(self) -> list[dict[str, str]]:
        """Return the device's serial ports."""
        service, _ = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetSerialPorts",
            body_inner=envelopes.device_get_serial_ports(),
        )
        return parsers.parse_serial_ports(xml)

    async def get_endpoint_reference(self) -> str:
        """Return the device's WS-Discovery endpoint reference GUID."""
        xml = await self.call(
            service="device",
            operation="GetEndpointReference",
            body_inner=envelopes.device_get_endpoint_reference(),
        )
        return parsers.parse_text_element(xml, "GUID")

    async def get_storage_configurations(self) -> list[dict[str, Any]]:
        """Return the device's configured storage targets (NFS/CIFS/local paths)."""
        xml = await self.call(
            service="device",
            operation="GetStorageConfigurations",
            body_inner=envelopes.device_get_storage_configurations(),
        )
        return parsers.parse_storage_configurations(xml)

    async def start_firmware_upgrade(self) -> dict[str, str]:
        """Begin a firmware upgrade and return where to upload the image.

        The device replies with ``upload_uri``, ``upload_delay`` and ``expected_down_time``;
        POST the firmware image to ``upload_uri`` yourself after waiting ``upload_delay``.
        This reboots the device — there is no undo.
        """
        xml = await self.call(
            service="device",
            operation="StartFirmwareUpgrade",
            body_inner=envelopes.device_start_firmware_upgrade(),
        )
        return parsers.parse_upload_target(xml)

    async def start_system_restore(self) -> dict[str, str]:
        """Begin a system restore and return where to upload the backup file.

        Same shape as :meth:`start_firmware_upgrade`: POST the backup to ``upload_uri``.
        This overwrites the device's configuration.
        """
        xml = await self.call(
            service="device",
            operation="StartSystemRestore",
            body_inner=envelopes.device_start_system_restore(),
        )
        return parsers.parse_upload_target(xml)
