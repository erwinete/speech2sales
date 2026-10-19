"""Ручная правка ролей реплик (doc 02 §2.3 п.3): API сохраняет Label и
меняет speaker сегмента."""

import uuid

from conftest import AUTH, wav_bytes


async def test_segment_role_flip_and_label(app_client):
    client, app = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("c.wav", wav_bytes(11.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79001230001"},
    )
    call_id = r.json()["call"]["id"]

    detail = (await client.get(f"/api/v1/calls/{call_id}", headers=AUTH)).json()
    idx = detail["segments"][0]["idx"]
    before = detail["segments"][0]["speaker"]

    r = await client.post(
        f"/api/v1/calls/{call_id}/segments/{idx}/role", headers=AUTH,
        data={"speaker": "client" if before == "agent" else "agent"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["speaker"] in ("agent", "client")

    # сегмент изменился
    detail2 = (await client.get(f"/api/v1/calls/{call_id}", headers=AUTH)).json()
    after = next(s for s in detail2["segments"] if s["idx"] == idx)["speaker"]
    assert after != before

    # Label сохранён (before/after)
    from sqlalchemy import select

    from polylog.models.system import Label

    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as s:
        rows = (
            (
                await s.execute(
                    select(Label).where(
                        Label.call_id == uuid.UUID(call_id), Label.target_type == "segment"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].before["speaker"] == before
        assert rows[0].after["speaker"] == after


async def test_segment_role_validation(app_client):
    client, _ = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("c.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79001230002"},
    )
    call_id = r.json()["call"]["id"]

    # неверная роль
    r = await client.post(
        f"/api/v1/calls/{call_id}/segments/0/role", headers=AUTH,
        data={"speaker": "boss"},
    )
    assert r.status_code == 422

    # несуществующий сегмент
    r = await client.post(
        f"/api/v1/calls/{call_id}/segments/999/role", headers=AUTH,
        data={"speaker": "agent"},
    )
    assert r.status_code == 404

    # несуществующий звонок
    r = await client.post(
        f"/api/v1/calls/{uuid.uuid4()}/segments/0/role", headers=AUTH,
        data={"speaker": "agent"},
    )
    assert r.status_code == 404
