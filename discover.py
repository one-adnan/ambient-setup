"""
WiZ bulb discovery over UDP (port 38899).

Why this is more reliable than a single broadcast:
  * Finds *every* local IPv4 address (Windows often has extra adapters such as
    WSL / Hyper-V / VPN) and broadcasts from a socket bound to each of them,
    so the packet actually leaves through the interface your bulbs are on.
  * Sends to both the global broadcast (255.255.255.255) and each /24 subnet
    broadcast, and keeps re-sending for the whole window (UDP gets dropped).
  * Sends two different request types that WiZ firmware answers to.
  * If broadcast finds nothing (or fewer bulbs than expected), falls back to
    a unicast sweep of the local /24 subnets, which works even when the
    router filters broadcast traffic.
  * Bulbs are identified by MAC, so a saved setup survives DHCP IP changes.

Run directly to list bulbs:  python discover.py
"""

import ipaddress
import json
import select
import socket
import sys
import time

PORT = 38899

_PROBE = json.dumps({"method": "getSystemConfig", "params": {}}).encode()
_REGISTER = json.dumps({
    "method": "registration",
    "params": {"phoneMac": "AAAAAAAAAAAA", "register": False,
               "phoneIp": "1.2.3.4", "id": "1"},
}).encode()
_DISCOVERY_MSGS = (_PROBE, _REGISTER)


# -------------------
# Local network helpers
# -------------------
def local_ipv4s():
    """All usable local IPv4 addresses, primary (default-route) one first."""
    ips = []

    def add(ip):
        if ip and not ip.startswith(("127.", "169.254.", "0.")) and ip not in ips:
            ips.append(ip)

    # UDP connect() sends nothing; it just asks the OS which interface it would use.
    for target in ("8.8.8.8", "10.255.255.255", "192.168.255.255", "172.31.255.255"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            add(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except socket.gaierror:
        pass
    return ips


def _subnet24(ip):
    return ipaddress.ip_network(f"{ip}/24", strict=False)


def _make_socket(bind_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if sys.platform == "win32" and hasattr(socket, "SIO_UDP_CONNRESET"):
        # Stop Windows from raising ConnectionResetError on ICMP "port unreachable"
        # replies (common during the unicast sweep).
        try:
            s.ioctl(socket.SIO_UDP_CONNRESET, False)
        except (OSError, ValueError):
            pass
    s.bind((bind_ip, 0))
    s.setblocking(False)
    return s


def _open_sockets(ips):
    """One socket per local interface plus a wildcard one: [(sock, bind_ip), ...]."""
    socks = []
    for ip in list(ips) + ["0.0.0.0"]:
        try:
            socks.append((_make_socket(ip), ip))
        except OSError:
            pass
    return socks


def _close(socks):
    for s, _ in socks:
        try:
            s.close()
        except OSError:
            pass


def _send(sock, payload, ip):
    try:
        sock.sendto(payload, (ip, PORT))
    except OSError:
        pass  # unreachable/busy interface; other sockets will cover it


# -------------------
# Response handling
# -------------------
def _parse(data):
    """Return (mac, module_name) from a bulb reply, or None for anything else."""
    try:
        resp = json.loads(data.decode("utf-8", errors="ignore"))
    except ValueError:
        return None
    result = resp.get("result") if isinstance(resp, dict) else None
    if not isinstance(result, dict) or not result.get("mac"):
        return None
    return str(result["mac"]).lower(), result.get("moduleName", "")


def _collect(socks, found, until):
    """Read replies into `found` (mac -> device) until `until`. Returns True if a new bulb appeared."""
    new = False
    raw = [s for s, _ in socks]
    while True:
        remaining = until - time.monotonic()
        if remaining <= 0:
            return new
        try:
            readable, _, _ = select.select(raw, [], [], remaining)
        except (OSError, ValueError):
            return new
        if not readable:
            return new
        for s in readable:
            while True:
                try:
                    data, addr = s.recvfrom(4096)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                parsed = _parse(data)
                if not parsed:
                    continue
                mac, name = parsed
                if mac not in found:
                    found[mac] = {"mac": mac, "ip": addr[0], "name": name}
                    new = True
                else:
                    found[mac]["ip"] = addr[0]
                    if name and not found[mac]["name"]:
                        found[mac]["name"] = name   # only some reply types include the model name


# -------------------
# Public API
# -------------------
def discover(timeout=4.0, expected=None, sweep=True, verbose=False):
    """
    Find WiZ bulbs on the local network.

    timeout  : seconds to spend broadcasting
    expected : stop as soon as this many bulbs have answered
    sweep    : unicast-scan local /24 subnets if broadcast finds too few
    Returns a list of {"mac", "ip", "name"} sorted by IP.
    """
    ips = local_ipv4s()
    if verbose:
        print(f"  local addresses: {', '.join(ips) or 'none found'}")
    socks = _open_sockets(ips)
    if not socks:
        return []

    targets = {"255.255.255.255"} | {str(_subnet24(ip).broadcast_address) for ip in ips}
    found = {}
    try:
        start = time.monotonic()
        end = start + timeout
        last_new = start
        while time.monotonic() < end:
            for s, bind_ip in socks:
                if bind_ip == "0.0.0.0":
                    dests = targets
                else:
                    dests = ("255.255.255.255", str(_subnet24(bind_ip).broadcast_address))
                for dest in dests:
                    for msg in _DISCOVERY_MSGS:
                        _send(s, msg, dest)

            if _collect(socks, found, min(end, time.monotonic() + 0.4)):
                last_new = time.monotonic()

            now = time.monotonic()
            if expected and len(found) >= expected:
                break
            # Without a target count, stop once replies have settled down.
            if not expected and found and now - last_new > 1.5 and now - start > 2.0:
                break

        too_few = not found or (expected and len(found) < expected)
        if sweep and too_few:
            if verbose:
                print("  broadcast found too few bulbs, scanning subnet directly...")
            _sweep(socks, ips, found)
    finally:
        _close(socks)

    return sorted(found.values(), key=lambda d: ipaddress.ip_address(d["ip"]))


def _sweep(socks, ips, found, rounds=2, wait=1.5):
    by_ip = {bind_ip: s for s, bind_ip in socks}
    fallback = by_ip.get("0.0.0.0") or socks[0][0]
    for _ in range(rounds):
        for ip in ips:
            s = by_ip.get(ip, fallback)
            for n, host in enumerate(_subnet24(ip).hosts()):
                if str(host) == ip:
                    continue
                _send(s, _PROBE, str(host))
                if n % 32 == 31:
                    _collect(socks, found, time.monotonic() + 0.005)  # drain + don't flood
        _collect(socks, found, time.monotonic() + wait)


def probe(ips, timeout=1.5):
    """Ask specific IPs directly. Returns {mac: device} for those that answered."""
    found = {}
    socks = _open_sockets(["0.0.0.0"])
    if not socks:
        return found
    try:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for ip in ips:
                _send(socks[0][0], _PROBE, ip)
            _collect(socks, found, min(end, time.monotonic() + 0.3))
            if all(any(d["ip"] == ip for d in found.values()) for ip in ips):
                break
    finally:
        _close(socks)
    return found


def run_discover():
    """Backwards-compatible helper."""
    return discover()


if __name__ == "__main__":
    print("Searching for WiZ bulbs...")
    devices = discover(verbose=True)
    if not devices:
        print("No bulbs found.")
    for d in devices:
        print(f"  {d['ip']:<15}  mac={d['mac']}  {d['name']}")
