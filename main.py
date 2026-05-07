import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from baidu_client import BaiduChatClient

DEBUG = "debug" in [a.lower() for a in sys.argv[1:]]

logger = logging.getLogger("baidu2api")

client = BaiduChatClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await client.close()


app = FastAPI(title="Baidu2API - OpenAI Compatible API", lifespan=lifespan)


class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = ""
    name: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = "smartMode"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    tools: Optional[list] = None


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: dict
    finish_reason: Optional[str] = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: UsageInfo = UsageInfo()


def generate_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:29]}"


MAX_QUERY_LENGTH = 30000


def build_query(messages: list[ChatMessage], tools: Optional[list] = None) -> str:
    parts = []

    if tools:
        tool_lines = []
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {})
            tool_lines.append(f"- {name}: {desc}\n  Parameters: {json.dumps(params, ensure_ascii=False)}")
        parts.append("# Available Tools\n\nYou have access to the following tools. When you need to call a tool, respond with a JSON block in the following format:\n```json\n{\"name\": \"tool_name\", \"arguments\": {...}}\n```\n\n" + "\n\n".join(tool_lines))

    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            tc_lines = []
            for tc in msg.tool_calls:
                func = tc.get("function", {})
                tc_lines.append(f"Assistant called tool: {func.get('name', '')}({func.get('arguments', '')})")
            if msg.content:
                parts.append(f"Assistant: {msg.content}\n" + "\n".join(tc_lines))
            else:
                parts.append("\n".join(tc_lines))
            continue

        if not msg.content:
            continue

        if msg.role == "system":
            parts.append(f"System: {msg.content}")
        elif msg.role == "user":
            parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            parts.append(f"Assistant: {msg.content}")
        elif msg.role == "tool":
            label = msg.name or msg.tool_call_id or "tool"
            parts.append(f"Tool({label}): {msg.content}")
        else:
            parts.append(f"{msg.role}: {msg.content}")

    full = "\n\n".join(parts)

    if len(full) > MAX_QUERY_LENGTH:
        logger.warning("Query too long (%d chars), truncating to %d", len(full), MAX_QUERY_LENGTH)
        user_msg = ""
        for msg in reversed(messages):
            if msg.content and msg.role == "user":
                user_msg = msg.content
                break
        if not user_msg:
            for msg in reversed(messages):
                if msg.content:
                    user_msg = msg.content
                    break

        system_parts = []
        tool_parts = []
        for msg in messages:
            if msg.role == "system" and msg.content:
                system_parts.append(msg.content)
        if tools:
            for tool in tools:
                func = tool.get("function", {})
                name = func.get("name", "")
                desc = func.get("description", "")
                params = func.get("parameters", {})
                tool_parts.append(f"- {name}: {desc}\n  Parameters: {json.dumps(params, ensure_ascii=False)}")

        truncated_parts = []
        if tools:
            truncated_parts.append("# Available Tools\n\nYou have access to the following tools. When you need to call a tool, respond with a JSON block in the following format:\n```json\n{\"name\": \"tool_name\", \"arguments\": {...}}\n```\n\n" + "\n\n".join(tool_parts))
        if system_parts:
            truncated_parts.append("System: " + "\n\n".join(system_parts))
        truncated_parts.append(f"User: {user_msg}")

        truncated = "\n\n".join(truncated_parts)
        if len(truncated) > MAX_QUERY_LENGTH:
            full = user_msg[:MAX_QUERY_LENGTH] if user_msg else full[:MAX_QUERY_LENGTH]
        else:
            full = truncated

    return full


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": BaiduChatClient.AVAILABLE_MODELS}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    query = build_query(request.messages, request.tools)
    if not query:
        raise HTTPException(status_code=400, detail="No message content provided")

    completion_id = generate_id()
    created = int(time.time())

    logger.info("Chat request: model=%s, stream=%s, query_len=%d", request.model, request.stream, len(query))
    if DEBUG:
        logger.debug("Full query: %s", query[:500])
        logger.debug("Full messages: %s", json.dumps([m.model_dump() for m in request.messages], ensure_ascii=False))

    if request.stream:
        return StreamingResponse(
            _stream_response(query, request.model, completion_id, created),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _non_stream_response(
            query, request.model, completion_id, created
        )


async def _stream_response(query: str, model: str, completion_id: str, created: int):
    full_content = ""
    full_thinking = ""
    try:
        async for event in client.chat_stream(query, model):
            if event["type"] == "basedata":
                continue
            if event["type"] != "message":
                continue

            thinking = client.extract_thinking(event)
            if thinking:
                full_thinking += thinking
                chunk_data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"reasoning_content": thinking}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                continue

            content = client.extract_content(event)
            if content:
                full_content += content
                chunk_data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"

            if client.is_end_turn(event):
                chunk_data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                logger.info("Stream completed: content_len=%d, thinking_len=%d", len(full_content), len(full_thinking))
                if DEBUG:
                    logger.debug("Stream full content: %s", full_content[:500])
                    if full_thinking:
                        logger.debug("Stream full thinking: %s", full_thinking[:500])
                return

    except Exception as e:
        logger.error("Stream error: %s", str(e))
        error_data = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": f"\n\n[Error: {str(e)}]"}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    yield "data: [DONE]\n\n"


async def _non_stream_response(
    query: str, model: str, completion_id: str, created: int
):
    full_content = ""
    full_thinking = ""

    async for event in client.chat_stream(query, model):
        if event["type"] != "message":
            continue

        thinking = client.extract_thinking(event)
        if thinking:
            full_thinking += thinking

        content = client.extract_content(event)
        if content:
            full_content += content

        if client.is_end_turn(event):
            break

    message = {"role": "assistant", "content": full_content}
    if full_thinking:
        message["reasoning_content"] = full_thinking

    logger.info("Non-stream completed: content_len=%d, thinking_len=%d", len(full_content), len(full_thinking))
    if DEBUG:
        logger.debug("Non-stream full content: %s", full_content[:500])
        if full_thinking:
            logger.debug("Non-stream full thinking: %s", full_thinking[:500])

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=model,
        choices=[ChatCompletionChoice(message=message)],
    )


def setup_logging():
    log_level = logging.DEBUG if DEBUG else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger = logging.getLogger("baidu2api")
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(logging.WARNING if not DEBUG else logging.INFO)

    logger.info("Debug mode: %s", DEBUG)


if __name__ == "__main__":
    import uvicorn

    setup_logging()

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning" if not DEBUG else "info")
