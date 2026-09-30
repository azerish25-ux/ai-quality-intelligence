"""Opt-in, fixed-destination CONNECT gate; no credentials or HTTP interception.

Only trusted constructor injection can substitute DNS/socket implementations for
fixtures. The CLI exposes no bypass, private-address exception or test mode.
"""

from __future__ import annotations

import ipaddress
import os
import queue
import re
import select
import socket
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass


class ProxyDenied(Exception):
    """Deliberately carries no upstream or request detail."""


@dataclass(frozen=True)
class Address:
    family: socket.AddressFamily
    ip: str


@dataclass(frozen=True)
class ProxyPolicy:
    host: str
    concurrency: int = 2
    header_bytes: int = 4096
    direction_bytes: int = 524288
    header_seconds: float = 5
    total_seconds: float = 35

    def __post_init__(self) -> None:
        labels = self.host.split(".")
        if (
            not 1 <= len(self.host) <= 253
            or len(labels) < 2
            or any(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                for label in labels
            )
            or not re.search(r"[a-z]", labels[-1])
        ):
            raise ValueError("explicit lowercase DNS hostname required")
        if (
            type(self.concurrency) is not int
            or not 1 <= self.concurrency <= 4
            or type(self.header_bytes) is not int
            or not 128 <= self.header_bytes <= 4096
            or type(self.direction_bytes) is not int
            or not 1024 <= self.direction_bytes <= 524288
            or not 0 < self.header_seconds <= 5
            or not 0 < self.total_seconds <= 35
        ):
            raise ValueError("proxy limits outside supported bounds")

    @property
    def authority(self) -> str:
        return self.host + ":443"


def resolve(host: str) -> Sequence[Address]:
    answers = socket.getaddrinfo(
        host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return [
        Address(socket.AddressFamily(family), str(address[0]))
        for family, _, _, _, address in answers
    ]


def checked_addresses(answers: Sequence[Address]) -> list[Address]:
    if not answers or len(answers) > 16:
        raise ProxyDenied
    selected = []
    for answer in answers:
        try:
            parsed = ipaddress.ip_address(answer.ip)
        except ValueError:
            raise ProxyDenied from None
        if (
            not parsed.is_global
            or parsed.is_multicast
            or parsed.is_reserved
            or parsed.is_unspecified
            or "%" in answer.ip
            or (
                isinstance(parsed, ipaddress.IPv6Address)
                and (
                    parsed.ipv4_mapped
                    or parsed.sixtofour
                    or parsed.teredo
                    or parsed in ipaddress.IPv6Network("64:ff9b::/96")
                    or parsed in ipaddress.IPv6Network("64:ff9b:1::/48")
                )
            )
            or answer.family
            != (socket.AF_INET if parsed.version == 4 else socket.AF_INET6)
        ):
            # Reject a mixed public/private answer too; never "try the public one".
            raise ProxyDenied
        if answer not in selected:
            selected.append(answer)
    return selected


def connect(address: Address, timeout: float) -> socket.socket:
    upstream = socket.socket(address.family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    try:
        upstream.settimeout(timeout)
        # Numeric, already-vetted destination: never call create_connection or
        # re-resolve the hostname between validation and connect (DNS rebinding).
        upstream.connect((address.ip, 443))
    except BaseException:
        upstream.close()
        raise
    return upstream


def validate_header(raw: bytes, policy: ProxyPolicy) -> None:
    try:
        lines = raw.decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        raise ProxyDenied from None
    if (
        len(raw) > policy.header_bytes
        or len(lines) < 4
        or lines[0] != f"CONNECT {policy.authority} HTTP/1.1"
        or lines[-2:] != ["", ""]
    ):
        raise ProxyDenied
    seen: set[str] = set()
    for line in lines[1:-2]:
        name, separator, value = line.partition(":")
        name = name.lower()
        # httpcore emits only Host and Accept. Reject body framing, proxy auth,
        # forwarding headers, repeated Host, obs-fold and request smuggling.
        if not separator or name in seen or name not in {"host", "accept"}:
            raise ProxyDenied
        seen.add(name)
        if value != " " + (policy.authority if name == "host" else "*/*"):
            raise ProxyDenied
    if "host" not in seen:
        raise ProxyDenied


class ProviderProxy:
    def __init__(
        self,
        policy: ProxyPolicy,
        *,
        resolver: Callable[[str], Sequence[Address]] = resolve,
        connector: Callable[[Address, float], socket.socket] = connect,
        event: Callable[[str], None] | None = None,
    ) -> None:
        self.policy = policy
        self.resolver = resolver
        self.connector = connector
        self.event = event or (lambda name: print(name, file=sys.stderr, flush=True))
        self.slots = threading.BoundedSemaphore(policy.concurrency)
        self.dns_slots = threading.BoundedSemaphore(policy.concurrency)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return remaining

    def _header(self, client: socket.socket, deadline: float) -> bytes:
        raw = bytearray()
        while b"\r\n\r\n" not in raw:
            client.settimeout(self._remaining(deadline))
            chunk = client.recv(min(1024, self.policy.header_bytes + 1 - len(raw)))
            if not chunk:
                raise ProxyDenied
            raw.extend(chunk)
            if len(raw) > self.policy.header_bytes:
                raise ProxyDenied
        return bytes(raw)

    def _resolve(self, deadline: float) -> list[Address]:
        if not self.dns_slots.acquire(blocking=False):
            raise ProxyDenied
        result: queue.Queue[list[Address] | None] = queue.Queue(maxsize=1)

        def lookup() -> None:
            try:
                result.put(checked_addresses(self.resolver(self.policy.host)))
            except (OSError, ValueError, ProxyDenied):
                result.put(None)
            finally:
                # A timed-out caller does not free a still-running resolver's
                # permit. At most concurrency DNS threads can remain stuck.
                self.dns_slots.release()

        threading.Thread(target=lookup, daemon=True).start()
        try:
            addresses = result.get(timeout=self._remaining(deadline))
        except queue.Empty:
            raise TimeoutError from None
        if addresses is None:
            raise ProxyDenied
        return addresses

    def _relay(
        self, client: socket.socket, upstream: socket.socket, deadline: float
    ) -> None:
        counters = {client: 0, upstream: 0}
        while True:
            ready, _, _ = select.select(
                [client, upstream], [], [], self._remaining(deadline)
            )
            for source in ready:
                source.settimeout(self._remaining(deadline))
                data = source.recv(16384)
                if not data:
                    return
                counters[source] += len(data)
                if counters[source] > self.policy.direction_bytes:
                    raise ProxyDenied
                target = upstream if source is client else client
                target.settimeout(self._remaining(deadline))
                target.sendall(data)

    def handle(self, client: socket.socket) -> None:
        """Run one accepted connection; caller owns the bounded admission slot."""
        connected = False
        try:
            started = time.monotonic()
            deadline = started + self.policy.total_seconds
            validate_header(
                self._header(
                    client, min(deadline, started + self.policy.header_seconds)
                ),
                self.policy,
            )
            addresses = self._resolve(deadline)
            # No fallback/retry: even connection establishment can be ambiguous.
            with self.connector(addresses[0], self._remaining(deadline)) as upstream:
                client.settimeout(self._remaining(deadline))
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                connected = True
                self._relay(client, upstream, deadline)
            self.event("provider_proxy_closed")
        except (OSError, ValueError, ProxyDenied):
            if not connected:
                try:
                    # Error reporting must not extend an expired wall deadline.
                    client.setblocking(False)
                    client.sendall(
                        b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                except OSError:
                    pass
            self.event("provider_proxy_denied")
        finally:
            client.close()

    def dispatch(self, client: socket.socket) -> bool:
        if not self.slots.acquire(blocking=False):
            client.close()
            self.event("provider_proxy_busy")
            return False

        def run() -> None:
            try:
                self.handle(client)
            finally:
                self.slots.release()

        threading.Thread(target=run, daemon=True).start()
        return True

    def serve(
        self, listener: socket.socket, stop: threading.Event | None = None
    ) -> None:
        stop = stop or threading.Event()
        listener.settimeout(0.2)
        self.event("provider_proxy_started")
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            self.dispatch(client)


def main() -> None:
    try:
        policy = ProxyPolicy(host=os.environ.get("FAILURELENS_PROVIDER_PROXY_HOST", ""))
    except ValueError:
        raise SystemExit("provider_proxy_invalid_configuration") from None
    # No proxy variables, credentials, HTTP headers or CA environment variables
    # are consumed. TLS passes through and is verified by the provider client.
    with socket.create_server(("0.0.0.0", 8080), backlog=8) as listener:
        ProviderProxy(policy).serve(listener)


if __name__ == "__main__":
    main()
