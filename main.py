import asyncio
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
    StreamingFunctionCallDetector,
    build_tool_prompt,
    format_tool_choice_prompt,
    get_content_before_tool_call,
    get_trigger_signal,
    parse_tool_calls,
    preprocess_messages,
    set_current_tools,
    validate_parsed_tools,
    parse_function_calls_xml,
    _convert_parsed_to_openai,
    _classify_fc_failure,
    _diagnose_fc_parse_error,
    get_fc_error_retry_prompt,
    get_fc_continuation_prompt,
    _is_continuation_response,
    _merge_truncated_and_continuation,
    ENABLE_FC_ERROR_RETRY,
    FC_ERROR_RETRY_MAX_ATTEMPTS,
    find_last_trigger_signal_outside_think,
)
from admin import admin_router, increment_request_count

DEBUG = "debug" in [a.lower() for a in sys.argv[1:]]

logger = logging.getLogger("baidu2api")

client = BaiduChatClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await client.close()


app = FastAPI(title="Baidu2API - OpenAI Compatible API", lifespan=lifespan)
app.include_router(admin_router)


WELCOME_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Baidu2API</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f7fa;color:#1f2937;min-height:100vh;display:flex;align-items:center;justify-content:center}
.wrap{text-align:center;max-width:600px;padding:3rem 2rem}
h1{font-size:2.5rem;color:#2563eb;margin-bottom:0.5rem}
.sub{color:#6b7280;font-size:1.1rem;margin-bottom:2.5rem}
.links{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap}
.links a{display:inline-flex;align-items:center;gap:0.5rem;padding:0.75rem 1.5rem;border-radius:10px;text-decoration:none;font-weight:600;font-size:0.95rem;transition:all .2s}
.links a.primary{background:#2563eb;color:#fff}
.links a.primary:hover{background:#1d4ed8}
.links a.secondary{background:#fff;color:#374151;border:1px solid #d1d5db;box-shadow:0 1px 3px rgba(0,0,0,0.06)}
.links a.secondary:hover{border-color:#2563eb;color:#2563eb}
</style>
</head>
<body>
<div class="wrap">
  <h1>Baidu2API</h1>
  <p class="sub" id="subtitle"></p>
  <div class="links">
    <a href="/admin/" class="primary" id="adminLink"></a>
    <a href="/docs" class="secondary" id="docsLink"></a>
    <a href="https://github.com/dijiaozhibei-top/baidu2api" target="_blank" class="secondary" id="githubLink"></a>
  </div>
</div>
<script>
const zh = navigator.language.startsWith('zh');
document.getElementById('subtitle').textContent = zh ? '将 chat.baidu.com 的 AI 对话能力封装为 OpenAI 兼容 API' : 'Wrap chat.baidu.com AI into OpenAI-compatible API';
document.getElementById('adminLink').textContent = zh ? '管理后台' : 'Admin Panel';
document.getElementById('docsLink').textContent = zh ? 'API 文档' : 'API Docs';
document.getElementById('githubLink').textContent = 'GitHub';
</script>
</body>
</html>"""


@app.get("/")
async def welcome():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=WELCOME_HTML)


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
    if not config.api_keys and not config.admin_key:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    key = auth[7:].strip()
    if config.admin_key and key == config.admin_key:
        return
    if config.api_keys and key in config.api_keys:
        return
    if config.api_keys or config.admin_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _extract_multimodal_content(content: any) -> tuple[str, list[dict]]:
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return str(content), []
    text_parts = []
    images = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text_parts.append(item.get("text", ""))
        elif item.get("type") == "image_url":
            image_url = item.get("image_url", {})
            url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
            detail = image_url.get("detail", "auto") if isinstance(image_url, dict) else "auto"
            if url:
                images.append({"url": url, "detail": detail})
    return "\n".join(text_parts), images


def build_query(messages: list[dict], tools: Optional[list] = None, tool_choice=None, mode: str = "xml"):
    all_images = []
    normalized_messages = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            text, images = _extract_multimodal_content(content)
            if images:
                all_images.extend(images)
            normalized_messages.append({**msg, "content": text})
        else:
            normalized_messages.append(msg)

    processed = preprocess_messages(normalized_messages, tools, mode)

    parts = []
    if tools and mode != "none":
        parts.append(f"System: {build_tool_prompt(tools, mode)}")
        choice_prompt = format_tool_choice_prompt(tool_choice, tools)
        if choice_prompt:
            parts.append(f"System: {choice_prompt}")

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
            content = msg.get("content", "")
            if isinstance(content, list):
                text, _ = _extract_multimodal_content(content)
                content = text
            if content and msg.get("role") == "user":
                user_msg = content
                break
        if not user_msg:
            for msg in reversed(messages):
                content = msg.get("content", "")
                if isinstance(content, list):
                    text, _ = _extract_multimodal_content(content)
                    content = text
                if content:
                    user_msg = content
                    break

        system_parts = [msg["content"] for msg in messages if msg.get("role") == "system" and msg.get("content")]

        truncated_parts = []
        if tools and mode != "none":
            truncated_parts.append(f"System: {build_tool_prompt(tools, mode)}")
            choice_prompt = format_tool_choice_prompt(tool_choice, tools)
            if choice_prompt:
                truncated_parts.append(f"System: {choice_prompt}")
        if system_parts:
            truncated_parts.append("System: " + "\n\n".join(system_parts))
        truncated_parts.append(f"User: {user_msg}")

        truncated = "\n\n".join(truncated_parts)
        if len(truncated) > max_len:
            full = user_msg[:max_len] if user_msg else full[:max_len]
        else:
            full = truncated

    images = all_images if all_images else None
    return full, images


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": BaiduChatClient.AVAILABLE_MODELS}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    _check_api_key(request)
    increment_request_count()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    model = body.get("model", "smartMode")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    force = config.force_stream
    if force == "stream":
        stream = True
    elif force == "non-stream":
        stream = False
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")
    mode = config.toolcall_mode

    set_current_tools(tools)

    query, images = build_query(messages, tools, tool_choice, mode)
    if not query:
        raise HTTPException(status_code=400, detail="No message content provided")

    completion_id = generate_id()
    created = int(time.time())
    has_tools = tools is not None and mode != "none"

    logger.info("Chat request: model=%s, stream=%s, query_len=%d, has_tools=%s, mode=%s, images=%d",
                model, stream, len(query), has_tools, mode, len(images) if images else 0)
    if DEBUG:
        logger.debug("Full query: %s", query[:500])
        logger.debug("Full messages: %s", json.dumps(messages, ensure_ascii=False)[:500])

    if stream:
        return StreamingResponse(
            _stream_response(query, model, completion_id, created, has_tools, mode, tools, images),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _non_stream_response(
            query, model, completion_id, created, has_tools, mode, tools, messages, images
        )


async def _attempt_fc_retry(
    content: str,
    trigger_signal: str,
    messages: list[dict],
    tools: Optional[list],
    model: str,
    mode: str,
) -> Optional[list[dict]]:
    if not ENABLE_FC_ERROR_RETRY:
        return None

    max_attempts = FC_ERROR_RETRY_MAX_ATTEMPTS
    current_content = content
    current_messages = messages.copy()

    for attempt in range(max_attempts):
        if find_last_trigger_signal_outside_think(current_content, trigger_signal) == -1:
            logger.debug("No trigger signal found outside think blocks; not a function call attempt")
            return None

        parsed = parse_function_calls_xml(current_content, trigger_signal)
        if parsed:
            validation_error = validate_parsed_tools(parsed, tools or [])
            if not validation_error:
                if attempt > 0:
                    logger.info(f"Function call parsing succeeded on retry attempt {attempt + 1}")
                return _convert_parsed_to_openai(parsed)

        if attempt >= max_attempts - 1:
            logger.warning(f"Function call parsing failed after {max_attempts} attempts")
            return None

        failure_type = _classify_fc_failure(current_content, trigger_signal)
        if failure_type == "no_fc":
            return None

        error_details = _diagnose_fc_parse_error(current_content, trigger_signal)

        if failure_type == "truncated":
            retry_prompt = get_fc_continuation_prompt(current_content, error_details)
            logger.info(f"Function call output truncated, requesting continuation {attempt + 2}/{max_attempts}")
        else:
            retry_prompt = get_fc_error_retry_prompt(current_content, error_details)
            logger.info(f"Function call syntax error, requesting rewrite {attempt + 2}/{max_attempts}")

        retry_messages = current_messages + [
            {"role": "assistant", "content": current_content},
            {"role": "user", "content": retry_prompt}
        ]

        try:
            retry_query, _ = build_query(retry_messages, tools, mode=mode)
            retry_content = ""
            async for event in client.chat_stream(retry_query, model):
                if event["type"] != "message":
                    continue
                c = client.extract_content(event)
                if c:
                    retry_content += c
                if client.is_end_turn(event) or client.is_finished(event):
                    break

            if not retry_content:
                logger.warning("Retry response is empty")
                return None

            if failure_type == "truncated" and _is_continuation_response(retry_content, trigger_signal):
                current_content = _merge_truncated_and_continuation(current_content, retry_content)
                logger.info(f"Merged continuation, total length: {len(current_content)}")
            else:
                current_content = retry_content

            current_messages = retry_messages
        except Exception as e:
            logger.error(f"Retry request failed: {e}")
            return None

    return None


async def _stream_from_result(result, completion_id: str, created: int, model: str):
    """Convert a non-stream ChatCompletionResponse to SSE stream chunks."""
    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]}, ensure_ascii=True)}\n\n"

    message = result.choices[0].message
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls")
    thinking = message.get("reasoning_content") or ""
    finish = result.choices[0].finish_reason

    if thinking:
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'reasoning_content': thinking}, 'finish_reason': None}]}, ensure_ascii=True)}\n\n"

    if content:
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'content': content}, 'finish_reason': None}]}, ensure_ascii=True)}\n\n"

    if tool_calls:
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'tool_calls': tool_calls}, 'finish_reason': tool_calls and 'tool_calls' or 'stop'}]}, ensure_ascii=True)}\n\n"

    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}, ensure_ascii=True)}\n\n"
    yield "data: [DONE]\n\n"
    logger.info("Stream reconstructed from result: content_len=%d, thinking_len=%d, finish=%s",
                len(content), len(thinking), finish)


async def _stream_response(query: str, model: str, completion_id: str, created: int, has_tools: bool, mode: str, tools: Optional[list] = None, images: Optional[list] = None):
    full_content = ""
    full_thinking = ""
    trigger_signal = get_trigger_signal() if has_tools else None
    detector = StreamingFunctionCallDetector(trigger_signal) if has_tools else None
    max_retries = 2

    for attempt in range(max_retries + 1):
        full_content = ""
        full_thinking = ""
        if detector:
            detector.reset()
        got_end = False

        try:
            stream = client.chat_stream(query, model, images=images).__aiter__()
            while True:
                try:
                    timeout = 0.5 if got_end else 120.0
                    event = await asyncio.wait_for(stream.__anext__(), timeout=timeout)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break

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
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=True)}\n\n"

                content = client.extract_content(event)
                if content:
                    if detector:
                        is_detected, content_to_yield = detector.process_chunk(content)
                        if content_to_yield:
                            full_content += content_to_yield
                            chunk_data = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": content_to_yield}, "finish_reason": None}],
                            }
                            yield f"data: {json.dumps(chunk_data, ensure_ascii=True)}\n\n"
                        if is_detected:
                            continue
                    else:
                        if isinstance(content, str):
                            full_content += content
                            chunk_data = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
                            }
                            yield f"data: {json.dumps(chunk_data, ensure_ascii=True)}\n\n"
                        elif content:
                            logger.warning("extract_content returned non-str type: %s", type(content).__name__)

                if client.is_end_turn(event) or client.is_finished(event):
                    got_end = True
                    logger.debug("Stream end_turn: full_content_len=%d, thinking_len=%d, last_content=%s",
                                 len(full_content), len(full_thinking), repr(full_content[-80:]))

                    if detector and detector.state == "tool_parsing":
                        parsed = detector.finalize()
                        if parsed:
                            validation_error = validate_parsed_tools(parsed, tools or [])
                            if validation_error:
                                logger.info(f"Tool/schema validation failed in stream finalize: {validation_error}")
                                parsed = None

                        if parsed:
                            tool_calls = _convert_parsed_to_openai(parsed)
                            tc_chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": tool_calls,
                                    },
                                    "finish_reason": "tool_calls",
                                }],
                            }
                            yield f"data: {json.dumps(tc_chunk, ensure_ascii=True)}\n\n"
                            yield "data: [DONE]\n\n"
                            logger.info("Stream completed with tool calls: content_len=%d, tool_calls=%d",
                                        len(full_content), len(tool_calls))
                            return
                        else:
                            if detector.content_buffer:
                                full_content += detector.content_buffer
                                chunk_data = {
                                    "id": completion_id,
                                    "object": "chat.completion.chunk",
                                    "created": created,
                                    "model": model,
                                    "choices": [{"index": 0, "delta": {"content": detector.content_buffer}, "finish_reason": None}],
                                }
                                yield f"data: {json.dumps(chunk_data, ensure_ascii=True)}\n\n"

                    elif has_tools:
                        tool_calls = parse_tool_calls(full_content, mode)
                        if tool_calls:
                            tc_chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": tool_calls,
                                    },
                                    "finish_reason": "tool_calls",
                                }],
                            }
                            yield f"data: {json.dumps(tc_chunk, ensure_ascii=True)}\n\n"
                            yield "data: [DONE]\n\n"
                            logger.info("Stream completed with tool calls: content_len=%d, tool_calls=%d",
                                        len(full_content), len(tool_calls))
                            return

                    # got_end=True: timeout switches to 0.5s for drain
                    # No explicit break needed - the while True loop handles it

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

        if full_content or full_thinking or not got_end:
            break

        if attempt < max_retries:
            logger.warning("Stream empty response (attempt %d/%d), waiting and retrying...", attempt + 1, max_retries)
            await asyncio.sleep(2)
        else:
            logger.warning("Stream empty response after %d retries", max_retries)

    chunk_data = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(chunk_data, ensure_ascii=True)}\n\n"
    yield "data: [DONE]\n\n"
    logger.info("Stream completed: content_len=%d, thinking_len=%d", len(full_content), len(full_thinking))
    if DEBUG:
        logger.debug("Stream full content: %s", full_content[:500])
        if full_thinking:
            logger.debug("Stream full thinking: %s", full_thinking[:500])


async def _non_stream_response(
    query: str, model: str, completion_id: str, created: int, has_tools: bool, mode: str,
    tools: Optional[list] = None, messages: Optional[list] = None,
    images: Optional[list] = None,
):
    full_content = ""
    full_thinking = ""
    max_retries = 2

    for attempt in range(max_retries + 1):
        full_content = ""
        full_thinking = ""

        async for event in client.chat_stream(query, model, images=images):
            if event["type"] != "message":
                continue

            thinking = client.extract_thinking(event)
            if thinking:
                full_thinking += thinking

            content = client.extract_content(event)
            if isinstance(content, str):
                full_content += content
            elif content:
                logger.warning("extract_content returned non-str type: %s", type(content).__name__)

            if client.is_end_turn(event) or client.is_finished(event):
                break

        if full_content or full_thinking:
            break

        if attempt < max_retries:
            logger.warning("Empty response (attempt %d/%d), waiting and retrying...", attempt + 1, max_retries)
            await asyncio.sleep(2)
        else:
            logger.warning("Empty response after %d retries", max_retries)

    message = {"role": "assistant", "content": full_content}
    finish_reason = "stop"

    if has_tools:
        trigger_signal = get_trigger_signal()
        parsed = parse_function_calls_xml(full_content, trigger_signal)
        if parsed:
            validation_error = validate_parsed_tools(parsed, tools or [])
            if validation_error:
                logger.info(f"Tool call validation failed: {validation_error}")
                retry_result = await _attempt_fc_retry(
                    full_content, trigger_signal, messages or [], tools, model, mode
                )
                if retry_result:
                    prefix_content = get_content_before_tool_call(full_content, mode)
                    message = {
                        "role": "assistant",
                        "content": prefix_content,
                        "tool_calls": retry_result,
                    }
                    finish_reason = "tool_calls"
                else:
                    parsed = None
            else:
                tool_calls = _convert_parsed_to_openai(parsed)
                prefix_content = get_content_before_tool_call(full_content, mode)
                message = {
                    "role": "assistant",
                    "content": prefix_content,
                    "tool_calls": tool_calls,
                }
                finish_reason = "tool_calls"
        else:
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
