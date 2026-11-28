import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "studio_tunnel.py"


class TunnelTests(unittest.TestCase):
    def test_only_healthy_tunnel_is_published_and_other_settings_survive(self):
        self.assertTrue(MODULE_PATH.exists(), "Missing tunnel recovery supervisor")
        spec = importlib.util.spec_from_file_location("studio_tunnel", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / ".env"
            original = "TELEGRAM_BOT_TOKEN=test-only\nSTUDIO_URL=https://old.invalid/\nOTHER=keep-me\n"
            env.write_text(original)
            calls = []
            def menu(url):
                calls.append(("menu", url))
            def restart():
                calls.append(("restart",))
            bad = module.activate_url("https://new.free.pinggy.net", env, lambda _: False, menu, restart)
            self.assertFalse(bad)
            self.assertEqual(env.read_text(), original)
            self.assertEqual(calls, [])
            good = module.activate_url("https://new.free.pinggy.net", env, lambda _: True, menu, restart)
            self.assertTrue(good)
            self.assertEqual(env.read_text(), original.replace("https://old.invalid/", "https://new.free.pinggy.net/"))
            self.assertEqual(calls, [("menu", "https://new.free.pinggy.net/"), ("restart",)])

    def test_menu_failure_keeps_previous_env(self):
        spec = importlib.util.spec_from_file_location("studio_tunnel", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            original = "STUDIO_URL=https://old.invalid/\nSECRET=unchanged\n"
            env.write_text(original)
            def fail(_):
                raise RuntimeError("network unavailable")
            with self.assertRaises(RuntimeError):
                module.activate_url("https://new.free.pinggy.net", env, lambda _: True, fail, lambda: self.fail("must not restart"))
            self.assertEqual(env.read_text(), original)

    def test_untrusted_url_is_never_probed(self):
        spec = importlib.util.spec_from_file_location("studio_tunnel", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(ValueError):
            module.activate_url("https://evil.invalid", Path("unused"), lambda _: self.fail("must not probe"), lambda _: None, lambda: None)


if __name__ == "__main__":
    unittest.main()
