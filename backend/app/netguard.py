"""Offline guard. In DEMO_MODE=replay nothing may touch the network: install() makes every non-loopback
connection or DNS lookup fail at once and logs where it came from, so a forgotten call shows up in the log
and its caller falls back instead of hanging on a dead Wi-Fi."""
import logging
import socket
import traceback

log = logging.getLogger("qrwapsi.netguard")

_LOCAL_HOSTS = {"localhost", "::1", "0.0.0.0", "", "testserver"}
blocked: list[str] = []
_installed = False


def _is_local(host) -> bool:
    if host is None:
        return True
    h = host.decode() if isinstance(host, bytes) else str(host)
    return h in _LOCAL_HOSTS or h.startswith("127.")


def _refuse(target: str) -> None:
    blocked.append(target)
    log.error("OFFLINE GUARD: blocked a network call to %s (DEMO_MODE=replay)\n%s", target,
              "".join(traceback.format_stack(limit=14)[:-2]))
    raise ConnectionRefusedError(f"network access is disabled in replay mode ({target})")


def install() -> None:
    global _installed
    if _installed:
        return
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def connect(self, address):
        if isinstance(address, tuple) and not _is_local(address[0]):
            _refuse(f"{address[0]}:{address[1]}")
        return real_connect(self, address)

    def connect_ex(self, address):
        if isinstance(address, tuple) and not _is_local(address[0]):
            _refuse(f"{address[0]}:{address[1]}")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            _refuse(str(host))
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    _installed = True
    log.info("offline guard active: only loopback connections are allowed")


def status() -> dict:
    return {"active": _installed, "blocked_calls": len(blocked), "last_blocked": blocked[-5:]}
