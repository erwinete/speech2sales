"""Правила-детекция v0: возражения, отработка, сигналы, нарушения."""

from polylog.nlp.rules import agent_open_questions, detect_findings, handled_success_ratio


def _segs():
    return [
        {"idx": 0, "speaker": "agent", "start_ms": 0, "end_ms": 3000,
         "text": "Добрый день, компания Ромашка, меня зовут Ирина. Какими объёмами вы торгуете?"},
        {"idx": 1, "speaker": "client", "start_ms": 3200, "end_ms": 6500,
         "text": "Здравствуйте! У нас уже есть поставщик, всё устраивает."},
        {"idx": 2, "speaker": "agent", "start_ms": 7000, "end_ms": 11000,
         "text": "Понимаю, поэтому предлагаю не менять, а сравнить условия по цене."},
        {"idx": 3, "speaker": "client", "start_ms": 11500, "end_ms": 14000,
         "text": "Ну ладно, давайте созвонимся в четверг."},
        {"idx": 4, "speaker": "agent", "start_ms": 14500, "end_ms": 17000,
         "text": "Отлично, договорились! До свидания."},
    ]


def test_objection_detected_with_quote_and_timing():
    findings = detect_findings(_segs())
    objs = [f for f in findings if f.kind == "objection"]
    assert len(objs) == 1
    o = objs[0]
    assert o.type == "existing_supplier"
    assert "уже есть поставщик" in o.span_text
    assert o.speaker == "client"
    assert o.start_ms == 3200


def test_objection_response_classified_as_success():
    findings = detect_findings(_segs())
    o = next(f for f in findings if f.kind == "objection")
    # агент ответил сравнением условий в течение окна → handled_success
    assert o.response_status == "handled_success"
    assert o.response_span is not None
    assert handled_success_ratio([o]) == 1.0


def test_next_step_signal_detected():
    findings = detect_findings(_segs())
    # клиент предлагает шаг (сегмент #3); агент подтверждает («Договорились!», #4)
    client_sigs = [
        f for f in findings
        if f.kind == "signal" and f.type == "next_step_agreed" and f.speaker == "client"
    ]
    assert len(client_sigs) == 1
    assert client_sigs[0].start_ms == 11500
    assert any(
        f.kind == "signal" and f.type == "next_step_agreed" and f.speaker == "agent"
        for f in findings
    )


def test_deferral_classified():
    segs = [
        {"idx": 0, "speaker": "agent", "start_ms": 0, "end_ms": 2000, "text": "Здравствуйте!"},
        {"idx": 1, "speaker": "client", "start_ms": 2100, "end_ms": 4000, "text": "Пришлите нам КП на почту."},
        {"idx": 2, "speaker": "agent", "start_ms": 4500, "end_ms": 6500, "text": "Хорошо, я вышлю КП сегодня."},
    ]
    findings = detect_findings(segs)
    o = next(f for f in findings if f.kind == "objection")
    assert o.type == "send_offer"
    assert o.response_status == "deferred"


def test_ignored_objection():
    segs = [
        {"idx": 0, "speaker": "agent", "start_ms": 0, "end_ms": 2000, "text": "Здравствуйте!"},
        {"idx": 1, "speaker": "client", "start_ms": 2100, "end_ms": 4000, "text": "Какая у вас цена?"},
        {"idx": 2, "speaker": "agent", "start_ms": 4100, "end_ms": 6000,
         "text": "Так, отлично, наша система самая лучшая."},
    ]
    findings = detect_findings(segs)
    o = next(f for f in findings if f.kind == "objection")
    assert o.type == "price"
    assert o.response_status == "handled_partial"  # ответил, но по-другому
    assert handled_success_ratio([o]) == 0.0


def test_agent_open_questions():
    segs = _segs()
    assert agent_open_questions(segs) == 1  # "Какими объёмами вы торгуете?"


def test_all_findings_have_quotes_and_timing():
    """Инвариант объяснимости: ни одной находки без цитаты и таймкода."""
    for f in detect_findings(_segs()):
        assert f.span_text
        assert f.end_ms > f.start_ms or f.kind == "signal"
