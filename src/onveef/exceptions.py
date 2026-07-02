from __future__ import annotations


class OnvifError(Exception):
    """Base class for every error raised by onveef.

    Attributes:
        status_code: A suggested HTTP status code, handy when surfacing the error
            through a web API.
        code: A stable, machine-readable error slug.
        retryable: ``True`` when the failure is transient and the same request may
            succeed if retried (timeouts, ``503``, connection resets). ``False`` for
            deterministic failures such as auth, faults, or a missing capability.
    """

    status_code = 502
    code = "onvif_error"
    retryable = False


class OnvifNotConfiguredError(OnvifError):
    """The client is missing something it needs to make the call (e.g. no endpoint)."""

    status_code = 409
    code = "onvif_not_configured"


class OnvifAuthError(OnvifError):
    """Authentication/authorisation failed (HTTP 401 or a ``NotAuthorized`` fault)."""

    status_code = 401
    code = "onvif_unauthorized"


class OnvifServiceUnavailableError(OnvifError):
    """The device is up but temporarily cannot serve the request (HTTP 503). Retryable."""

    status_code = 503
    code = "onvif_service_unavailable"
    retryable = True


class OnvifFaultError(OnvifError):
    """The device returned a SOAP fault that is not auth- or capability-related."""

    status_code = 502
    code = "onvif_fault"


class OnvifTransportError(OnvifError):
    """A network/HTTP-level failure (connection error, unexpected status, oversized body).

    Instances may be flagged ``retryable=True`` when the underlying cause is transient.
    """

    status_code = 502
    code = "onvif_transport"

    def __init__(self, *args: object, retryable: bool = False) -> None:
        super().__init__(*args)
        self.retryable = retryable


class OnvifTimeoutError(OnvifTransportError):
    """A connect/read/write/pool timeout. Always retryable."""

    status_code = 504
    code = "onvif_timeout"

    def __init__(self, *args: object, retryable: bool = True) -> None:
        super().__init__(*args, retryable=retryable)


class OnvifCapabilityMissingError(OnvifError):
    """The device does not advertise the ONVIF service/capability the call needs."""

    status_code = 409
    code = "onvif_capability_missing"


class OnvifOperationNotSupportedError(OnvifError):
    """The device advertises the service but does not implement this (often optional) operation."""

    status_code = 501
    code = "onvif_operation_not_supported"
