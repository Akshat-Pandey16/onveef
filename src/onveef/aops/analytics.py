"""Analytics operations for the asyncio ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import envelopes, parsers
from onveef.atransport import AsyncTransport


class AnalyticsOperations(AsyncTransport):
    """Analytics operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def analytics_get_supported_rules(
        self, *, configuration_token: str
    ) -> list[dict[str, Any]]:
        """Return the analytics rules supported by a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetSupportedRules",
            body_inner=envelopes.analytics_get_supported_rules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_supported_rules(xml)

    async def analytics_get_rules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the analytics rules configured on a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetRules",
            body_inner=envelopes.analytics_get_rules(configuration_token=configuration_token),
        )
        return parsers.parse_rules(xml)

    async def analytics_get_supported_modules(
        self, *, configuration_token: str
    ) -> list[dict[str, Any]]:
        """Return the analytics modules supported by a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetSupportedAnalyticsModules",
            body_inner=envelopes.analytics_get_supported_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_supported_analytics_modules(xml)

    async def analytics_get_modules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the analytics modules configured on a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetAnalyticsModules",
            body_inner=envelopes.analytics_get_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_analytics_modules(xml)

    async def create_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Create analytics modules on a configuration."""
        await self.call(
            service="analytics",
            operation="CreateAnalyticsModules",
            body_inner=envelopes.analytics_create_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    async def modify_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Modify analytics modules on a configuration."""
        await self.call(
            service="analytics",
            operation="ModifyAnalyticsModules",
            body_inner=envelopes.analytics_modify_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    async def delete_analytics_modules(self, *, configuration_token: str, names: list[str]) -> None:
        """Delete named analytics modules from a configuration."""
        await self.call(
            service="analytics",
            operation="DeleteAnalyticsModules",
            body_inner=envelopes.analytics_delete_analytics_modules(
                configuration_token=configuration_token, names=names
            ),
        )

    async def create_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Create analytics rules on a configuration."""
        await self.call(
            service="analytics",
            operation="CreateRules",
            body_inner=envelopes.analytics_create_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    async def modify_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Modify analytics rules on a configuration."""
        await self.call(
            service="analytics",
            operation="ModifyRules",
            body_inner=envelopes.analytics_modify_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    async def delete_rules(self, *, configuration_token: str, names: list[str]) -> None:
        """Delete named analytics rules from a configuration."""
        await self.call(
            service="analytics",
            operation="DeleteRules",
            body_inner=envelopes.analytics_delete_rules(
                configuration_token=configuration_token, names=names
            ),
        )
