"""Analytics operations for the synchronous ONVIF client."""

from __future__ import annotations

from typing import Any

from onveef import envelopes, parsers
from onveef.transport import (
    SyncTransport,
)


class AnalyticsOperations(SyncTransport):
    """Analytics operations, mixed into :class:`~onveef.client.OnvifClient`."""

    def analytics_get_supported_rules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the rule types this configuration supports, with their parameters.

        Each dict carries ``name`` (the rule type), ``fixed``, ``max_instances``,
        ``parameters`` (parameter name to XSD type) and ``messages`` (the events it
        emits) — a *description* of what you may create, not the rules in force. Read
        those with :meth:`analytics_get_rules`.
        """
        xml = self.call(
            service="analytics",
            operation="GetSupportedRules",
            body_inner=envelopes.analytics_get_supported_rules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_supported_rules(xml)

    def analytics_get_rules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRules`` result from the Analytics service, parsed by ``parsers.parse_rules`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="analytics",
            operation="GetRules",
            body_inner=envelopes.analytics_get_rules(configuration_token=configuration_token),
        )
        return parsers.parse_rules(xml)

    def analytics_get_supported_modules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the analytics module types this configuration supports.

        The module counterpart of :meth:`analytics_get_supported_rules`: what the camera
        can run, described by parameter name and type, rather than what it is running.
        """
        xml = self.call(
            service="analytics",
            operation="GetSupportedAnalyticsModules",
            body_inner=envelopes.analytics_get_supported_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_supported_analytics_modules(xml)

    def analytics_get_modules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAnalyticsModules`` result from the Analytics service, parsed by ``parsers.parse_analytics_modules`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="analytics",
            operation="GetAnalyticsModules",
            body_inner=envelopes.analytics_get_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_analytics_modules(xml)

    def create_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Send the ONVIF ``CreateAnalyticsModules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="CreateAnalyticsModules",
            body_inner=envelopes.analytics_create_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    def modify_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Send the ONVIF ``ModifyAnalyticsModules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="ModifyAnalyticsModules",
            body_inner=envelopes.analytics_modify_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    def delete_analytics_modules(self, *, configuration_token: str, names: list[str]) -> None:
        """Send the ONVIF ``DeleteAnalyticsModules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="DeleteAnalyticsModules",
            body_inner=envelopes.analytics_delete_analytics_modules(
                configuration_token=configuration_token, names=names
            ),
        )

    def create_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Send the ONVIF ``CreateRules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="CreateRules",
            body_inner=envelopes.analytics_create_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    def modify_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Send the ONVIF ``ModifyRules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="ModifyRules",
            body_inner=envelopes.analytics_modify_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    def delete_rules(self, *, configuration_token: str, names: list[str]) -> None:
        """Send the ONVIF ``DeleteRules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="DeleteRules",
            body_inner=envelopes.analytics_delete_rules(
                configuration_token=configuration_token, names=names
            ),
        )
