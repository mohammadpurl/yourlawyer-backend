import hmac
import hashlib
import time
import os
from typing import Optional
import requests

from app.core.config import ALGORITHM


# Env config
OTP_SECRET = os.getenv("OTP_SECRET", "").encode()
OTP_STEP_SECONDS = int(os.getenv("OTP_STEP_SECONDS", "120"))  # 2 minutes window
OTP_DRIFT_WINDOWS = int(os.getenv("OTP_DRIFT_WINDOWS", "1"))  # allow ±1 window
OTP_DIGITS = 5
OTP_URL = os.getenv("OTP_URL", "https://api.sms.ir/v1/send/verify")
OTP_API_KEY = os.getenv("OTP_API_KEY", "")
OTP_TEMPLATE_ID = int(os.getenv("OTP_TEMPLATE_ID", "0"))  # باید integer باشد


def _hotp(key: bytes, counter: int, digits: int = OTP_DIGITS) -> str:
    counter_bytes = counter.to_bytes(8, "big")
    h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = (
        ((h[offset] & 0x7F) << 24)
        | ((h[offset + 1] & 0xFF) << 16)
        | ((h[offset + 2] & 0xFF) << 8)
        | (h[offset + 3] & 0xFF)
    )
    return str(code % (10**digits)).zfill(digits)


def _counter_for_mobile(mobile: str, ts: Optional[int] = None) -> tuple[int, bytes]:
    # TOTP counter: combine mobile with time window to avoid storing state
    now = int((ts if ts is not None else time.time()) // OTP_STEP_SECONDS)
    # Bind to mobile by including it in key derivation
    derived_key = hmac.new(OTP_SECRET, mobile.encode("utf-8"), hashlib.sha1).digest()
    # Use the time window as counter with mobile-bound key
    return now, derived_key


def generate_otp(mobile: str, ts: Optional[int] = None) -> str:
    counter, key = _counter_for_mobile(mobile, ts)
    return _hotp(key, counter, OTP_DIGITS)


def verify_otp(mobile: str, code: str, ts: Optional[int] = None) -> bool:
    base_counter, key = _counter_for_mobile(mobile, ts)
    windows = [
        base_counter + i for i in range(-OTP_DRIFT_WINDOWS, OTP_DRIFT_WINDOWS + 1)
    ]
    for c in windows:
        if _hotp(key, c, OTP_DIGITS) == code:
            return True
    return False


def send_sms_mock(mobile: str, message: str) -> None:
    # Placeholder for real SMS integration (e.g., Kavenegar, Ghasedak, SMS.ir)
    print(f"[SMS] to={mobile} text={message}")


def send_sms_real(mobile: str, code: str) -> None:
    """
    ارسال SMS واقعی از طریق SMS.ir API

    Args:
        mobile: شماره موبایل (مثلاً 09123456789)
        code: کد OTP
    """
    if not OTP_API_KEY:
        raise ValueError("OTP_API_KEY is not set in environment variables")

    if not OTP_TEMPLATE_ID:
        raise ValueError("OTP_TEMPLATE_ID is not set in environment variables")

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/plain",
        "x-api-key": OTP_API_KEY,
    }

    data = {
        "mobile": mobile,
        "templateId": OTP_TEMPLATE_ID,
        "parameters": [{"name": "Code", "value": code}],
    }

    try:
        response = requests.post(
            OTP_URL,
            json=data,  # استفاده از json به جای data برای ارسال JSON
            headers=headers,
            timeout=10,  # timeout برای جلوگیری از hang شدن
        )
        response.raise_for_status()  # بررسی خطاهای HTTP
        result = response.json()
        print(f"[SMS] Sent to {mobile}: {result}")
        return result
    except requests.exceptions.RequestException as e:
        print(f"[SMS] Error sending to {mobile}: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"[SMS] Error detail: {error_detail}")
            except:
                print(f"[SMS] Error response: {e.response.text}")
        raise
