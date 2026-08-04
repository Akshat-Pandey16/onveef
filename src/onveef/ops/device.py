"""Device Management and DeviceIO operations for the synchronous ONVIF client."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from onveef import envelopes, parsers
from onveef.transport import (
    SyncTransport,
)


class DeviceOperations(SyncTransport):
    """Device Management and DeviceIO operations, mixed into :class:`~onveef.client.OnvifClient`."""

    def get_device_information(self) -> dict[str, str]:
        """Return the ONVIF ``GetDeviceInformation`` result from the Device service, parsed by ``parsers.parse_device_information`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetDeviceInformation",
            body_inner=envelopes.device_get_information(),
        )
        return parsers.parse_device_information(xml)

    def set_system_date_time(
        self,
        *,
        date_time_type: str = "Manual",
        daylight_savings: bool = False,
        timezone: str = "",
        utc_datetime: datetime | None = None,
    ) -> None:
        """Send the ONVIF ``SetSystemDateAndTime`` request to the Device service."""
        self.call(
            service="device",
            operation="SetSystemDateAndTime",
            body_inner=envelopes.device_set_system_date_time(
                date_time_type=date_time_type,
                daylight_savings=daylight_savings,
                timezone=timezone,
                utc_datetime=utc_datetime,
            ),
        )

    def get_hostname(self) -> str:
        """Return the ONVIF ``GetHostname`` result from the Device service, parsed by ``parsers.parse_hostname`` into ``str``."""
        xml = self.call(
            service="device",
            operation="GetHostname",
            body_inner=envelopes.device_get_hostname(),
        )
        return parsers.parse_hostname(xml)

    def set_hostname(self, name: str) -> None:
        """Send the ONVIF ``SetHostname`` request to the Device service."""
        self.call(
            service="device",
            operation="SetHostname",
            body_inner=envelopes.device_set_hostname(name),
        )

    def get_network_interfaces(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetNetworkInterfaces`` result from the Device service, parsed by ``parsers.parse_network_interfaces`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="device",
            operation="GetNetworkInterfaces",
            body_inner=envelopes.device_get_network_interfaces(),
        )
        return parsers.parse_network_interfaces(xml)

    def get_users(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetUsers`` result from the Device service, parsed by ``parsers.parse_users`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="device",
            operation="GetUsers",
            body_inner=envelopes.device_get_users(),
        )
        return parsers.parse_users(xml)

    def system_reboot(self) -> None:
        """Send the ONVIF ``SystemReboot`` request to the Device service."""
        self.call(
            service="device",
            operation="SystemReboot",
            body_inner=envelopes.device_system_reboot(),
        )

    def system_factory_default(self, *, hard: bool = False) -> None:
        """Send the ONVIF ``SetSystemFactoryDefault`` request to the Device service."""
        self.call(
            service="device",
            operation="SetSystemFactoryDefault",
            body_inner=envelopes.device_set_system_factory_default(hard=hard),
        )

    def create_user(self, *, username: str, password: str, user_level: str) -> None:
        """Send the ONVIF ``CreateUsers`` request to the Device service."""
        self.call(
            service="device",
            operation="CreateUsers",
            body_inner=envelopes.device_create_users(
                username=username, password=password, user_level=user_level
            ),
        )

    def set_user(self, *, username: str, password: str, user_level: str) -> None:
        """Send the ONVIF ``SetUser`` request to the Device service."""
        self.call(
            service="device",
            operation="SetUser",
            body_inner=envelopes.device_set_user(
                username=username, password=password, user_level=user_level
            ),
        )

    def delete_users(self, *, usernames: list[str]) -> None:
        """Send the ONVIF ``DeleteUsers`` request to the Device service."""
        self.call(
            service="device",
            operation="DeleteUsers",
            body_inner=envelopes.device_delete_users(usernames=usernames),
        )

    def set_network_interface(
        self,
        *,
        token: str,
        enabled: bool,
        dhcp: bool,
        ipv4_address: str = "",
        prefix_length: int = 24,
        mtu: int | None = None,
    ) -> None:
        """Send the ONVIF ``SetNetworkInterfaces`` request to the Device service."""
        self.call(
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

    def get_network_protocols(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetNetworkProtocols`` result from the Device service, parsed by ``parsers.parse_network_protocols`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="device",
            operation="GetNetworkProtocols",
            body_inner=envelopes.device_get_network_protocols(),
        )
        return parsers.parse_network_protocols(xml)

    def set_network_protocols(self, *, protocols: list[dict[str, Any]]) -> None:
        """Send the ONVIF ``SetNetworkProtocols`` request to the Device service."""
        self.call(
            service="device",
            operation="SetNetworkProtocols",
            body_inner=envelopes.device_set_network_protocols(protocols=protocols),
        )

    def get_network_default_gateway(self) -> dict[str, list[str]]:
        """Return the ONVIF ``GetNetworkDefaultGateway`` result from the Device service, parsed by ``parsers.parse_network_default_gateway`` into ``dict[str, list[str]]``."""
        xml = self.call(
            service="device",
            operation="GetNetworkDefaultGateway",
            body_inner=envelopes.device_get_network_default_gateway(),
        )
        return parsers.parse_network_default_gateway(xml)

    def set_network_default_gateway(self, *, ipv4_addresses: list[str]) -> None:
        """Send the ONVIF ``SetNetworkDefaultGateway`` request to the Device service."""
        self.call(
            service="device",
            operation="SetNetworkDefaultGateway",
            body_inner=envelopes.device_set_network_default_gateway(ipv4_addresses=ipv4_addresses),
        )

    def get_relay_outputs(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRelayOutputs`` result from the Device service, parsed by ``parsers.parse_relay_outputs`` into ``list[dict[str, Any]]``."""
        service, use_deviceio = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetRelayOutputs",
            body_inner=envelopes.device_get_relay_outputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_relay_outputs(xml)

    def set_relay_output_state(self, *, token: str, logical_state: str) -> None:
        """Send the ONVIF ``SetRelayOutputState`` request to the Device service."""
        service, use_deviceio = self._relay_service()
        self.call(
            service=service,
            operation="SetRelayOutputState",
            body_inner=envelopes.device_set_relay_output_state(
                token=token, logical_state=logical_state, use_deviceio=use_deviceio
            ),
        )

    def set_relay_output_settings(
        self,
        *,
        token: str,
        mode: str,
        delay_time: str,
        idle_state: str,
    ) -> None:
        """Send the ONVIF ``SetRelayOutputSettings`` request to the Device service."""
        service, use_deviceio = self._relay_service()
        self.call(
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

    def get_dns(self) -> dict[str, Any]:
        """Return the ONVIF ``GetDNS`` result from the Device service, parsed by ``parsers.parse_dns`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetDNS",
            body_inner=envelopes.device_get_dns(),
        )
        return parsers.parse_dns(xml)

    def set_dns(
        self,
        *,
        from_dhcp: bool,
        ipv4_servers: list[str],
        search_domains: list[str],
    ) -> None:
        """Send the ONVIF ``SetDNS`` request to the Device service."""
        self.call(
            service="device",
            operation="SetDNS",
            body_inner=envelopes.device_set_dns(
                from_dhcp=from_dhcp,
                ipv4_servers=ipv4_servers,
                search_domains=search_domains,
            ),
        )

    def get_ntp(self) -> dict[str, Any]:
        """Return the ONVIF ``GetNTP`` result from the Device service, parsed by ``parsers.parse_ntp`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetNTP",
            body_inner=envelopes.device_get_ntp(),
        )
        return parsers.parse_ntp(xml)

    def set_ntp(self, *, from_dhcp: bool, ipv4_servers: list[str]) -> None:
        """Send the ONVIF ``SetNTP`` request to the Device service."""
        self.call(
            service="device",
            operation="SetNTP",
            body_inner=envelopes.device_set_ntp(from_dhcp=from_dhcp, ipv4_servers=ipv4_servers),
        )

    def get_digital_inputs(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetDigitalInputs`` result from the Device service, parsed by ``parsers.parse_digital_inputs`` into ``list[dict[str, Any]]``."""
        service, use_deviceio = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetDigitalInputs",
            body_inner=envelopes.device_get_digital_inputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_digital_inputs(xml)

    def get_scopes(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetScopes`` result from the Device service, parsed by ``parsers.parse_scopes`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="device",
            operation="GetScopes",
            body_inner=envelopes.device_get_scopes(),
        )
        return parsers.parse_scopes(xml)

    def set_scopes(self, *, scopes: list[str]) -> None:
        """Send the ONVIF ``SetScopes`` request to the Device service."""
        self.call(
            service="device",
            operation="SetScopes",
            body_inner=envelopes.device_set_scopes(scopes=scopes),
        )

    def add_scopes(self, *, scopes: list[str]) -> None:
        """Send the ONVIF ``AddScopes`` request to the Device service."""
        self.call(
            service="device",
            operation="AddScopes",
            body_inner=envelopes.device_add_scopes(scopes=scopes),
        )

    def remove_scopes(self, *, scopes: list[str]) -> None:
        """Send the ONVIF ``RemoveScopes`` request to the Device service."""
        self.call(
            service="device",
            operation="RemoveScopes",
            body_inner=envelopes.device_remove_scopes(scopes=scopes),
        )

    def get_system_log(self, *, log_type: str = "System") -> dict[str, str]:
        """Return the ONVIF ``GetSystemLog`` result from the Device service, parsed by ``parsers.parse_system_log`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetSystemLog",
            body_inner=envelopes.device_get_system_log(log_type=log_type),
        )
        return parsers.parse_system_log(xml)

    def get_system_support_information(self) -> dict[str, str]:
        """Return the ONVIF ``GetSystemSupportInformation`` result from the Device service, parsed by ``parsers.parse_support_information`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetSystemSupportInformation",
            body_inner=envelopes.device_get_system_support_information(),
        )
        return parsers.parse_support_information(xml)

    def get_certificates(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetCertificates`` result from the Device service, parsed by ``parsers.parse_certificates`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="device",
            operation="GetCertificates",
            body_inner=envelopes.device_get_certificates(),
        )
        return parsers.parse_certificates(xml)

    def get_dot1x_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetDot1XConfigurations`` result from the Device service, parsed by ``parsers.parse_dot1x_configurations`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="device",
            operation="GetDot1XConfigurations",
            body_inner=envelopes.device_get_dot1x_configurations(),
        )
        return parsers.parse_dot1x_configurations(xml)

    def get_service_capabilities(self, service: str) -> dict[str, Any]:
        """Return the parsed ``GetServiceCapabilities`` response for ``service`` (``media`` resolves to Media or Media2 automatically)."""
        resolved = service
        if service == "media":
            resolved, _ = self._media_service()
        xml = self.call(
            service=resolved,
            operation="GetServiceCapabilities",
            body_inner=envelopes.get_service_capabilities(resolved),
        )
        return parsers.parse_service_capabilities(xml)

    def get_relay_output_options(self, *, token: str = "") -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRelayOutputOptions`` result from the Device service, parsed by ``parsers.parse_relay_output_options`` into ``list[dict[str, Any]]``."""
        service, _ = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetRelayOutputOptions",
            body_inner=envelopes.device_get_relay_output_options(token=token),
        )
        return parsers.parse_relay_output_options(xml)

    def get_serial_ports(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetSerialPorts`` result from the Device service, parsed by ``parsers.parse_serial_ports`` into ``list[dict[str, str]]``."""
        service, _ = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetSerialPorts",
            body_inner=envelopes.device_get_serial_ports(),
        )
        return parsers.parse_serial_ports(xml)

    def get_system_uris(self) -> dict[str, Any]:
        """Return the ONVIF ``GetSystemUris`` result from the Device service, parsed by ``parsers.parse_system_uris`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetSystemUris",
            body_inner=envelopes.device_get_system_uris(),
        )
        return parsers.parse_system_uris(xml)

    def get_geo_location(self) -> list[dict[str, float | None]]:
        """Return the ONVIF ``GetGeoLocation`` result from the Device service, parsed by ``parsers.parse_geo_location`` into ``list[dict[str, float | None]]``."""
        xml = self.call(
            service="device",
            operation="GetGeoLocation",
            body_inner=envelopes.device_get_geo_location(),
        )
        return parsers.parse_geo_location(xml)

    def set_geo_location(self, *, lon: float, lat: float, elevation: float = 0.0) -> None:
        """Send the ONVIF ``SetGeoLocation`` request to the Device service."""
        self.call(
            service="device",
            operation="SetGeoLocation",
            body_inner=envelopes.device_set_geo_location(lon=lon, lat=lat, elevation=elevation),
        )

    def get_wsdl_url(self) -> str:
        """Return the ONVIF ``GetWsdlUrl`` result from the Device service, parsed by ``parsers.parse_text_element`` into ``str``."""
        xml = self.call(
            service="device",
            operation="GetWsdlUrl",
            body_inner=envelopes.device_get_wsdl_url(),
        )
        return parsers.parse_text_element(xml, "Url")

    def get_zero_configuration(self) -> dict[str, Any]:
        """Return the device's zero-configuration (link-local) interface and addresses."""
        xml = self.call(
            service="device",
            operation="GetZeroConfiguration",
            body_inner=envelopes.device_get_zero_configuration(),
        )
        return parsers.parse_zero_configuration(xml)

    def get_endpoint_reference(self) -> str:
        """Return the device's WS-Discovery endpoint reference GUID."""
        xml = self.call(
            service="device",
            operation="GetEndpointReference",
            body_inner=envelopes.device_get_endpoint_reference(),
        )
        return parsers.parse_text_element(xml, "GUID")

    def get_storage_configurations(self) -> list[dict[str, Any]]:
        """Return the device's configured storage targets (NFS/CIFS/local paths)."""
        xml = self.call(
            service="device",
            operation="GetStorageConfigurations",
            body_inner=envelopes.device_get_storage_configurations(),
        )
        return parsers.parse_storage_configurations(xml)

    def start_firmware_upgrade(self) -> dict[str, str]:
        """Begin a firmware upgrade and return where to upload the image.

        The device replies with ``upload_uri``, ``upload_delay`` and ``expected_down_time``;
        POST the firmware image to ``upload_uri`` yourself after waiting ``upload_delay``.
        This reboots the device — there is no undo.
        """
        xml = self.call(
            service="device",
            operation="StartFirmwareUpgrade",
            body_inner=envelopes.device_start_firmware_upgrade(),
        )
        return parsers.parse_upload_target(xml)

    def start_system_restore(self) -> dict[str, str]:
        """Begin a system restore and return where to upload the backup file.

        Same shape as :meth:`start_firmware_upgrade`: POST the backup to ``upload_uri``.
        This overwrites the device's configuration.
        """
        xml = self.call(
            service="device",
            operation="StartSystemRestore",
            body_inner=envelopes.device_start_system_restore(),
        )
        return parsers.parse_upload_target(xml)
