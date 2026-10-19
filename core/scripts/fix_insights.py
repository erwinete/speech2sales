from pathlib import Path

# 1) main.py: добавить Insight в импорт AuditLog (строка внутри call_audio)
p = Path(r"F:\Z\rechevaua analitika\core\polylog\api\main.py")
t = p.read_text(encoding="utf-8")
t = t.replace(
    "        from polylog.models.system import AuditLog\n",
    "        from polylog.models.system import AuditLog, Insight\n",
    1,
)
# верхнеуровневый импорт для новых эндпоинтов
t = t.replace(
    "from polylog.models.calls import Call\n",
    "from polylog.models.calls import Call\nfrom polylog.models.system import Insight\n",
    1,
)
p.write_text(t, encoding="utf-8")

# 2) Insight.contact_id — колонка в модели
p2 = Path(r"F:\Z\rechevaua analitika\core\polylog\models\system.py")
t2 = p2.read_text(encoding="utf-8")
t2 = t2.replace(
    "    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)\n"
    "    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)\n"
    "    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)\n"
    "    period_start",
    "    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)\n"
    "    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)\n"
    "    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)\n"
    "    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)\n"
    "    period_start",
    1,
)
p2.write_text(t2, encoding="utf-8")

# 3) risk_for_contact: naive-datetime фикс
p3 = Path(r"F:\Z\rechevaua analitika\core\polylog\risk\__init__.py")
t3 = p3.read_text(encoding="utf-8")
t3 = t3.replace(
    "    last = calls[0].started_at\n"
    "    days_silence = max(0, (datetime.now(UTC) - last).days)",
    "    last = calls[0].started_at\n"
    "    if last.tzinfo is None:  # sqlite возвращает naive\n"
    "        last = last.replace(tzinfo=UTC)\n"
    "    days_silence = max(0, (datetime.now(UTC) - last).days)",
    1,
)
p3.write_text(t3, encoding="utf-8")
print("3 fixes applied")
