"""URL validators for the Web client, which calls one on every URL before requesting it.

A validator is a callable taking a URL that raises BlockedURL to refuse it (any return value is
ignored). The Web client calls it on each URL it requests, including robots.txt, Wayback Machine
and Google Drive URLs, and each redirect target before following it. The default allows
everything.

public_only is a ready-made validator for running on a server, against server-side request
forgery: it refuses URLs whose host resolves to a private, loopback, link-local, multicast,
reserved or cloud metadata address. It checks the addresses the host resolves to when it's
called, and the request resolves the host again, so a DNS server that answers differently the
second time (DNS rebinding) can get past it; block those addresses at the network level too.
"""

import ipaddress
import socket
import urllib.error
from urllib.parse import urlsplit

# Cloud instance metadata services: AWS, GCP and Azure (IPv4 and AWS's IPv6), AWS ECS task
# metadata, and Alibaba Cloud. Most are also link-local, private or shared addresses.
METADATA = {ipaddress.ip_address(a) for a in ("169.254.169.254", "fd00:ec2::254", "169.254.170.2", "100.100.100.200")}
NAT64 = ipaddress.ip_network("64:ff9b::/96")


class BlockedURL(urllib.error.URLError):
    """A URL refused by the Web client's URL validator. The Web client doesn't retry it."""

    def __init__(self, url, reason):
        super().__init__(reason)
        self.url = url

    def __str__(self):
        return f"blocked {self.url}: {self.reason}"


def allow_all(url):
    """The default validator: allows every URL."""


def blocked_address(ip):
    """Whether ip is a private, loopback, link-local, multicast, reserved or metadata address, or an
    IPv6 address that embeds one (IPv4-mapped, 6to4 or NAT64)."""
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and ip in NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None and blocked_address(embedded):
            return True
    return (
        ip in METADATA
        or not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def public_only(url):
    """Refuse url unless it's http or https and every address its host resolves to is public.

    Non-public includes cloud metadata services such as 169.254.169.254 (AWS, GCP and Azure
    instances), 169.254.170.2 (AWS ECS task metadata and credentials) and fd00:ec2::254.

    Raises BlockedURL, or URLError if the host can't be resolved.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedURL(url, "only http and https URLs with a host are allowed")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise BlockedURL(url, "invalid port") from None
    try:
        infos = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as e:
        raise urllib.error.URLError(f"can't resolve {parts.hostname}: {e}") from None
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if blocked_address(ip):
            raise BlockedURL(url, f"{parts.hostname} resolves to a non-public address ({ip})")
