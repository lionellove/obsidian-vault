# DeepSeek + OpenAI/Codex Usage Tracker

Local desktop app for tracking DeepSeek API usage through a local proxy and OpenAI/Codex-visible organization usage through OpenAI Usage/Costs APIs.

## Features

- OpenAI/Codex page pulls `organization/usage/completions` and `organization/costs`.
- DeepSeek proxy listens on `127.0.0.1:8787` by default and forwards `/v1/chat/completions`.
- SQLite stores usage buckets, cost buckets, proxy request metadata, and non-secret settings.
- API keys are stored in the operating system keyring under the service name `api-usage-tracker`.
- Request and response bodies are not persisted.

## Run

```bash
npm install
npm run tauri dev
```

## Configure DeepSeek clients

Set your DeepSeek SDK base URL to the local proxy:

```text
http://127.0.0.1:8787/v1
```

The app forwards traffic to `https://api.deepseek.com/v1` and records usage metadata from the response.

## OpenAI Admin API Key

OpenAI Usage and Costs APIs require an Admin API key created by an organization owner. The app uses it only from the local backend and stores it in the OS keyring.
