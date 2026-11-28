"""Process-local DoH for Telegram and Studio tunnel names only.

The TUN resolver can return stale fake IPs. Preserve hostnames and TLS/SNI;
replace only getaddrinfo results for the affected endpoints.
"""
import json
import socket
import threading
import time
import urllib.parse
import urllib.request


def doh_addresses(host):
    request = urllib.request.Request(
        "https://dns.google/resolve?" + urllib.parse.urlencode({"name": host, "type": "A"}),
        headers={"Accept": "application/dns-json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=8) as response:
        data = json.load(response)
    addresses = [entry["data"] for entry in data.get("Answer", []) if entry.get("type") == 1]
    if not addresses:
        raise socket.gaierror("DoH returned no addresses")
    return addresses


def make_resolver(resolve, original):
    cache = {}
    lock = threading.RLock()

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        name = host.decode() if isinstance(host, bytes) else host
        target = name == "api.telegram.org" or (
            isinstance(name, str) and name.endswith((".free.pinggy.net", ".run.pinggy-free.link"))
        )
        if not target:
            return original(host, port, family, type, proto, flags)
        with lock:
            current = cache.get(name)
            if not current or current[0] < time.monotonic():
                try:
                    addresses = resolve(name)
                    cache[name] = (time.monotonic() + 120, addresses)
                except Exception:
                    if current:
                        addresses = current[1]
                    else:
                        return original(host, port, family, type, proto, flags)
            else:
                addresses = current[1]
        results = []
        if family in (0, socket.AF_INET):
            for address in addresses:
                results.extend(original(address, port, socket.AF_INET, type, proto, flags))
        if not results:
            raise socket.gaierror("No address in requested family")
        return results

    return getaddrinfo


def install():
    if not getattr(socket.getaddrinfo, "_voidfeed_dns", False):
        lookup = make_resolver(doh_addresses, socket.getaddrinfo)
        lookup._voidfeed_dns = True
        socket.getaddrinfo = lookup


if __name__ == "__main__":
    import runpy
    import sys
    install()
    target = sys.argv[1]
    sys.argv = sys.argv[1:]
    runpy.run_path(target, run_name="__main__")
