"""Tests for document templates (no LLM)."""

from app.services.templates import (
    validate_field_values,
    render_template_body,
    build_docx_bytes,
)


def test_render_jinja_fields():
    body = "موجر: {{ landlord_name }} / مستأجر: {{ tenant_name }}"
    out = render_template_body(
        body, {"landlord_name": "علی", "tenant_name": "رضا"}
    )
    assert "علی" in out and "رضا" in out


def test_validate_required_fields():
    schema = {
        "fields": [
            {"key": "landlord_name", "label": "موجر", "type": "string", "required": True},
            {"key": "rent", "label": "اجاره", "type": "number", "required": True},
        ]
    }
    cleaned = validate_field_values(
        schema, {"landlord_name": "علی", "rent": "1000"}
    )
    assert cleaned["landlord_name"] == "علی"
    assert cleaned["rent"] == 1000


def test_sanitize_jinja_injection_in_values():
    schema = {
        "fields": [
            {"key": "name", "label": "نام", "type": "string", "required": True},
        ]
    }
    cleaned = validate_field_values(
        schema, {"name": "x {{ secret }} y"}
    )
    assert "{{" not in cleaned["name"]
    assert "}}" not in cleaned["name"]


def test_build_docx_bytes_nonempty():
    data = build_docx_bytes("عنوان", "متن نمونه\nخط دوم")
    assert isinstance(data, (bytes, bytearray))
    assert len(data) > 100
