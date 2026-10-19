[English](README.md) | [Русский](README-ru.md)

# Полилог — self-hosted речевая аналитика для отделов продаж

Опенсорс, self-hosted речевая аналитика для B2B-отделов продаж:
записи звонков на входе → автоматический транскрипт с ролями спикеров →
анализ правилами + NLI (возражения, сигналы) → скоринг по рубрике с цитатами →
инсайты о рисках → веб-интерфейс.

```
АТС/CRM → коннектор (webhook / SFTP / SQL / HTTP-загрузка)
        → пайплайн: нормализация → ASR (GigaAM) → диаризация (pyannote)
          → правила+NLI → скоринг → эмбеддинги (pgvector)
        → API (FastAPI) → веб-интерфейс (React)
```

## Возможности

- **ASR**: GigaAM-v3-e2e-rnnt (Сбер, MIT) — WER 5,05% на телефонном эталоне;
  бэкенд Whisper-large-v3-turbo для тяжёлых полевых записей; реестр бэкендов.
- **Диаризация**: стерео-каналы с runtime-автофлипом (по маркерам)
  + pyannote speaker-diarization-3.1 для mono; роль агента — по маркерам
  продающей речи; опциональные голосовые отпечатки агентов (wespeaker,
  откалиброванный порог).
- **Анализ**: таксономия возражений (правила + верификация RuBERT-NLI),
  сигналы разговора, метрики (доля речи, паузы), сентимент клиента −1…+1.
- **Скоринг**: рубричный движок с цитатами-доказательствами; дефолтная B2B-рубрика, версионирование.
- **Customer 360**: реестр клиентов с бейджами риска/скора/тона и фильтрами,
  лента-цепочка звонков (#1→#N с паузами), граф связей, похожие звонки (pgvector kNN),
  повторяющиеся нерешённые возражения («Unresolved Repeat»), Next Best Action по правилам.
- **Лента инсайтов**: карточки рисков и повторов с severity-фильтрами, ack/dismiss;
  периодические джобы (обновление инсайтов 06:00, ночной регресс ASR 03:00).
- **Коннекторы**: Asterisk/FreePBX (полный), amoCRM (OAuth2 + push), Битрикс24
  (webhook + pull), Cisco UCM (CDR), Oktell (MS SQL), MightyCall (REST),
  универсальные SFTP-monitor и SQL-CDR для остальных АТС.
- **Безопасность**: авторизация по API-ключу, HMAC-подпись вебхуков, стадия
  детекции ПДн, дизайн под 152-ФЗ (self-hosted, записи не покидают вашу инфраструктуру).

## Структура монорепо

| Путь | Что |
|---|---|
| `docs/` | Дизайн-документы 01–09 + журнал ADR |
| `schemas/` | JSON Schema обменного формата + общая таксономия возражений |
| `core/` | FastAPI-приложение, пайплайн, коннекторы, инсайты, риск, Alembic |
| `web/` | React UI (дашборд, экран звонка, Customer 360) |
| `tools/` | Dev-стенд (Asterisk + инжектор), инструменты датасетов |
| `docker/` | Dockerfile (api, worker) |

## Быстрый старт

```bash
# ядро + тесты (ML-зависимости не нужны, sqlite)
cd core
pip install -e ".[dev]"
pytest -q

# API (читает POLYLOG_* из окружения / .env)
uvicorn polylog.api.main:app --port 8000
# OpenAPI: http://localhost:8000/docs
```

Полное окружение с dev-стендом:

```bash
docker compose --profile base --profile devstand up -d
docker compose --profile devstand run --rm injector
# воркер + периодические джобы (инсайты, ночной регресс):
docker compose --profile worker up -d worker
```

Загрузка звонка без АТС (generic HTTP-коннектор):

```bash
curl -X POST http://localhost:8000/api/v1/calls/upload \
  -H "X-Api-Key: dev-insecure-token" \
  -F "file=@call.wav" -F "direction=outbound" \
  -F "phone_from=101" -F "phone_to=+79001234567"
```

Идемпотентно: `external_id` = sha256 контента — повторная загрузка не создаёт дубль.

## Конфигурация (выборочно)

| Переменная | Назначение |
|---|---|
| `POLYLOG_DATABASE_URL` | DSN asyncpg (Postgres) или sqlite для dev |
| `POLYLOG_ASR_BACKEND` | `gigaam-v3-e2e-rnnt` (по умолчанию) / `whisper-large-v3-turbo` / `stub` |
| `POLYLOG_DIARIZATION=pyannote` | включить диаризацию mono (нужен `HF_TOKEN`) |
| `POLYLOG_VOICEPRINT=1` | голосовые отпечатки агентов (enrollment из стерео, подсказка ролей на mono) |
| `POLYLOG_SFTP_*` | конфиг live-коннектора SFTP-monitor |

Полный список: [.env.example](.env.example).

## Тесты

```bash
cd core
pytest -q          # 151 passed (ML-бэкенды подменены, sqlite)
ruff check polylog tests
```

## Документация

Дизайн-документы: [docs/01-architecture.md](docs/01-architecture.md) (архитектура),
[02-modules](docs/02-modules.md) (модули), [03-data-model](docs/03-data-model.md) (данные),
[04-security-152fz](docs/04-security-152fz.md) (безопасность/152-ФЗ),
[05-exchange-format](docs/05-exchange-format.md) (обменный формат),
[06-datasets](docs/06-datasets.md) (датасеты), [07-nli-rubert-reuse](docs/07-nli-rubert-reuse.md) (NLI),
[08-predictive-analytics](docs/08-predictive-analytics.md) (предиктив),
[09-dev-stand](docs/09-dev-stand.md) (dev-стенд), [ADR](docs/adr.md).

## Лицензия

AGPLv3 (намерение, ADR-10). Сторонние модели сохраняют свои лицензии:
GigaAM (MIT), pyannote (MIT), Whisper (MIT); веса ruBERT/NLI не распространяются.
