import importlib.util
from pathlib import Path
import socket
import unittest

PATH = Path(__file__).resolve().parents[1] / "voidfeed_dns.py"


class DnsTests(unittest.TestCase):
    def test_target_host_uses_real_ip_and_preserves_port(self):
        self.assertTrue(PATH.exists(), "Missing process-scoped DNS workaround")
        spec = importlib.util.spec_from_file_location("voidfeed_dns", PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []
        def resolve(host):
            calls.append(host)
            return ["149.154.166.110"]
        lookup = module.make_resolver(resolve, socket.getaddrinfo)
        result = lookup("api.telegram.org", 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        self.assertEqual(result[0][4], ("149.154.166.110", 443))
        lookup("api.telegram.org", 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        self.assertEqual(calls, ["api.telegram.org"])
        local = lookup("127.0.0.1", 8077, socket.AF_INET, socket.SOCK_STREAM)
        self.assertEqual(local[0][4], ("127.0.0.1", 8077))
        self.assertEqual(calls, ["api.telegram.org"])


if __name__ == "__main__":
    unittest.main()
