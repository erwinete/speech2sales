[English](README.md) | [Русский](README-ru.md)

# Polylog — self-hosted speech analytics for sales teams

Open-source, self-hosted speech analytics for B2B sales departments (CIS-friendly):
call recordings in → automatic transcript with speaker roles → rule + NLI analysis
(objections, signals) → rubric scoring with quoted evidence → risk insights → web UI.

```
PBX/CRM → connector (webhook / SFTP / SQL / HTTP upload)
        → pipeline: normalize → ASR (GigaAM) → diarization (pyannote)
          → rules+NLI → scoring → embeddings (pgvector)
        → API (FastAPI) → Web UI (React)
```

## Features

- **ASR**: GigaAM-v3-e2e-rnnt (Sber, MIT) — WER 5.05% on a phone-speech golden set;
  Whisper-large-v3-turbo backend for harsh field recordings; per-backend registry.
- **Diarization**: stereo channel mapping with runtime auto-flip (marker-based)
  + pyannote speaker-diarization-3.1 for mono; agent role detection from sales-speech
  markers, optional agent voiceprints (wespeaker embeddings, calibrated threshold).
- **Analysis**: objection taxonomy (rules + RuBERT NLI verification), conversation
  signals, talk-ratio/pause metrics, per-call client sentiment (−1…+1).
- **Scoring**: rubric engine with quoted evidence; default B2B rubric, versioned.
- **Customer 360**: contact registry with risk/score/sentiment badges and filters,
  call chain timeline (#1→#N with gaps), relationship graph, similar calls (pgvector kNN),
  recurring unresolved objections ("Unresolved Repeat"), rule-based Next Best Action.
- **Insights feed**: risk and repeat-objection cards with severity filters, ack/dismiss;
  periodic jobs (daily 06:00 refresh, nightly ASR regression at 03:00).
- **Connectors**: Asterisk/FreePBX (full), amoCRM (OAuth2 + push), Bitrix24
  (webhook + pull), Cisco UCM (CDR), Oktell (MS SQL), MightyCall (REST),
  generic SFTP-monitor and SQL-CDR for anything else.
- **Security posture**: API-key auth, HMAC webhook signatures, PII detection stage,
  152-ФЗ-oriented design (self-hosted, recordings never leave your infra).

## Monorepo layout

| Path | What |
|---|---|
| `docs/` | Design docs 01–09 + ADR log (architecture, security, datasets, predictive) |
| `schemas/` | Exchange format JSON Schema + shared objection taxonomy |
| `core/` | FastAPI app, pipeline, connectors, insights, risk, Alembic migrations |
| `web/` | React UI (dashboard, call review screen, Customer 360) |
| `tools/` | Dev-stand (Asterisk + injector), dataset tooling |
| `docker/` | Dockerfiles (api, worker) |

## Quick start

```bash
# core + tests (no ML dependencies needed, sqlite)
cd core
pip install -e ".[dev]"
pytest -q

# API (reads POLYLOG_* from environment / .env)
uvicorn polylog.api.main:app --port 8000
# OpenAPI: http://localhost:8000/docs
```

Full environment with dev stand:

```bash
docker compose --profile base --profile devstand up -d
docker compose --profile devstand run --rm injector
# worker + periodic jobs (insights refresh, nightly regression):
docker compose --profile worker up -d worker
```

Upload a call without a PBX (generic HTTP connector):

```bash
curl -X POST http://localhost:8000/api/v1/calls/upload \
  -H "X-Api-Key: dev-insecure-token" \
  -F "file=@call.wav" -F "direction=outbound" \
  -F "phone_from=101" -F "phone_to=+79001234567"
```

Idempotent: `external_id` is the content sha256 — re-uploads don't duplicate.

## Configuration (selected)

| Variable | Purpose |
|---|---|
| `POLYLOG_DATABASE_URL` | asyncpg DSN (Postgres) or sqlite for dev |
| `POLYLOG_ASR_BACKEND` | `gigaam-v3-e2e-rnnt` (default) / `whisper-large-v3-turbo` / `stub` |
| `POLYLOG_DIARIZATION=pyannote` | enable mono diarization (needs `HF_TOKEN`) |
| `POLYLOG_VOICEPRINT=1` | agent voiceprints (enrollment from stereo, mono role hints) |
| `POLYLOG_SFTP_*` | live SFTP-monitor connector config |

Full list: [.env.example](.env.example).

## Tests

```bash
cd core
pytest -q          # 151 passed (ML backends stubbed, sqlite)
ruff check polylog tests
```

## Documentation

Design docs (Russian): [docs/01-architecture.md](docs/01-architecture.md),
[02-modules](docs/02-modules.md), [03-data-model](docs/03-data-model.md),
[04-security-152fz](docs/04-security-152fz.md), [05-exchange-format](docs/05-exchange-format.md),
[06-datasets](docs/06-datasets.md), [07-nli-rubert-reuse](docs/07-nli-rubert-reuse.md),
[08-predictive-analytics](docs/08-predictive-analytics.md), [09-dev-stand](docs/09-dev-stand.md),
[ADR log](docs/adr.md).

## License

AGPLv3 (intent, ADR-10). Third-party models keep their own licenses:
GigaAM (MIT), pyannote (MIT), Whisper (MIT), ruBERT/NLI weights are not redistributed.
