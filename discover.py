import asyncio
import json
import socket

DISCOVERY_PORT = 38899
DISCOVERY_MESSAGE = '{"method":"getSystemConfig","params":{}}'

def get_broadcast_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()
    # Extract first three octets
    ip_parts = local_ip.split('.')
    broadcast_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"
    return broadcast_ip

class WizDiscoveryProtocol:
    def __init__(self):
        self.devices = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        ip = addr[0]
        if any(d['ip'] == ip for d in self.devices):
            return  # Avoid duplicates
        try:
            msg = data.decode()
            resp = json.loads(msg)
            params = resp.get("result", {})
            name = params.get("moduleName") or params.get("mac") or ""
            self.devices.append({"name":name,"ip": ip})
        except Exception:
            pass

    def error_received(self, exc):
        pass

    def connection_lost(self, exc):
        pass

async def send_discovery_broadcast(broadcast_ip, protocol, transport):
    transport.sendto(DISCOVERY_MESSAGE.encode(), (broadcast_ip, DISCOVERY_PORT))

async def discover_wiz(retries=3, wait_between=1.0, timeout=5.0):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        WizDiscoveryProtocol,
        local_addr=('0.0.0.0', 0),
        allow_broadcast=True
    )
    broadcast_ip = get_broadcast_ip()
    try:
        for _ in range(retries):
            await send_discovery_broadcast(broadcast_ip, protocol, transport)
            await asyncio.sleep(wait_between)
        # Wait extra time to receive late responses
        await asyncio.sleep(timeout - retries * wait_between)
    finally:
        transport.close()
    
    return protocol.devices

def run_discover():
    return asyncio.run(discover_wiz())

if __name__ == "__main__":
    devices = run_discover()