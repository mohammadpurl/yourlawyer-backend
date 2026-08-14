"""Unit tests for expert-opinion domain detection (no LLM)."""

from app.config.expert_opinion_domains import (
    detect_expert_opinion_domain,
    expert_opinion_api_payload,
)


def test_worker_fault_percentage_detected():
    q = (
        "در صورتی که کارگر ساختمانی از ساختمان سقوط کرده و دچار ضربه مغزی شود "
        "کارفرما یا مالک ساختمان چند درصد مقصر هستند چون مالک ساختمان وسایل ایمنی "
        "را فراهم نکرده بوده است"
    )
    d = detect_expert_opinion_domain(q)
    assert d is not None
    assert d["id"] == "fault_percentage_accident"
    payload = expert_opinion_api_payload(d)
    assert payload["flag"] is True
    assert "کارشناس" in payload["expert_type"]


def test_ojrat_almesl_detected():
    q = "اجرت المثل ایام زوجیت چگونه محاسبه می‌شود؟"
    d = detect_expert_opinion_domain(q)
    assert d is not None
    assert d["id"] == "ojrat_almesl"


def test_ordinary_question_no_false_positive():
    q = "شرایط طلاق توافقی چیست و چه مدارکی لازم است؟"
    assert detect_expert_opinion_domain(q) is None


def test_check_law_no_false_positive():
    q = "قانون برگشت چک چیست و مهلت شکایت چند روز است؟"
    assert detect_expert_opinion_domain(q) is None
