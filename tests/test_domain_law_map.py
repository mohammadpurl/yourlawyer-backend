"""Unit tests for expanded domain_law_map rules."""

from app.services.domain_law_map import map_law_to_domain


def test_map_labor_and_tamin():
    r = map_law_to_domain(law_name="قانون کار جمهوری اسلامی ایران")
    assert r["domain"] == "کار_و_تامین_اجتماعی"
    r2 = map_law_to_domain(law_name="قانون تأمین اجتماعی")
    assert r2["domain"] == "کار_و_تامین_اجتماعی"


def test_map_criminal_core():
    r = map_law_to_domain(law_name="قانون مجازات اسلامی")
    assert r["domain"] == "کیفری"
    r2 = map_law_to_domain(law_name="قانون آیین دادرسی کیفری")
    assert r2["domain"] == "کیفری"


def test_map_check_is_commercial_not_forced_criminal():
    r = map_law_to_domain(law_name="قانون صدور چک")
    assert r["domain"] == "تجاری_و_اسناد_تجاری"


def test_map_family_and_civil():
    assert map_law_to_domain(law_name="قانون حمایت خانواده")["domain"] == "خانواده"
    assert map_law_to_domain(law_name="قانون مدنی")["domain"] == "مدنی"


def test_unknown_stays_unclassified():
    r = map_law_to_domain(law_name="آیین‌نامه داخلی فلان اداره ناشناخته ۱۲۳")
    assert r["domain"] == "unclassified"
    assert r["method"] == "unclassified"


def test_map_priority_unclassified_titles():
    assert map_law_to_domain(law_name="قانون اساسي جمهوري اسلامي ايران")["domain"] == "اداری"
    assert (
        map_law_to_domain(
            law_name="قانون آیین دادرسی دادگاههای عمومی و انقلاب (در امور مدنی)"
        )["domain"]
        == "مدنی"
    )
    assert map_law_to_domain(law_name="قانون دیات")["domain"] == "کیفری"
    assert map_law_to_domain(law_name="آیین نامه ایمنی در تونل سازی")["domain"] == (
        "کار_و_تامین_اجتماعی"
    )
