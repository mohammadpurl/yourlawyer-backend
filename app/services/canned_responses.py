"""Persian canned replies for non-legal intents (no RAG / no citations).

Edit wording here only — pipeline logic stays in intent_detector / rag.
"""

from __future__ import annotations

CANNED_RESPONSES: dict[str, str] = {
    "meta_capability": (
        "در حال حاضر امکان تنظیم شکواییه، دادخواست یا لایحه در این سیستم فراهم نیست؛ "
        "این قابلیت در حال توسعه است.\n\n"
        "آنچه امروز می‌توانم انجام دهم: پاسخ به سؤالات حقوقی با استناد به منابع موجود "
        "در پایگاه (به‌ویژه حوزه‌های مدنی، خانواده، کیفری و کار/تأمین اجتماعی)، "
        "همراه با ارجاع به مواد و متون بازیابی‌شده.\n\n"
        "لطفاً سؤال حقوقی خود را مطرح کنید تا بر اساس منابع پاسخ بدهم."
    ),
    "greeting_chitchat": (
        "سلام، خوش آمدید. من دستیار حقوقی «وکیل تو» هستم و به سؤالات حقوقی "
        "با استناد به منابع پاسخ می‌دهم.\n\n"
        "سؤال حقوقی‌تان را بنویسید تا کمک کنم."
    ),
    "out_of_scope": (
        "این دستیار فقط برای سؤالات حقوقی مرتبط با قوانین و مقررات ایران طراحی شده است. "
        "لطفاً سؤال حقوقی خود را مطرح کنید تا بتوانم بر اساس منابع موجود پاسخ بدهم."
    ),
}


def get_canned_response(intent: str) -> str:
    """Return template text; unknown intent falls back to out_of_scope wording."""
    return CANNED_RESPONSES.get(intent) or CANNED_RESPONSES["out_of_scope"]
