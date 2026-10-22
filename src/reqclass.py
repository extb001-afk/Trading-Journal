from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

import settings_store as ss

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

__all__ = ["PROXY_HDRS", "BEHIND_PROXY", "mark_conn", "proxied", "loopback_unmarked", "direct_loopback", "client_ip", "bucket_of",
           "proxied_https", "setup_allowed", "client_allowed", "setup_client_ok"]

PROXY_HDRS = ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "Forwarded", "X-Real-Ip", "Via", "Cdn-Loop",
              "Cf-Connecting-Ip", "Cf-Ray", "Cf-Visitor", "Cf-Warp-Tag-Id", "True-Client-Ip")
_PROXY_PREFIX = ("cf-", "x-forwarded-", "tailscale-")
_PROXY_HDRS = PROXY_HDRS
BEHIND_PROXY = False


def _ip(s):
    try:
        a = ipaddress.ip_address((s or "").strip())
    except ValueError:
        return None
    return a.ipv4_mapped if getattr(a, "ipv4_mapped", None) else a


def _peer(h):
    return _ip(h.client_address[0] if h.client_address else "")


def _proxy_marked(hd) -> bool:
    if any(hd.get(k) is not None for k in PROXY_HDRS):
        return True
    try:
        return any(str(k).lower().startswith(_PROXY_PREFIX) for k in hd.keys())
    except Exception:   # noqa: BLE001 [fallback]
        return False


def mark_conn(h) -> None:
    try:
        if not getattr(h, "tj_conn_proxied", False) and _proxy_marked(h.headers):
            h.tj_conn_proxied = True
    except Exception:   # noqa: BLE001 [optional]
        pass


def proxied(h) -> bool:
    if BEHIND_PROXY or getattr(h, "tj_conn_proxied", False):
        return True
    return _proxy_marked(h.headers)


def loopback_unmarked(h: BaseHTTPRequestHandler) -> bool:
    p = _peer(h)
    return p is not None and p.is_loopback and not getattr(h, "tj_conn_proxied", False) and not _proxy_marked(h.headers)


def direct_loopback(h) -> bool:
    p = _peer(h)
    return bool(p is not None and p.is_loopback and not proxied(h))


def client_ip(h) -> str:
    p = _peer(h)
    if p is not None and p.is_loopback:
        xff = (h.headers.get("X-Forwarded-For") or "").split(",")[-1]
        x = _ip(xff)
        if x is not None:
            return str(x)
    return str(p) if p is not None else "?"


def _bucket(ip: str) -> str:
    a = _ip(ip)
    if a is None:
        return ip
    if a.version == 6:
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(a)


def bucket_of(h) -> str:
    p = _peer(h)
    if not (p is not None and p.is_loopback and proxied(h)):
        return _bucket(client_ip(h))
    x = _ip((h.headers.get("X-Forwarded-For") or "").split(",")[-1])
    return "p:" + _bucket(str(x)) if x is not None and not x.is_loopback else "p:?"


def proxied_https(h) -> bool:
    p = _peer(h)
    xfp = (h.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    return bool(p is not None and p.is_loopback and xfp == "https")


def _hostname(h) -> str:
    x = (h.headers.get("Host") or "").strip().lower()
    if x.startswith("["):
        return x[1:x.find("]")] if "]" in x else x
    return x.rsplit(":", 1)[0] if x.count(":") == 1 else x


def setup_allowed(h) -> bool:
    return direct_loopback(h) and _hostname(h) in ("127.0.0.1", "localhost", "::1")


_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def _setup_allow_lan() -> bool:
    try:
        return (ss.read_config_raw().get("web") or {}).get("setup_allow_lan") is True
    except Exception:   # noqa: BLE001 [fallback]
        return False


def client_allowed(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    if a.is_loopback:
        return True
    if (a.version == 4 and a in _TAILNET_V4) or (a.version == 6 and a in _TAILNET_V6):
        return True
    return bool(a.is_private) and _setup_allow_lan()


def _setup_allow_proxy() -> bool:
    try:
        return (ss.read_config_raw().get("web") or {}).get("setup_allow_proxy") is True
    except Exception:   # noqa: BLE001 [probe]
        return False


def setup_client_ok(h: BaseHTTPRequestHandler) -> bool:
    return client_allowed(h.client_address[0]) and (not proxied(h) or _setup_allow_proxy())
