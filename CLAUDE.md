# Baidu2API

将 [chat.baidu.com](https://chat.baidu.com) 的 AI 对话能力封装为 OpenAI 兼容 API。

## Version Management

- **VERSION file**: at project root, contains current version string (e.g. `v1.3.0`)
- **CHANGELOG.md**: conventional changelog, keep [Unreleased] section updated
- **Commit format**: conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`)
- **Version bump rules**:
  - `feat!:` or includes `BREAKING CHANGE` → MAJOR +1
  - `feat:` → MINOR +1
  - `fix:` → PATCH +1
  - Other types → no bump
- **Release**: `npx commit-and-tag-version` to auto-bump and tag
- **GHCR**: Docker images auto-pushed on main branch push and v* tag via `.github/workflows/docker.yml`

## Project Structure

- `main.py` — FastAPI app, OpenAI-compatible endpoints, stream/non-stream handlers
- `baidu_client.py` — Baidu chat.baidu.com API client (SSE parsing, token management)
- `toolcall.py` — Dual-mode function calling (XML + JSON)
- `config.py` — Configuration management (JSON persistence)
- `admin.py` — Web admin panel
