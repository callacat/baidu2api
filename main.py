import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from baidu_client import BaiduChatClient
from config import config
from toolcall import (
    build_tool_prompt,
    format_tool_choice_prompt,
    get_content_before_tool_call,
    parse_tool_calls,
    preprocess_messages,
)
from admin import admin_router

DEBUG = "debug" in [a.lower() for a in sys.argv[1:]]

logger = logging.getLogger("baidu2api")

client = BaiduChatClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await client.close()


app = FastAPI(title="Baidu2API - OpenAI Compatible API", lifespan=lifespan)
app.include_router(admin_router)


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


def _check_api_key(request: Request):
    if not config.api_keys:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    key = auth[7:].strip()
    if key not in config.api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")


def build_query(messages: list[dict], tools: Optional[list] = None, tool_choice=None, mode: str = "xml") -> str:
    processed = preprocess_messages(messages, tools, mode)

    parts = []
    if tools:
        parts.append(build_tool_prompt(tools, mode))
        choice_prompt = format_tool_choice_prompt(tool_choice, tools)
        if choice_prompt:
            parts.append(choice_prompt)

    for msg in processed:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        else:
            parts.append(f"{role}: {content}")

    full = "\n\n".join(parts)

    max_len = config.max_query_length
    if max_len > 0 and len(full) > max_len:
        logger.warning("Query too long (%d chars), truncating to %d", len(full), max_len)
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("content") and msg.get("role") == "user":
                user_msg = msg["content"]
                break
        if not user_msg:
            for msg in reversed(messages):
                if msg.get("content"):
                    user_msg = msg["content"]
                    break

        system_parts = [msg["content"] for msg in messages if msg.get("role") == "system" and msg.get("content")]

        truncated_parts = []
        if tools:
            truncated_parts.append(build_tool_prompt(tools, mode))
            choice_prompt = format_tool_choice_prompt(tool_choice, tools)
            if choice_prompt:
                truncated_parts.append(choice_prompt)
        if system_parts:
            truncated_parts.append("System: " + "\n\n".join(system_parts))
        truncated_parts.append(f"User: {user_msg}")

        truncated = "\n\n".join(truncated_parts)
        if len(truncated) > max_len:
            full = user_msg[:max_len] if user_msg else full[:max_len]
        else:
            full = truncated

    return full


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": BaiduChatClient.AVAILABLE_MODELS}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    _check_api_key(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    model = body.get("model", "smartMode")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")
    mode = config.toolcall_mode

    query = build_query(messages, tools, tool_choice, mode)
    if not query:
        raise HTTPException(status_code=400, detail="No message content provided")

    completion_id = generate_id()
    created = int(time.time())
    has_tools = tools is not None

    logger.info("Chat request: model=%s, stream=%s, query_len=%d, has_tools=%s, mode=%s",
                model, stream, len(query), has_tools, mode)
    if DEBUG:
        logger.debug("Full query: %s", query[:500])
        logger.debug("Full messages: %s", json.dumps(messages, ensure_ascii=False)[:500])

    if stream:
        return StreamingResponse(
            _stream_response(query, model, completion_id, created, has_tools, mode),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _non_stream_response(
            query, model, completion_id, created, has_tools, mode
        )


async def _stream_response(query: str, model: str, completion_id: str, created: int, has_tools: bool, mode: str):
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

            if client.is_end_turn(event) or client.is_finished(event):
                if has_tools:
                    tool_calls = parse_tool_calls(full_content, mode)
                    if tool_calls:
                        prefix_content = get_content_before_tool_call(full_content, mode)
                        tc_chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "content": prefix_content,
                                    "tool_calls": tool_calls,
                                },
                                "finish_reason": "tool_calls",
                            }],
                        }
                        yield f"data: {json.dumps(tc_chunk, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        logger.info("Stream completed with tool calls: content_len=%d, tool_calls=%d",
                                    len(full_content), len(tool_calls))
                        return

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
    query: str, model: str, completion_id: str, created: int, has_tools: bool, mode: str
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

        if client.is_end_turn(event) or client.is_finished(event):
            break

    message = {"role": "assistant", "content": full_content}
    finish_reason = "stop"

    if has_tools:
        tool_calls = parse_tool_calls(full_content, mode)
        if tool_calls:
            prefix_content = get_content_before_tool_call(full_content, mode)
            message = {
                "role": "assistant",
                "content": prefix_content,
                "tool_calls": tool_calls,
            }
            finish_reason = "tool_calls"

    if full_thinking:
        message["reasoning_content"] = full_thinking

    logger.info("Non-stream completed: content_len=%d, thinking_len=%d, finish_reason=%s",
                len(full_content), len(full_thinking), finish_reason)
    if DEBUG:
        logger.debug("Non-stream full content: %s", full_content[:500])
        if full_thinking:
            logger.debug("Non-stream full thinking: %s", full_thinking[:500])

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=model,
        choices=[ChatCompletionChoice(message=message, finish_reason=finish_reason)],
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
