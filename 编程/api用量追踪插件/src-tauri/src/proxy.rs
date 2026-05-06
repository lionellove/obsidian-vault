use std::{
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::Instant,
};

use axum::{
    body::Bytes,
    extract::State,
    http::{HeaderMap, HeaderName, Method, StatusCode},
    response::{IntoResponse, Response},
    routing::{any, get},
    Json, Router,
};
use reqwest::Client;
use serde_json::{json, Value};
use tokio::sync::oneshot;
use tower_http::cors::{Any, CorsLayer};

use crate::store::{cost_estimate, now_ts, AppStore, ProxyRequestLog};

#[derive(Debug)]
pub struct ProxyHandle {
    shutdown: oneshot::Sender<()>,
    join: tokio::task::JoinHandle<()>,
}

impl ProxyHandle {
    pub async fn stop(self) {
        let _ = self.shutdown.send(());
        let _ = self.join.await;
    }
}

#[derive(Clone)]
struct ProxyState {
    deepseek_key: String,
    deepseek_base_url: String,
    client: Client,
    store: Arc<Mutex<AppStore>>,
}

pub async fn test_deepseek_key(key: &str) -> anyhow::Result<String> {
    let response = Client::new()
        .get("https://api.deepseek.com/user/balance")
        .bearer_auth(key)
        .send()
        .await?;
    if response.status().is_success() {
        Ok("DeepSeek API key can read balance".to_string())
    } else {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("DeepSeek balance check failed with {status}: {text}");
    }
}

pub async fn deepseek_balance_summary(key: &str) -> anyhow::Result<String> {
    let response = Client::new()
        .get("https://api.deepseek.com/user/balance")
        .bearer_auth(key)
        .send()
        .await?;
    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("DeepSeek balance check failed with {status}: {text}");
    }
    let value = response.json::<Value>().await?;
    let balances = value
        .get("balance_infos")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
        .filter_map(|item| {
            let currency = item.get("currency").and_then(|v| v.as_str()).unwrap_or("");
            let total = item
                .get("total_balance")
                .or_else(|| item.get("granted_balance"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if currency.is_empty() || total.is_empty() {
                None
            } else {
                Some(format!("{total} {currency}"))
            }
        })
        .collect::<Vec<_>>();
    if balances.is_empty() {
        Ok(value.to_string())
    } else {
        Ok(balances.join(" / "))
    }
}

pub async fn start_proxy(
    port: u16,
    deepseek_key: String,
    deepseek_base_url: String,
    store: Arc<Mutex<AppStore>>,
) -> anyhow::Result<ProxyHandle> {
    let state = ProxyState {
        deepseek_key,
        deepseek_base_url: deepseek_base_url.trim_end_matches('/').to_string(),
        client: Client::new(),
        store,
    };
    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/*path", any(handle_proxy))
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(addr).await?;
    let (tx, rx) = oneshot::channel::<()>();
    let join = tokio::spawn(async move {
        let server = axum::serve(listener, app).with_graceful_shutdown(async {
            let _ = rx.await;
        });
        if let Err(err) = server.await {
            eprintln!("DeepSeek proxy failed: {err}");
        }
    });
    Ok(ProxyHandle { shutdown: tx, join })
}

async fn handle_proxy(
    State(state): State<ProxyState>,
    method: Method,
    headers: HeaderMap,
    axum::extract::Path(path): axum::extract::Path<String>,
    body: Bytes,
) -> Response {
    let started = Instant::now();
    let endpoint = format!("/{path}");
    if method != Method::POST || endpoint != "/v1/chat/completions" {
        return (
            StatusCode::NOT_FOUND,
            "Only POST /v1/chat/completions is supported",
        )
            .into_response();
    }

    let mut request_json = serde_json::from_slice::<Value>(&body).unwrap_or_else(|_| json!({}));
    let model = request_json
        .get("model")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string();
    let is_stream = request_json
        .get("stream")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    if is_stream {
        ensure_stream_usage(&mut request_json);
    }
    let outbound_body = serde_json::to_vec(&request_json).unwrap_or_else(|_| body.to_vec());

    let url = format!("{}{}", state.deepseek_base_url, endpoint);
    let mut request = state
        .client
        .request(reqwest::Method::POST, url)
        .bearer_auth(&state.deepseek_key)
        .body(outbound_body);

    for (name, value) in headers.iter() {
        if should_forward_header(name) {
            request = request.header(name.as_str(), value.as_bytes());
        }
    }

    match request.send().await {
        Ok(response) => {
            let status = response.status();
            let response_headers = response.headers().clone();
            match response.bytes().await {
                Ok(bytes) => {
                    let usage = if is_stream {
                        extract_stream_usage(&bytes)
                    } else {
                        serde_json::from_slice::<Value>(&bytes)
                            .ok()
                            .and_then(|value| value.get("usage").cloned())
                    }
                    .unwrap_or_else(|| json!({}));
                    record_log(&state, model, status.as_u16() as i64, started, &usage);
                    build_response(status, response_headers, bytes)
                }
                Err(err) => {
                    record_log(&state, model, 502, started, &json!({}));
                    (
                        StatusCode::BAD_GATEWAY,
                        format!("Failed to read DeepSeek response: {err}"),
                    )
                        .into_response()
                }
            }
        }
        Err(err) => {
            record_log(&state, model, 502, started, &json!({}));
            (
                StatusCode::BAD_GATEWAY,
                format!("Failed to reach DeepSeek: {err}"),
            )
                .into_response()
        }
    }
}

fn build_response(status: reqwest::StatusCode, headers: HeaderMap, bytes: Bytes) -> Response {
    let mut response = (
        StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::BAD_GATEWAY),
        bytes,
    )
        .into_response();
    for (name, value) in headers.iter() {
        if should_return_header(name) {
            response.headers_mut().insert(name.clone(), value.clone());
        }
    }
    response
}

fn should_forward_header(name: &HeaderName) -> bool {
    !matches!(
        name.as_str().to_ascii_lowercase().as_str(),
        "authorization" | "host" | "content-length" | "connection"
    )
}

fn should_return_header(name: &HeaderName) -> bool {
    !matches!(
        name.as_str().to_ascii_lowercase().as_str(),
        "content-length" | "connection" | "transfer-encoding"
    )
}

fn ensure_stream_usage(value: &mut Value) {
    if let Some(obj) = value.as_object_mut() {
        obj.insert(
            "stream_options".to_string(),
            json!({
                "include_usage": true
            }),
        );
    }
}

fn extract_stream_usage(bytes: &[u8]) -> Option<Value> {
    let text = String::from_utf8_lossy(bytes);
    text.lines()
        .filter_map(|line| line.strip_prefix("data: "))
        .filter(|payload| *payload != "[DONE]")
        .filter_map(|payload| serde_json::from_str::<Value>(payload).ok())
        .filter_map(|value| value.get("usage").cloned())
        .last()
}

fn record_log(state: &ProxyState, model: String, status: i64, started: Instant, usage: &Value) {
    let latency_ms = started.elapsed().as_millis().min(i64::MAX as u128) as i64;
    let mut store = state.store.lock().expect("store mutex poisoned");
    let settings = store.public_settings().unwrap_or_default();
    let log = ProxyRequestLog {
        id: 0,
        provider: "deepseek".to_string(),
        timestamp: now_ts(),
        model,
        status,
        latency_ms,
        usage_json: usage.to_string(),
        cost_estimate: cost_estimate(&settings, usage),
    };
    if let Err(err) = store.insert_proxy_log(&log) {
        eprintln!("Failed to record DeepSeek proxy log: {err}");
    }
}

#[allow(dead_code)]
async fn balance_handler(State(state): State<ProxyState>) -> Result<Json<Value>, StatusCode> {
    let response = state
        .client
        .get("https://api.deepseek.com/user/balance")
        .bearer_auth(&state.deepseek_key)
        .send()
        .await
        .map_err(|_| StatusCode::BAD_GATEWAY)?;
    let value = response
        .json::<Value>()
        .await
        .map_err(|_| StatusCode::BAD_GATEWAY)?;
    Ok(Json(value))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{ensure_stream_usage, extract_stream_usage};

    #[test]
    fn stream_usage_is_injected() {
        let mut value = json!({ "model": "deepseek-chat", "stream": true });
        ensure_stream_usage(&mut value);
        assert_eq!(value["stream_options"]["include_usage"], true);
    }

    #[test]
    fn stream_usage_is_extracted() {
        let bytes = br#"data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}

data: [DONE]
"#;
        let usage = extract_stream_usage(bytes).unwrap();
        assert_eq!(usage["total_tokens"], 12);
    }
}
