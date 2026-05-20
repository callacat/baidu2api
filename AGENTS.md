# AGENTS.md

## Run

```bash
python main.py          # normal mode
python main.py debug    # debug logging
```

Service listens on `http://0.0.0.0:8000`. Docker: `docker-compose up -d`.

## Architecture

- `main.py` — FastAPI server, OpenAI-format `/v1/chat/completions` + `/v1/models`, SSE streaming
- `baidu_client.py` — Baidu chat API client: token extraction from HTML, SSE parsing, request signing
- `toolcall.py` — dual-mode function calling: XML (Toolify-style, default) and JSON (DS2API-style)
- `admin.py` — web admin panel at `/admin/` (config UI, API key management)
- `config.py` — `Config` singleton wrapping `config.json`; auto-loads on import, persists on mutation

## Config

- **`config.json`** (gitignored) — auto-created on first run. Keys: `api_keys`, `admin_key`, `toolcall_mode`, `max_query_length`.
- Env overrides: `BAIDU2API_CONFIG_PATH` (alt config path), `BAIDU2API_ADMIN_KEY` (initial admin password).
- Config auto-saves on mutation via `config.save()`.

## Key behaviors

- **Token lifecycle**: Baidu token extracted from `chat.baidu.com` HTML on first request, refreshed after 10 min or on 1001 status / empty response.
- **Context isolation**: Shared `httpx.AsyncClient` preserves cookies, but each request uses empty `ori_lid` so conversations don't leak across users.
- **Tools**: Default mode is XML (`config.toolcall_mode = "xml"`). Both XML and JSON modes auto-fallback to the other on parse failure.
- **API key auth**: Disabled by default when `api_keys` is empty. Adding any key via admin panel enables auth.
- **Tool call retry**: `ENABLE_FC_ERROR_RETRY = False` by default (in `toolcall.py`). Enables up to 3 retry attempts on parse/validation failure.

## No test/lint infrastructure

This project has no tests, no linter config, no typechecker setup, and no pre-commit hooks. The only CI is GitHub Actions for Docker builds and PyInstaller releases.

## Dependencies

Only 4 packages: `fastapi`, `uvicorn`, `httpx`, `pydantic`. Install with `pip install -r requirements.txt`.
