"""Synthetic socket-pair tests; never resolve or connect to a real provider."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import replace

import pytest
from failurelens.provider_proxy import (
    Address,
    ProviderProxy,
    ProxyDenied,
    ProxyPolicy,
    checked_addresses,
    connect,
    validate_header,
)

POLICY = ProxyPolicy("provider.example")
PUBLIC = Address(socket.AF_INET, "8.8.8.8")
HEADER = b"CONNECT provider.example:443 HTTP/1.1\r\nHost: provider.example:443\r\nAccept: */*\r\n\r\n"


@pytest.mark.parametrize(
    "host",
    [
        "",
        "localhost",
        "127.0.0.1",
        "8.8.8.8",
        "::1",
        "example.com.",
        "UPPER.example",
        "example.com:443",
        "evil@provider.example",
        "-a.example",
        "a..example",
        "a/example",
        "a\\example.com",
        "a.example\n",
    ],
)
def test_policy_rejects_ambiguous_authority(host: str) -> None:
    with pytest.raises(ValueError):
        ProxyPolicy(host)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.2",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "198.18.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:8.8.8.8",
        "2002:0808:0808::1",
        "64:ff9b::7f00:1",
        "64:ff9b::a00:1",
        "64:ff9b:1::7f00:1",
        "fe80::1%eth0",
        "not-an-ip",
    ],
)
def test_nonpublic_mixed_dns_denied(ip: str) -> None:
    candidate = Address(socket.AF_INET6 if ":" in ip else socket.AF_INET, ip)
    with pytest.raises(ProxyDenied):
        checked_addresses([PUBLIC, candidate])


def test_empty_excessive_and_mismatched_dns_denied() -> None:
    for answers in [[], [PUBLIC] * 17, [Address(socket.AF_INET6, PUBLIC.ip)]]:
        with pytest.raises(ProxyDenied):
            checked_addresses(answers)
    assert checked_addresses([PUBLIC, PUBLIC]) == [PUBLIC]
    ipv6 = Address(socket.AF_INET6, "2606:4700:4700::1111")
    assert checked_addresses([ipv6]) == [ipv6]


@pytest.mark.parametrize(
    "raw",
    [
        HEADER.replace(b"CONNECT ", b"GET https://"),
        HEADER.replace(b"provider.example:443", b"other.example:443"),
        HEADER.replace(b"provider.example:443", b"provider.example:80"),
        HEADER.replace(b"provider.example:443", b"provider.example.:443"),
        HEADER.replace(b"provider.example:443", b"provider.example@evil.example:443"),
        HEADER.replace(b"provider.example:443", b"provider.example:443/evil"),
        HEADER.replace(b"provider.example:443", b"provider.example%00.evil:443"),
        HEADER.replace(b"provider.example:443", b"127.0.0.1:443"),
        HEADER.replace(b"provider.example:443", b"[::1]:443"),
        HEADER.replace(b"provider.example:443", b"PROVIDER.example:443"),
        HEADER.replace(b"HTTP/1.1", b"HTTP/1.0"),
        HEADER.replace(b"Host:", b"Host :"),
        HEADER.replace(b"Host: provider.example:443\r\n", b""),
        HEADER.replace(b"Accept: */*", b"Host: provider.example:443"),
        HEADER.replace(b"Accept: */*", b"Content-Length: 12"),
        HEADER.replace(b"Accept: */*", b"Transfer-Encoding: chunked"),
        HEADER.replace(b"Accept: */*", b"Proxy-Authorization: secret-canary-413"),
        HEADER.replace(b"Accept: */*", b"Forwarded: host=evil.example"),
        HEADER.replace(b"Accept: */*", b" Host: provider.example:443"),
        HEADER.replace(b"Accept: */*", b"Accept: */*\x00"),
        HEADER.replace(b"\r\n", b"\n"),
        HEADER + b"GET / HTTP/1.1\r\n\r\n",
        HEADER + b"\xff",
    ],
)
def test_authority_and_header_tricks_denied(raw: bytes) -> None:
    with pytest.raises(ProxyDenied):
        validate_header(raw, POLICY)


def test_exact_header_and_httpcore_minimum_accepted() -> None:
    validate_header(HEADER, POLICY)
    validate_header(HEADER.replace(b"Accept: */*\r\n", b""), POLICY)


def start(proxy: ProviderProxy) -> tuple[socket.socket, threading.Thread]:
    client, accepted = socket.socketpair()
    client.settimeout(1)
    thread = threading.Thread(target=proxy.handle, args=(accepted,), daemon=True)
    thread.start()
    return client, thread


def test_bad_authority_never_resolves_and_logs_only_fixed_event() -> None:
    events: list[str] = []

    def forbidden(host: str) -> list[Address]:
        raise AssertionError("unapproved request reached DNS")

    client, thread = start(
        ProviderProxy(POLICY, resolver=forbidden, event=events.append)
    )
    with client:
        client.sendall(
            HEADER.replace(b"provider.example", b"secret-canary-413.example")
        )
        assert b"403 Forbidden" in client.recv(4096)
    thread.join(1)
    assert not thread.is_alive()
    assert events == ["provider_proxy_denied"]


def test_private_dns_denied_before_connection() -> None:
    events: list[str] = []

    def forbidden(address: Address, timeout: float) -> socket.socket:
        raise AssertionError("private DNS answer reached connection")

    proxy = ProviderProxy(
        POLICY,
        resolver=lambda _: [PUBLIC, Address(socket.AF_INET, "127.0.0.1")],
        connector=forbidden,
        event=events.append,
    )
    client, thread = start(proxy)
    with client:
        client.sendall(HEADER)
        assert b"403 Forbidden" in client.recv(4096)
    thread.join(1)
    assert events == ["provider_proxy_denied"]


def fixture_proxy(
    policy: ProxyPolicy = POLICY,
) -> tuple[ProviderProxy, socket.socket, list[object]]:
    upstream, origin = socket.socketpair()
    origin.settimeout(1)
    calls: list[object] = []

    def resolver(host: str) -> list[Address]:
        calls.append(host)
        # A rebinding resolver would return private on the next query. There
        # must be exactly one query and a pinned numeric connector argument.
        return [PUBLIC] if len(calls) == 1 else [Address(socket.AF_INET, "127.0.0.1")]

    def connector(address: Address, timeout: float) -> socket.socket:
        calls.append(address)
        assert 0 < timeout <= policy.total_seconds
        return upstream

    return (
        ProviderProxy(
            policy, resolver=resolver, connector=connector, event=calls.append
        ),
        origin,
        calls,
    )


def test_pinned_dns_tunnel_relays_without_inspecting_or_logging_content() -> None:
    proxy, origin, calls = fixture_proxy()
    client, thread = start(proxy)
    with client, origin:
        client.sendall(HEADER)
        assert b"200 Connection Established" in client.recv(4096)
        client.sendall(b"synthetic-encrypted-credential-canary")
        assert origin.recv(4096) == b"synthetic-encrypted-credential-canary"
        # Opaque TLS records can contain redirects; the proxy never interprets
        # them, resolves a Location or follows a second authority.
        origin.sendall(b"synthetic-encrypted-redirect-canary")
        assert client.recv(4096) == b"synthetic-encrypted-redirect-canary"
    thread.join(1)
    assert not thread.is_alive()
    assert calls == ["provider.example", PUBLIC, "provider_proxy_closed"]


@pytest.mark.parametrize("direction", ["request", "response"])
def test_each_tunnel_direction_has_byte_limit(direction: str) -> None:
    proxy, origin, calls = fixture_proxy(replace(POLICY, direction_bytes=1024))
    client, thread = start(proxy)
    with client, origin:
        client.sendall(HEADER)
        assert b"200 Connection Established" in client.recv(4096)
        source, target = (
            (client, origin) if direction == "request" else (origin, client)
        )
        source.sendall(b"x" * 1025)
        assert target.recv(4096) == b""
    thread.join(1)
    assert calls[-1] == "provider_proxy_denied"


def test_header_and_tunnel_deadlines_are_bounded() -> None:
    events: list[str] = []
    client, thread = start(
        ProviderProxy(replace(POLICY, header_seconds=0.03), event=events.append)
    )
    with client:
        client.sendall(b"CONNECT ")
        assert b"403 Forbidden" in client.recv(4096)
    thread.join(1)
    assert not thread.is_alive()
    assert events == ["provider_proxy_denied"]
    proxy, origin, calls = fixture_proxy(replace(POLICY, total_seconds=0.03))
    client, thread = start(proxy)
    with client, origin:
        client.sendall(HEADER)
        assert b"200 Connection Established" in client.recv(4096)
        assert client.recv(4096) == b""
    thread.join(1)
    assert not thread.is_alive()
    assert calls[-1] == "provider_proxy_denied"


def test_header_byte_limit_is_enforced_before_dns() -> None:
    events: list[str] = []
    client, thread = start(
        ProviderProxy(replace(POLICY, header_bytes=128), event=events.append)
    )
    with client:
        client.sendall(b"A" * 129)
        assert b"403 Forbidden" in client.recv(4096)
    thread.join(1)
    assert events == ["provider_proxy_denied"]


def test_blocked_dns_closes_caller_but_keeps_resolver_permit() -> None:
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    calls: list[str] = []
    events: list[str] = []

    def resolver(host: str) -> list[Address]:
        calls.append(host)
        entered.set()
        assert release.wait(2)
        exited.set()
        return [PUBLIC]

    def forbidden(address: Address, timeout: float) -> socket.socket:
        raise AssertionError("expired DNS result reached connection")

    proxy = ProviderProxy(
        replace(POLICY, concurrency=1, total_seconds=0.03),
        resolver=resolver,
        connector=forbidden,
        event=events.append,
    )
    first, first_thread = start(proxy)
    try:
        first.sendall(HEADER)
        assert entered.wait(1)
        assert b"403 Forbidden" in first.recv(4096)
        first_thread.join(1)
        assert not first_thread.is_alive()
        assert not exited.is_set()
        assert not proxy.dns_slots.acquire(blocking=False)
        # Repeated callers fail closed without creating another DNS worker.
        for _ in range(5):
            client, thread = start(proxy)
            with client:
                client.sendall(HEADER)
                assert b"403 Forbidden" in client.recv(4096)
            thread.join(1)
            assert not thread.is_alive()
        assert calls == ["provider.example"]
    finally:
        first.close()
        release.set()
    assert exited.wait(1)
    deadline = time.monotonic() + 1
    while not proxy.dns_slots.acquire(blocking=False):
        assert time.monotonic() < deadline
        time.sleep(0.001)
    proxy.dns_slots.release()
    assert events == ["provider_proxy_denied"] * 6


def test_concurrent_client_admission_is_bounded() -> None:
    proxy = ProviderProxy(replace(POLICY, concurrency=1), event=lambda _: None)
    assert proxy.slots.acquire(blocking=False)
    client, accepted = socket.socketpair()
    try:
        assert not proxy.dispatch(accepted)
        assert client.recv(1) == b""
    finally:
        client.close()
        proxy.slots.release()


def test_numeric_connect_never_resolves_again(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    class FakeSocket:
        def settimeout(self, value: float) -> None:
            calls.append(value)

        def connect(self, destination: tuple[str, int]) -> None:
            calls.append(destination)

        def close(self) -> None:
            calls.append("close")

    def constructor(*args: object) -> FakeSocket:
        calls.append(args)
        return FakeSocket()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("connector tried DNS rebinding")

    monkeypatch.setattr(socket, "socket", constructor)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    connect(PUBLIC, 0.5)
    assert calls == [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP),
        0.5,
        (PUBLIC.ip, 443),
    ]


def test_accept_loop_and_stop_use_only_local_sockets() -> None:
    events: list[str] = []
    stop = threading.Event()
    proxy = ProviderProxy(POLICY, event=events.append)
    with socket.create_server(("127.0.0.1", 0)) as listener:
        thread = threading.Thread(
            target=proxy.serve, args=(listener, stop), daemon=True
        )
        thread.start()
        with socket.create_connection(listener.getsockname(), timeout=1) as client:
            client.sendall(b"GET / HTTP/1.1\r\nHost: canary.example\r\n\r\n")
            assert b"403 Forbidden" in client.recv(4096)
        stop.set()
        thread.join(1)
    assert not thread.is_alive()
    assert events == ["provider_proxy_started", "provider_proxy_denied"]


@pytest.mark.parametrize(
    "location",
    [
        "https://other.example/completions",
        "https://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data/",
        "https://provider.example@other.example/completions",
    ],
)
def test_adapter_never_follows_redirect_or_forwards_ambient_headers(
    location: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    from failurelens.providers import HTTPModelProvider, ProviderConfig, RunBudget

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://ambient-canary.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/missing/ambient-ca-canary.pem")
    monkeypatch.setenv("Authorization", "ambient-credential-canary")
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "ambient-credential-canary" not in str(request.headers)
        return httpx.Response(
            307, headers={"Location": location}, text="response-canary-582"
        )

    provider = HTTPModelProvider(
        ProviderConfig(
            endpoint="https://provider.example/v1/chat/completions",
            model="test-fixture-not-a-model",
            token="synthetic-fixture-token",
            proxy="http://provider-proxy:8080",
            enabled=True,
            max_attempts=1,
            min_interval_seconds=0,
        ),
        transport=httpx.MockTransport(respond),
    )
    try:
        result = provider.propose(
            deterministic_category="product_defect",
            evidence=[
                {"id": "e1", "excerpt": "Observed HTTP status 500", "approved": True}
            ],
            budget=RunBudget(),
        )
        assert result.status == "fallback" and result.reason == "http_307"
        assert len(calls) == 1
        assert str(calls[0].url) == "https://provider.example/v1/chat/completions"
        assert "response-canary-582" not in str(result)
    finally:
        provider.close()


def test_actual_httpx_connect_uses_exact_gate_then_tls_without_plaintext_token() -> (
    None
):
    import httpx

    events: list[str] = []
    upstream, origin = socket.socketpair()
    origin.settimeout(2)
    proxy = ProviderProxy(
        POLICY,
        resolver=lambda _: [PUBLIC],
        connector=lambda _address, _timeout: upstream,
        event=events.append,
    )
    tls_records: list[bytes] = []

    def capture() -> None:
        with origin:
            tls_records.append(origin.recv(16384))
            # Closing without a TLS certificate must fail the client handshake.

    stop = threading.Event()
    capture_thread = threading.Thread(target=capture, daemon=True)
    capture_thread.start()
    with socket.create_server(("127.0.0.1", 0)) as listener:
        thread = threading.Thread(
            target=proxy.serve, args=(listener, stop), daemon=True
        )
        thread.start()
        try:
            with (
                httpx.Client(
                    proxy=f"http://127.0.0.1:{listener.getsockname()[1]}",
                    timeout=2,
                    trust_env=False,
                ) as client,
                pytest.raises(httpx.ConnectError),
            ):
                client.post(
                    "https://provider.example/v1/chat/completions",
                    headers={"Authorization": "Bearer plaintext-token-canary-872"},
                )
        finally:
            stop.set()
            thread.join(2)
            capture_thread.join(2)
    assert tls_records and tls_records[0][0] == 22  # TLS handshake record.
    assert b"plaintext-token-canary-872" not in tls_records[0]
    assert not thread.is_alive() and not capture_thread.is_alive()
    assert set(events) <= {
        "provider_proxy_started",
        "provider_proxy_closed",
        "provider_proxy_denied",
    }
