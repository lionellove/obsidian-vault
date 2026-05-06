import { invoke } from "@tauri-apps/api/core";

export type Dashboard = {
  openaiTodayTokens: number;
  openaiTodayCost: number;
  deepseekTodayTokens: number;
  deepseekTodayCost: number;
  recentFailures: number;
  proxyRequestsToday: number;
};

export type PublicSettings = {
  openaiDaysBack: number;
  openaiBucketWidth: string;
  refreshMinutes: number;
  proxyPort: number;
  deepseekBaseUrl: string;
  deepseekInputPricePerMillion: number;
  deepseekOutputPricePerMillion: number;
};

export type UsageBucket = {
  provider: string;
  endpoint: string;
  bucketStart: number;
  bucketEnd: number;
  projectId: string;
  apiKeyId: string;
  model: string;
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  numRequests: number;
};

export type CostBucket = {
  provider: string;
  bucketStart: number;
  bucketEnd: number;
  currency: string;
  amount: number;
  projectId: string;
  lineItem: string;
  apiKeyId: string;
};

export type ProxyRequestLog = {
  id: number;
  provider: string;
  timestamp: number;
  model: string;
  status: number;
  latencyMs: number;
  usageJson: string;
  costEstimate: number;
};

export const api = {
  dashboard: () => invoke<Dashboard>("get_dashboard"),
  settings: () => invoke<PublicSettings>("get_settings"),
  saveSettings: (settings: PublicSettings) => invoke<PublicSettings>("save_settings", { settings }),
  saveSecret: (provider: string, key: string) => invoke<void>("save_secret", { payload: { provider, key } }),
  testOpenAI: (key: string) => invoke<string>("test_openai_key", { payload: { provider: "openai", key } }),
  testDeepSeek: (key: string) => invoke<string>("test_deepseek_key", { payload: { provider: "deepseek", key } }),
  deepseekBalance: () => invoke<string>("get_deepseek_balance"),
  syncOpenAI: () => invoke<string>("sync_openai_usage"),
  usage: (provider?: string) => invoke<UsageBucket[]>("list_usage", { provider }),
  costs: (provider?: string) => invoke<CostBucket[]>("list_costs", { provider }),
  proxyLogs: () => invoke<ProxyRequestLog[]>("list_proxy_logs"),
  startProxy: () => invoke<string>("start_deepseek_proxy"),
  stopProxy: () => invoke<string>("stop_deepseek_proxy"),
  proxyStatus: () => invoke<boolean>("proxy_status"),
};

export function errorMessage(error: unknown) {
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return "Unexpected error";
}
