from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Callable, Optional, TextIO

from core.config import AppConfig, ConfigError, load_config
from core.factories import register
from core.interfaces import HealthStatus, InterfaceAdapter

QUIT = "/quit"
NEW = "/new"
OTP = "/otp"
HELP = "/help"
COMMANDS = frozenset({QUIT, NEW, OTP, HELP})

HELP_TEXT = (
    "Commands (these are handled by the CLI, never sent to the agent):\n"
    "  /help  show this help\n"
    "  /new   start a new session (fresh conversation)\n"
    "  /otp   print the latest OTP line from the OTP log (dev only)\n"
    "  /quit  exit"
)

OTP_DISABLED_TEXT = (
    "The /otp command is disabled. Set adapters.cli.allow_otp_command: true "
    "in the config to enable it."
)

BANK_API_HINT = (
    "start the bank API with: python -m uvicorn bank_api.main:create_app "
    "--factory --host 127.0.0.1 --port 8001"
)


@register("adapter", "cli")
class CliAdapter(InterfaceAdapter):
    """Line-based terminal adapter for one local conversation session.

    Commands (/quit, /new, /otp, /help) are handled here and never reach the
    model or count as turns. The session token is never printed, and OTPs are
    only ever read from the configured OTP log file.
    """

    def __init__(
        self,
        cfg: AppConfig,
        env=None,
        runner=None,
        input_stream: Optional[TextIO] = None,
        output_stream: Optional[TextIO] = None,
        runner_factory: Optional[Callable[[], object]] = None,
    ):
        self.cfg = cfg
        self.env = env or cfg.env
        cli = cfg.settings.adapters.cli
        self.prompt_text = cli.prompt_text
        self.agent_label = cli.agent_label
        self.allow_otp_command = cli.allow_otp_command
        self.otp_log_path = cfg.settings.bank_api.otp_log_path
        self.runner = runner
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self._runner_factory = runner_factory or self._build_runner
        self.handler = None
        self._running = False

    # --- InterfaceAdapter ---

    def describe(self) -> str:
        return "cli:stdin"

    def healthcheck(self) -> HealthStatus:
        # No network here: the bank API is checked by main() before run().
        return HealthStatus("cli", True, "stdin/stdout ready")

    def start(self, handler) -> None:
        self.handler = handler
        self._running = True

    def stop(self) -> None:
        self._running = False

    # --- main loop ---

    def run(self) -> int:
        self._running = True
        while self._running:
            self._write(self.prompt_text)
            try:
                line = self.input.readline()
            except KeyboardInterrupt:
                self._write("\n")
                break
            if line == "":  # EOF
                break
            text = line.rstrip("\n")
            if not text.strip():
                continue
            command = text.strip()
            if command in COMMANDS:
                if not self._handle_command(command):
                    break
                continue
            self._write(self.agent_label)
            self._stream_message(text)
            self.output.write("\n")
            self.output.flush()
        self._running = False
        try:
            self.output.flush()
        except Exception:
            pass
        return 0

    def _handle_command(self, command: str) -> bool:
        """Handle a command. Return False to stop the loop."""
        if command == QUIT:
            return False
        if command == NEW:
            self.runner = self._runner_factory()
            self._write("Started a new session.\n")
        elif command == OTP:
            self._write(self._otp_line() + "\n")
        elif command == HELP:
            self._write(HELP_TEXT + "\n")
        return True

    def _build_runner(self):
        # Fresh SessionState and runtime, same config (and same model).
        from core.factories import create_agent_runner

        llm = getattr(self.runner, "llm", None)
        return create_agent_runner(self.cfg, llm=llm)

    def _otp_line(self) -> str:
        if not self.allow_otp_command:
            return OTP_DISABLED_TEXT
        latest = ""
        try:
            lines = [
                line for line in Path(self.otp_log_path).read_text().splitlines()
                if line.strip()
            ]
            latest = lines[-1] if lines else ""
        except Exception:
            latest = ""
        if not latest:
            return f"DEV ONLY: no OTP lines found in {self.otp_log_path}"
        return f"DEV ONLY: latest OTP line: {latest}"

    def _scrub(self, text) -> str:
        text = "" if text is None else str(text)
        token = getattr(getattr(self.runner, "session", None), "token", None)
        if token and isinstance(token, str):
            text = text.replace(token, "***")
        return text

    def _stream_message(self, text: str) -> None:
        try:
            agent = getattr(self.runner, "agent", None)
            if agent is None:
                self.output.write(str(self.runner.handle_message(text)))
                return
            async def _consume():
                tool_seen: set = set()
                # Fixed: use runner.stream_events so start_turn/counter reset fire.
                async for event in self.runner.stream_events(text):
                    # Text chunks
                    chunk_text = event.get("data")
                    if chunk_text is not None:
                        if chunk_text:
                            self.output.write(chunk_text)
                            self.output.flush()
                        continue
                    # Tool stream event
                    event_type = event.get("type")
                    if event_type == "tool_use_stream":
                        current = event.get("current_tool_use")
                        name = None
                        if isinstance(current, dict):
                            name = current.get("name")
                        if name and name not in tool_seen:
                            tool_seen.add(name)
                            self.output.write(f"[using tool: {name}]")
                            self.output.flush()
            asyncio.run(_consume())
        except KeyboardInterrupt:
            self.output.write("\n")
            self.output.flush()
            raise

    def _write(self, text: str) -> None:
        self.output.write(text)
        try:
            self.output.flush()
        except Exception:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m adapters.cli_chat")
    parser.add_argument("--config", default="config", help="config directory")
    parser.add_argument("--debug", action="store_true", help="verbose logging for this run")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(config_dir=args.config)
    except ConfigError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    if args.debug:
        # In-memory only: never written back to the config files.
        cfg.settings.logging.debug = True

    try:
        from core.startup import run_startup

        run_startup(config_dir=args.config)  # existing component banner
    except ConfigError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    try:
        from core.factories import create_agent_runner

        runner = create_agent_runner(cfg)
    except ConfigError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    gateway = getattr(getattr(runner, "runtime", None), "gateway", None)
    base = getattr(gateway, "base_url", None) or cfg.env.BANK_API_URL
    print(f"Bank API: {base}")

    health = gateway.healthcheck() if gateway is not None else None
    if health is None or not health.ok:
        detail = health.detail if health is not None else "no bank gateway"
        print(f"Could not reach the bank API at {base} ({detail}).", file=sys.stderr)
        print(BANK_API_HINT, file=sys.stderr)
        return 1

    adapter = CliAdapter(cfg, cfg.env, runner)
    try:
        return adapter.run()
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
