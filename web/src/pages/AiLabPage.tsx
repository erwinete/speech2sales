/** Экран «ИИ-Анализатор (LLM & MCP)» (ТЗ v3.0 §5, AI Lab).
    Блок 1 — выборка данных (3 режима, период, фильтры);
    Блок 2 — слайдер очистки ПДн (152-ФЗ Safe Mode) с предпросмотром;
    Блок 3 — вкладки: прямой анализ через OpenRouter/OpenAI-compatible API
    и нативное MCP-подключение (Claude Code, Codex, ZCode, Cursor). */
import React from "react";
import { api, AiContextRequest, AiPreset, PreviewContextResponse, PiiSanitizerConfig } from "../api";
import { Badge, EmptyState, Icon } from "../components/ui";
import { useToast } from "../context/app";

const MODES = [
  {
    id: "rubert_scores",
    title: "Скоринг RuBERT и чек-листы",
    icon: "coach",
    hint: "Оценки по рубрике, цитаты-доказательства, NLI-проверки ответов на вопросы и ошибки скрипта",
  },
  {
    id: "problematic_calls",
    title: "Проблемные звонки и риски",
    icon: "alert",
    hint: "Клиенты в зоне риска (Scorecard/CatBoost), повторяющиеся возражения Unresolved Repeat и проваленные звонки",
  },
  {
    id: "transcripts_range",
    title: "Транскрипты за период",
    icon: "phone",
    hint: "Полные тексты разговоров за выбранный диапазон дат для глубокого поиска инсайтов и паттернов",
  },
] as const;

const DAY_PRESETS = [7, 14, 30, 90];

const PROVIDERS = [
  { id: "openrouter", label: "OpenRouter (openrouter.ai)", url: "https://openrouter.ai/api/v1" },
  { id: "local", label: "Локальная модель (Ollama / vLLM / LM Studio)", url: "http://localhost:11434/v1" },
  { id: "custom", label: "Свой OpenAI-compatible Endpoint", url: "" },
];

/** SanitizedReportRenderer (DEF-05, ТЗ v4.0 §8.1): мини-рендер Markdown без
    внешних зависимостей. decode=true — локальная расшифровка алиасов ПДн в
    браузере по alias_map (значения не покидали сервер); [CALL_#N] — всегда
    кликабельный бейдж перехода к звонку. */
const ID_TOKEN_RE = /\[(CALL|CONTACT|DEAL)_#(\d+)\]/;
const ANY_ALIAS_RE = /\[[A-ZА-ЯЁ0-9_#]+\]/g;

function MarkdownView({ text, aliasMap, onOpenCall, decode = false }: {
  text: string;
  aliasMap: Record<string, string> | null;
  onOpenCall?: (id: string) => void;
  decode?: boolean;
}) {
  const renderLine = (line: string, key: number) => {
    // Текст вставляем только как React-строки (авто-экранирование)
    const parts: React.ReactNode[] = [];
    let last = 0;
    ANY_ALIAS_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = ANY_ALIAS_RE.exec(line)) !== null) {
      if (m.index > last) parts.push(line.slice(last, m.index));
      const alias = m[0];
      const real = aliasMap?.[alias];
      const idMatch = ID_TOKEN_RE.exec(alias);
      if (idMatch) {
        const kind = idMatch[1];
        if (kind === "CALL" && real && onOpenCall) {
          parts.push(
            <a key={`${key}-${m.index}`} href={`/calls/${real}`} className="badge brand"
               onClick={(e) => { e.preventDefault(); onOpenCall(real); }}>
              <Icon name="play" size={11} /> {alias}
            </a>,
          );
        } else if (kind === "CONTACT" && decode) {
          parts.push(<span key={`${key}-${m.index}`} className="badge violet">{real ?? alias}</span>);
        } else {
          parts.push(<span key={`${key}-${m.index}`} className="badge neutral">{alias}</span>);
        }
      } else if (decode && real) {
        parts.push(real); // DEF-05: локальная расшифровка ПДн-алиасов
      } else {
        parts.push(<span key={`${key}-${m.index}`} className="badge neutral">{alias}</span>);
      }
      last = m.index + alias.length;
    }
    if (last < line.length) parts.push(line.slice(last));
    return parts;
  };

  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  let listBuf: string[] = [];
  const flushList = (k: number) => {
    if (listBuf.length) {
      blocks.push(<ul key={`ul-${k}`}>{listBuf.map((li, i) => <li key={i}>{renderLine(li, k * 100 + i)}</li>)}</ul>);
      listBuf = [];
    }
  };
  lines.forEach((line, i) => {
    if (line.startsWith("- ")) { listBuf.push(line.slice(2)); return; }
    flushList(i);
    if (!line.trim()) return;
    if (line.startsWith("# ")) blocks.push(<h2 key={i} style={{ fontSize: 18 }}>{renderLine(line.slice(2), i)}</h2>);
    else if (line.startsWith("## ")) blocks.push(<h3 key={i} style={{ marginTop: 14 }}>{renderLine(line.slice(3), i)}</h3>);
    else if (line.startsWith("> ")) blocks.push(<div key={i} style={{ borderLeft: "3px solid var(--border-strong)", paddingLeft: 10, color: "var(--text-secondary)" }}>{renderLine(line.slice(2), i)}</div>);
    else if (line.startsWith("|")) blocks.push(<div key={i} className="mono" style={{ fontSize: 12 }}>{renderLine(line, i)}</div>);
    else blocks.push(<p key={i}>{renderLine(line, i)}</p>);
  });
  flushList(lines.length);
  return <div className="md-view">{blocks}</div>;
}

export default function AiLabPage({ onOpenCall }: { onOpenCall: (id: string) => void }) {
  const { push } = useToast();
  const [mode, setMode] = React.useState<AiContextRequest["mode"]>("rubert_scores");
  const [days, setDays] = React.useState(30);
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  const [riskBand, setRiskBand] = React.useState("high");
  const [scoreMax, setScoreMax] = React.useState<string>("");
  const [minDuration, setMinDuration] = React.useState("");
  const [objectionType, setObjectionType] = React.useState("");
  const [limit, setLimit] = React.useState(30);
  const [agentName, setAgentName] = React.useState("");

  const [pii, setPii] = React.useState<PiiSanitizerConfig>({
    enabled: true,
    strip_names: true,
    strip_phones_emails: true,
    strip_orders_contracts: true,
    strip_internal_ids: true,
    strip_company_names: false,
    custom_stop_words: [],
  });
  const [stopWords, setStopWords] = React.useState("");

  const [tab, setTab] = React.useState<"llm" | "mcp">("llm");
  const [presets, setPresets] = React.useState<AiPreset[]>([]);
  const [recommended, setRecommended] = React.useState<{ id: string; label: string }[]>([]);
  const [systemPrompt, setSystemPrompt] = React.useState("");
  const [userPrompt, setUserPrompt] = React.useState("");
  const [provider, setProvider] = React.useState("openrouter");
  const [baseUrl, setBaseUrl] = React.useState("https://openrouter.ai/api/v1");
  const [apiKey, setApiKey] = React.useState("");
  const [showKey, setShowKey] = React.useState(false);
  const [model, setModel] = React.useState("anthropic/claude-3.7-sonnet");
  const [modelList, setModelList] = React.useState<{ id: string; name: string | null }[]>([]);
  const [temperature, setTemperature] = React.useState(0.2);
  const [maxTokens, setMaxTokens] = React.useState(4096);

  const [preview, setPreview] = React.useState<PreviewContextResponse | null>(null);
  const [previewBusy, setPreviewBusy] = React.useState(false);
  const [analyzing, setAnalyzing] = React.useState(false);
  const [result, setResult] = React.useState<{ markdown: string; aliasMap: Record<string, string>; usage?: Record<string, number> } | null>(null);
  const [runs, setRuns] = React.useState<{ id: string; status: string; model_id: string; created_at: string; prompt_text: string }[]>([]);
  // DEF-05: локальная расшифровка алиасов ПДн в браузере (значения не покидали сервер)
  const [decodeAliases, setDecodeAliases] = React.useState(false);
  // DEF-03: потоковый вывод отчёта через POST /ai/analyze/stream
  const [streaming, setStreaming] = React.useState(true);
  // V5-06: Map-Reduce по батчам из 15 звонков (для больших выборок)
  const [mapReduce, setMapReduce] = React.useState(false);
  // V5-03: сценарий тренажёра из кластера возражений
  const [scenarioBusy, setScenarioBusy] = React.useState(false);
  const [reasoning, setReasoning] = React.useState("");
  // DEF-07: предвыборка из других экранов (?mode=…&call_ids=…&agent_name=…&risk_band=…)
  const [callIds, setCallIds] = React.useState<string[]>([]);

  const [mcpCfg, setMcpCfg] = React.useState<Awaited<ReturnType<typeof api.mcpConfig>> | null>(null);
  const [harness, setHarness] = React.useState("claude_code");
  // V5-06: интерактивный MCP Playground (тест тулзов/ресурсов/промптов в браузере)
  const [pgMethod, setPgMethod] = React.useState("tools/list");
  const [pgTool, setPgTool] = React.useState("polylog_get_problematic_calls");
  const [pgToolArgs, setPgToolArgs] = React.useState('{"days": 30}');
  const [pgResource, setPgResource] = React.useState("polylog://stats/summary");
  const [pgPrompt, setPgPrompt] = React.useState("churn_audit");
  const [pgRequest, setPgRequest] = React.useState("");
  const [pgResponse, setPgResponse] = React.useState("");
  const [pgMs, setPgMs] = React.useState<number | null>(null);
  const [pgBusy, setPgBusy] = React.useState(false);

  React.useEffect(() => {
    api.aiPresets().then((p) => {
      setPresets(p.presets);
      setRecommended(p.recommended_models);
      setSystemPrompt(p.system_prompt_default);
      if (p.provider_settings.base_url) setBaseUrl(p.provider_settings.base_url);
      if (p.provider_settings.model) setModel(p.provider_settings.model);
    }).catch((e) => push("error", `Пресеты: ${String(e).slice(0, 100)}`));
    api.aiRuns().then((r) => setRuns(r.items)).catch(() => undefined);
    api.mcpConfig(true).then(setMcpCfg).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // DEF-07: параметры быстрого перехода («✨ Разобрать в ИИ») из других экранов
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const modeQ = q.get("mode");
    if (modeQ === "rubert_scores" || modeQ === "problematic_calls" || modeQ === "transcripts_range") {
      setMode(modeQ);
    }
    const ids = q.get("call_ids");
    if (ids) setCallIds(ids.split(",").map((s) => s.trim()).filter(Boolean));
    const agentQ = q.get("agent_name");
    if (agentQ) setAgentName(agentQ);
    const bandQ = q.get("risk_band");
    if (bandQ) setRiskBand(bandQ);
  }, []);

  const buildRequest = () => ({
    mode,
    days,
    date_from: dateFrom || null,
    date_to: dateTo || null,
    risk_band: mode === "problematic_calls" ? riskBand : null,
    score_max: scoreMax ? Number(scoreMax) : null,
    min_duration_sec: mode === "transcripts_range" && minDuration ? Number(minDuration) : null,
    objection_type: objectionType || null,
    agent_name: agentName || null,
    limit_calls: limit,
    call_ids: callIds,
    pii,
  });

  const doPreview = async () => {
    setPreviewBusy(true);
    try {
      const body = await api.previewContext(buildRequest());
      setPreview(body);
    } catch (e) {
      push("error", `Предпросмотр: ${String(e).slice(0, 140)}`);
    } finally {
      setPreviewBusy(false);
    }
  };

  const applyPreset = (p: AiPreset) => {
    setMode(p.mode as typeof mode);
    setSystemPrompt(p.system_prompt);
    setUserPrompt(p.user_prompt);
    setTab("llm");
  };

  // V5-03: сценарий тренажёра из кластера возражений текущих фильтров
  const makeClusterScenario = async () => {
    setScenarioBusy(true);
    try {
      const scn = await api.scenarioFromCluster({
        days,
        limit: 10,
        objection_type: objectionType || null,
      });
      const blob = new Blob([JSON.stringify(scn, null, 1)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${scn.scenario_id}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      push("success", `Сценарий «${scn.title}» готов`);
    } catch (e) {
      push("error", `Сценарий: ${String(e).slice(0, 140)}`);
    } finally {
      setScenarioBusy(false);
    }
  };

  const runAnalysis = async () => {
    if (!userPrompt.trim()) { push("error", "Напишите задание для ИИ или выберите пресет"); return; }
    if (!apiKey.trim()) { push("error", "Укажите API-ключ провайдера"); return; }
    setAnalyzing(true);
    setResult(null);
    setReasoning("");
    const reqBody = {
      ...buildRequest(),
      provider,
      base_url: baseUrl,
      api_key: apiKey,
      model,
      system_prompt: systemPrompt,
      user_prompt: userPrompt,
      temperature,
      max_tokens: maxTokens,
      map_reduce: mapReduce,
    };
    try {
      if (streaming && !mapReduce) {
        // DEF-03: SSE-стриминг — чанки content/reasoning появляются по мере генерации
        let acc = "";
        let aliases: Record<string, string> = {};
        let usage: Record<string, number> | undefined;
        await api.aiAnalyzeStream(reqBody, (e) => {
          if (e.type === "meta") {
            aliases = (e.data.alias_map as Record<string, string>) ?? {};
            setResult({ markdown: "", aliasMap: aliases });
          } else if (e.type === "content") {
            acc += String(e.data.delta ?? "");
            setResult({ markdown: acc, aliasMap: aliases });
          } else if (e.type === "reasoning") {
            setReasoning((r) => r + String(e.data.delta ?? ""));
          } else if (e.type === "done") {
            usage = (e.data.token_usage as Record<string, number>) ?? undefined;
            setResult({ markdown: acc, aliasMap: aliases, usage });
            const n = Number(e.data.calls_count ?? 0);
            push("success", `ИИ-анализ готов (поток): ${n} звонков в выборке`);
          } else if (e.type === "error") {
            push("error", `Анализ: ${String(e.data.message ?? "").slice(0, 160)}`);
          }
        });
        setResult((prev) => ({ ...prev!, markdown: acc || prev?.markdown || "", aliasMap: aliases, usage }));
      } else {
        const body = await api.aiAnalyze(reqBody);
        setResult({ markdown: body.result_markdown, aliasMap: body.alias_map, usage: body.token_usage });
        push("success", `ИИ-анализ готов: ${body.calls_count} звонков в выборке`);
      }
      api.aiRuns().then((r) => setRuns(r.items)).catch(() => undefined);
    } catch (e) {
      push("error", `Анализ: ${String(e).slice(0, 160)}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const loadModels = async () => {
    try {
      const body = await api.aiModels(baseUrl, apiKey || undefined);
      setModelList(body.items);
      push("success", `Загружено моделей: ${body.items.length}`);
    } catch (e) {
      push("error", `Модели: ${String(e).slice(0, 140)}`);
    }
  };

  const downloadBundle = (kind: "md" | "json") => {
    if (!preview) return;
    const content = kind === "md"
      ? `${userPrompt || "Проанализируй данные речевой аналитики."}\n\n---\n\n${preview.context_preview}`
      : JSON.stringify({ prompt: userPrompt, ...preview.structured_bundle, pii_stats: preview.pii_stats }, null, 1);
    const blob = new Blob([content], { type: kind === "md" ? "text/markdown" : "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `polylog-ai-bundle-${Date.now()}.${kind}`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  // V5-06: MCP Playground — прямой JSON-RPC вызов POST /api/v1/mcp/rpc
  const runMcpCall = async () => {
    setPgBusy(true);
    setPgRequest("");
    setPgResponse("");
    setPgMs(null);
    const id = Date.now();
    let payload: Record<string, unknown>;
    if (pgMethod === "tools/call") {
      let args: Record<string, unknown> = {};
      try { args = JSON.parse(pgToolArgs || "{}"); } catch { args = {}; }
      payload = { jsonrpc: "2.0", id, method: "tools/call",
                  params: { name: pgTool, arguments: args } };
    } else if (pgMethod === "resources/read") {
      payload = { jsonrpc: "2.0", id, method: "resources/read", params: { uri: pgResource } };
    } else if (pgMethod === "prompts/get") {
      payload = { jsonrpc: "2.0", id, method: "prompts/get", params: { name: pgPrompt } };
    } else {
      payload = { jsonrpc: "2.0", id, method: pgMethod };
    }
    setPgRequest(JSON.stringify(payload, null, 1));
    const t0 = performance.now();
    try {
      const resp = await api.mcpRpc(payload);
      setPgMs(Math.round(performance.now() - t0));
      setPgResponse(JSON.stringify(resp, null, 1));
    } catch (e) {
      setPgMs(Math.round(performance.now() - t0));
      setPgResponse(`Ошибка вызова: ${String(e).slice(0, 300)}`);
    } finally {
      setPgBusy(false);
    }
  };

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      push("success", `${label}: скопировано`);
    } catch {
      push("error", "Буфер обмена недоступен");
    }
  };

  const cfg = mcpCfg?.harnesses[harness];

  const chip = (key: keyof PiiSanitizerConfig, label: string, hint: string) => (
    <label key={key} className="pii-chip" style={{ opacity: pii.enabled ? 1 : 0.5 }}>
      <input
        type="checkbox"
        disabled={!pii.enabled}
        checked={Boolean(pii[key])}
        onChange={(e) => setPii({ ...pii, [key]: e.target.checked })}
      />
      <span>{label}<br /><small>{hint}</small></span>
    </label>
  );

  const stats = preview?.pii_stats;

  return (
    <div>
      {/* ── Блок 1: выборка данных ── */}
      <div className="ai-mode-grid">
        {MODES.map((m) => (
          <button key={m.id} className={`card ai-mode ${mode === m.id ? "active" : ""}`} onClick={() => setMode(m.id)}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Icon name={m.icon} size={18} />
              <h3 style={{ margin: 0 }}>{m.title}</h3>
            </div>
            <small className="muted" style={{ display: "block", marginTop: 6 }}>{m.hint}</small>
          </button>
        ))}
      </div>

      <div className="card">
        <div className="filter-bar" style={{ margin: 0 }}>
          {DAY_PRESETS.map((d) => (
            <button key={d} className={days === d && !dateFrom && !dateTo ? "primary" : ""} onClick={() => { setDays(d); setDateFrom(""); setDateTo(""); }}>
              {d} дней
            </button>
          ))}
          <span className="muted">С</span>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <span className="muted">По</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          <span className="muted">|</span>
          <input placeholder="Менеджер (имя)" value={agentName} onChange={(e) => setAgentName(e.target.value)} style={{ width: 160 }} />
          {mode === "problematic_calls" && (
            <select value={riskBand} onChange={(e) => setRiskBand(e.target.value)}>
              <option value="high">Риск: высокий</option>
              <option value="medium">Риск: средний и выше</option>
            </select>
          )}
          {(mode === "rubert_scores" || mode === "problematic_calls") && (
            <input placeholder="Макс. скор (например 50)" value={scoreMax} onChange={(e) => setScoreMax(e.target.value)} style={{ width: 170 }} />
          )}
          {mode === "transcripts_range" && (
            <>
              <select value={""} onChange={(e) => e.target.value && setObjectionType(e.target.value)}>
                <option value="">Тип возражения: любой</option>
                <option value="price">price</option>
                <option value="timing">timing</option>
                <option value="competitor">competitor</option>
                <option value="authority">authority</option>
              </select>
              <input placeholder="Мин. длительность, сек" value={minDuration} onChange={(e) => setMinDuration(e.target.value)} style={{ width: 150 }} />
            </>
          )}
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[10, 25, 30, 50, 100].map((n) => <option key={n} value={n}>Лимит: {n}</option>)}
          </select>
        </div>
      </div>

      {/* ── Блок 2: слайдер ПДн (152-ФЗ) ── */}
      <div className={`card pii-card ${pii.enabled ? "on" : ""}`}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Icon name="shield" size={20} />
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: 0 }}>Удалять персональные данные и ID перед передачей в ИИ</h3>
            <small className="muted">152-ФЗ Safe Mode: ФИО → [ФИО_1], телефоны → [ТЕЛЕФОН_1], заказы → [ЗАКАЗ_ДОГОВОР_1], UUID → [CALL_#1]</small>
          </div>
          <button
            className={pii.enabled ? "primary" : ""}
            onClick={() => setPii({ ...pii, enabled: !pii.enabled })}
            aria-pressed={pii.enabled}
          >
            {pii.enabled ? "Защита активна ✓" : "Выключена"}
          </button>
        </div>
        {pii.enabled && (
          <>
            <div className="pii-chips">
              {chip("strip_names", "ФИО и имена", "Иванов И.И. → [ФИО_1]")}
              {chip("strip_phones_emails", "Телефоны и Email", "+7 900 … → [ТЕЛЕФОН_1]")}
              {chip("strip_orders_contracts", "Заказы, договоры, карты, паспорта", "заказ № 4512 → [ЗАКАЗ_ДОГОВОР_1]")}
              {chip("strip_internal_ids", "Внутренние и CRM ID", "UUID → [CALL_#1], [CONTACT_#1]")}
              {chip("strip_company_names", "Компании и адреса", "ООО Ромашка → [КОМПАНИЯ_1]")}
            </div>
            <div className="form-row" style={{ marginBottom: 0 }}>
              <label>Дополнительные стоп-слова через запятую (бренды, фамилии руководителей)</label>
              <input
                value={stopWords}
                onChange={(e) => {
                  setStopWords(e.target.value);
                  setPii({ ...pii, custom_stop_words: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) });
                }}
                placeholder="например: Ромашка, Проект Альфа"
              />
            </div>
          </>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          <button className="primary" disabled={previewBusy} onClick={() => void doPreview()}>
            <Icon name="search" size={14} /> {previewBusy ? "Сборка…" : "Предпросмотр выборки и проверка очистки"}
          </button>
          {preview && (
            <>
              <button onClick={() => downloadBundle("md")}><Icon name="download" size={14} /> Скачать .md для агента</button>
              <button onClick={() => downloadBundle("json")}><Icon name="download" size={14} /> Скачать .json датасет</button>
              <button onClick={() => copyText(`${userPrompt || "Проанализируй данные."}\n\n---\n\n${preview.context_preview}`, "Промпт + данные")}><Icon name="copy" size={14} /> Копировать промпт + данные</button>
            </>
          )}
        </div>
        {preview && (
          <div style={{ marginTop: 10 }}>
            <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", margin: "8px 0" }}>
              <div className="kpi"><div className="label">Звонков найдено</div><div className="value">{preview.calls_matched}</div></div>
              <div className="kpi"><div className="label">Примерный объём</div><div className="value">~{preview.estimated_tokens.toLocaleString("ru")}</div><div className="sub">токенов</div></div>
              <div className="kpi"><div className="label">Вырезано ПДн</div><div className="value">{stats?.total_redactions ?? 0}</div></div>
              <div className="kpi"><div className="label">Расшифровка</div><div className="sub" style={{ marginTop: 4 }}>
                ФИО: {stats?.by_category?.names ?? 0} · Тел: {stats?.by_category?.phones_emails ?? 0} · Заказы: {stats?.by_category?.orders_contracts ?? 0} · ID: {stats?.by_category?.internal_ids ?? 0}
              </div></div>
            </div>
            <details>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>Подготовленный пакет (очищенный текст)</summary>
              <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12, background: "var(--bg-subtle)", padding: 12, borderRadius: 8, maxHeight: 320, overflow: "auto" }}>
                {preview.context_preview}
              </pre>
            </details>
          </div>
        )}
      </div>

      {/* ── Блок 3: вкладки LLM / MCP ── */}
      <div className="tabs">
        <button className={`tab ${tab === "llm" ? "active" : ""}`} onClick={() => setTab("llm")}>Облачная / локальная LLM (OpenRouter API)</button>
        <button className={`tab ${tab === "mcp" ? "active" : ""}`} onClick={() => setTab("mcp")}>Нативный MCP / агентский харнес</button>
      </div>

      {tab === "llm" && (
        <div className="ai-grid">
          <div className="card">
            <h3>Подключение модели</h3>
            <div className="form-row">
              <label>Провайдер</label>
              <select value={provider} onChange={(e) => {
                setProvider(e.target.value);
                const p = PROVIDERS.find((x) => x.id === e.target.value);
                if (p?.url) setBaseUrl(p.url);
              }}>
                {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </div>
            {provider === "custom" && (
              <div className="form-row">
                <label>Base URL</label>
                <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://localhost:8000/v1" />
              </div>
            )}
            <div className="form-row">
              <label>API Key</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input type={showKey ? "text" : "password"} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-or-v1-…" style={{ flex: 1 }} />
                <button onClick={() => setShowKey(!showKey)}>{showKey ? "Скрыть" : "Показать"}</button>
              </div>
            </div>
            <div className="form-row">
              <label>Модель</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input value={model} onChange={(e) => setModel(e.target.value)} style={{ flex: 1 }} list="ai-models" />
                <button onClick={() => void loadModels()}>Загрузить список с сервера</button>
              </div>
              <datalist id="ai-models">
                {recommended.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                {modelList.map((m) => <option key={m.id} value={m.id}>{m.name ?? ""}</option>)}
              </datalist>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                {recommended.map((m) => (
                  <button key={m.id} className={model === m.id ? "primary" : ""} onClick={() => setModel(m.id)}>{m.label}</button>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <div className="form-row" style={{ flex: 1 }}>
                <label>Temperature</label>
                <input type="number" step="0.1" min="0" max="2" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
              </div>
              <div className="form-row" style={{ flex: 1 }}>
                <label>Max tokens</label>
                <input type="number" step="256" min="256" max="32000" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} />
              </div>
            </div>

            <h3 style={{ marginTop: 16 }}>Задание для ИИ</h3>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
              {presets.map((p) => (
                <button key={p.id} onClick={() => applyPreset(p)}>{p.title}</button>
              ))}
            </div>
            <div className="form-row">
              <label>Системный промпт</label>
              <textarea rows={4} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} />
            </div>
            <div className="form-row">
              <label>Задание (User Prompt)</label>
              <textarea rows={4} value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} placeholder="Что должен найти и подготовить ИИ" />
            </div>
            <label className="pii-chip" style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={streaming} onChange={(e) => setStreaming(e.target.checked)} />
              <span>Потоковый вывод (SSE)<br /><small>отчёт появляется чанками по мере генерации</small></span>
            </label>
            {limit > 20 && (
              <label className="pii-chip" style={{ marginBottom: 8 }}>
                <input type="checkbox" checked={mapReduce} onChange={(e) => setMapReduce(e.target.checked)} />
                <span>Глубокий Map-Reduce по батчам (15 звонков)<br />
                  <small>Map: выжимки фактов по батчам параллельно; Reduce: мастер-отчёт. Отключает SSE.</small></span>
              </label>
            )}
            <label className="pii-chip" style={{ marginBottom: 8 }}>
              <input type="checkbox" disabled={scenarioBusy} checked={false}
                onChange={() => void makeClusterScenario()} />
              <span>Сценарий тренажёра из кластера возражений (V5-03)<br />
                <small>скачивает .json по текущим фильтрам возражений</small></span>
            </label>
            <button className="primary" disabled={analyzing} onClick={() => void runAnalysis()} style={{ width: "100%", padding: "10px 0" }}>
              <Icon name="sparkles" size={15} /> {analyzing ? "ИИ анализирует…" : "Запустить глубокий ИИ-анализ"}
            </button>
          </div>

          <div className="card">
            <div className="card-title">
              <h3>Результат анализа</h3>
              {result?.usage && <small className="muted">токены: {result.usage.total_tokens ?? "—"}</small>}
            </div>
            {/* DEF-05: локальная расшифровка алиасов ПДн в браузере */}
            <label className="pii-chip" style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={decodeAliases} onChange={(e) => setDecodeAliases(e.target.checked)} />
              <span>Локально расшифровать алиасы в браузере (только для чтения)<br />
                <small>подставляет реальные значения из alias_map — данные не покидали ваш сервер</small></span>
            </label>
            {analyzing && streaming && (
              <small className="muted" style={{ display: "block", marginBottom: 6 }}>Отчёт печатается по мере генерации…</small>
            )}
            {reasoning && (
              <details style={{ marginBottom: 8 }}>
                <summary style={{ cursor: "pointer", fontWeight: 600 }}>Рассуждения модели (reasoning)</summary>
                <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12, background: "var(--bg-subtle)", padding: 12, borderRadius: 8, maxHeight: 240, overflow: "auto" }}>{reasoning}</pre>
              </details>
            )}
            {result ? (
              <MarkdownView text={result.markdown} aliasMap={result.aliasMap} onOpenCall={onOpenCall} decode={decodeAliases} />
            ) : (
              <EmptyState icon="sparkles" text="Результат появится после запуска анализа" />
            )}
            {runs.length > 0 && (
              <>
                <h3 style={{ marginTop: 16 }}>История анализов</h3>
                <table>
                  <thead><tr><th>Дата</th><th>Режим</th><th>Модель</th><th>Статус</th></tr></thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.id} onClick={() => { void api.aiRun(r.id).then((d) => d.result_markdown && setResult({ markdown: d.result_markdown, aliasMap: (d.pii_config as { stats?: { alias_map?: Record<string, string> } })?.stats?.alias_map ?? {} })).catch(() => undefined); }}>
                        <td className="muted">{r.created_at.slice(0, 16).replace("T", " ")}</td>
                        <td>{r.prompt_text?.slice(0, 40) || "—"}</td>
                        <td className="mono">{r.model_id}</td>
                        <td><Badge tone={r.status === "done" ? "success" : r.status === "failed" ? "danger" : "warning"}>{r.status}</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      )}

      {tab === "mcp" && (
        <div className="ai-grid">
          <div className="card">
            <h3>Подключение MCP-сервера</h3>
            <small className="section-hint">
              Работайте с данными «Полилога» из своей подписки (Claude Code, Codex, ZCode, Cursor):
              5 MCP-тулзов отдают те же срезы, что AI Lab, с автоматической очисткой ПДн.
            </small>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {Object.entries(mcpCfg?.harnesses ?? {}).map(([key, h]) => (
                <button key={key} className={harness === key ? "primary" : ""} onClick={() => setHarness(key)}>{h.title}</button>
              ))}
            </div>
            {cfg && (
              <div style={{ marginTop: 10 }}>
                {cfg.cli_command && (
                  <div className="form-row">
                    <label>Команда терминала</label>
                    <pre className="mono" style={{ background: "var(--bg-subtle)", padding: 10, borderRadius: 8, overflow: "auto" }}>{cfg.cli_command}</pre>
                  </div>
                )}
                {cfg.mcp_json && (
                  <div className="form-row">
                    <label>Конфиг (.mcp.json)</label>
                    <pre className="mono" style={{ background: "var(--bg-subtle)", padding: 10, borderRadius: 8, overflow: "auto" }}>{JSON.stringify(cfg.mcp_json, null, 2)}</pre>
                  </div>
                )}
                {cfg.config_toml && (
                  <div className="form-row">
                    <label>config.toml</label>
                    <pre className="mono" style={{ background: "var(--bg-subtle)", padding: 10, borderRadius: 8, overflow: "auto" }}>{cfg.config_toml}</pre>
                  </div>
                )}
                <button onClick={() => copyText(cfg.cli_command ?? (cfg.mcp_json ? JSON.stringify(cfg.mcp_json, null, 2) : cfg.config_toml ?? ""), "Конфиг")}>
                  <Icon name="copy" size={14} /> Скопировать конфиг
                </button>
              </div>
            )}
            <h3 style={{ marginTop: 16 }}>Тулзы MCP</h3>
            <table>
              <thead><tr><th>Имя</th><th>Что возвращает</th></tr></thead>
              <tbody>
                {(mcpCfg?.tools ?? []).map((t) => (
                  <tr key={t.name}><td className="mono">{t.name}</td><td>{t.description}</td></tr>
                ))}
              </tbody>
            </table>
            <div className="form-row">
              <label>Стартовый промпт для агента</label>
              <textarea rows={3} value={mcpCfg?.starter_prompt ?? ""} readOnly />
              <button onClick={() => copyText(mcpCfg?.starter_prompt ?? "", "Промпт")}><Icon name="copy" size={14} /> Копировать промпт</button>
            </div>
          </div>
          <div className="card">
            <h3>Готовый пакет данных в любой чат</h3>
            <small className="section-hint">
              Сделайте предпросмотр выборки выше, затем скачайте файл — он уже прошёл через слайдер ПДн
              и готов к работе в Claude Code / Codex / ZCode или обычном чате.
            </small>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button disabled={!preview} onClick={() => downloadBundle("md")}><Icon name="download" size={14} /> Скачать .md для агента</button>
              <button disabled={!preview} onClick={() => downloadBundle("json")}><Icon name="download" size={14} /> Скачать .json датасет</button>
              <button disabled={!preview} onClick={() => copyText(preview ? `${userPrompt || "Проанализируй данные."}\n\n---\n\n${preview.context_preview}` : "", "Пакет")}><Icon name="copy" size={14} /> Копировать промпт + данные</button>
            </div>
            {!preview && <small className="muted" style={{ display: "block", marginTop: 8 }}>Сначала сделайте «Предпросмотр выборки» в блоке выше.</small>}
          </div>
        </div>
      )}

      {/* V5-06 (ТЗ v5.0 §9.2-4): интерактивный MCP Playground */}
      {tab === "mcp" && (
        <div className="card">
          <div className="card-title">
            <h3>Тестирование MCP-сервера прямо в браузере (MCP Playground)</h3>
          </div>
          <div className="filter-bar" style={{ margin: "8px 0" }}>
            <select value={pgMethod} onChange={(e) => setPgMethod(e.target.value)}>
              <option value="tools/list">tools/list</option>
              <option value="tools/call">tools/call</option>
              <option value="resources/list">resources/list</option>
              <option value="resources/read">resources/read</option>
              <option value="prompts/list">prompts/list</option>
              <option value="prompts/get">prompts/get</option>
            </select>
            {pgMethod === "tools/call" && (
              <>
                <select value={pgTool} onChange={(e) => setPgTool(e.target.value)}>
                  {(mcpCfg?.tools ?? []).map((tl) => (
                    <option key={tl.name} value={tl.name}>{tl.name}</option>
                  ))}
                </select>
                <input
                  value={pgToolArgs}
                  onChange={(e) => setPgToolArgs(e.target.value)}
                  placeholder='{"days": 30}'
                  style={{ width: 260, fontFamily: "var(--font-mono)", fontSize: 12 }}
                />
              </>
            )}
            {pgMethod === "resources/read" && (
              <select value={pgResource} onChange={(e) => setPgResource(e.target.value)}>
                <option value="polylog://stats/summary">polylog://stats/summary</option>
                <option value="polylog://rubrics/active">polylog://rubrics/active</option>
                <option value="polylog://risks/top">polylog://risks/top</option>
                <option value="polylog://managers/leaderboard">polylog://managers/leaderboard</option>
              </select>
            )}
            {pgMethod === "prompts/get" && (
              <input
                value={pgPrompt}
                onChange={(e) => setPgPrompt(e.target.value)}
                placeholder="churn_audit"
                style={{ width: 220 }}
              />
            )}
            <button className="primary" disabled={pgBusy} onClick={() => void runMcpCall()}>
              {pgBusy ? "Выполняется…" : "Выполнить MCP-вызов (POST /api/v1/mcp/rpc)"}
            </button>
          </div>
          <div className="ai-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <div>
              <small className="muted">JSON-RPC 2.0 запрос</small>
              <pre className="mono" style={{ background: "var(--bg-subtle)", padding: 10, borderRadius: 8, fontSize: 12, maxHeight: 260, overflow: "auto" }}>
                {pgRequest || "— выберите метод и выполните вызов"}
              </pre>
            </div>
            <div>
              <small className="muted">
                Ответ сервера{pgMs != null ? ` · ${pgMs} мс` : ""}
              </small>
              <pre className="mono" style={{ background: "var(--bg-subtle)", padding: 10, borderRadius: 8, fontSize: 12, maxHeight: 260, overflow: "auto" }}>
                {pgResponse || "—"}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
