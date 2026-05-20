import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from typing import AsyncIterator, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("baidu2api")


class BaiduChatClient:
    BASE_URL = "https://chat.baidu.com"
    CONVERSATION_URL = f"{BASE_URL}/aichat/api/conversation"

    MODEL_MAP = {
        "smartmode": "smartMode",
        "deepseek-v4-pro": "DeepSeek-V4",
        "deepseek-v4": "DeepSeek-V4",
        "deepseek-r1": "DeepSeek-R1",
        "ernie-4.5-turbo": "ERINE-4.5",
        "ernie-4.5": "ERINE-4.5",
    }

    AVAILABLE_MODELS = [
        {"id": "deepseek-v4-pro", "object": "model", "created": 0, "owned_by": "baidu"},
        {"id": "deepseek-r1", "object": "model", "created": 0, "owned_by": "baidu"},
        {"id": "ernie-4.5-turbo", "object": "model", "created": 0, "owned_by": "baidu"},
        {"id": "smartMode", "object": "model", "created": 0, "owned_by": "baidu"},
    ]

    X_CHAT_MESSAGE_QUERY_LIMIT = 200

    def __init__(self):
        self._token: Optional[str] = None
        self._lid: Optional[str] = None
        self._token_expire: float = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            now = time.time()
            if self._token and now < self._token_expire:
                return self._client

        async with self._lock:
            if self._client is not None and not self._client.is_closed:
                now = time.time()
                if self._token and now < self._token_expire:
                    return self._client
                await self._client.aclose()

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=120.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )

            resp = await self._client.get(self.BASE_URL)
            html = resp.text
            logger.debug("Visit chat.baidu.com: status=%d, cookies=%s", resp.status_code, list(self._client.cookies.keys()))

            token_match = re.search(r'"token"\s*:\s*"([^"]+)"', html)
            lid_match = re.search(r'"lid"\s*:\s*"(\d+)"', html)
            if token_match and lid_match:
                self._token = token_match.group(1)
                self._lid = lid_match.group(1)
                self._token_expire = time.time() + 600
                logger.info("Token refreshed: token=%s, lid=%s", self._token, self._lid)
            else:
                logger.warning("Failed to extract token/lid from page")

            return self._client

    async def _force_refresh(self):
        async with self._lock:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
            self._client = None
            self._token = None
            self._lid = None
            self._token_expire = 0

    def _generate_chat_token(self, query: str) -> str:
        ts = int(time.time() * 1000)
        md5_hash = hashlib.md5(query.encode()).hexdigest()
        payload = f"{self._token}|{md5_hash}|{ts}|{self._lid}"
        b64 = base64.b64encode(payload.encode()).decode()
        chat_token = f"{b64}-{self._lid}-3"
        logger.debug("Generated chat_token: token=%s, md5=%s, ts=%d, lid=%s", self._token, md5_hash, ts, self._lid)
        return chat_token

    def _resolve_model(self, model: str) -> str:
        model_lower = model.lower()
        for key, value in self.MODEL_MAP.items():
            if key == model_lower:
                return value
        return "smartMode"

    def _is_deepseek_model(self, model_name: str) -> bool:
        return model_name.startswith("DeepSeek")

    def _build_request_body(self, query: str, model_name: str, chat_token: str, images: Optional[list] = None) -> dict:
        query_entries = [
            {
                "type": "TEXT",
                "data": {
                    "text": {
                        "query": query,
                        "extData": "{}",
                        "text_type": "",
                    }
                },
            }
        ]
        if images:
            for img in images:
                url = img.get("url", "") if isinstance(img, dict) else str(img)
                if url:
                    query_entries.append({
                        "type": "IMAGE",
                        "data": {
                            "image": {
                                "url": url,
                            }
                        },
                    })
        return {
            "message": {
                "inputMethod": "chat_search",
                "isRebuild": False,
                "content": {
                    "query": "",
                    "agentInfo": {
                        "agent_id": [""],
                        "params": '{"agt_rk":1,"agt_sess_cnt":1}',
                    },
                    "agentInfoList": [],
                    "qtype": 0,
                },
                "searchInfo": {
                    "srcid": "",
                    "order": "",
                    "tplname": "",
                    "dqaKey": "",
                    "re_rank": "1",
                    "ori_lid": "",
                    "sa": "bkb",
                    "enter_type": "sidebar_dialog",
                    "chatParams": {
                        "setype": "csaitab",
                        "chat_samples": "WISE_NEW_CSAITAB",
                        "chat_token": chat_token,
                        "scene": "",
                    },
                    "isPrivateChat": False,
                    "usedModel": {
                        "modelName": model_name,
                        "modelFunction": {"deepSearch": "0", "internetSearch": "0"},
                        "showModelName": model_name,
                    },
                    "landingPageSwitch": "",
                    "landingPage": "aitab",
                    "ecomFrom": "",
                    "hasLocPermission": "",
                    "isInnovate": 2,
                    "applid": "",
                    "a_lid": "",
                    "showMindMap": False,
                    "deepDecisionInfo": {"isDeepDecision": 0},
                },
                "from": "",
                "source": "pc_csaitab",
                "query": query_entries,
                "anti_ext": {"inputT": None, "ck1": 162, "ck9": 496, "ck10": 350},
            },
            "sa": "bkb",
            "setype": "csaitab",
            "rank": 1,
        }

    def _build_headers(self, query: str, model_name: str) -> dict:
        is_deepseek = self._is_deepseek_model(model_name)
        header_query = query[:self.X_CHAT_MESSAGE_QUERY_LIMIT] if len(query) > self.X_CHAT_MESSAGE_QUERY_LIMIT else query
        headers = {
            "accept": "text/event-stream",
            "content-type": "application/json",
            "source": "pc_csaitab",
            "landingpageswitch": "",
            "personifiedswitch": "0",
            "X-Chat-Message": f"query:{quote(header_query)},anti_ext:%7B%22inputT%22%3Anull%2C%22ck1%22%3A162%2C%22ck9%22%3A496%2C%22ck10%22%3A350%7D,enter_type:sidebar_dialog,re_rank:1,modelName:{model_name},sa:bkb",
            "Origin": "https://chat.baidu.com",
            "Referer": "https://chat.baidu.com/search?enter_type=sidebar_dialog&internal=1",
        }
        if is_deepseek:
            headers["isDeepseek"] = "1"
        return headers

    async def chat_stream(
        self,
        query: str,
        model: str = "smartMode",
        images: Optional[list] = None,
    ) -> AsyncIterator[dict]:
        async for event in self._do_chat_stream(query, model, retry_on_token_fail=True, images=images):
            yield event

    async def _do_chat_stream(
        self,
        query: str,
        model: str,
        retry_on_token_fail: bool = True,
        images: Optional[list] = None,
    ) -> AsyncIterator[dict]:
        model_name = self._resolve_model(model)

        client = await self._ensure_client()
        chat_token = self._generate_chat_token(query)
        body = self._build_request_body(query, model_name, chat_token, images)
        headers = self._build_headers(query, model_name)

        logger.info("Request: model=%s -> %s, query_len=%d", model, model_name, len(query))
        logger.debug("Request body query: %s", query[:200])

        try:
            async with client.stream(
                "POST",
                self.CONVERSATION_URL,
                json=body,
                headers=headers,
            ) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    logger.error("Baidu API error: status=%d, body=%s", resp.status_code, error_text.decode()[:500])
                    raise RuntimeError(
                        f"Baidu API error: status={resp.status_code}, body={error_text.decode()}"
                    )

                buffer = ""
                token_failed = False
                has_content = False
                event_count = 0
                raw_chunks = []
                async for chunk in resp.aiter_text():
                    raw_chunks.append(chunk)
                    buffer += chunk
                    while "\n\n" in buffer:
                        event_str, buffer = buffer.split("\n\n", 1)
                        parsed = self._parse_sse_event(event_str)
                        if parsed:
                            event_count += 1
                            if (
                                parsed["type"] == "message"
                                and parsed["data"].get("status") == 1001
                            ):
                                logger.warning("Token validation failed (status=1001)")
                                token_failed = True
                            else:
                                if parsed["type"] == "message":
                                    has_content = True
                                    logger.debug("SSE message event #%d: keys=%s, component=%s",
                                                 event_count,
                                                 list(parsed["data"].keys()),
                                                 self._get_component_name(parsed["data"]))
                                yield parsed

                raw_total = "".join(raw_chunks)
                logger.info("SSE stream ended: events=%d, has_content=%s, token_failed=%s, raw_len=%d",
                            event_count, has_content, token_failed, len(raw_total))
                if not has_content and event_count > 0:
                    logger.warning("Got %d SSE events but no message events! Raw tail: %s",
                                   event_count, raw_total[-500:] if len(raw_total) > 500 else raw_total)

                if token_failed and retry_on_token_fail:
                    logger.info("Retrying with fresh token...")
                    await self._force_refresh()
                    async for event in self._do_chat_stream(
                        query, model, retry_on_token_fail=False, images=images
                    ):
                        yield event
                elif not has_content and retry_on_token_fail:
                    logger.warning("Empty response from Baidu API, refreshing token and retrying...")
                    await self._force_refresh()
                    async for event in self._do_chat_stream(
                        query, model, retry_on_token_fail=False, images=images
                    ):
                        yield event
        except httpx.ConnectError as e:
            logger.error("Connection error: %s", e)
            await self._force_refresh()
            raise

    @staticmethod
    def _get_component_name(data: dict) -> str:
        try:
            return data["data"]["message"]["content"]["generator"].get("component", "N/A")
        except (KeyError, TypeError):
            return "N/A"

    def _parse_sse_event(self, event_str: str) -> Optional[dict]:
        event_type = None
        data_str = None

        for line in event_str.strip().split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()

        if event_type == "ping" or not data_str:
            return None

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            logger.debug("Failed to parse SSE data: %s", data_str[:200])
            return None

        if event_type == "basedata":
            return {"type": "basedata", "data": data}

        if event_type == "message":
            return {"type": "message", "data": data}

        return None

    @staticmethod
    def extract_content(event: dict) -> Optional[str]:
        if event["type"] != "message":
            return None

        data = event["data"]

        try:
            generator = data["data"]["message"]["content"]["generator"]
            component = generator.get("component", "")
            if component == "markdown-yiyan":
                return generator.get("data", {}).get("value", "")
            if component == "thinkingSteps":
                return None
            if component in ("searchResult", "questionClosely"):
                return None
            value = generator.get("data", {}).get("value", "")
            if value:
                return value
        except (KeyError, TypeError):
            pass

        try:
            items = data["data"]["message"]["content"].get("items", [])
            for item in items:
                if item.get("type") == "text":
                    return item.get("data", {}).get("text", "")
        except (KeyError, TypeError):
            pass

        try:
            msg_data = data.get("data", {})
            msg = msg_data.get("message", {})
            content = msg.get("content", {})
            if isinstance(content, str) and content:
                return content
        except (KeyError, TypeError):
            pass

        return None

    @staticmethod
    def extract_thinking(event: dict) -> Optional[str]:
        if event["type"] != "message":
            return None

        data = event["data"]
        try:
            generator = data["data"]["message"]["content"]["generator"]
            component = generator.get("component", "")
            if component == "thinkingSteps":
                reasoning = generator.get("data", {}).get("reasoningContentArr", [])
                return "".join(reasoning)
        except (KeyError, TypeError):
            pass
        return None

    @staticmethod
    def is_finished(event: dict) -> bool:
        if event["type"] != "message":
            return False
        try:
            generator = event["data"]["data"]["message"]["content"]["generator"]
            return generator.get("isFinished", False)
        except (KeyError, TypeError):
            return False

    @staticmethod
    def is_end_turn(event: dict) -> bool:
        if event["type"] != "message":
            return False
        try:
            return event["data"]["data"]["message"]["metaData"].get("endTurn", False)
        except (KeyError, TypeError):
            return False

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
