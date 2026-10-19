# Dev-стенд «Полилога» (doc 09)

Dockerized Asterisk + инжектор звонков из датасета. Проверяет реальный путь
ингеста (CDR + monitor-файлы → коннектор → пайплайн) без пилотного заказчика.

## Быстрый старт

```bash
# 1. Поднять платформу + стенд
docker compose --profile base --profile devstand up -d

# 2. Положить датасет (InfoBayAI dual-channel) в ./data/datasets/infoabayai/dual

# 3. Инжектировать 20 звонков (детерминированно, seed=42)
docker compose --profile devstand run --rm injector

# 4. Через ≤10 мин все звонки должны быть state=done (S1–S2, doc 09 §5)
curl -s http://localhost:8000/api/v1/calls -H "X-Api-Key: dev-insecure-token"
```

## Что проверяем (doc 09 §5)

| Проверка | Как |
|---|---|
| S1 smoke | 1 звонок E2E ≤ 10 мин, roles по каналам |
| S2 батч | 100 звонков overnight, DLQ пуст |
| S3 роли | dual-channel → 100% верных ролей |
| S5 WER | sidecar-транскрипты + реальный ASR-бэкенд (M1) |
| S6 регресс | тот же seed → сравнение метрик до/после обновления моделей |

## Ограничения

Стенд эмулирует артефакты АТС (CDR + файлы), не сигналинг — это проверяет наш
код, но не интеграцию с реальной инфраструктурой заказчика (зона пилота M2+).
