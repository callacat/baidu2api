# Baidu2API

将 [chat.baidu.com](https://chat.baidu.com) 的 AI 对话能力封装为 OpenAI 兼容 API，无需登录即可使用。

**English**: [README_EN.md](README_EN.md)

## 功能特性

- **OpenAI 兼容** — 完整支持 `/v1/chat/completions` 和 `/v1/models` 接口
- **多模型支持** — DeepSeek-V4、DeepSeek-R1、ERINE-4.5、智能模式
- **流式输出** — 支持 SSE 流式响应，兼容所有 OpenAI SDK
- **思维链输出** — DeepSeek-R1 的推理过程通过 `reasoning_content` 字段输出
- **工具调用** — 支持 OpenAI 格式的 tools 定义，自动注入 prompt
- **上下文隔离** — 每次请求独立，不会泄漏跨请求的会话信息
- **长上下文** — 支持最长 30000 字符的 prompt（含 system/tools/历史消息）
- **零配置** — 无需百度账号，无需 API Key，开箱即用

## 支持的模型

| 模型 ID | 百度模型 | 思维链 | 说明 |
|---------|---------|--------|------|
| `deepseek-v4-pro` | DeepSeek-V4 | ❌ | DeepSeek V4，1M 上下文 |
| `deepseek-r1` | DeepSeek-R1 | ✅ | DeepSeek R1 推理模型 |
| `ernie-4.5-turbo` | ERINE-4.5 | ❌ | 文心 4.5 |
| `smartMode` | 智能模式 | ❌ | 百度智能路由 |

## 快速开始

### 方式一：本地运行

```bash
# 克隆仓库
git clone https://github.com/your-username/baidu2api.git
cd baidu2api

# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py

# 调试模式
python main.py debug
```

服务默认监听 `http://0.0.0.0:8000`

### 方式二：Docker 运行

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 方式三：手动 Docker 构建

```bash
docker build -t baidu2api .
docker run -d -p 8000:8000 --name baidu2api baidu2api
```

## API 文档

### 获取模型列表

```bash
curl http://localhost:8000/v1/models
```

### 对话补全

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [
      {"role": "user", "content": "你好"}
    ],
    "stream": false
  }'
```

### 流式对话

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-r1",
    "messages": [
      {"role": "user", "content": "1+1等于几？"}
    ],
    "stream": true
  }'
```

### 带工具调用

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [
      {"role": "user", "content": "北京天气怎么样？"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "获取指定城市的天气",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {"type": "string", "description": "城市名称"}
            },
            "required": ["location"]
          }
        }
      }
    ]
  }'
```

### 多轮对话

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [
      {"role": "system", "content": "你是一个有帮助的助手"},
      {"role": "user", "content": "我叫小明"},
      {"role": "assistant", "content": "你好小明！"},
      {"role": "user", "content": "我叫什么名字？"}
    ]
  }'
```

## 接入第三方客户端

### OpenAI SDK (Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "user", "content": "你好"}],
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
  messages: [{ role: 'user', content: '你好' }],
  stream: true,
});

for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content || '');
}
```

### Claude Code / Cursor / Continue 等工具

在工具设置中将 API Base URL 设为 `http://localhost:8000/v1`，API Key 填任意值即可。

## 项目结构

```
baidu2api/
├── baidu_client.py    # 百度聊天 API 客户端（Token 管理、请求构建、SSE 解析）
├── main.py            # FastAPI 服务（OpenAI 格式适配、消息拼接、流式输出）
├── requirements.txt   # Python 依赖
├── Dockerfile         # Docker 构建文件
├── docker-compose.yml # Docker Compose 配置
├── .gitignore
├── .dockerignore
├── LICENSE
└── README.md
```

## 工作原理

1. **Token 获取** — 访问 chat.baidu.com 首页，从页面 HTML 中提取 token 和 lid
2. **签名生成** — 使用 `base64(token|md5(query)|timestamp|lid)-lid-3` 生成 chat_token
3. **消息拼接** — 将 OpenAI 多消息格式（system/user/assistant/tool）扁平化为单条文本
4. **SSE 流式** — 解析百度 SSE 事件流，实时转换为 OpenAI 兼容的 SSE 格式
5. **上下文隔离** — 共享 HTTP 客户端保持 Cookie，但每次请求使用空 ori_lid 确保独立

## 注意事项

- 本项目仅供学习交流使用，请勿用于商业用途
- 百度可能会随时更改 API 接口，导致本项目失效
- 请合理使用，避免高频请求给百度服务器带来压力
- 本项目不收集、不存储任何用户数据

## 致谢

- [ds2api](https://github.com/CJackHwang/ds2api) — 提供了将 Web 聊天封装为 OpenAI API 的架构参考

## License

[MIT](LICENSE)
