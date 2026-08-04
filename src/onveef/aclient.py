"""The asyncio ONVIF client.

:class:`AsyncOnvifClient` is assembled from the transport core in
:mod:`onveef.atransport` and one mixin per ONVIF service in :mod:`onveef.aops`, mirroring
the layout — and the full operation set — of :mod:`onveef.client`.
"""

from __future__ import annotations

from onveef.aops.accesscontrol import AccessControlOperations
from onveef.aops.analytics import AnalyticsOperations
from onveef.aops.device import DeviceOperations
from onveef.aops.events import AsyncPullPointSubscription, EventOperations
from onveef.aops.imaging import ImagingOperations
from onveef.aops.media import MediaOperations
from onveef.aops.ptz import PtzOperations
from onveef.aops.recording import RecordingOperations
from onveef.atransport import AsyncTransport

__all__ = [
    "AsyncOnvifClient",
    "AsyncPullPointSubscription",
    "AsyncTransport",
]


class AsyncOnvifClient(
    DeviceOperations,
    MediaOperations,
    PtzOperations,
    ImagingOperations,
    EventOperations,
    AnalyticsOperations,
    RecordingOperations,
    AccessControlOperations,
):
    """An asyncio ONVIF client for a single device, mirroring :class:`~onveef.client.OnvifClient`.

    The quick way to connect is just host/port/username/password — service endpoints are
    discovered automatically on first use::

        async with AsyncOnvifClient("192.168.1.64", 80, "admin", "secret") as cam:
            print(await cam.get_device_information())
            for profile in await cam.get_profiles():
                print(await cam.get_stream_uri(profile_token=profile["token"]))

    For full control you may instead pass a pre-built ``endpoint=`` (and ``credentials=``);
    in that mode auto-discovery is off by default and you manage the service map yourself.

    Args mirror :class:`~onveef.client.OnvifClient` exactly; see its documentation for the
    meaning of every parameter.
    """
