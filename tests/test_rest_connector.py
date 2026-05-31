"""Round 176 (Phase 3): REST/Service connector safety (scenario S6).

A user-supplied API URL is an SSRF vector. These tests pin the guard rails:
only public http(s) hosts are allowed; localhost / private / link-local (incl.
the cloud-metadata endpoint) are refused; header parsing is forgiving. No
network I/O — numeric hosts resolve to themselves via getaddrinfo.
"""

from __future__ import annotations

import pytest

from ai4bi.ui.connector_panel import (
    _ip_is_blocked, validate_fetch_url, safe_fetch_json, _parse_headers,
)


@pytest.mark.parametrize("ip,blocked", [
    ("127.0.0.1", True),       # loopback
    ("10.0.0.1", True),        # private
    ("192.168.1.1", True),     # private
    ("172.16.0.1", True),      # private
    ("169.254.169.254", True), # link-local — cloud metadata SSRF target
    ("::1", True),             # ipv6 loopback
    ("0.0.0.0", True),         # unspecified
    ("8.8.8.8", False),        # public
    ("1.1.1.1", False),        # public
    ("not-an-ip", True),       # unparseable → fail closed
])
def test_ip_is_blocked(ip, blocked):
    assert _ip_is_blocked(ip) is blocked


@pytest.mark.parametrize("url", [
    "ftp://example.com/data",        # wrong scheme
    "file:///etc/passwd",            # wrong scheme
    "http://127.0.0.1/x",            # loopback
    "http://169.254.169.254/meta",   # cloud metadata
    "http://10.1.2.3/data",          # private
    "https://192.168.0.5/api",       # private
    "not-a-url",                     # no scheme/host
    "",                              # empty
])
def test_unsafe_urls_rejected(url):
    ok, reason = validate_fetch_url(url)
    assert ok is False
    assert reason  # a human-readable zh reason is given


@pytest.mark.parametrize("url", [
    "https://8.8.8.8/data.json",   # public IP (numeric → no DNS)
    "http://1.1.1.1/v1/records",
])
def test_public_urls_allowed(url):
    ok, reason = validate_fetch_url(url)
    assert ok is True
    assert reason == ""


def test_safe_fetch_json_refuses_blocked_url_before_io():
    # Must raise on validation (no socket opened) for a private address.
    with pytest.raises(ValueError):
        safe_fetch_json("http://127.0.0.1:9/should-not-connect")


def test_parse_headers():
    text = "Authorization: Bearer abc123\nX-Env: prod\n\nbad line no colon\n: novalue"
    assert _parse_headers(text) == {"Authorization": "Bearer abc123", "X-Env": "prod"}
    assert _parse_headers("") == {}
