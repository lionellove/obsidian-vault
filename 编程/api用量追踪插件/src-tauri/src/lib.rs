mod openai;
mod proxy;
mod store;

use std::sync::{Arc, Mutex};

use proxy::ProxyHandle;
use serde::{Deserialize, Serialize};
use store::{AppStore, Dashboard, PublicSettings};
use tauri::{Manager, State};

const KEYRING_SERVICE: &str = "api-usage-tracker";

pub struct AppState {
    store: Arc<Mutex<AppStore>>,
    proxy: Arc<Mutex<Option<ProxyHandle>>>,
}

#[derive(Debug, Serialize)]
struct CommandError {
    message: String,
}

impl From<anyhow::Error> for CommandError {
    fn from(value: anyhow::Error) -> Self {
        Self {
            message: value.to_string(),
        }
    }
}

type CommandResult<T> = Result<T, CommandError>;

#[derive(Debug, Deserialize)]
struct SecretPayload {
    provider: String,
    key: String,
}

#[tauri::command]
fn get_dashboard(state: State<'_, AppState>) -> CommandResult<Dashboard> {
    let store = state.store.lock().expect("store mutex poisoned");
    store.dashboard().map_err(Into::into)
}

#[tauri::command]
fn get_settings(state: State<'_, AppState>) -> CommandResult<PublicSettings> {
    let store = state.store.lock().expect("store mutex poisoned");
    store.public_settings().map_err(Into::into)
}

#[tauri::command]
fn save_settings(
    state: State<'_, AppState>,
    settings: PublicSettings,
) -> CommandResult<PublicSettings> {
    let mut store = state.store.lock().expect("store mutex poisoned");
    store.save_public_settings(&settings)?;
    store.public_settings().map_err(Into::into)
}

#[tauri::command]
fn save_secret(payload: SecretPayload) -> CommandResult<()> {
    set_secret(&payload.provider, &payload.key).map_err(Into::into)
}

#[tauri::command]
async fn test_openai_key(payload: SecretPayload) -> CommandResult<String> {
    let key = payload.key.trim();
    if key.is_empty() {
        return Err(anyhow::anyhow!("OpenAI Admin API key is empty").into());
    }
    openai::test_admin_key(key).await.map_err(Into::into)
}

#[tauri::command]
async fn test_deepseek_key(payload: SecretPayload) -> CommandResult<String> {
    let key = payload.key.trim();
    if key.is_empty() {
        return Err(anyhow::anyhow!("DeepSeek API key is empty").into());
    }
    proxy::test_deepseek_key(key).await.map_err(Into::into)
}

#[tauri::command]
async fn get_deepseek_balance() -> CommandResult<String> {
    let key = get_secret("deepseek")?;
    proxy::deepseek_balance_summary(&key)
        .await
        .map_err(Into::into)
}

#[tauri::command]
async fn sync_openai_usage(state: State<'_, AppState>) -> CommandResult<String> {
    let key = get_secret("openai")?;
    let settings = {
        let store = state.store.lock().expect("store mutex poisoned");
        store.public_settings()?
    };
    let report = openai::sync_usage(&key, &settings).await?;
    {
        let mut store = state.store.lock().expect("store mutex poisoned");
        store.insert_usage_buckets(&report.usage_buckets)?;
        store.insert_cost_buckets(&report.cost_buckets)?;
    }
    Ok(format!(
        "Synced {} usage buckets and {} cost buckets",
        report.usage_buckets.len(),
        report.cost_buckets.len()
    ))
}

#[tauri::command]
fn list_usage(
    state: State<'_, AppState>,
    provider: Option<String>,
) -> CommandResult<Vec<store::UsageBucket>> {
    let store = state.store.lock().expect("store mutex poisoned");
    store.list_usage(provider.as_deref()).map_err(Into::into)
}

#[tauri::command]
fn list_costs(
    state: State<'_, AppState>,
    provider: Option<String>,
) -> CommandResult<Vec<store::CostBucket>> {
    let store = state.store.lock().expect("store mutex poisoned");
    store.list_costs(provider.as_deref()).map_err(Into::into)
}

#[tauri::command]
fn list_proxy_logs(state: State<'_, AppState>) -> CommandResult<Vec<store::ProxyRequestLog>> {
    let store = state.store.lock().expect("store mutex poisoned");
    store.list_proxy_logs().map_err(Into::into)
}

#[tauri::command]
async fn start_deepseek_proxy(state: State<'_, AppState>) -> CommandResult<String> {
    let deepseek_key = get_secret("deepseek")?;
    let settings = {
        let store = state.store.lock().expect("store mutex poisoned");
        store.public_settings()?
    };

    if state.proxy.lock().expect("proxy mutex poisoned").is_some() {
        return Ok(format!(
            "Proxy already running on 127.0.0.1:{}",
            settings.proxy_port
        ));
    }

    let handle = proxy::start_proxy(
        settings.proxy_port,
        deepseek_key,
        settings.deepseek_base_url.clone(),
        state.store.clone(),
    )
    .await?;
    let mut guard = state.proxy.lock().expect("proxy mutex poisoned");
    *guard = Some(handle);
    Ok(format!(
        "Proxy running on 127.0.0.1:{}",
        settings.proxy_port
    ))
}

#[tauri::command]
async fn stop_deepseek_proxy(state: State<'_, AppState>) -> CommandResult<String> {
    let handle = {
        let mut guard = state.proxy.lock().expect("proxy mutex poisoned");
        guard.take()
    };
    if let Some(handle) = handle {
        handle.stop().await;
        Ok("Proxy stopped".to_string())
    } else {
        Ok("Proxy is not running".to_string())
    }
}

#[tauri::command]
fn proxy_status(state: State<'_, AppState>) -> bool {
    state.proxy.lock().expect("proxy mutex poisoned").is_some()
}

fn set_secret(provider: &str, key: &str) -> anyhow::Result<()> {
    let entry = keyring::Entry::new(KEYRING_SERVICE, provider)?;
    entry.set_password(key.trim())?;
    Ok(())
}

fn get_secret(provider: &str) -> anyhow::Result<String> {
    let entry = keyring::Entry::new(KEYRING_SERVICE, provider)?;
    let key = entry.get_password()?;
    if key.trim().is_empty() {
        anyhow::bail!("{provider} API key is empty");
    }
    Ok(key)
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_data = app.path().app_data_dir()?;
            std::fs::create_dir_all(&app_data)?;
            let db_path = app_data.join("usage-tracker.sqlite");
            let store = AppStore::open(db_path)?;
            app.manage(AppState {
                store: Arc::new(Mutex::new(store)),
                proxy: Arc::new(Mutex::new(None)),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_dashboard,
            get_settings,
            save_settings,
            save_secret,
            test_openai_key,
            test_deepseek_key,
            get_deepseek_balance,
            sync_openai_usage,
            list_usage,
            list_costs,
            list_proxy_logs,
            start_deepseek_proxy,
            stop_deepseek_proxy,
            proxy_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
