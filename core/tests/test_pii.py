"""PII-детекторы v0: телефон/email/карта(Luhn)/паспорт/ИНН + политики."""

from polylog.pii.detect import apply_policy, detect_pii, mask_text


def test_phone_detected():
    spans = detect_pii("Перезвоните на +7 (900) 123-45-67 после пяти")
    assert any(s.kind == "phone" and "900" in s.value for s in spans)


def test_email_detected():
    spans = detect_pii("Пишите на ivan.petrov@example.ru")
    assert any(s.kind == "email" for s in spans)


def test_card_requires_luhn():
    valid = "4539 1488 0343 6467"  # валидная тестовая карта по Luhn
    invalid = "4539 1488 0343 6468"
    assert any(s.kind == "card" for s in detect_pii(f"Карта {valid}"))
    assert not any(s.kind == "card" for s in detect_pii(f"Карта {invalid}"))


def test_inn_detected():
    spans = detect_pii("ИНН 7707083893 указан в договоре")
    assert any(s.kind == "inn" for s in spans)


def test_mask_text_replaces_all_pii():
    masked = mask_text("Звоните на +7 900 123-45-67 или ivan@example.ru")
    assert "+7" not in masked and "@" not in masked
    assert "[ПДн]" in masked


def test_apply_policy_keep_vs_mask():
    text = "Телефон 89001234567"
    kept, spans = apply_policy(text, "keep")
    assert kept == text and len(spans) == 1
    masked, spans2 = apply_policy(text, "mask")
    assert "89001234567" not in masked and len(spans2) == 1


def test_plain_text_untouched():
    text = "Обсудили поставку оборудования на склад №4"
    assert mask_text(text) == text
    _, spans = apply_policy(text, "mask")
    assert spans == []
