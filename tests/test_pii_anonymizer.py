"""Tests for PII anonymization module."""

from concurrent.futures import ThreadPoolExecutor

from app.core.pii_anonymizer import (
    PIIAnonymizer,
    PIIType,
    RAW_MOBILE_ASSERT_RE,
    RAW_NATIONAL_ID_ASSERT_RE,
    call_llm_with_pii_protection,
    is_valid_iranian_national_id,
)

# Known-valid Iranian national ID (check-digit verified)
VALID_NATIONAL_ID = "0013542419"
INVALID_NATIONAL_ID = "1234567890"


def test_valid_national_id_check_digit():
    assert is_valid_iranian_national_id(VALID_NATIONAL_ID)
    assert is_valid_iranian_national_id("001-354-2419")
    assert is_valid_iranian_national_id("001 354 2419")
    assert not is_valid_iranian_national_id(INVALID_NATIONAL_ID)
    assert not is_valid_iranian_national_id("0000000000")


def test_detect_national_id_with_separators():
    anon = PIIAnonymizer(enabled=True, ner_enabled=False)
    for raw in (VALID_NATIONAL_ID, "001-354-2419", "001 354 2419"):
        text = f"کد ملی موکل {raw} است"
        out, maps = anon.anonymize(text)
        assert any(m.pii_type == PIIType.NATIONAL_ID for m in maps)
        assert "[PII_NATIONAL_ID_1]" in out
        assert VALID_NATIONAL_ID not in out.replace("-", "").replace(" ", "")
        # No raw 10-digit national id left
        for m in RAW_NATIONAL_ID_ASSERT_RE.finditer(out):
            assert not is_valid_iranian_national_id(m.group(0))


def test_detect_mobile_formats():
    anon = PIIAnonymizer(enabled=True)
    samples = [
        "09123456789",
        "+989123456789",
        "00989123456789",
        "0912-345-6789",
    ]
    for mobile in samples:
        text = f"با شماره {mobile} تماس بگیرید"
        out, maps = anon.anonymize(text)
        assert any(m.pii_type == PIIType.PHONE for m in maps), mobile
        assert "[PII_PHONE_1]" in out
        assert not RAW_MOBILE_ASSERT_RE.search(out.replace("-", "").replace(" ", ""))


def test_round_trip_restore():
    anon = PIIAnonymizer(enabled=True)
    original = (
        f"آقای رضایی با کد ملی {VALID_NATIONAL_ID} و موبایل 09121234567 "
        f"در خیابان ولیعصر پلاک ۱۲ پرونده ۱۴۰۲/۱۲۳۴۵ دارد."
    )
    anonymized, mappings = anon.anonymize(original)
    # Simulate LLM echoing placeholders
    fake_llm = f"درباره {anonymized} توضیح داده شد."
    restored = anon.restore(fake_llm, mappings)
    assert VALID_NATIONAL_ID in restored
    assert "09121234567" in restored or "0912" in restored
    assert "[PII_" not in restored


def test_no_pii_unchanged():
    anon = PIIAnonymizer(enabled=True)
    text = "ماده ۱۰ قانون مدنی در مورد اهلیت چیست؟"
    out, maps = anon.anonymize(text)
    assert out == text
    assert maps == []


def test_multiple_pii_in_long_text():
    anon = PIIAnonymizer(enabled=True)
    text = (
        f"موکل اول آقای احمدی کد ملی {VALID_NATIONAL_ID} تلفن 09121111111 "
        f"و موکل دوم خانم محمدی تلفن +989122222222 در کوچه گلستان پلاک ۳."
    )
    out, maps = anon.anonymize(text)
    assert len(maps) >= 3
    assert not RAW_MOBILE_ASSERT_RE.search(out.replace("-", "").replace(" ", ""))
    for m in RAW_NATIONAL_ID_ASSERT_RE.finditer(out):
        assert not is_valid_iranian_national_id(m.group(0))
    restored = anon.restore(out, maps)
    assert restored == text


def test_concurrent_requests_isolated_mappings():
    anon = PIIAnonymizer(enabled=True)

    def worker(mobile: str):
        text = f"شماره من {mobile} است"
        out, maps = anon.anonymize(text)
        restored = anon.restore(out, maps)
        return restored, maps[0].original_value if maps else None

    mobiles = ["09120000001", "09120000002", "09120000003", "09120000004"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, mobiles))

    for mobile, (restored, original) in zip(mobiles, results):
        assert mobile in restored
        assert original == mobile


def test_call_llm_with_pii_protection_wrapper():
    def fake_llm(prompt: str) -> str:
        assert VALID_NATIONAL_ID not in prompt
        assert "[PII_NATIONAL_ID_1]" in prompt
        return f"پاسخ درباره {[p for p in prompt.split() if p.startswith('[PII')][0]}"

    # Ensure singleton path works with a dedicated instance via wrapper's get
    # Use local invoke with module helper — temporarily patch by direct anonymizer
    anon = PIIAnonymizer(enabled=True)
    prompt = f"کد ملی {VALID_NATIONAL_ID}"
    anonymized, mappings = anon.anonymize(prompt)
    raw = fake_llm(anonymized)
    restored = anon.restore(raw, mappings)
    assert VALID_NATIONAL_ID in restored

    # Also exercise helper with a simple echo that preserves placeholders
    def echo(p: str) -> str:
        return p

    # call_llm_with_pii_protection uses get_pii_anonymizer() from config
    result = call_llm_with_pii_protection(echo, f"موبایل 09123334444")
    assert "09123334444" in result


def test_disabled_anonymizer_passthrough():
    anon = PIIAnonymizer(enabled=False)
    text = f"کد ملی {VALID_NATIONAL_ID}"
    out, maps = anon.anonymize(text)
    assert out == text
    assert maps == []
