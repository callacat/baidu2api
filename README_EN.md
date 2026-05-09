# Baidu2API

Wrap [chat.baidu.com](https://chat.baidu.com) AI chat into an OpenAI-compatible API. No login required.

**中文**: [README.md](README.md)

## Features

- **OpenAI Compatible** — Full support for `/v1/chat/completions` and `/v1/models`
- **Multi-Model** — DeepSeek-V4, DeepSeek-R1, ERNIE-4.5, Smart Mode
- **Streaming** — SSE streaming output, compatible with all OpenAI SDKs
- **Chain of Thought** — DeepSeek-R1 reasoning via `reasoning_content` field
- **Dual Tool Calling** — XML (Toolify-style) and JSON (DS2API-style) function calling mechanisms
- **API Key Auth** — Optional API key authentication to protect your API
- **Web Admin Panel** — Visual configuration management, API key management, tool calling mode
- **Context Isolation** — Each request is independent, no cross-request session leakage
- **Unlimited Context** — No prompt length limit by default, configurable max length
- **Zero Config** — No Baidu account or API key required, works out of the box

## Supported Models

| Model ID | Baidu Model | Thinking | Description |
|----------|-------------|----------|-------------|
| `deepseek-v4-pro` | DeepSeek-V4 | ✅ | DeepSeek V4, 1M context |
| `deepseek-r1` | DeepSeek-R1 | ✅ | DeepSeek R1 reasoning model |
| `ernie-4.5-turbo` | ERNIE-4.5 | ❌ | ERNIE 4.5 |
| `smartMode` | Smart Mode | ❌ | Baidu intelligent routing |

## Quick Start

### Option 1: Local

```bash
git clone https://github.com/dijiaozhibei-top/baidu2api.git
cd baidu2api
pip install -r requirements.txt
python main.py          # Start server
python main.py debug    # Debug mode
```

Server listens on `http://0.0.0.0:8000`

### Option 2: Docker (Pre-built Image)

```bash
# Copy environment config
cp .env.example .env
# Edit .env to set admin key
# BAIDU2API_ADMIN_KEY=your-secret-key

# Start with Docker Compose
docker-compose up -d
docker-compose logs -f
```

Image URLs:
- **Docker Hub**: `dijiaozhibei/baidu2api:latest`
- 🇨🇳 China mirror: `docker.1ms.run/dijiaozhibei/baidu2api:latest`
- **ghcr.io**: `ghcr.io/dijiaozhibei-top/baidu2api:latest`
- 🇨🇳 China mirror: `ghcr.nju.edu.cn/dijiaozhibei-top/baidu2api:latest`

Or use `docker run` directly:

```bash
docker run -d -p 8000:8000 \
  -e BAIDU2API_ADMIN_KEY=mysecret \
  -v ./config.json:/app/config.json \
  dijiaozhibei/baidu2api:latest
```

### Option 3: Manual Docker Build

```bash
docker build -t baidu2api .
docker run -d -p 8000:8000 --name baidu2api baidu2api
```

## Web Admin Panel

After starting the service, visit `http://localhost:8000/admin/` to access the admin panel.

On first access, you will be prompted to create an admin password (minimum 4 characters). Subsequent visits require this password to log in.

Admin panel features:
- View service status
- Switch tool calling mode (XML / JSON)
- Manage API keys (add/delete)
- Modify configuration

## API Key Authentication

Authentication is disabled by default. Add API keys via the admin panel to enable it.

When enabled, all `/v1/chat/completions` requests require the `Authorization: Bearer <your-api-key>` header.

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Tool Calling

Two function calling mechanisms are supported, switchable via the admin panel:

### XML Mode (Toolify-style, default)

Uses XML tag format to trigger tool calls, better compatibility:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [{"role": "user", "content": "Weather in Beijing?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
          "type": "object",
          "properties": {"location": {"type": "string"}},
          "required": ["location"]
        }
      }
    }]
  }'
```

### JSON Mode (DS2API-style)

Uses JSON format to trigger tool calls, compatible with the DS2API project.

Both modes support automatic fallback: when the primary mode fails to parse, it automatically tries the other mode.

## API Reference

### List Models

```bash
curl http://localhost:8000/v1/models
```

### Chat Completion

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

### Streaming

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-r1",
    "messages": [{"role": "user", "content": "What is 1+1?"}],
    "stream": true
  }'
```

## Integration with Third-Party Clients

### OpenAI SDK (Python)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### OpenAI SDK (Node.js)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'not-needed',
});

const stream = await client.chat.completions.create({
  model: 'deepseek-r1',
  messages: [{ role: 'user', content: 'Hello' }],
  stream: true,
});

for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content || '');
}
```

### Claude Code / Cursor / Continue

Set the API Base URL to `http://localhost:8000/v1` and fill any value for the API Key (when auth is disabled).

## Configuration

Config file is `config.json`, supports `BAIDU2API_CONFIG_PATH` environment variable for custom path.

| Setting | Default | Description |
|---------|---------|-------------|
| `api_keys` | `[]` | API key list, empty = no auth |
| `admin_key` | `""` | Admin panel access key (created on first access) |
| `toolcall_mode` | `"xml"` | Tool calling mode: `xml` or `json` |
| `max_query_length` | `0` | Max prompt length, 0 = unlimited |

## How It Works

1. **Token Acquisition** — Visit chat.baidu.com, extract token and lid from HTML
2. **Signature Generation** — `base64(token|md5(query)|timestamp|lid)-lid-3`
3. **Message Flattening** — Convert OpenAI multi-message format into single text prompt
4. **Tool Injection** — Inject tool definitions into prompt based on configured mode
5. **SSE Streaming** — Parse Baidu SSE events, convert to OpenAI-compatible SSE format
6. **Context Isolation** — Shared HTTP client for cookies, empty ori_lid per request

## Disclaimer

- This project is for educational purposes only
- Baidu may change their API at any time, breaking this project
- Please use responsibly and avoid excessive requests
- This project does not collect or store any user data

## Acknowledgements

- [ds2api](https://github.com/CJackHwang/ds2api) — Architecture reference and JSON tool calling mechanism
- [toolify](https://github.com/funnycups/toolify) — XML tool calling mechanism reference

## License

[AGPL-3.0](LICENSE)

This project integrates code from [toolify](https://github.com/funnycups/toolify) (GPL-3.0) and [ds2api](https://github.com/CJackHwang/ds2api) (AGPL-3.0), therefore licensed under AGPL-3.0.
