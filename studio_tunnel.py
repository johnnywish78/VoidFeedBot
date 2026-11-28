#!/usr/bin/env python3
"""Keep Studio reachable through SSH/443 and sync rotated Telegram URLs."""
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from voidfeed_dns import install as install_dns

install_dns()

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env"
STATE = ROOT / "data" / "tunnel"
LOG = logging.getLogger("StudioTunnel")
URL_RE = re.compile(r"https://[a-z0-9-]+\.(?:free\.pinggy\.net|run\.pinggy-free\.link)")
STOP = asyncio.Event()


def activate_url(url, env_path, healthy, set_menu, restart):
    """Publish only a checked HTTPS tunnel, preserving unrelated env values."""
    url = url.rstrip("/") + "/"
    parts = urlsplit(url)
    if parts.scheme != "https" or not URL_RE.fullmatch(url.rstrip("/")):
        raise ValueError("Unexpected tunnel URL")
    if not healthy(url):
        return False
    set_menu(url)
    original = env_path.read_text()
    line = "STUDIO_URL=" + url
    updated, count = re.subn(r"(?m)^STUDIO_URL=[^\r\n]*", lambda _: line, original)
    if not count:
        updated = original.rstrip("\n") + "\n" + line + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".studio-env-", dir=env_path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            os.chmod(temporary, env_path.stat().st_mode & 0o777)
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, env_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    restart()
    return True


def healthy(url):
    try:
        with httpx.Client(trust_env=False, timeout=12) as client:
            response = client.get(url + "healthz")
            response.raise_for_status()
            data = response.json()
            if data.get("ok") is not True or data.get("demo") is not False:
                return False
            response = client.get(url)
            response.raise_for_status()
            return "VoidFeed Studio" in response.text
    except Exception:
        return False


def set_menu(url):
    """Keep the native square menu button as the STUDIO web app (MenuButtonWebApp).

    The button points at the live STUDIO_URL; the supervisor refreshes it on
    every tunnel rotation so it never goes stale.
    """
    env = dotenv_values(ENV)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    admin_raw = (env.get("VOIDFEED_ADMIN_ID", "") or "").strip()
    with httpx.Client(trust_env=False, timeout=20) as client:
        api = "https://api.telegram.org/bot" + token + "/"
        expected = {"type": "web_app", "text": "🌌 استودیو",
                    "web_app": {"url": url}}
        scopes = [{}]
        if admin_raw.isdigit():
            scopes.append({"scope": {"type": "chat", "chat_id": int(admin_raw)}})
        for scope in scopes:
            params = {"menu_button": dict(expected)}
            params.update(scope)
            response = client.post(api + "setChatMenuButton", json=params)
            if response.status_code != 200 or response.json().get("ok") is not True:
                raise RuntimeError("Telegram menu update failed")
            verify = client.post(api + "getChatMenuButton", json=scope)
            if verify.status_code != 200 or verify.json().get("result") != expected:
                raise RuntimeError("Telegram menu verification failed")


def restart_bot():
    subprocess.run(["systemctl", "--user", "restart", "voidfeedbot"], check=True, timeout=40)


async def pause(seconds):
    try:
        await asyncio.wait_for(STOP.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def publish_when_ready(url):
    for attempt in range(6):
        if STOP.is_set():
            return False
        try:
            if await asyncio.to_thread(activate_url, url, ENV, healthy, set_menu, restart_bot):
                STATE.mkdir(parents=True, exist_ok=True)
                (STATE / "active.json").write_text(json.dumps({"url": url.rstrip("/") + "/", "transport": "ssh443"}))
                LOG.info("Studio URL verified and activated: %s", url)
                return True
        except Exception as error:
            # Never log HTTP exception URLs: they may contain Telegram credentials.
            LOG.warning("URL activation retry (%s): %s", type(error).__name__, str(error) if isinstance(error, RuntimeError) else "network/restart failure")
        await pause(min(3 * (attempt + 1), 15))
    return False


async def connect():
    process = await asyncio.create_subprocess_exec(
        "ssh", "-T", "-p", "443", "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes", "-o", "BatchMode=yes",
        "-o", "IdentityAgent=none", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "LogLevel=ERROR",
        "-o", "UserKnownHostsFile=" + str(STATE / "known_hosts"),
        "-i", str(STATE / "id_ed25519"),
        "-R", "0:127.0.0.1:8077", "free@free.pinggy.io",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    seen = set()
    active = None
    reader = None
    stop = asyncio.create_task(STOP.wait())
    try:
        while process.returncode is None and not STOP.is_set():
            reader = asyncio.create_task(process.stdout.readline())
            done, _ = await asyncio.wait({reader, stop}, timeout=180, return_when=asyncio.FIRST_COMPLETED)
            if stop in done:
                break
            if reader not in done:
                reader.cancel()
                if active is None:
                    LOG.warning("Tunnel registration timed out")
                    break
                if not await asyncio.to_thread(healthy, active):
                    await pause(5)
                    if not await asyncio.to_thread(healthy, active):
                        LOG.warning("Public health failed twice; reconnecting")
                        break
                continue
            raw = reader.result()
            if not raw:
                break
            text = raw.decode(errors="replace")
            for match in URL_RE.finditer(text):
                url = match.group()
                if url in seen or active:
                    continue
                seen.add(url)
                LOG.info("Tunnel assigned: %s", url)
                if await publish_when_ready(url):
                    active = url
        return active is not None
    finally:
        stop.cancel()
        if reader and not reader.done():
            reader.cancel()
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 6)
            except TimeoutError:
                process.kill()
                await process.wait()


async def main():
    os.umask(0o077)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, STOP.set)
    while not STOP.is_set():
        try:
            await connect()
        except Exception as error:
            LOG.warning("Tunnel stopped (%s)", type(error).__name__)
        if not STOP.is_set():
            LOG.info("Reconnecting SSH/443 tunnel in 10 seconds")
            await pause(10)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
