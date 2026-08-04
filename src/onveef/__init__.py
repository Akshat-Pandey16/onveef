from __future__ import annotations

from onveef import breaker, envelopes, exceptions, models, pacs, parsers, urls, wsdiscovery
from onveef.aclient import AsyncOnvifClient, AsyncPullPointSubscription
from onveef.client import (
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
    OnvifCallResult,
    OnvifClient,
    OnvifCredentials,
    OnvifEndpoint,
    PullPointSubscription,
    fetch_snapshot_bytes,
)
from onveef.exceptions import (
    OnvifAuthError,
    OnvifCapabilityMissingError,
    OnvifError,
    OnvifFaultError,
    OnvifNotConfiguredError,
    OnvifOperationNotSupportedError,
    OnvifServiceUnavailableError,
    OnvifTimeoutError,
    OnvifTransportError,
)
from onveef.wsdiscovery import DiscoveredDevice

__version__ = "0.6.0"

__all__ = (
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_USER_AGENT",
    "AsyncOnvifClient",
    "AsyncPullPointSubscription",
    "DiscoveredDevice",
    "OnvifAuthError",
    "OnvifCallResult",
    "OnvifCapabilityMissingError",
    "OnvifClient",
    "OnvifCredentials",
    "OnvifEndpoint",
    "OnvifError",
    "OnvifFaultError",
    "OnvifNotConfiguredError",
    "OnvifOperationNotSupportedError",
    "OnvifServiceUnavailableError",
    "OnvifTimeoutError",
    "OnvifTransportError",
    "PullPointSubscription",
    "__version__",
    "breaker",
    "envelopes",
    "exceptions",
    "fetch_snapshot_bytes",
    "models",
    "pacs",
    "parsers",
    "urls",
    "wsdiscovery",
)
