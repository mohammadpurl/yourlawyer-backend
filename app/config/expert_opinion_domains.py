"""
حوزه‌هایی که تعیین میزان/عدد دقیق آن‌ها در نظام حقوقی ایران
بر عهده کارشناس رسمی دادگستری یا نهاد تخصصی است، نه متن مستقیم قانون.

TODO: ماهانه بر اساس لاگ سوالات production این لیست را بازبینی و گسترش دهید.
این لیست کامل نیست و عمداً قابل‌گسترش طراحی شده است.
"""

from __future__ import annotations

from typing import Any

EXPERT_OPINION_DOMAINS: list[dict[str, Any]] = [
    {
        "id": "fault_percentage_accident",
        "label_fa": "تعیین درصد تقصیر در حوادث",
        "keywords": [
            "درصد تقصیر",
            "چند درصد مقصر",
            "میزان مسئولیت",
            "سهم تقصیر",
            "درصد مقصر",
        ],
        "expert_type": "کارشناس رسمی دادگستری (رشته مرتبط با نوع حادثه)",
        "guidance_factors_hint": (
            "مسئولیت تامین ایمنی، محدوده قرارداد/وظایف هر طرف، نظارت انجام‌شده یا نشده"
        ),
    },
    {
        "id": "property_damage_valuation",
        "label_fa": "برآورد خسارت مالی",
        "keywords": ["برآورد خسارت", "ارزش خسارت", "میزان خسارت وارده"],
        "expert_type": "کارشناس رسمی ارزیابی اموال",
        "guidance_factors_hint": None,
    },
    {
        "id": "complex_diyeh",
        "label_fa": "محاسبه دیه در موارد پیچیده",
        "keywords": ["محاسبه دیه", "درصد نقص عضو", "چند مصدومیت"],
        "expert_type": "پزشکی قانونی",
        "guidance_factors_hint": None,
    },
    {
        "id": "ojrat_almesl",
        "label_fa": "اجرت‌المثل ایام تصرف/زوجیت",
        "keywords": ["اجرت المثل", "اجرت‌المثل"],
        "expert_type": "کارشناس رسمی دادگستری",
        "guidance_factors_hint": None,
    },
    {
        "id": "mahrieh_current_rate",
        "label_fa": "محاسبه مهریه به نرخ روز",
        "keywords": ["مهریه به نرخ روز", "محاسبه سکه مهریه"],
        "expert_type": "کارشناس رسمی / بانک مرکزی",
        "guidance_factors_hint": None,
    },
    {
        "id": "document_authenticity",
        "label_fa": "تشخیص اصالت سند یا امضا",
        "keywords": ["جعل امضا", "اصالت سند", "کارشناس خط"],
        "expert_type": "کارشناس رسمی خط و امضا",
        "guidance_factors_hint": None,
    },
    {
        "id": "property_boundaries",
        "label_fa": "حدود و مساحت دقیق ملک",
        "keywords": ["حدود اربعه", "مساحت دقیق ملک", "اختلاف ثبتی مرز"],
        "expert_type": "نقشه‌بردار رسمی دادگستری",
        "guidance_factors_hint": None,
    },
    {
        "id": "insolvency_assessment",
        "label_fa": "ارزیابی اعسار و توان مالی",
        "keywords": ["اعسار", "توان مالی بدهکار", "تقسیط بدهی"],
        "expert_type": "کارشناس رسمی مالی",
        "guidance_factors_hint": None,
    },
    {
        "id": "construction_defects",
        "label_fa": "عیوب فنی ساختمان",
        "keywords": ["عیب ساختمان", "نقص فنی ساخت", "مصالح غیراستاندارد"],
        "expert_type": "کارشناس رسمی فنی ساختمان",
        "guidance_factors_hint": None,
    },
    {
        "id": "business_valuation",
        "label_fa": "ارزش‌گذاری کسب‌وکار یا سهام",
        "keywords": ["ارزش‌گذاری سهام", "ارزش شرکت در دعوا"],
        "expert_type": "کارشناس رسمی مالی/حسابرس",
        "guidance_factors_hint": None,
    },
]


def detect_expert_opinion_domain(user_query: str) -> dict[str, Any] | None:
    """
    بررسی سریع (بدون LLM) که آیا سوال با حوزه نیازمند نظر کارشناس مطابقت دارد.
    خروجی: دیکشنری همان domain یا None.
    """
    q = (user_query or "").replace("\u200c", " ")
    if not q.strip():
        return None
    for domain in EXPERT_OPINION_DOMAINS:
        for kw in domain["keywords"]:
            if kw in q:
                return domain
    return None


def expert_opinion_api_payload(
    domain: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Shape returned on RAG API responses when expert opinion is required."""
    if not domain:
        return None
    return {
        "flag": True,
        "expert_type": domain.get("expert_type"),
        "domain_label": domain.get("label_fa"),
        "domain_id": domain.get("id"),
        "guidance_factors_hint": domain.get("guidance_factors_hint"),
    }


def expert_opinion_prompt_addon(domain: dict[str, Any]) -> str:
    """Extra system-prompt block when expert_opinion_flag is set."""
    expert_type = domain.get("expert_type") or "کارشناس رسمی دادگستری"
    hint = domain.get("guidance_factors_hint")
    hint_line = ""
    if hint:
        hint_line = (
            f"\nعوامل راهنما که اگر در منابع بود استخراج کن: {hint}"
        )
    return f"""
توجه ویژه برای این پاسخ:
این سوال به نوعی است که تعیین عدد یا میزان دقیق آن در نظام حقوقی ایران معمولاً
بر عهده {expert_type} است، نه متن مستقیم قانون. در پاسخ خود:
۱. به‌صراحت توضیح بده که چرا عدد دقیق در قانون مشخص نشده (این یک محدودیت سیستم نیست،
   بلکه بخشی از نظام حقوقی است که تشخیص موردی را به کارشناس/دادگاه می‌سپارد).
۲. اگر در منابع بازیابی‌شده، معیارها یا عواملی وجود دارد که کارشناس/دادگاه معمولاً
   در نظر می‌گیرد، آن‌ها را استخراج و با استناد به منبع ارائه بده. هرگز عددی که در
   منابع نیست را حدس نزن یا نسازی.
۳. اگر منابع بازیابی‌شده هیچ معیاری هم ندارند، صریحاً بگو که این پرونده باید نزد
   {expert_type} یا وکیل بررسی شود.
۴. پاسخ را با جملهٔ صرف «اطلاعات کافی یافت نشد» تمام نکن؛ چارچوب حقوقی موجود در منابع
   را بگو و نیاز به کارشناسی را مشخص کن.{hint_line}
""".strip()
