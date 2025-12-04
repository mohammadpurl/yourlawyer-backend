# scripts/generate_otp_secret.py
#!/usr/bin/env python3
"""
اسکریپت تولید OTP_SECRET ایمن
"""
import secrets
import base64
from pathlib import Path


def generate_otp_secret():
    # تولید 32 بایت (256 بیت) - استاندارد برای OTP
    secret_bytes = secrets.token_bytes(32)
    secret_base64 = base64.b64encode(secret_bytes).decode("utf-8")

    print("=" * 60)
    print("OTP_SECRET جدید تولید شد:")
    print("=" * 60)
    print(f"OTP_SECRET={secret_base64}")
    print("=" * 60)
    print("\nاین مقدار را در فایل .env خود اضافه/به‌روزرسانی کنید:")
    print("OTP_SECRET=" + secret_base64)
    print("\n⚠️  هشدار: این secret را محرمانه نگه دارید!")
    print("=" * 60)

    return secret_base64


if __name__ == "__main__":
    generate_otp_secret()
``