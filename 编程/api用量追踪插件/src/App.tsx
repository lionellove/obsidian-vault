import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Database,
  KeyRound,
  LayoutDashboard,
  PlugZap,
  RefreshCw,
  Settings,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, CostBucket, Dashboard, errorMessage, ProxyRequestLog, PublicSettings, UsageBucket } from "./api";
import { Empty, Loading, Notice, Panel, Stat } from "./components";
import { compactNumber, currency, dateTime, dayLabel, statusClass } from "./format";

type Tab = "overview" | "openai" | "deepseek" | "settings";

type LoadState = {
  dashboard?: Dashboard;
  settings?: PublicSettings;
  usage: UsageBucket[];
  costs: CostBucket[];
  logs: ProxyRequestLog[];
  proxyRunning: boolean;
  deepseekBalance?: string;
};

const defaultState: LoadState = {
  usage: [],
  costs: [],
  logs: [],
  proxyRunning: false,
};

export function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [state, setState] = useState<LoadState>(defaultState);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>("");

  const refresh = async () => {
    setLoading(true);
    try {
      const [dashboard, settings, usage, costs, logs, proxyRunning] = await Promise.all([
        api.dashboard(),
        api.settings(),
        api.usage(),
        api.costs(),
        api.proxyLogs(),
        api.proxyStatus(),
      ]);
      const deepseekBalance = await api.deepseekBalance().catch(() => "");
      setState({ dashboard, settings, usage, costs, logs, proxyRunning, deepseekBalance });
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const runAction = async (action: () => Promise<string | void>) => {
    setBusy(true);
    setMessage("");
    try {
      const result = await action();
      if (result) setMessage(result);
      await refresh();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Database size={24} />
          <div>
            <strong>Usage Tracker</strong>
            <span>DeepSeek + Codex</span>
          </div>
        </div>
        <nav>
          <NavButton active={tab === "overview"} icon={<LayoutDashboard size={18} />} onClick={() => setTab("overview")}>
            总览
          </NavButton>
          <NavButton active={tab === "openai"} icon={<Activity size={18} />} onClick={() => setTab("openai")}>
            OpenAI/Codex
          </NavButton>
          <NavButton active={tab === "deepseek"} icon={<PlugZap size={18} />} onClick={() => setTab("deepseek")}>
            DeepSeek
          </NavButton>
          <NavButton active={tab === "settings"} icon={<Settings size={18} />} onClick={() => setTab("settings")}>
            设置
          </NavButton>
        </nav>
        <div className="sidebar-foot">
          <span className={`dot ${state.proxyRunning ? "on" : ""}`} />
          DeepSeek proxy {state.proxyRunning ? "running" : "stopped"}
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <h1>{titleFor(tab)}</h1>
            <p>OpenAI/Codex 数据来自 OpenAI Usage/Costs API；DeepSeek 数据来自本地代理。</p>
          </div>
          <button className="icon-button" onClick={() => void refresh()} disabled={loading || busy} title="Refresh">
            <RefreshCw size={18} />
          </button>
        </header>

        {message ? <Notice tone={message.toLowerCase().includes("failed") || message.includes("error") ? "danger" : "ok"}>{message}</Notice> : null}
        {loading ? <Loading /> : null}

        {!loading && tab === "overview" ? <Overview state={state} /> : null}
        {!loading && tab === "openai" ? <OpenAIPage state={state} onSync={() => runAction(api.syncOpenAI)} busy={busy} /> : null}
        {!loading && tab === "deepseek" ? (
          <DeepSeekPage
            state={state}
            busy={busy}
            onStart={() => runAction(api.startProxy)}
            onStop={() => runAction(api.stopProxy)}
          />
        ) : null}
        {!loading && tab === "settings" && state.settings ? (
          <SettingsPage settings={state.settings} onSaved={refresh} setMessage={setMessage} />
        ) : null}
      </main>
    </div>
  );
}

function NavButton({
  active,
  icon,
  children,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button className={active ? "active" : ""} onClick={onClick}>
      {icon}
      {children}
    </button>
  );
}

function titleFor(tab: Tab) {
  return {
    overview: "总览",
    openai: "OpenAI/Codex",
    deepseek: "DeepSeek",
    settings: "设置",
  }[tab];
}

function Overview({ state }: { state: LoadState }) {
  const dashboard = state.dashboard;
  const chart = useMemo(() => dailyUsage(state.usage, state.logs), [state.usage, state.logs]);
  if (!dashboard) return null;

  return (
    <div className="content">
      <div className="stats-grid">
        <Stat label="OpenAI/Codex 今日 Token" value={compactNumber(dashboard.openaiTodayTokens)} detail="Usage API visible usage" />
        <Stat label="OpenAI 今日成本" value={currency(dashboard.openaiTodayCost)} detail="Costs API authoritative amount" />
        <Stat label="DeepSeek 今日 Token" value={compactNumber(dashboard.deepseekTodayTokens)} detail={`${dashboard.proxyRequestsToday} proxied requests`} />
        <Stat label="DeepSeek 今日估算" value={currency(dashboard.deepseekTodayCost)} detail={`余额 ${state.deepseekBalance || "未配置"}`} />
        <Stat label="近 24h 失败" value={dashboard.recentFailures} detail="DeepSeek proxy status >= 400" />
      </div>
      <Panel title="Token 趋势">
        {chart.length ? (
          <div className="chart">
            <ResponsiveContainer>
              <LineChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" minTickGap={22} />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="openai" stroke="#2563eb" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="deepseek" stroke="#059669" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <Empty>还没有用量数据。先在设置里保存密钥，然后同步 OpenAI 或启动 DeepSeek 代理。</Empty>
        )}
      </Panel>
    </div>
  );
}

function OpenAIPage({ state, onSync, busy }: { state: LoadState; onSync: () => void; busy: boolean }) {
  const usage = state.usage.filter((item) => item.provider === "openai");
  const costs = state.costs.filter((item) => item.provider === "openai");
  const byModel = useMemo(() => modelUsage(usage), [usage]);

  return (
    <div className="content">
      <Panel
        title="Usage API"
        action={
          <button className="primary" onClick={onSync} disabled={busy}>
            <RefreshCw size={16} />
            同步
          </button>
        }
      >
        <Notice tone="info">这里展示 OpenAI 组织 Usage API 可见的数据；如果 Codex 客户端订阅额度不进入该 API，界面会只显示 API 可见部分。</Notice>
        {byModel.length ? (
          <div className="chart compact">
            <ResponsiveContainer>
              <BarChart data={byModel}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="model" minTickGap={14} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="input" stackId="tokens" fill="#2563eb" />
                <Bar dataKey="output" stackId="tokens" fill="#14b8a6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <Empty>暂无 OpenAI 用量。保存 Admin API Key 后点击同步。</Empty>
        )}
      </Panel>
      <Panel title="Costs API">
        <DataTable
          headers={["时间", "金额", "项目", "费用项", "Key"]}
          rows={costs.slice(0, 12).map((item) => [
            dateTime(item.bucketStart),
            currency(item.amount, item.currency || "USD"),
            item.projectId || "-",
            item.lineItem || "-",
            item.apiKeyId || "-",
          ])}
          empty="暂无成本数据。"
        />
      </Panel>
    </div>
  );
}

function DeepSeekPage({
  state,
  busy,
  onStart,
  onStop,
}: {
  state: LoadState;
  busy: boolean;
  onStart: () => void;
  onStop: () => void;
}) {
  const logs = state.logs;

  return (
    <div className="content">
      <Panel
        title="本地代理"
        action={
          <div className="button-row">
            <button className="primary" onClick={onStart} disabled={busy || state.proxyRunning}>
              <PlugZap size={16} />
              启动
            </button>
            <button onClick={onStop} disabled={busy || !state.proxyRunning}>
              停止
            </button>
          </div>
        }
      >
        <div className="proxy-box">
          <KeyRound size={18} />
          <code>http://127.0.0.1:{state.settings?.proxyPort ?? 8787}/v1</code>
        </div>
      </Panel>
      <Panel title="请求日志">
        <DataTable
          headers={["时间", "模型", "状态", "延迟", "Usage", "估算成本"]}
          rows={logs.slice(0, 18).map((log) => [
            dateTime(log.timestamp),
            log.model || "-",
            <span className={`pill ${statusClass(log.status)}`}>{log.status}</span>,
            `${log.latencyMs} ms`,
            usageLabel(log.usageJson),
            currency(log.costEstimate),
          ])}
          empty="还没有 DeepSeek 代理请求。"
        />
      </Panel>
    </div>
  );
}

function SettingsPage({
  settings,
  onSaved,
  setMessage,
}: {
  settings: PublicSettings;
  onSaved: () => Promise<void>;
  setMessage: (message: string) => void;
}) {
  const [form, setForm] = useState(settings);
  const [openaiKey, setOpenaiKey] = useState("");
  const [deepseekKey, setDeepseekKey] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      await api.saveSettings(form);
      if (openaiKey.trim()) await api.saveSecret("openai", openaiKey);
      if (deepseekKey.trim()) await api.saveSecret("deepseek", deepseekKey);
      setOpenaiKey("");
      setDeepseekKey("");
      setMessage("Settings saved");
      await onSaved();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const test = async (provider: "openai" | "deepseek") => {
    setBusy(true);
    setMessage("");
    try {
      const result = provider === "openai" ? await api.testOpenAI(openaiKey) : await api.testDeepSeek(deepseekKey);
      setMessage(result);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="content two-col">
      <Panel title="API Keys">
        <div className="form-grid">
          <label>
            OpenAI Admin API Key
            <input type="password" value={openaiKey} onChange={(event) => setOpenaiKey(event.target.value)} placeholder="sk-admin-..." />
          </label>
          <button onClick={() => void test("openai")} disabled={busy || !openaiKey.trim()}>
            测试 OpenAI
          </button>
          <label>
            DeepSeek API Key
            <input type="password" value={deepseekKey} onChange={(event) => setDeepseekKey(event.target.value)} placeholder="sk-..." />
          </label>
          <button onClick={() => void test("deepseek")} disabled={busy || !deepseekKey.trim()}>
            测试 DeepSeek
          </button>
        </div>
      </Panel>
      <Panel title="同步与代理">
        <div className="form-grid">
          <label>
            OpenAI 回溯天数
            <input type="number" min={1} max={90} value={form.openaiDaysBack} onChange={(event) => setForm({ ...form, openaiDaysBack: Number(event.target.value) })} />
          </label>
          <label>
            OpenAI bucket
            <select value={form.openaiBucketWidth} onChange={(event) => setForm({ ...form, openaiBucketWidth: event.target.value })}>
              <option value="1h">1h</option>
              <option value="1d">1d</option>
            </select>
          </label>
          <label>
            刷新间隔（分钟）
            <input type="number" min={5} max={1440} value={form.refreshMinutes} onChange={(event) => setForm({ ...form, refreshMinutes: Number(event.target.value) })} />
          </label>
          <label>
            DeepSeek 代理端口
            <input type="number" min={1024} max={65535} value={form.proxyPort} onChange={(event) => setForm({ ...form, proxyPort: Number(event.target.value) })} />
          </label>
          <label className="wide">
            DeepSeek 上游地址
            <input value={form.deepseekBaseUrl} onChange={(event) => setForm({ ...form, deepseekBaseUrl: event.target.value })} />
          </label>
          <label>
            输入价 / 1M tokens
            <input type="number" step="0.01" value={form.deepseekInputPricePerMillion} onChange={(event) => setForm({ ...form, deepseekInputPricePerMillion: Number(event.target.value) })} />
          </label>
          <label>
            输出价 / 1M tokens
            <input type="number" step="0.01" value={form.deepseekOutputPricePerMillion} onChange={(event) => setForm({ ...form, deepseekOutputPricePerMillion: Number(event.target.value) })} />
          </label>
        </div>
        <button className="primary save" onClick={() => void save()} disabled={busy}>
          保存设置
        </button>
      </Panel>
    </div>
  );
}

function DataTable({
  headers,
  rows,
  empty,
}: {
  headers: string[];
  rows: Array<Array<React.ReactNode>>;
  empty: string;
}) {
  if (!rows.length) return <Empty>{empty}</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function dailyUsage(usage: UsageBucket[], logs: ProxyRequestLog[]) {
  const map = new Map<string, { label: string; openai: number; deepseek: number }>();
  for (const item of usage) {
    const label = dayLabel(item.bucketStart);
    const entry = map.get(label) ?? { label, openai: 0, deepseek: 0 };
    entry.openai += item.inputTokens + item.outputTokens;
    map.set(label, entry);
  }
  for (const log of logs) {
    const label = dayLabel(log.timestamp);
    const entry = map.get(label) ?? { label, openai: 0, deepseek: 0 };
    entry.deepseek += usageTotal(log.usageJson);
    map.set(label, entry);
  }
  return Array.from(map.values()).slice(-24);
}

function modelUsage(usage: UsageBucket[]) {
  const map = new Map<string, { model: string; input: number; output: number }>();
  for (const item of usage) {
    const model = item.model || "unknown";
    const entry = map.get(model) ?? { model, input: 0, output: 0 };
    entry.input += item.inputTokens;
    entry.output += item.outputTokens;
    map.set(model, entry);
  }
  return Array.from(map.values()).sort((a, b) => b.input + b.output - (a.input + a.output)).slice(0, 12);
}

function usageTotal(usageJson: string) {
  try {
    const usage = JSON.parse(usageJson) as { total_tokens?: number; prompt_tokens?: number; completion_tokens?: number };
    return usage.total_tokens ?? (usage.prompt_tokens ?? 0) + (usage.completion_tokens ?? 0);
  } catch {
    return 0;
  }
}

function usageLabel(usageJson: string) {
  try {
    const usage = JSON.parse(usageJson) as { total_tokens?: number; prompt_tokens?: number; completion_tokens?: number };
    const total = usage.total_tokens ?? (usage.prompt_tokens ?? 0) + (usage.completion_tokens ?? 0);
    return total ? compactNumber(total) : "-";
  } catch {
    return "-";
  }
}
