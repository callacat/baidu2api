import json
import logging
import re
import secrets
import string
import uuid
import xml.etree.ElementTree as ET
from typing import Optional

logger = logging.getLogger("baidu2api")

TRIGGER_SIGNAL = None


def get_trigger_signal() -> str:
    global TRIGGER_SIGNAL
    if TRIGGER_SIGNAL is None:
        chars = string.ascii_letters + string.digits
        random_str = "".join(secrets.choice(chars) for _ in range(4))
        TRIGGER_SIGNAL = f"<Function_{random_str}_Start/>"
        logger.info("Generated trigger signal: %s", TRIGGER_SIGNAL)
    return TRIGGER_SIGNAL


def generate_xml_prompt(tools: list[dict]) -> str:
    signal = get_trigger_signal()
    tool_lines = []
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        tool_lines.append(
            f"### {name}\n{desc}\nParameters:\n```json\n{json.dumps(params, ensure_ascii=False)}\n```"
        )

    return f"""# Available Tools

You have access to the following tools. When you need to call a tool, you MUST follow this exact format:

1. On a new line, output the trigger signal: {signal}
2. Immediately after, output a <function_calls> XML block
3. Each tool call goes inside a <function_call> tag
4. The tool name goes inside <tool> tags
5. Arguments go inside <args_json> tags as a JSON object (use CDATA to avoid XML escaping)
6. Multiple tool calls can be in the same <function_calls> block
7. Do NOT output any text after </function_calls>

Example:
{signal}
<function_calls>
    <function_call>
        <tool>tool_name</tool>
        <args_json><![CDATA[{{"param1": "value1", "param2": "value2"}}]]></args_json>
    </function_call>
</function_calls>

## Tool Definitions

{chr(10).join(tool_lines)}
"""


def generate_json_prompt(tools: list[dict]) -> str:
    tool_lines = []
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        tool_lines.append(
            f"- {name}: {desc}\n  Parameters: {json.dumps(params, ensure_ascii=False)}"
        )

    return f"""# Available Tools

You have access to the following tools. When you need to use a tool, respond with a JSON object in this exact format:
{{"tool_calls": [{{"id": "call_xxx", "type": "function", "function": {{"name": "tool_name", "arguments": "{{\\"param\\": \\"value\\"}}"}}}}]}}

IMPORTANT: The "arguments" field must be a JSON string, not a JSON object.

## Tool Definitions

{chr(10).join(tool_lines)}
"""


def build_tool_prompt(tools: list[dict], mode: str = "xml") -> str:
    if mode == "xml":
        return generate_xml_prompt(tools)
    else:
        return generate_json_prompt(tools)


def format_tool_choice_prompt(tool_choice, tools: list[dict]) -> str:
    if tool_choice == "none":
        return "\n\nYou are NOT allowed to use any tools. Respond as a regular chat assistant."
    elif tool_choice == "required":
        return "\n\nYou MUST call at least one tool in your response."
    elif isinstance(tool_choice, dict):
        func = tool_choice.get("function", {})
        name = func.get("name", "")
        if name:
            return f"\n\nYou MUST only use the tool named `{name}`."
    return ""


def preprocess_messages(messages: list[dict], tools: Optional[list[dict]], mode: str = "xml") -> list[dict]:
    if not tools:
        return messages

    tool_call_index = {}
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                func = tc.get("function", {})
                tool_call_index[tc_id] = {
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", "{}"),
                }

    processed = []
    for msg in messages:
        role = msg.get("role", "")

        if role == "assistant" and msg.get("tool_calls"):
            content = msg.get("content") or ""
            if mode == "xml":
                xml_str = _format_assistant_tool_calls_xml(msg["tool_calls"])
                final_content = f"{content}\n{xml_str}".strip()
            else:
                json_str = _format_assistant_tool_calls_json(msg["tool_calls"])
                final_content = f"{content}\n{json_str}".strip()
            processed.append({"role": "assistant", "content": final_content})

        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            tool_info = tool_call_index.get(tc_id, {})
            tool_name = tool_info.get("name", "unknown")
            tool_args = tool_info.get("arguments", "{}")
            result_content = msg.get("content") or ""
            if mode == "xml":
                formatted = f"Tool execution result:\n- Tool name: {tool_name}\n- Tool arguments: {tool_args}\n- Execution result:\n<tool_result>\n{result_content}\n</tool_result>"
            else:
                formatted = f"Tool execution result:\n- Tool name: {tool_name}\n- Tool arguments: {tool_args}\n- Execution result:\n{result_content}"
            processed.append({"role": "user", "content": formatted})

        else:
            processed.append(msg)

    return processed


def _format_assistant_tool_calls_xml(tool_calls: list[dict]) -> str:
    signal = get_trigger_signal()
    calls = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "")
        args = func.get("arguments", "{}")
        calls.append(
            f"<function_call>\n<tool>{name}</tool>\n<args_json><![CDATA[{args}]]></args_json>\n</function_call>"
        )
    return f"{signal}\n<function_calls>\n{chr(10).join(calls)}\n</function_calls>"


def _format_assistant_tool_calls_json(tool_calls: list[dict]) -> str:
    calls = []
    for tc in tool_calls:
        calls.append({
            "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
            "type": "function",
            "function": {
                "name": tc["function"]["name"],
                "arguments": tc["function"].get("arguments", "{}"),
            },
        })
    return json.dumps({"tool_calls": calls}, ensure_ascii=False)


def parse_tool_calls(content: str, mode: str = "xml") -> Optional[list[dict]]:
    if mode == "xml":
        result = _parse_xml_tool_calls(content)
        if result:
            return result
        return _parse_json_tool_calls(content)
    else:
        result = _parse_json_tool_calls(content)
        if result:
            return result
        return _parse_xml_tool_calls(content)


def _parse_xml_tool_calls(content: str) -> Optional[list[dict]]:
    signal = get_trigger_signal()
    clean_content = _remove_think_blocks(content)

    signal_pos = clean_content.find(signal)
    if signal_pos == -1:
        return None

    after_signal = clean_content[signal_pos + len(signal):]

    calls_match = re.search(r"<function_calls>([\s\S]*?)</function_calls>", after_signal)
    if not calls_match:
        return None

    calls_content = calls_match.group(1)
    results = _parse_function_calls_from_xml(calls_content)

    if results:
        tool_calls = []
        for r in results:
            tool_calls.append({
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": r["name"],
                    "arguments": json.dumps(r["args"], ensure_ascii=False),
                },
            })
        return tool_calls

    return None


def _parse_function_calls_from_xml(calls_content: str) -> Optional[list[dict]]:
    results = []

    try:
        root = ET.fromstring(f"<function_calls>{calls_content}</function_calls>")
        for fc in root.findall("function_call"):
            tool_el = fc.find("tool")
            name = (tool_el.text or "").strip() if tool_el is not None else ""

            args_json_el = fc.find("args_json")
            if args_json_el is not None:
                raw = args_json_el.text or ""
                payload = _extract_cdata(raw)
                parsed_args = _parse_args_json(payload)
                if parsed_args is None:
                    return None
                args = parsed_args
            else:
                args = {}

            if name:
                results.append({"name": name, "args": args})

        if results:
            return results
    except ET.ParseError:
        pass

    call_blocks = re.findall(r"<function_call>([\s\S]*?)</function_call>", calls_content)
    for block in call_blocks:
        tool_match = re.search(r"<tool>(.*?)</tool>", block)
        name = tool_match.group(1).strip() if tool_match else ""

        args_json_match = re.search(r"<args_json>([\s\S]*?)</args_json>", block)
        if args_json_match:
            raw = args_json_match.group(1)
            payload = _extract_cdata(raw)
            parsed_args = _parse_args_json(payload)
            if parsed_args is None:
                continue
            args = parsed_args
        else:
            args = {}

        if name:
            results.append({"name": name, "args": args})

    return results if results else None


def _parse_json_tool_calls(content: str) -> Optional[list[dict]]:
    patterns = [
        r'\{[\s\n]*"tool_calls"[\s\n]*:[\s\n]*\[(.*?)\][\s\n]*\}',
        r'\{\s*"tool_calls"\s*:\s*\[(.*?)\]\s*\}',
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            try:
                json_str = match.group(0)
                parsed = json.loads(json_str)
                if "tool_calls" in parsed and isinstance(parsed["tool_calls"], list):
                    tool_calls = []
                    for call in parsed["tool_calls"]:
                        func = call.get("function", {})
                        name = func.get("name", "")
                        args = func.get("arguments", "{}")
                        if isinstance(args, dict):
                            args = json.dumps(args, ensure_ascii=False)
                        if name:
                            tool_calls.append({
                                "id": call.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                                "type": call.get("type", "function"),
                                "function": {
                                    "name": name,
                                    "arguments": args,
                                },
                            })
                    if tool_calls:
                        return tool_calls
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    single_patterns = [
        r'```json\s*(\{[^`]*?"name"\s*:\s*"(\w+)"[^`]*?\})\s*```',
        r'(\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\s*\})',
        r'(\{\s*"function"\s*:\s*\{\s*"name"\s*:\s*"(\w+)"[^}]*\}\s*\})',
    ]

    for pattern in single_patterns:
        matches = re.finditer(pattern, content, re.DOTALL)
        tool_calls = []
        for match in matches:
            try:
                json_str = match.group(1)
                parsed = json.loads(json_str)
                name = ""
                args = {}

                if "name" in parsed:
                    name = parsed["name"]
                    if "arguments" in parsed:
                        args = parsed["arguments"]
                        if isinstance(args, str):
                            args = json.loads(args)
                    elif "parameters" in parsed:
                        args = parsed["parameters"]
                        if isinstance(args, str):
                            args = json.loads(args)
                elif "function" in parsed:
                    func = parsed["function"]
                    name = func.get("name", "")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)

                if name:
                    tool_calls.append({
                        "id": f"call_{uuid.uuid4().hex[:24]}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
                        },
                    })
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        if tool_calls:
            return tool_calls

    return None


def _remove_think_blocks(text: str) -> str:
    result = ""
    depth = 0
    i = 0
    while i < len(text):
        if text[i:].startswith("<think>"):
            depth += 1
            i += len("<think>")
        elif text[i:].startswith("</think>"):
            depth = max(0, depth - 1)
            i += len("</think>")
        else:
            if depth == 0:
                result += text[i]
            i += 1
    return result


def _extract_cdata(raw: str) -> str:
    if "<![CDATA[" not in raw:
        return raw.strip()
    parts = re.findall(r"<!\[CDATA\[(.*?)\]\]>", raw, flags=re.DOTALL)
    return "".join(parts).strip() if parts else raw.strip()


def _parse_args_json(payload: str) -> Optional[dict]:
    s = payload.strip()
    if not s:
        return {}
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def get_content_before_tool_call(content: str, mode: str = "xml") -> Optional[str]:
    if mode == "xml":
        signal = get_trigger_signal()
        clean = _remove_think_blocks(content)
        pos = clean.find(signal)
        if pos > 0:
            return content[:pos].rstrip()
        match = re.search(r'\{[\s\n]*"tool_calls"', content)
        if match and match.start() > 0:
            return content[:match.start()].rstrip()
        return None
    else:
        match = re.search(r'\{[\s\n]*"tool_calls"', content)
        if match and match.start() > 0:
            return content[:match.start()].rstrip()
        signal = get_trigger_signal()
        clean = _remove_think_blocks(content)
        pos = clean.find(signal)
        if pos > 0:
            return content[:pos].rstrip()
        return None
