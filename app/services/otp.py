import hmac
import hashlib
import time
import os
from typing import Optional

from app.core.config import ALGORITHM


# Env config
OTP_SECRET = os.getenv("OTP_SECRET", "change-this-otp-secret").encode()
OTP_STEP_SECONDS = int(os.getenv("OTP_STEP_SECONDS", "120"))  # 2 minutes window
OTP_DRIFT_WINDOWS = int(os.getenv("OTP_DRIFT_WINDOWS", "1"))  # allow ±1 window
OTP_DIGITS = 5


def _hotp(key: bytes, counter: int, digits: int = OTP_DIGITS) -> str:
    counter_bytes = counter.to_bytes(8, "big")
    h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = ((h[offset] & 0x7F) << 24) | ((h[offset + 1] & 0xFF) << 16) | ((h[offset + 2] & 0xFF) << 8) | (
        h[offset + 3] & 0xFF
    )
    return str(code % (10**digits)).zfill(digits)


def _counter_for_phone(phone: str, ts: Optional[int] = None) -> int:
    # TOTP counter: combine phone with time window to avoid storing state
    now = int((ts if ts is not None else time.time()) // OTP_STEP_SECONDS)
    # Bind to phone by including it in key derivation
    derived_key = hmac.new(OTP_SECRET, phone.encode("utf-8"), hashlib.sha1).digest()
    # Use the time window as counter with phone-bound key
    return now, derived_key


def generate_otp(phone: str, ts: Optional[int] = None) -> str:
    counter, key = _counter_for_phone(phone, ts)
    return _hotp(key, counter, OTP_DIGITS)


def verify_otp(phone: str, code: str, ts: Optional[int] = None) -> bool:
    base_counter, key = _counter_for_phone(phone, ts)
    windows = [base_counter + i for i in range(-OTP_DRIFT_WINDOWS, OTP_DRIFT_WINDOWS + 1)]
    for c in windows:
        if _hotp(key, c, OTP_DIGITS) == code:
            return True
    return False


def send_sms_mock(phone: str, message: str) -> None:
    # Placeholder for real SMS integration (e.g., Kavenegar, Ghasedak, SMS.ir)
    print(f"[SMS] to={phone} text={message}")

