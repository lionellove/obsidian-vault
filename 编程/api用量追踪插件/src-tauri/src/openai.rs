use reqwest::Client;
use serde_json::Value;

use crate::store::{CostBucket, PublicSettings, UsageBucket};

#[derive(Debug)]
pub struct SyncReport {
    pub usage_buckets: Vec<UsageBucket>,
    pub cost_buckets: Vec<CostBucket>,
}

pub async fn test_admin_key(key: &str) -> anyhow::Result<String> {
    let client = Client::new();
    let now = chrono::Utc::now().timestamp();
    let start = now - 3600;
    let response = client
        .get("https://api.openai.com/v1/organization/usage/completions")
        .bearer_auth(key)
        .query(&[
            ("start_time", start.to_string()),
            ("end_time", now.to_string()),
            ("bucket_width", "1h".to_string()),
            ("limit", "1".to_string()),
        ])
        .send()
        .await?;
    if response.status().is_success() {
        Ok("OpenAI Admin API key can read organization usage".to_string())
    } else {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("OpenAI usage check failed with {status}: {text}");
    }
}

pub async fn sync_usage(key: &str, settings: &PublicSettings) -> anyhow::Result<SyncReport> {
    let client = Client::new();
    let now = chrono::Utc::now().timestamp();
    let start = now - settings.openai_days_back.max(1) * 24 * 3600;
    let usage_buckets =
        fetch_usage_completions(&client, key, start, now, &settings.openai_bucket_width).await?;
    let cost_buckets = fetch_costs(&client, key, start, now, &settings.openai_bucket_width).await?;
    Ok(SyncReport {
        usage_buckets,
        cost_buckets,
    })
}

async fn fetch_usage_completions(
    client: &Client,
    key: &str,
    start: i64,
    end: i64,
    bucket_width: &str,
) -> anyhow::Result<Vec<UsageBucket>> {
    let mut page: Option<String> = None;
    let mut buckets = Vec::new();

    loop {
        let mut query = vec![
            ("start_time".to_string(), start.to_string()),
            ("end_time".to_string(), end.to_string()),
            ("bucket_width".to_string(), bucket_width.to_string()),
            ("limit".to_string(), "100".to_string()),
            ("group_by".to_string(), "project_id".to_string()),
            ("group_by".to_string(), "api_key_id".to_string()),
            ("group_by".to_string(), "model".to_string()),
        ];
        if let Some(page_value) = &page {
            query.push(("page".to_string(), page_value.clone()));
        }

        let response = client
            .get("https://api.openai.com/v1/organization/usage/completions")
            .bearer_auth(key)
            .query(&query)
            .send()
            .await?;
        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            anyhow::bail!("OpenAI usage sync failed with {status}: {text}");
        }

        let value: Value = response.json().await?;
        buckets.extend(parse_usage_buckets(&value));
        page = value
            .get("next_page")
            .and_then(|v| v.as_str())
            .filter(|v| !v.is_empty())
            .map(ToOwned::to_owned);
        if page.is_none()
            || !value
                .get("has_more")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        {
            break;
        }
    }

    Ok(buckets)
}

async fn fetch_costs(
    client: &Client,
    key: &str,
    start: i64,
    end: i64,
    bucket_width: &str,
) -> anyhow::Result<Vec<CostBucket>> {
    let mut page: Option<String> = None;
    let mut buckets = Vec::new();

    loop {
        let mut query = vec![
            ("start_time".to_string(), start.to_string()),
            ("end_time".to_string(), end.to_string()),
            ("bucket_width".to_string(), bucket_width.to_string()),
            ("limit".to_string(), "100".to_string()),
            ("group_by".to_string(), "project_id".to_string()),
            ("group_by".to_string(), "line_item".to_string()),
        ];
        if let Some(page_value) = &page {
            query.push(("page".to_string(), page_value.clone()));
        }

        let response = client
            .get("https://api.openai.com/v1/organization/costs")
            .bearer_auth(key)
            .query(&query)
            .send()
            .await?;
        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            anyhow::bail!("OpenAI cost sync failed with {status}: {text}");
        }

        let value: Value = response.json().await?;
        buckets.extend(parse_cost_buckets(&value));
        page = value
            .get("next_page")
            .and_then(|v| v.as_str())
            .filter(|v| !v.is_empty())
            .map(ToOwned::to_owned);
        if page.is_none()
            || !value
                .get("has_more")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        {
            break;
        }
    }

    Ok(buckets)
}

pub fn parse_usage_buckets(value: &Value) -> Vec<UsageBucket> {
    value
        .get("data")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
        .flat_map(|bucket| {
            let start = bucket
                .get("start_time")
                .and_then(|v| v.as_i64())
                .unwrap_or_default();
            let end = bucket
                .get("end_time")
                .and_then(|v| v.as_i64())
                .unwrap_or_default();
            bucket
                .get("results")
                .and_then(|v| v.as_array())
                .into_iter()
                .flatten()
                .map(move |result| UsageBucket {
                    provider: "openai".to_string(),
                    endpoint: "completions".to_string(),
                    bucket_start: start,
                    bucket_end: end,
                    project_id: string_field(result, "project_id"),
                    api_key_id: string_field(result, "api_key_id"),
                    model: string_field(result, "model"),
                    input_tokens: int_field(result, "input_tokens"),
                    cached_input_tokens: int_field(result, "input_cached_tokens")
                        + int_field(result, "cached_input_tokens"),
                    output_tokens: int_field(result, "output_tokens"),
                    num_requests: int_field(result, "num_model_requests")
                        + int_field(result, "num_requests"),
                })
                .collect::<Vec<_>>()
        })
        .collect()
}

pub fn parse_cost_buckets(value: &Value) -> Vec<CostBucket> {
    value
        .get("data")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
        .flat_map(|bucket| {
            let start = bucket
                .get("start_time")
                .and_then(|v| v.as_i64())
                .unwrap_or_default();
            let end = bucket
                .get("end_time")
                .and_then(|v| v.as_i64())
                .unwrap_or_default();
            bucket
                .get("results")
                .and_then(|v| v.as_array())
                .into_iter()
                .flatten()
                .map(move |result| {
                    let amount = result.get("amount").unwrap_or(&Value::Null);
                    CostBucket {
                        provider: "openai".to_string(),
                        bucket_start: start,
                        bucket_end: end,
                        currency: string_field(amount, "currency")
                            .or_else(|| string_field(result, "currency")),
                        amount: amount
                            .get("value")
                            .and_then(|v| v.as_f64())
                            .unwrap_or_else(|| {
                                result
                                    .get("amount")
                                    .and_then(|v| v.as_f64())
                                    .unwrap_or_default()
                            }),
                        project_id: string_field(result, "project_id"),
                        line_item: string_field(result, "line_item"),
                        api_key_id: string_field(result, "api_key_id"),
                    }
                })
                .collect::<Vec<_>>()
        })
        .collect()
}

fn int_field(value: &Value, key: &str) -> i64 {
    value.get(key).and_then(|v| v.as_i64()).unwrap_or_default()
}

fn string_field(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string()
}

trait EmptyStringFallback {
    fn or_else<F: FnOnce() -> String>(self, f: F) -> String;
}

impl EmptyStringFallback for String {
    fn or_else<F: FnOnce() -> String>(self, f: F) -> String {
        if self.is_empty() {
            f()
        } else {
            self
        }
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{parse_cost_buckets, parse_usage_buckets};

    #[test]
    fn parses_usage_buckets() {
        let value = json!({
            "data": [{
                "start_time": 10,
                "end_time": 20,
                "results": [{
                    "project_id": "proj",
                    "api_key_id": "key",
                    "model": "gpt-5.4",
                    "input_tokens": 100,
                    "input_cached_tokens": 30,
                    "output_tokens": 40,
                    "num_model_requests": 2
                }]
            }]
        });
        let parsed = parse_usage_buckets(&value);
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].input_tokens, 100);
        assert_eq!(parsed[0].cached_input_tokens, 30);
        assert_eq!(parsed[0].num_requests, 2);
    }

    #[test]
    fn parses_cost_buckets() {
        let value = json!({
            "data": [{
                "start_time": 10,
                "end_time": 20,
                "results": [{
                    "amount": { "value": 1.25, "currency": "usd" },
                    "project_id": "proj",
                    "line_item": "Models"
                }]
            }]
        });
        let parsed = parse_cost_buckets(&value);
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].currency, "usd");
        assert_eq!(parsed[0].amount, 1.25);
    }
}
