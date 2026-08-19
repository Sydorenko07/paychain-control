"""Local worker: receives commands and runs the existing Playwright monitor.

This program is installed on each user's PC.  Paychain browser data stays here.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import websockets


ROOT = Path(__file__).parents[1]
HERE = Path(__file__).parent
CONFIG_PATH = HERE / "agent-config.json"
SIGNAL_PATH = ROOT / ".start_monitoring.signal"
ACTIVITY_LOG = ROOT / "logs" / "activity.log"
DOWNLOAD_CONFIG_PATH = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads" / "agent-config.json"


class Agent:
    def __init__(self, config: dict[str, str]) -> None:
        self.config = config
        self.process: subprocess.Popen[str] | None = None
        self.threshold = "5000"
        self.login_pending = False
        self.activity_position = ACTIVITY_LOG.stat().st_size if ACTIVITY_LOG.exists() else 0

    def start(self, threshold: str) -> None:
        if self.process and self.process.poll() is None and self.login_pending:
            self.threshold = threshold
            SIGNAL_PATH.write_text("start", encoding="utf-8")
            self.login_pending = False
            return
        self.stop()
        self.threshold = threshold
        SIGNAL_PATH.unlink(missing_ok=True)
        self.process = subprocess.Popen(
            [str(Path(sys.executable)), str(ROOT / "main.py"), "--auto-accept", "--minimum-amount", threshold, "--start-signal", str(SIGNAL_PATH)],
            cwd=ROOT,
        )
        SIGNAL_PATH.write_text("start", encoding="utf-8")

    def open_login(self, threshold: str) -> None:
        self.stop()
        self.threshold = threshold
        SIGNAL_PATH.unlink(missing_ok=True)
        self.process = subprocess.Popen(
            [str(Path(sys.executable)), str(ROOT / "main.py"), "--auto-accept", "--minimum-amount", threshold, "--start-signal", str(SIGNAL_PATH)],
            cwd=ROOT,
        )
        self.login_pending = True

    def stop(self) -> None:
        process = self.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.process = None
        self.login_pending = False
        SIGNAL_PATH.unlink(missing_ok=True)

    @property
    def running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def new_activity(self) -> list[dict[str, str]]:
        if not ACTIVITY_LOG.exists():
            return []
        with ACTIVITY_LOG.open("r", encoding="utf-8") as file:
            file.seek(self.activity_position)
            lines = file.readlines()
            self.activity_position = file.tell()
        events = []
        for line in lines:
            if "ПРИЙНЯТО |" not in line:
                continue
            # Example: timestamp ПРИЙНЯТО | оффер abc | 2500.00 UAH
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 3:
                values = parts[-1].split(maxsplit=1)
                if len(values) == 2:
                    amount, currency = values
                    events.append({"amount": amount, "currency": currency})
        return events


def adopt_downloaded_config() -> bool:
    """Move a valid one-time pairing file downloaded on this same PC."""
    if not DOWNLOAD_CONFIG_PATH.exists():
        return False
    try:
        config = json.loads(DOWNLOAD_CONFIG_PATH.read_text(encoding="utf-8"))
        required = ("server_ws_url", "agent_id", "agent_token")
        if any(not str(config.get(key, "")).strip() for key in required):
            return False
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.unlink(missing_ok=True)
        shutil.move(str(DOWNLOAD_CONFIG_PATH), str(CONFIG_PATH))
        return True
    except (OSError, json.JSONDecodeError):
        return False


async def run() -> None:
    # The Windows installer starts this process before the PC is paired.
    # Keep it alive and wait for the one-time config from the Mini App.
    agent = Agent({})
    while True:
        adopt_downloaded_config()
        if not CONFIG_PATH.exists():
            await asyncio.sleep(5)
            continue
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            required = ("server_ws_url", "agent_id", "agent_token")
            if any(not str(config.get(key, "")).strip() for key in required):
                await asyncio.sleep(5)
                continue
            url = f"{config['server_ws_url']}?agent_id={config['agent_id']}&agent_token={config['agent_token']}"
            async with websockets.connect(url, ping_interval=20) as socket:
                await socket.send(json.dumps({"type": "status", "running": False, "status": "Агент готовий"}))
                while True:
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=1)
                        command = json.loads(raw)
                        if command["action"] == "open_login":
                            agent.open_login(command["threshold"])
                        elif command["action"] == "start":
                            agent.start(command["threshold"])
                        elif command["action"] == "stop":
                            agent.stop()
                        elif command["action"] == "set_threshold":
                            if agent.login_pending:
                                agent.open_login(command["threshold"])
                            elif agent.running:
                                agent.start(command["threshold"])
                            else:
                                agent.threshold = command["threshold"]
                        elif command["action"] == "disconnect":
                            agent.stop()
                            CONFIG_PATH.unlink(missing_ok=True)
                            await socket.close(code=1000, reason="Disconnected by user")
                            break
                    except asyncio.TimeoutError:
                        pass
                    status = "Очікується вхід у Paychain" if agent.login_pending else ("Моніторинг працює" if agent.running else "Зупинено")
                    await socket.send(json.dumps({"type": "status", "running": agent.running and not agent.login_pending, "status": status}))
                    for event in agent.new_activity():
                        await socket.send(json.dumps({"type": "status", "running": agent.running, "status": "Угоду прийнято", "accepted": True, **event}))
        except Exception as error:
            # A 403 means the pairing token is stale (for example after a new
            # pairing or a server redeploy). Let the next downloaded config be
            # adopted automatically instead of requiring manual file removal.
            if "403" in str(error) and CONFIG_PATH.exists():
                CONFIG_PATH.unlink(missing_ok=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
