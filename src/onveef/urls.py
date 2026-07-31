"""Helpers for repairing and decorating the URLs ONVIF devices report about themselves.

Devices routinely advertise service ``XAddr``s, subscription references and stream URIs
built from their *own* idea of their address. Behind NAT, a port forward, a Docker bridge,
or after a DHCP lease change that address is not the one you reached the device on, so
every follow-up request targets an unreachable host. :func:`rewrite_host` re-points such a
URL at the address that demonstrably works — the one you connected to.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

__all__ = (
    "UNROUTABLE_HOSTS",
    "host_of",
    "rewrite_host",
    "rewrite_service_map",
    "with_credentials",
)

UNROUTABLE_HOSTS = frozenset({"", "0.0.0.0", "::", "127.0.0.1", "localhost"})
"""Hosts a device may advertise that are never reachable from another machine."""

_HTTP_SCHEMES = frozenset({"http", "https"})


def _authority(host: str, port: int | None) -> str:
    """Join a host and optional port into a netloc, bracketing bare IPv6 literals."""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}" if port else host


def host_of(url: str) -> str:
    """Return the hostname of ``url`` without port or userinfo (``""`` if unparseable)."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def rewrite_host(url: str, reference: str) -> str:
    """Re-point ``url`` at the host that ``reference`` was reached on.

    ``reference`` is the URL you actually connected to (the device service XAddr). The
    rewrite is scheme-aware, because the two cases need different treatment:

    * **http/https URLs** — service XAddrs, subscription references and snapshot URIs are
      all served by the device's own web server, so scheme, host *and* port are taken from
      ``reference``. This is what makes port-forwarded and HTTPS-fronted devices work.
    * **any other scheme** (``rtsp``, ``rtsps``, …) — only the host is replaced; the port
      belongs to a different daemon and is kept as the device reported it.

    Userinfo, path, query and fragment are always preserved. Unparseable or relative URLs,
    and URLs already pointing at the reference host, are returned unchanged.
    """
    if not url or not reference:
        return url
    try:
        parts = urlsplit(url)
        ref = urlsplit(reference)
    except ValueError:
        return url
    if not parts.scheme or not ref.hostname:
        return url
    userinfo = ""
    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo += f":{parts.password}"
        userinfo += "@"
    if parts.scheme.lower() in _HTTP_SCHEMES:
        scheme = ref.scheme or parts.scheme
        netloc = userinfo + _authority(ref.hostname, ref.port)
    else:
        scheme = parts.scheme
        try:
            port = parts.port
        except ValueError:
            port = None
        netloc = userinfo + _authority(ref.hostname, port)
    rewritten = urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))
    return url if rewritten == url else rewritten


def rewrite_service_map(services: dict[str, str], reference: str) -> dict[str, str]:
    """Apply :func:`rewrite_host` to every XAddr in a discovered service map."""
    return {key: rewrite_host(value, reference) for key, value in services.items()}


def with_credentials(url: str, username: str, password: str = "") -> str:
    """Return ``url`` with ``username``/``password`` embedded as percent-encoded userinfo.

    This is what media consumers (ffmpeg, OpenCV, GStreamer, go2rtc) expect of the RTSP and
    snapshot URIs ONVIF hands back — ``GetStreamUri`` never includes credentials of its own.
    Reserved characters such as ``@``, ``:`` and ``/`` are escaped, so passwords that would
    corrupt a hand-built URL are handled correctly. Any userinfo already present is
    replaced; an empty ``username`` returns ``url`` unchanged.
    """
    if not url or not username:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.hostname:
        return url
    userinfo = quote(username, safe="")
    if password:
        userinfo += f":{quote(password, safe='')}"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{userinfo}@{_authority(parts.hostname, port)}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
