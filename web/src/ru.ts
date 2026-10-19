// Русификация внутренней терминологии (doc 08: дашборд — человекочитаемый).

export const STATE_RU: Record<string, string> = {
  discovered: "найден",
  downloading: "скачивается",
  downloaded: "скачан",
  normalized: "нормализован",
  diarized: "размечен по ролям",
  transcribed: "транскрибирован",
  lexicon_corrected: "постобработан",
  analyzed: "проанализирован",
  scored: "оценён",
  embedded: "проиндексирован",
  risk_assessed: "оценён риск",
  done: "готов",
  failed: "ошибка",
};

export const OBJECTION_RU: Record<string, string> = {
  price: "Цена",
  existing_supplier: "Есть поставщик",
  send_offer: "Просьба прислать КП",
  timing: "Сроки",
  no_authority: "Не тот, кто решает",
  trust: "Доверие к компании",
  not_interested: "Не интересно",
  legal_contract: "Договор / юридические",
  competitor_compare: "Сравнивают с конкурентом",
  other: "Другое",
};

export const RESPONSE_RU: Record<string, string> = {
  handled_success: "отработано успешно",
  handled_partial: "отработано частично",
  ignored: "проигнорировано",
  deferred: "отложено («вышлю КП»)",
  failed: "не отработано",
};

export const SIGNAL_RU: Record<string, string> = {
  next_step_agreed: "Согласован следующий шаг",
  budget_mentioned: "Упомянут бюджет",
  timeline_mentioned: "Упомянуты сроки",
  authority_confirmed: "Подтверждено ЛПР",
  details_requested: "Запрошены детали",
  demo_positive: "Позитив на демо",
};

export const DIRECTION_RU: Record<string, string> = {
  inbound: "← входящий",
  outbound: "→ исходящий",
  internal: "внутренний",
};

export const ru = (dict: Record<string, string>, key: string | null | undefined, fallback = "—"): string =>
  (key && dict[key]) || fallback;
