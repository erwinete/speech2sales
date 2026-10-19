"""Сентимент клиента (правила) и Next Best Action (rule-engine)."""

from conftest import AUTH, wav_bytes

from polylog.insights.nba import next_best_actions
from polylog.nlp.sentiment import client_sentiment, sentiment_emoji, sentiment_of_text


def test_sentiment_lexicons():
    pos, neg = sentiment_of_text("да, конечно, интересно, пришлите предложение")
    assert pos >= 2 and neg == 0
    pos, neg = sentiment_of_text("это дорого, не нужно, не интересно")
    assert pos == 0 and neg >= 2


def test_client_sentiment_ignores_agent():
    """Считаем только клиентские реплики: позитив оператора не поднимает тон."""
    utts = [
        {"speaker": "agent", "text": "рад помочь, всё отлично, давайте"},
        {"speaker": "client", "text": "не интересно, дорого"},
        {"speaker": "client", "text": "хорошо, давайте посмотрим"},
    ]
    res = client_sentiment(utts)
    # «хорошо», «давайте», «посмотрим» — 3 позитива; «не интересно», «дорого» — 2 негатива
    assert res["positive"] == 3
    assert res["negative"] == 2
    assert res["score"] == 0.2
    assert res["client_words"] > 0


def test_sentiment_emoji():
    assert sentiment_emoji(0.5) == "😊"
    assert sentiment_emoji(-0.5) == "☹"
    assert sentiment_emoji(0.0) == "😐"
    assert sentiment_emoji(None) == ""


def test_nba_priorities():
    risk = {"band": "high", "score": 70, "factors": [{"feature": "days_silence", "value": 9}]}
    repeats = [{"type": "price", "calls": 3, "last_status": "ignored"}]
    last = {
        "score_total": 30,
        "objections": [{"type": "price", "response_status": "ignored"}],
        "signals": ["next_step_agreed"],
    }
    items = next_best_actions(risk, repeats, {"calls_total": 5}, last, None)
    actions = [i["action"] for i in items]
    # приоритеты: смена подхода → перезвонить → КП → подтвердить → коучинг; топ-3
    assert actions == ["Сменить подход по возражению", "Перезвонить клиенту", "Отправить КП с ценами"]
    assert all(i["reason"] for i in items)


def test_nba_empty_and_fallback():
    # нет звонков — рекомендаций нет
    assert next_best_actions(None, [], {"calls_total": 0}, None, None) == []
    # звонки есть, критичных сигналов нет → поддержка контакта
    items = next_best_actions(
        {"band": "low", "score": 5, "factors": []},
        [],
        {"calls_total": 2},
        {"score_total": 90, "objections": [], "signals": []},
        None,
    )
    assert items[0]["action"] == "Поддерживать контакт"


def test_nba_negative_sentiment():
    items = next_best_actions(
        {"band": "low", "score": 5, "factors": []},
        [],
        {"calls_total": 1},
        {"score_total": 80, "objections": [], "signals": []},
        {"score": -0.5, "positive": 0, "negative": 3},
    )
    assert any(i["action"] == "Снизить накал" for i in items)


async def test_card_sentiment_and_nba(app_client):
    """Пайплайн считает client_sentiment → карточка отдаёт тон/тренд и NBA."""
    client, _ = app_client
    for i, size in enumerate((2.0, 2.5)):
        r = await client.post(
            "/api/v1/calls/upload", headers=AUTH,
            files={"file": (f"sn{i}.wav", wav_bytes(size), "audio/wav")},
            data={"direction": "outbound", "phone_to": "+79006660011"},
        )
        assert r.status_code == 201, r.text
    contact_id = r.json()["call"]["contact_id"]

    r = await client.get(f"/api/v1/contacts/{contact_id}/card", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    # у обоих звонков есть сентимент (stub-транскрипт без маркеров → 0.0)
    assert all(c["sentiment"] is not None for c in body["calls"])
    assert body["stats"]["sentiment_last"] is not None
    assert body["stats"]["sentiment_trend"] is not None  # два звонка → тренд есть
    # NBA непустой: есть звонки → минимум «Поддерживать контакт»/коучинг
    assert len(body["nba"]["items"]) >= 1
    assert all(i["action"] and i["reason"] for i in body["nba"]["items"])


async def test_registry_sentiment_fields(app_client):
    client, _ = app_client
    await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("r.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79006660022"},
    )
    r = await client.get("/api/v1/contacts/search", headers=AUTH)
    row = next(i for i in r.json()["items"] if i["phones"] == ["+79006660022"])
    assert row["sentiment_last"] is not None
    assert row["sentiment_trend"] is None  # один звонок — тренда нет
