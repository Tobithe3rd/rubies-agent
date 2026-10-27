from __future__ import annotations

import datetime
import logging
import os

from core.factories import register
from core.interfaces import OTPSender


@register("otp_sender", "mock")
class MockOTPSender(OTPSender):
    """Mock delivery: appends phone, code, time to the configured log file.

    The code is written only to the mock delivery log (a dev artifact) and is
    never logged at INFO or returned to callers.
    """

    def __init__(self, cfg, env):
        self.log_path = cfg.otp_log_path

    def describe(self) -> str:
        return "mock"

    def send(self, phone: str, code: str) -> None:
        directory = os.path.dirname(self.log_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        line = f"{phone}, {code}, {datetime.datetime.now().isoformat()}\n"
        with open(self.log_path, "a") as f:
            f.write(line)
        # Only the phone is logged at debug level; never the code.
        logging.getLogger("rubies.otp").debug("OTP delivered to %s (mock)", phone)
