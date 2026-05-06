use std::path::PathBuf;

use chrono::{DateTime, Duration, Utc};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};

#[derive(Debug)]
pub struct AppStore {
    conn: Connection,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PublicSettings {
    pub openai_days_back: i64,
    pub openai_bucket_width: String,
    pub refresh_minutes: i64,
    pub proxy_port: u16,
    pub deepseek_base_url: String,
    pub deepseek_input_price_per_million: f64,
    pub deepseek_output_price_per_million: f64,
}

impl Default for PublicSettings {
    fn default() -> Self {
        Self {
            openai_days_back: 7,
            openai_bucket_width: "1h".to_string(),
            refresh_minutes: 30,
            proxy_port: 8787,
            deepseek_base_url: "https://api.deepseek.com".to_string(),
            deepseek_input_price_per_million: 0.27,
            deepseek_output_price_per_million: 1.10,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UsageBucket {
    pub provider: String,
    pub endpoint: String,
    pub bucket_start: i64,
    pub bucket_end: i64,
    pub project_id: String,
    pub api_key_id: String,
    pub model: String,
    pub input_tokens: i64,
    pub cached_input_tokens: i64,
    pub output_tokens: i64,
    pub num_requests: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CostBucket {
    pub provider: String,
    pub bucket_start: i64,
    pub bucket_end: i64,
    pub currency: String,
    pub amount: f64,
    pub project_id: String,
    pub line_item: String,
    pub api_key_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProxyRequestLog {
    pub id: i64,
    pub provider: String,
    pub timestamp: i64,
    pub model: String,
    pub status: i64,
    pub latency_ms: i64,
    pub usage_json: String,
    pub cost_estimate: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Dashboard {
    pub openai_today_tokens: i64,
    pub openai_today_cost: f64,
    pub deepseek_today_tokens: i64,
    pub deepseek_today_cost: f64,
    pub recent_failures: i64,
    pub proxy_requests_today: i64,
}

impl AppStore {
    pub fn open(path: PathBuf) -> anyhow::Result<Self> {
        let conn = Connection::open(path)?;
        let store = Self { conn };
        store.migrate()?;
        store.seed_default_settings()?;
        Ok(store)
    }

    fn migrate(&self) -> anyhow::Result<()> {
        self.conn.execute_batch(
            r#"
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS provider_usage_buckets (
              provider TEXT NOT NULL,
              endpoint TEXT NOT NULL,
              bucket_start INTEGER NOT NULL,
              bucket_end INTEGER NOT NULL,
              project_id TEXT NOT NULL DEFAULT '',
              api_key_id TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL DEFAULT '',
              input_tokens INTEGER NOT NULL DEFAULT 0,
              cached_input_tokens INTEGER NOT NULL DEFAULT 0,
              output_tokens INTEGER NOT NULL DEFAULT 0,
              num_requests INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (provider, endpoint, bucket_start, bucket_end, project_id, api_key_id, model)
            );

            CREATE TABLE IF NOT EXISTS provider_cost_buckets (
              provider TEXT NOT NULL,
              bucket_start INTEGER NOT NULL,
              bucket_end INTEGER NOT NULL,
              currency TEXT NOT NULL DEFAULT 'usd',
              amount REAL NOT NULL DEFAULT 0,
              project_id TEXT NOT NULL DEFAULT '',
              line_item TEXT NOT NULL DEFAULT '',
              api_key_id TEXT NOT NULL DEFAULT '',
              PRIMARY KEY (provider, bucket_start, bucket_end, currency, project_id, line_item, api_key_id)
            );

            CREATE TABLE IF NOT EXISTS proxy_request_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              provider TEXT NOT NULL,
              timestamp INTEGER NOT NULL,
              model TEXT NOT NULL DEFAULT '',
              status INTEGER NOT NULL,
              latency_ms INTEGER NOT NULL,
              usage_json TEXT NOT NULL DEFAULT '{}',
              cost_estimate REAL NOT NULL DEFAULT 0
            );
            "#,
        )?;
        Ok(())
    }

    fn seed_default_settings(&self) -> anyhow::Result<()> {
        let defaults = PublicSettings::default();
        self.set_default("openai_days_back", defaults.openai_days_back.to_string())?;
        self.set_default("openai_bucket_width", defaults.openai_bucket_width)?;
        self.set_default("refresh_minutes", defaults.refresh_minutes.to_string())?;
        self.set_default("proxy_port", defaults.proxy_port.to_string())?;
        self.set_default("deepseek_base_url", defaults.deepseek_base_url)?;
        self.set_default(
            "deepseek_input_price_per_million",
            defaults.deepseek_input_price_per_million.to_string(),
        )?;
        self.set_default(
            "deepseek_output_price_per_million",
            defaults.deepseek_output_price_per_million.to_string(),
        )?;
        Ok(())
    }

    fn set_default(&self, key: &str, value: String) -> anyhow::Result<()> {
        self.conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?1, ?2)",
            params![key, value],
        )?;
        Ok(())
    }

    fn get_setting(&self, key: &str) -> anyhow::Result<Option<String>> {
        let value = self
            .conn
            .query_row(
                "SELECT value FROM settings WHERE key = ?1",
                params![key],
                |row| row.get(0),
            )
            .optional()?;
        Ok(value)
    }

    pub fn public_settings(&self) -> anyhow::Result<PublicSettings> {
        let defaults = PublicSettings::default();
        Ok(PublicSettings {
            openai_days_back: self
                .get_setting("openai_days_back")?
                .and_then(|v| v.parse().ok())
                .unwrap_or(defaults.openai_days_back),
            openai_bucket_width: self
                .get_setting("openai_bucket_width")?
                .unwrap_or(defaults.openai_bucket_width),
            refresh_minutes: self
                .get_setting("refresh_minutes")?
                .and_then(|v| v.parse().ok())
                .unwrap_or(defaults.refresh_minutes),
            proxy_port: self
                .get_setting("proxy_port")?
                .and_then(|v| v.parse().ok())
                .unwrap_or(defaults.proxy_port),
            deepseek_base_url: self
                .get_setting("deepseek_base_url")?
                .unwrap_or(defaults.deepseek_base_url),
            deepseek_input_price_per_million: self
                .get_setting("deepseek_input_price_per_million")?
                .and_then(|v| v.parse().ok())
                .unwrap_or(defaults.deepseek_input_price_per_million),
            deepseek_output_price_per_million: self
                .get_setting("deepseek_output_price_per_million")?
                .and_then(|v| v.parse().ok())
                .unwrap_or(defaults.deepseek_output_price_per_million),
        })
    }

    pub fn save_public_settings(&mut self, settings: &PublicSettings) -> anyhow::Result<()> {
        let tx = self.conn.transaction()?;
        let entries = [
            ("openai_days_back", settings.openai_days_back.to_string()),
            ("openai_bucket_width", settings.openai_bucket_width.clone()),
            ("refresh_minutes", settings.refresh_minutes.to_string()),
            ("proxy_port", settings.proxy_port.to_string()),
            ("deepseek_base_url", settings.deepseek_base_url.clone()),
            (
                "deepseek_input_price_per_million",
                settings.deepseek_input_price_per_million.to_string(),
            ),
            (
                "deepseek_output_price_per_million",
                settings.deepseek_output_price_per_million.to_string(),
            ),
        ];
        for (key, value) in entries {
            tx.execute(
                "INSERT INTO settings (key, value) VALUES (?1, ?2)
                 ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                params![key, value],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn insert_usage_buckets(&mut self, buckets: &[UsageBucket]) -> anyhow::Result<()> {
        let tx = self.conn.transaction()?;
        for bucket in buckets {
            tx.execute(
                r#"
                INSERT INTO provider_usage_buckets
                  (provider, endpoint, bucket_start, bucket_end, project_id, api_key_id, model,
                   input_tokens, cached_input_tokens, output_tokens, num_requests)
                VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
                ON CONFLICT(provider, endpoint, bucket_start, bucket_end, project_id, api_key_id, model)
                DO UPDATE SET
                  input_tokens = excluded.input_tokens,
                  cached_input_tokens = excluded.cached_input_tokens,
                  output_tokens = excluded.output_tokens,
                  num_requests = excluded.num_requests
                "#,
                params![
                    bucket.provider,
                    bucket.endpoint,
                    bucket.bucket_start,
                    bucket.bucket_end,
                    bucket.project_id,
                    bucket.api_key_id,
                    bucket.model,
                    bucket.input_tokens,
                    bucket.cached_input_tokens,
                    bucket.output_tokens,
                    bucket.num_requests
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn insert_cost_buckets(&mut self, buckets: &[CostBucket]) -> anyhow::Result<()> {
        let tx = self.conn.transaction()?;
        for bucket in buckets {
            tx.execute(
                r#"
                INSERT INTO provider_cost_buckets
                  (provider, bucket_start, bucket_end, currency, amount, project_id, line_item, api_key_id)
                VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
                ON CONFLICT(provider, bucket_start, bucket_end, currency, project_id, line_item, api_key_id)
                DO UPDATE SET amount = excluded.amount
                "#,
                params![
                    bucket.provider,
                    bucket.bucket_start,
                    bucket.bucket_end,
                    bucket.currency,
                    bucket.amount,
                    bucket.project_id,
                    bucket.line_item,
                    bucket.api_key_id
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn insert_proxy_log(&mut self, log: &ProxyRequestLog) -> anyhow::Result<()> {
        self.conn.execute(
            r#"
            INSERT INTO proxy_request_logs
              (provider, timestamp, model, status, latency_ms, usage_json, cost_estimate)
            VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
            "#,
            params![
                log.provider,
                log.timestamp,
                log.model,
                log.status,
                log.latency_ms,
                log.usage_json,
                log.cost_estimate
            ],
        )?;
        Ok(())
    }

    pub fn list_usage(&self, provider: Option<&str>) -> anyhow::Result<Vec<UsageBucket>> {
        let sql = if provider.is_some() {
            "SELECT provider, endpoint, bucket_start, bucket_end, project_id, api_key_id, model,
                    input_tokens, cached_input_tokens, output_tokens, num_requests
             FROM provider_usage_buckets WHERE provider = ?1 ORDER BY bucket_start DESC LIMIT 500"
        } else {
            "SELECT provider, endpoint, bucket_start, bucket_end, project_id, api_key_id, model,
                    input_tokens, cached_input_tokens, output_tokens, num_requests
             FROM provider_usage_buckets ORDER BY bucket_start DESC LIMIT 500"
        };
        let mut stmt = self.conn.prepare(sql)?;
        let rows = if let Some(provider) = provider {
            stmt.query_map(params![provider], map_usage_bucket)?
                .collect::<Result<Vec<_>, _>>()?
        } else {
            stmt.query_map([], map_usage_bucket)?
                .collect::<Result<Vec<_>, _>>()?
        };
        Ok(rows)
    }

    pub fn list_costs(&self, provider: Option<&str>) -> anyhow::Result<Vec<CostBucket>> {
        let sql = if provider.is_some() {
            "SELECT provider, bucket_start, bucket_end, currency, amount, project_id, line_item, api_key_id
             FROM provider_cost_buckets WHERE provider = ?1 ORDER BY bucket_start DESC LIMIT 500"
        } else {
            "SELECT provider, bucket_start, bucket_end, currency, amount, project_id, line_item, api_key_id
             FROM provider_cost_buckets ORDER BY bucket_start DESC LIMIT 500"
        };
        let mut stmt = self.conn.prepare(sql)?;
        let rows = if let Some(provider) = provider {
            stmt.query_map(params![provider], map_cost_bucket)?
                .collect::<Result<Vec<_>, _>>()?
        } else {
            stmt.query_map([], map_cost_bucket)?
                .collect::<Result<Vec<_>, _>>()?
        };
        Ok(rows)
    }

    pub fn list_proxy_logs(&self) -> anyhow::Result<Vec<ProxyRequestLog>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, provider, timestamp, model, status, latency_ms, usage_json, cost_estimate
             FROM proxy_request_logs ORDER BY timestamp DESC LIMIT 500",
        )?;
        let rows = stmt
            .query_map([], |row| {
                Ok(ProxyRequestLog {
                    id: row.get(0)?,
                    provider: row.get(1)?,
                    timestamp: row.get(2)?,
                    model: row.get(3)?,
                    status: row.get(4)?,
                    latency_ms: row.get(5)?,
                    usage_json: row.get(6)?,
                    cost_estimate: row.get(7)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    pub fn dashboard(&self) -> anyhow::Result<Dashboard> {
        let now = Utc::now().timestamp();
        let today = now - now.rem_euclid(86_400);
        let openai_today_tokens: i64 = self.conn.query_row(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0)
             FROM provider_usage_buckets WHERE provider = 'openai' AND bucket_start >= ?1",
            params![today],
            |row| row.get(0),
        )?;
        let openai_today_cost: f64 = self.conn.query_row(
            "SELECT COALESCE(SUM(amount), 0)
             FROM provider_cost_buckets WHERE provider = 'openai' AND bucket_start >= ?1",
            params![today],
            |row| row.get(0),
        )?;
        let deepseek_today_tokens: i64 = self.conn.query_row(
            "SELECT COALESCE(SUM(json_extract(usage_json, '$.total_tokens')), 0)
             FROM proxy_request_logs WHERE provider = 'deepseek' AND timestamp >= ?1",
            params![today],
            |row| row.get(0),
        )?;
        let deepseek_today_cost: f64 = self.conn.query_row(
            "SELECT COALESCE(SUM(cost_estimate), 0)
             FROM proxy_request_logs WHERE provider = 'deepseek' AND timestamp >= ?1",
            params![today],
            |row| row.get(0),
        )?;
        let recent_window = (Utc::now() - Duration::hours(24)).timestamp();
        let recent_failures: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM proxy_request_logs WHERE status >= 400 AND timestamp >= ?1",
            params![recent_window],
            |row| row.get(0),
        )?;
        let proxy_requests_today: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM proxy_request_logs WHERE provider = 'deepseek' AND timestamp >= ?1",
            params![today],
            |row| row.get(0),
        )?;
        Ok(Dashboard {
            openai_today_tokens,
            openai_today_cost,
            deepseek_today_tokens,
            deepseek_today_cost,
            recent_failures,
            proxy_requests_today,
        })
    }
}

fn map_usage_bucket(row: &rusqlite::Row<'_>) -> rusqlite::Result<UsageBucket> {
    Ok(UsageBucket {
        provider: row.get(0)?,
        endpoint: row.get(1)?,
        bucket_start: row.get(2)?,
        bucket_end: row.get(3)?,
        project_id: row.get(4)?,
        api_key_id: row.get(5)?,
        model: row.get(6)?,
        input_tokens: row.get(7)?,
        cached_input_tokens: row.get(8)?,
        output_tokens: row.get(9)?,
        num_requests: row.get(10)?,
    })
}

fn map_cost_bucket(row: &rusqlite::Row<'_>) -> rusqlite::Result<CostBucket> {
    Ok(CostBucket {
        provider: row.get(0)?,
        bucket_start: row.get(1)?,
        bucket_end: row.get(2)?,
        currency: row.get(3)?,
        amount: row.get(4)?,
        project_id: row.get(5)?,
        line_item: row.get(6)?,
        api_key_id: row.get(7)?,
    })
}

pub fn cost_estimate(settings: &PublicSettings, usage: &serde_json::Value) -> f64 {
    let input = usage
        .get("prompt_tokens")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    let output = usage
        .get("completion_tokens")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    input / 1_000_000.0 * settings.deepseek_input_price_per_million
        + output / 1_000_000.0 * settings.deepseek_output_price_per_million
}

pub fn now_ts() -> i64 {
    DateTime::<Utc>::from(Utc::now()).timestamp()
}
