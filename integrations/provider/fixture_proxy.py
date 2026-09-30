"""Docker verification fixture, mounted only by the disposable smoke script.

Production has no test-provider switch. This trusted harness injects socket-pair
transport into the exact proxy implementation, and a second production resolver
listener proves private-address denial against the container's /etc/hosts.
"""

from __future__ import annotations

import argparse
import os
import socket
import threading

from provider_proxy import Address, ProviderProxy, ProxyPolicy

HOST = "provider.fixture.invalid"


def connector(address: Address, timeout: float) -> socket.socket:
    assert address == Address(socket.AF_INET, "8.8.8.8")
    upstream, origin = socket.socketpair()
    origin.settimeout(timeout)

    def echo() -> None:
        with origin:
            try:
                while data := origin.recv(16384):
                    origin.sendall(data)
            except OSError:
                pass

    threading.Thread(target=echo, daemon=True).start()
    return upstream


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-disposable-stack", action="store_true", required=True
    )
    parser.parse_args()
    assert os.environ["FAILURELENS_PROVIDER_PROXY_HOST"] == HOST
    policy = ProxyPolicy(HOST)
    proxy = ProviderProxy(
        policy,
        resolver=lambda _: [Address(socket.AF_INET, "8.8.8.8")],
        connector=connector,
    )
    with (
        socket.create_server(("0.0.0.0", 8080)) as allowed,
        socket.create_server(("0.0.0.0", 8081)) as denied,
    ):
        threading.Thread(
            target=ProviderProxy(policy).serve, args=(denied,), daemon=True
        ).start()
        proxy.serve(allowed)


if __name__ == "__main__":
    main()
