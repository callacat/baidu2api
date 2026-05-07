# Baidu2API

Wrap [chat.baidu.com](https://chat.baidu.com) AI chat into an OpenAI-compatible API. No login required.

**中文**: [README.md](README.md)

## Features

- **OpenAI Compatible** — Full support for `/v1/chat/completions` and `/v1/models`
- **Multi-Model** — DeepSeek-V4, DeepSeek-R1, ERINE-4.5, Smart Mode
- **Streaming** — SSE streaming output, compatible with all OpenAI SDKs
- **Chain of Thought** — DeepSeek-R1 reasoning via `reasoning_content` field
- **Tool Calling** — OpenAI-format tools definition, auto-injected into prompt
- **Context Isolation** — Each request is independent, no cross-request session leakage
- **Long Context** — Supports up to 30000 characters of prompt (including system/tools/history)
- **Zero Config** — No Baidu account or API key required, works out of the box

## Supported Models

| Model ID | Baidu Model | Thinking | Description |
|----------|-------------|----------|-------------|
| `deepseek-v4-pro` | DeepSeek-V4 | ❌ | DeepSeek V4, 1M context |
| `deepseek-r1` | DeepSeek-R1 | ✅ | DeepSeek R1 reasoning model |
| `ernie-4.5-turbo` | ERINE-4.5 | ❌ | ERNIE 4.5 |
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

### Option 2: Docker Compose

```bash
docker-compose up -d
docker-compose logs -f
```

### Option 3: Manual Docker

```bash
docker build -t baidu2api .
docker run -d -p 8000:8000 --name baidu2api baidu2api
```

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

### With Tools

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

Set the API Base URL to `http://localhost:8000/v1` and fill any value for the API Key.

## How It Works

1. **Token Acquisition** — Visit chat.baidu.com, extract token and lid from HTML
2. **Signature Generation** — `base64(token|md5(query)|timestamp|lid)-lid-3`
3. **Message Flattening** — Convert OpenAI multi-message format into single text prompt
4. **SSE Streaming** — Parse Baidu SSE events, convert to OpenAI-compatible SSE format
5. **Context Isolation** — Shared HTTP client for cookies, empty ori_lid per request

## Disclaimer

- This project is for educational purposes only
- Baidu may change their API at any time, breaking this project
- Please use responsibly and avoid excessive requests
- This project does not collect or store any user data

## Acknowledgements

- [ds2api](https://github.com/CJackHwang/ds2api) — Architecture reference for wrapping web chat into OpenAI API

## License

[MIT](LICENSE)
