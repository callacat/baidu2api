# SPDX-License-Identifier: AGPL-3.0-or-later
# Toolify core functions integrated from https://github.com/funnycups/toolify
# Adapted for baidu2api integration

import json
import logging
import re
import secrets
import string
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger("baidu2api")

GLOBAL_TRIGGER_SIGNAL = None

ENABLE_FC_ERROR_RETRY = False
FC_ERROR_RETRY_MAX_ATTEMPTS = 3


def get_trigger_signal() -> str:
    global GLOBAL_TRIGGER_SIGNAL
    if GLOBAL_TRIGGER_SIGNAL is None:
        chars = string.ascii_letters + string.digits
        random_str = "".join(secrets.choice(chars) for _ in range(4))
        GLOBAL_TRIGGER_SIGNAL = f"<Function_{random_str}_Start/>"
        logger.info("Generated trigger signal: %s", GLOBAL_TRIGGER_SIGNAL)
    return GLOBAL_TRIGGER_SIGNAL


def build_tool_call_index_from_messages(messages: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    index = {}
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                        func = tc.get("function", {})
                        if tc_id and isinstance(func, dict):
                            name = func.get("name", "")
                            arguments = func.get("arguments", "{}")
                            if not isinstance(arguments, str):
                                try:
                                    arguments = json.dumps(arguments, ensure_ascii=False)
                                except Exception:
                                    arguments = str(arguments)
                            if name:
                                index[tc_id] = {"name": name, "arguments": arguments}
                                logger.debug(f"Indexed tool_call_id: {tc_id} -> {name}")
    logger.debug(f"Built tool_call index with {len(index)} entries")
    return index


def _schema_type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int) and not isinstance(v, bool):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _validate_value_against_schema(value: Any, schema: Dict[str, Any], path: str = "args", depth: int = 0) -> List[str]:
    if schema is None:
        schema = {}
    if depth > 8:
        return []
    errors: List[str] = []
    if isinstance(schema.get("allOf"), list):
        for idx, sub in enumerate(schema["allOf"]):
            errors.extend(_validate_value_against_schema(value, sub or {}, f"{path}.allOf[{idx}]", depth + 1))
        return errors
    if isinstance(schema.get("anyOf"), list):
        option_errors = [_validate_value_against_schema(value, sub or {}, path, depth + 1) for sub in schema["anyOf"]]
        if not any(len(e) == 0 for e in option_errors):
            errors.append(f"{path}: value does not satisfy anyOf options")
        return errors
    if isinstance(schema.get("oneOf"), list):
        option_errors = [_validate_value_against_schema(value, sub or {}, path, depth + 1) for sub in schema["oneOf"]]
        ok_count = sum(1 for e in option_errors if len(e) == 0)
        if ok_count != 1:
            errors.append(f"{path}: value must satisfy exactly one oneOf option (matched {ok_count})")
        return errors
    if "const" in schema:
        if value != schema.get("const"):
            errors.append(f"{path}: expected const={schema.get('const')!r}, got {value!r}")
            return errors
    enum_vals = schema.get("enum")
    if isinstance(enum_vals, list):
        if value not in enum_vals:
            errors.append(f"{path}: expected one of {enum_vals!r}, got {value!r}")
            return errors
    stype = schema.get("type")
    if stype is None:
        if any(k in schema for k in ("properties", "required", "additionalProperties")):
            stype = "object"

    def _type_ok(t: str) -> bool:
        if t == "object":
            return isinstance(value, dict)
        if t == "array":
            return isinstance(value, list)
        if t == "string":
            return isinstance(value, str)
        if t == "boolean":
            return isinstance(value, bool)
        if t == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if t == "number":
            return (isinstance(value, (int, float)) and not isinstance(value, bool))
        if t == "null":
            return value is None
        return True

    if isinstance(stype, str):
        if not _type_ok(stype):
            errors.append(f"{path}: expected type '{stype}', got '{_schema_type_name(value)}'")
            return errors
    elif isinstance(stype, list):
        if not any(_type_ok(t) for t in stype if isinstance(t, str)):
            errors.append(f"{path}: expected type in {stype!r}, got '{_schema_type_name(value)}'")
            return errors
    if isinstance(value, str):
        min_len = schema.get("minLength")
        max_len = schema.get("maxLength")
        if isinstance(min_len, int) and len(value) < min_len:
            errors.append(f"{path}: string shorter than minLength={min_len}")
        if isinstance(max_len, int) and len(value) > max_len:
            errors.append(f"{path}: string longer than maxLength={max_len}")
        pat = schema.get("pattern")
        if isinstance(pat, str):
            try:
                if re.search(pat, value) is None:
                    errors.append(f"{path}: string does not match pattern {pat!r}")
            except re.error:
                pass
    if isinstance(value, dict):
        props = schema.get("properties")
        if props is None:
            props = {}
        if not isinstance(props, dict):
            props = {}
        required = schema.get("required")
        if required is None:
            required = []
        if not isinstance(required, list):
            required = []
        required = [k for k in required if isinstance(k, str)]
        for k in required:
            if k not in value:
                errors.append(f"{path}: missing required property '{k}'")
        additional = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                errors.extend(_validate_value_against_schema(v, props.get(k) or {}, f"{path}.{k}", depth + 1))
            else:
                if additional is False:
                    errors.append(f"{path}: unexpected property '{k}'")
                elif isinstance(additional, dict):
                    errors.extend(_validate_value_against_schema(v, additional, f"{path}.{k}", depth + 1))
    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(value):
                errors.extend(_validate_value_against_schema(v, items, f"{path}[{i}]", depth + 1))
    return errors


def validate_parsed_tools(parsed_tools: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Optional[str]:
    tools = tools or []
    allowed = {}
    for t in tools:
        func = t.get("function", {})
        name = func.get("name", "")
        if name:
            allowed[name] = func.get("parameters", {}) or {}
    allowed_names = sorted(list(allowed.keys()))
    for idx, call in enumerate(parsed_tools or []):
        name = (call or {}).get("name")
        args = (call or {}).get("args")
        if not isinstance(name, str) or not name:
            return f"Tool call #{idx + 1}: missing tool name"
        if name not in allowed:
            return f"Tool call #{idx + 1}: unknown tool '{name}'. Allowed tools: {allowed_names}"
        if not isinstance(args, dict):
            return f"Tool call #{idx + 1} '{name}': arguments must be a JSON object, got {_schema_type_name(args)}"
        schema = allowed.get(name, {})
        errs = _validate_value_against_schema(args, schema, path=f"{name}")
        if errs:
            preview = "; ".join(errs[:6])
            more = f" (+{len(errs) - 6} more)" if len(errs) > 6 else ""
            return f"Tool call #{idx + 1} '{name}': schema validation failed: {preview}{more}"
    return None


def _prompt_schema_type_name(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "any"
    stype = schema.get("type")
    if isinstance(stype, str):
        return stype
    if isinstance(stype, list):
        parts = [t for t in stype if isinstance(t, str)]
        return " | ".join(parts) if parts else "any"
    if any(k in schema for k in ("properties", "required", "additionalProperties")):
        return "object"
    if "items" in schema:
        return "array"
    if isinstance(schema.get("anyOf"), list):
        return "anyOf"
    if isinstance(schema.get("oneOf"), list):
        return "oneOf"
    if isinstance(schema.get("allOf"), list):
        return "allOf"
    return "any"


def _prompt_schema_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _collect_prompt_schema_constraints(schema: Dict[str, Any]) -> Dict[str, Any]:
    constraints: Dict[str, Any] = {}
    for key in [
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "minLength", "maxLength", "pattern", "format",
        "minItems", "maxItems", "uniqueItems",
        "minProperties", "maxProperties", "multipleOf"
    ]:
        if key in schema:
            constraints[key] = schema.get(key)
    if _prompt_schema_type_name(schema) == "array":
        items = schema.get("items") or {}
        if isinstance(items, dict):
            item_type = _prompt_schema_type_name(items)
            if item_type != "any":
                constraints["items.type"] = item_type
    return constraints


def _append_prompt_schema_body(
    lines: List[str],
    schema: Any,
    is_required: Optional[bool],
    indent_level: int,
    depth: int = 0
) -> None:
    schema_dict = schema if isinstance(schema, dict) else {}
    indent = "  " * indent_level
    if depth > 8:
        lines.append(f"{indent}- note: nested schema omitted after depth 8")
        return
    lines.append(f"{indent}- type: {_prompt_schema_type_name(schema_dict)}")
    if is_required is not None:
        lines.append(f"{indent}- required: {'Yes' if is_required else 'No'}")
    description = schema_dict.get("description")
    if description:
        lines.append(f"{indent}- description: {description}")
    enum_vals = schema_dict.get("enum")
    if enum_vals is not None:
        lines.append(f"{indent}- enum: {_prompt_schema_dump(enum_vals)}")
    if "const" in schema_dict:
        lines.append(f"{indent}- const: {_prompt_schema_dump(schema_dict.get('const'))}")
    default_val = schema_dict.get("default")
    if default_val is not None:
        lines.append(f"{indent}- default: {_prompt_schema_dump(default_val)}")
    examples_val = schema_dict.get("examples") or schema_dict.get("example")
    if examples_val is not None:
        lines.append(f"{indent}- examples: {_prompt_schema_dump(examples_val)}")
    constraints = _collect_prompt_schema_constraints(schema_dict)
    if constraints:
        lines.append(f"{indent}- constraints: {_prompt_schema_dump(constraints)}")
    props_raw = schema_dict.get("properties")
    props = props_raw if isinstance(props_raw, dict) else {}
    required_raw = schema_dict.get("required")
    required_list = required_raw if isinstance(required_raw, list) else []
    required_list = [k for k in required_list if isinstance(k, str)]
    if required_list:
        lines.append(f"{indent}- required properties: {', '.join(required_list)}")
    if props:
        lines.append(f"{indent}- properties:")
        for child_name, child_schema in props.items():
            child_indent = "  " * (indent_level + 1)
            child_name_text = str(child_name)
            lines.append(f"{child_indent}- {child_name_text}:")
            _append_prompt_schema_body(lines, child_schema, child_name_text in required_list, indent_level + 2, depth + 1)
    items = schema_dict.get("items")
    if isinstance(items, dict):
        lines.append(f"{indent}- items:")
        _append_prompt_schema_body(lines, items, None, indent_level + 1, depth + 1)
    elif isinstance(items, list) and items:
        lines.append(f"{indent}- items:")
        for idx, item_schema in enumerate(items):
            item_indent = "  " * (indent_level + 1)
            lines.append(f"{item_indent}- item[{idx}]:")
            _append_prompt_schema_body(lines, item_schema, None, indent_level + 2, depth + 1)
    additional = schema_dict.get("additionalProperties", True)
    if additional is False:
        lines.append(f"{indent}- additionalProperties: false")
    elif isinstance(additional, dict):
        lines.append(f"{indent}- additionalProperties:")
        _append_prompt_schema_body(lines, additional, None, indent_level + 1, depth + 1)
    for keyword in ("anyOf", "oneOf", "allOf"):
        options = schema_dict.get(keyword)
        if isinstance(options, list) and options:
            lines.append(f"{indent}- {keyword}:")
            for idx, option_schema in enumerate(options, start=1):
                option_indent = "  " * (indent_level + 1)
                lines.append(f"{option_indent}- option {idx}:")
                _append_prompt_schema_body(lines, option_schema, None, indent_level + 2, depth + 1)


def format_tool_result_for_ai(tool_name: str, tool_arguments: str, result_content: str) -> str:
    formatted_text = f"""Tool execution result:
- Tool name: {tool_name}
- Tool arguments: {tool_arguments}
- Execution result:
<tool_result>
{result_content}
</tool_result>"""
    logger.debug(f"Formatted tool result for {tool_name}")
    return formatted_text


def format_assistant_tool_calls_for_ai(tool_calls: List[Dict[str, Any]], trigger_signal: str) -> str:
    logger.debug(f"Formatting assistant tool calls. Count: {len(tool_calls)}")

    def _wrap_cdata(text: str) -> str:
        safe = (text or "").replace("]]>", "]]]]><![CDATA[>")
        return f"<![CDATA[{safe}]]>"

    xml_calls_parts = []
    for tool_call in tool_calls:
        function_info = tool_call.get("function", {})
        name = function_info.get("name", "")
        arguments_val = function_info.get("arguments", "{}")
        try:
            if isinstance(arguments_val, dict):
                args_dict = arguments_val
            elif isinstance(arguments_val, str):
                s = arguments_val or "{}"
                decoder = json.JSONDecoder()
                try:
                    args_dict, end_idx = decoder.raw_decode(s)
                except json.JSONDecodeError as je:
                    raise ValueError(f"arguments is not valid JSON: {je}")
                rest = s[end_idx:].strip()
                if rest:
                    logger.warning(
                        "Extra content after JSON in tool '%s' arguments (ignored, %d extra chars): %s",
                        name, len(rest), rest[:100]
                    )
                if not isinstance(args_dict, dict):
                    raise ValueError(f"arguments must be a JSON object, got {type(args_dict).__name__}")
            else:
                raise ValueError(f"arguments must be a JSON object or JSON string, got {type(arguments_val).__name__}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid assistant.tool_calls arguments for tool '{name}': {e}")
        args_payload = json.dumps(args_dict, ensure_ascii=False)
        xml_call = (
            f"<function_call>\n"
            f"<tool>{name}</tool>\n"
            f"<args_json>{_wrap_cdata(args_payload)}</args_json>\n"
            f"</function_call>"
        )
        xml_calls_parts.append(xml_call)
    all_calls = "\n".join(xml_calls_parts)
    final_str = f"{trigger_signal}\n<function_calls>\n{all_calls}\n</function_calls>"
    logger.debug("Assistant tool calls formatted successfully.")
    return final_str


def get_function_call_prompt_template(trigger_signal: str) -> str:
    return f"""
You have access to the following available tools to help solve problems:

{{tools_list}}

**IMPORTANT CONTEXT NOTES:**
1. You can call MULTIPLE tools in a single response if needed.
2. Even though you can call multiple tools, you MUST respect the user's later constraints and preferences (e.g., the user may request no tools, only one tool, or a specific tool/workflow).
3. The conversation context may already contain tool execution results from previous function calls. Review the conversation history carefully to avoid unnecessary duplicate tool calls.
4. When tool execution results are present in the context, they will be formatted with XML tags like <tool_result>...</tool_result> for easy identification.
5. This is the ONLY format you can use for tool calls, and any deviation will result in failure.

When you need to use tools, you **MUST** strictly follow this format. Do NOT include any extra text, explanations, or dialogue on the first and second lines of the tool call syntax:

1. When starting tool calls, begin on a new line with exactly:
{trigger_signal}
No leading or trailing spaces, output exactly as shown above. The trigger signal MUST be on its own line and appear only once. Do not output a trigger signal for each tool call.

2. Starting from the second line, **immediately** follow with the complete <function_calls> XML block.

3. For multiple tool calls, include multiple <function_call> blocks within the same <function_calls> wrapper, not separate blocks. Output the trigger signal only once, then one <function_calls> with all <function_call> children.

4. Do not add any text or explanation after the closing </function_calls> tag.

STRICT ARGUMENT KEY RULES:
- You MUST use parameter keys EXACTLY as defined (case- and punctuation-sensitive). Do NOT rename, add, or remove characters.
- If a key starts with a hyphen (e.g., "-i", "-C"), you MUST keep the leading hyphen in the JSON key. Never convert "-i" to "i" or "-C" to "C".
- The <tool> tag must contain the exact name of a tool from the list. Any other tool name is invalid.
- The <args_json> tag must contain a single JSON object with all required arguments for that tool.
- You MAY wrap the JSON content inside <![CDATA[...]]> to avoid XML escaping issues.

CORRECT Example (multiple tool calls):
...response content (optional)...
{trigger_signal}
<function_calls>
    <function_call>
        <tool>Grep</tool>
        <args_json><![CDATA[{{"-i": true, "-C": 2, "path": "."}}]]></args_json>
    </function_call>
    <function_call>
        <tool>search</tool>
        <args_json><![CDATA[{{"keywords": ["Python Document", "how to use python"]}}]]></args_json>
    </function_call>
</function_calls>

INCORRECT Example (extra text + wrong key names — DO NOT DO THIS):
...response content (optional)...
{trigger_signal}
I will call the tools for you.
<function_calls>
    <function_call>
        <tool>Grep</tool>
        <args>
            <i>true</i>
            <C>2</C>
            <path>.</path>
        </args>
    </function_call>
</function_calls>

INCORRECT Example (output non-XML format — DO NOT DO THIS):
...response content (optional)...
```json
{{"files":[{{"path":"system.py"}}]}}
```

Now please be ready to strictly follow the above specifications.
"""


def generate_function_prompt(tools: List[Dict[str, Any]], trigger_signal: str) -> tuple[str, str]:
    tools_list_str = []
    for i, tool in enumerate(tools):
        func = tool.get('function', {})
        name = func.get('name', '')
        description = func.get('description', '') or ""
        schema: Dict[str, Any] = func.get('parameters', {}) or {}
        props_raw = schema.get("properties", {})
        if props_raw is None:
            props_raw = {}
        if not isinstance(props_raw, dict):
            raise HTTPException(status_code=400, detail=f"Tool '{name}': 'properties' must be an object, got {type(props_raw).__name__}")
        props: Dict[str, Any] = props_raw
        required_raw = schema.get("required", [])
        if required_raw is None:
            required_raw = []
        if not isinstance(required_raw, list):
            raise HTTPException(status_code=400, detail=f"Tool '{name}': 'required' must be a list, got {type(required_raw).__name__}")
        non_string_required = [k for k in required_raw if not isinstance(k, str)]
        if non_string_required:
            raise HTTPException(status_code=400, detail=f"Tool '{name}': 'required' entries must be strings, got {non_string_required}")
        required_list: List[str] = required_raw
        missing_keys = [key for key in required_list if key not in props]
        if missing_keys:
            raise HTTPException(status_code=400, detail=f"Tool '{name}': required parameters {missing_keys} are not defined in properties")
        params_summary = ", ".join([
            f"{p_name} ({_prompt_schema_type_name(p_info)})" for p_name, p_info in props.items()
        ]) or "None"
        detail_lines: List[str] = []
        for p_name, p_info in props.items():
            detail_lines.append(f"- {p_name}:")
            _append_prompt_schema_body(detail_lines, p_info, p_name in required_list, indent_level=1)
        detail_block = "\n".join(detail_lines) if detail_lines else "(no parameter details)"
        desc_block = f"```\n{description}\n```" if description else "None"
        tools_list_str.append(
            f"{i + 1}. <tool name=\"{name}\">\n"
            f"   Description:\n{desc_block}\n"
            f"   Parameters summary: {params_summary}\n"
            f"   Required parameters: {', '.join(required_list) if required_list else 'None'}\n"
            f"   Parameter details:\n{detail_block}"
        )
    prompt_template = get_function_call_prompt_template(trigger_signal)
    prompt_content = prompt_template.replace("{tools_list}", "\n\n".join(tools_list_str))
    return prompt_content, trigger_signal


def remove_think_blocks(text: str) -> str:
    while '<think>' in text and '</think>' in text:
        start_pos = text.find('<think>')
        if start_pos == -1:
            break
        pos = start_pos + 7
        depth = 1
        while pos < len(text) and depth > 0:
            if text[pos:pos+7] == '<think>':
                depth += 1
                pos += 7
            elif text[pos:pos+8] == '</think>':
                depth -= 1
                pos += 8
            else:
                pos += 1
        if depth == 0:
            text = text[:start_pos] + text[pos:]
        else:
            break
    return text


def find_last_trigger_signal_outside_think(text: str, trigger_signal: str) -> int:
    if not text or not trigger_signal:
        return -1
    i = 0
    think_depth = 0
    last_pos = -1
    while i < len(text):
        if text.startswith("<think>", i):
            think_depth += 1
            i += 7
            continue
        if text.startswith("</think>", i):
            think_depth = max(0, think_depth - 1)
            i += 8
            continue
        if think_depth == 0 and text.startswith(trigger_signal, i):
            last_pos = i
            i += 1
            continue
        i += 1
    return last_pos


class StreamingFunctionCallDetector:
    def __init__(self, trigger_signal: str):
        self.trigger_signal = trigger_signal
        self.reset()

    def reset(self):
        self.content_buffer = ""
        self.state = "detecting"
        self.in_think_block = False
        self.think_depth = 0
        self.signal = self.trigger_signal
        self.signal_len = len(self.signal)

    def process_chunk(self, delta_content: str) -> tuple[bool, str]:
        if not delta_content:
            return False, ""
        self.content_buffer += delta_content
        content_to_yield = ""
        if self.state == "tool_parsing":
            return False, ""
        if delta_content:
            logger.debug(f"Processing chunk: {repr(delta_content[:50])}{'...' if len(delta_content) > 50 else ''}, buffer length: {len(self.content_buffer)}, think state: {self.in_think_block}")
        i = 0
        while i < len(self.content_buffer):
            skip_chars = self._update_think_state(i)
            if skip_chars > 0:
                for j in range(skip_chars):
                    if i + j < len(self.content_buffer):
                        content_to_yield += self.content_buffer[i + j]
                i += skip_chars
                continue
            if not self.in_think_block and self._can_detect_signal_at(i):
                if self.content_buffer[i:i+self.signal_len] == self.signal:
                    logger.debug(f"Detected trigger signal in non-think block! Signal: {self.signal[:20]}...")
                    self.state = "tool_parsing"
                    self.content_buffer = self.content_buffer[i:]
                    return True, content_to_yield
            remaining_len = len(self.content_buffer) - i
            if remaining_len < self.signal_len or remaining_len < 8:
                break
            content_to_yield += self.content_buffer[i]
            i += 1
        self.content_buffer = self.content_buffer[i:]
        return False, content_to_yield

    def _update_think_state(self, pos: int):
        remaining = self.content_buffer[pos:]
        if remaining.startswith('<think>'):
            self.think_depth += 1
            self.in_think_block = True
            logger.debug(f"Entering think block, depth: {self.think_depth}")
            return 7
        elif remaining.startswith('</think>'):
            self.think_depth = max(0, self.think_depth - 1)
            self.in_think_block = self.think_depth > 0
            logger.debug(f"Exiting think block, depth: {self.think_depth}")
            return 8
        return 0

    def _can_detect_signal_at(self, pos: int) -> bool:
        return (pos + self.signal_len <= len(self.content_buffer) and not self.in_think_block)

    def finalize(self) -> Optional[List[Dict[str, Any]]]:
        if self.state == "tool_parsing":
            return parse_function_calls_xml(self.content_buffer, self.trigger_signal)
        return None


def parse_function_calls_xml(xml_string: str, trigger_signal: str) -> Optional[List[Dict[str, Any]]]:
    logger.debug(f"Parser starting, input length: {len(xml_string) if xml_string else 0}")
    logger.debug(f"Using trigger signal: {trigger_signal[:20]}...")
    if not xml_string or trigger_signal not in xml_string:
        logger.debug(f"Input is empty or doesn't contain trigger signal")
        return None
    cleaned_content = remove_think_blocks(xml_string)
    logger.debug(f"Content length after removing think blocks: {len(cleaned_content)}")
    signal_positions = []
    start_pos = 0
    while True:
        pos = cleaned_content.find(trigger_signal, start_pos)
        if pos == -1:
            break
        signal_positions.append(pos)
        start_pos = pos + 1
    if not signal_positions:
        logger.debug(f"No trigger signal found in cleaned content")
        return None
    logger.debug(f"Found {len(signal_positions)} trigger signal positions: {signal_positions}")
    chosen_signal_index = None
    chosen_signal_pos = None
    calls_content_match = None
    for idx in range(len(signal_positions) - 1, -1, -1):
        pos = signal_positions[idx]
        sub = cleaned_content[pos:]
        m = re.search(r"<function_calls>([\s\S]*?)</function_calls>", sub)
        if m:
            chosen_signal_index = idx
            chosen_signal_pos = pos
            calls_content_match = m
            logger.debug(f"Using trigger signal index {idx} at pos {pos}; content preview: {repr(sub[:100])}")
            break
    if calls_content_match is None:
        logger.debug(f"No function_calls tag found after any trigger signal (triggers={len(signal_positions)})")
        return None
    calls_xml = calls_content_match.group(0)
    calls_content = calls_content_match.group(1)
    logger.debug(f"function_calls content: {repr(calls_content)}")

    def _coerce_value(v: str):
        try:
            return json.loads(v)
        except Exception:
            return v

    def _parse_args_json_payload(payload: str) -> Optional[Dict[str, Any]]:
        if payload is None:
            return {}
        s = payload.strip()
        if not s:
            return {}
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?\s*", "", s)
            s = re.sub(r"\s*```$", "", s)
        try:
            decoder = json.JSONDecoder()
            parsed, end_idx = decoder.raw_decode(s)
        except json.JSONDecodeError as e:
            logger.debug(f"Invalid JSON in args_json: {type(e).__name__}: {e}")
            return None
        rest = s[end_idx:].strip()
        if rest:
            logger.debug(f"Extra content after JSON in args_json (ignored, {len(rest)} extra chars): {rest[:80]}")
        if not isinstance(parsed, dict):
            logger.debug(f"args_json must decode to an object, got {type(parsed).__name__}")
            return None
        return parsed

    def _extract_cdata_text(raw: str) -> str:
        if raw is None:
            return ""
        if "<![CDATA[" not in raw:
            return raw
        parts = re.findall(r"<!\[CDATA\[(.*?)\]\]>", raw, flags=re.DOTALL)
        return "".join(parts) if parts else raw

    results: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(calls_xml)
        for i, fc in enumerate(root.findall("function_call")):
            tool_el = fc.find("tool")
            name = (tool_el.text or "").strip() if tool_el is not None else ""
            if not name:
                logger.debug(f"No tool tag found in function_call #{i+1}")
                continue
            args: Dict[str, Any] = {}
            args_json_el = fc.find("args_json")
            if args_json_el is not None:
                parsed_args = _parse_args_json_payload(args_json_el.text or "")
                if parsed_args is None:
                    logger.debug(f"Invalid args_json in function_call #{i+1}; treating as parse failure")
                    return None
                args = parsed_args
            else:
                args_el = fc.find("args")
                if args_el is not None:
                    for child in list(args_el):
                        args[child.tag] = _coerce_value(child.text or "")
            result = {"name": name, "args": args}
            results.append(result)
            logger.debug(f"Added tool call: {result}")
        logger.debug(f"Final parsing result (XML): {results}")
        return results if results else None
    except Exception as e:
        logger.debug(f"XML library parse failed, falling back to regex parser: {type(e).__name__}: {e}")

    call_blocks = re.findall(r"<function_call>([\s\S]*?)</function_call>", calls_content)
    logger.debug(f"Found {len(call_blocks)} function_call blocks")
    for i, block in enumerate(call_blocks):
        logger.debug(f"Processing function_call #{i+1}: {repr(block)}")
        tool_match = re.search(r"<tool>(.*?)</tool>", block)
        if not tool_match:
            logger.debug(f"No tool tag found in block #{i+1}")
            continue
        name = tool_match.group(1).strip()
        args: Dict[str, Any] = {}
        args_json_match = re.search(r"<args_json>([\s\S]*?)</args_json>", block)
        if args_json_match:
            raw_payload = args_json_match.group(1)
            payload = _extract_cdata_text(raw_payload)
            parsed_args = _parse_args_json_payload(payload)
            if parsed_args is None:
                logger.debug(f"Invalid args_json in function_call #{i+1} (regex path); treating as parse failure")
                return None
            args = parsed_args
        else:
            args_block_match = re.search(r"<args>([\s\S]*?)</args>", block)
            if args_block_match:
                args_content_inner = args_block_match.group(1)
                arg_matches = re.findall(r"<([^\s>/]+)>([\s\S]*?)</\1>", args_content_inner)
                for k, v in arg_matches:
                    args[k] = _coerce_value(v)
        result = {"name": name, "args": args}
        results.append(result)
        logger.debug(f"Added tool call: {result}")
    logger.debug(f"Final parsing result (regex): {results}")
    return results if results else None


def safe_process_tool_choice(tool_choice, tools: Optional[List[Dict[str, Any]]] = None) -> str:
    try:
        if tool_choice is None:
            return ""
        if isinstance(tool_choice, str):
            if tool_choice == "none":
                return "\n\n**IMPORTANT:** You are prohibited from using any tools in this round. Please respond like a normal chat assistant and answer the user's question directly."
            elif tool_choice == "auto":
                return ""
            elif tool_choice == "required":
                return "\n\n**IMPORTANT:** You MUST call at least one tool in this response. Do not respond without using tools."
            else:
                logger.warning(f"Unknown tool_choice string value: {tool_choice}")
                return ""
        elif isinstance(tool_choice, dict) and "function" in tool_choice:
            function_dict = tool_choice.get("function", {})
            if not isinstance(function_dict, dict):
                logger.warning("tool_choice.function must be an object")
                return ""
            required_tool_name = function_dict.get("name")
            if not required_tool_name or not isinstance(required_tool_name, str):
                logger.warning("tool_choice.function.name must be a non-empty string")
                return ""
            if tools:
                tool_names = [t.get("function", {}).get("name", "") for t in tools]
                if required_tool_name not in tool_names:
                    logger.warning(f"tool_choice specifies tool '{required_tool_name}' not in tools list")
                    return ""
            return f"\n\n**IMPORTANT:** In this round, you must use ONLY the tool named `{required_tool_name}`. Generate the necessary parameters and output in the specified XML format."
        else:
            logger.warning(f"Unsupported tool_choice type: {type(tool_choice)}")
            return ""
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing tool_choice: {e}")
        return ""


def _diagnose_fc_parse_error(content: str, trigger_signal: str) -> str:
    errors = []
    if trigger_signal not in content:
        errors.append(f"Trigger signal '{trigger_signal[:30]}...' not found in response")
        return "; ".join(errors)
    cleaned = remove_think_blocks(content)
    if "<function_calls>" not in cleaned:
        errors.append("Missing <function_calls> tag after trigger signal")
    elif "</function_calls>" not in cleaned:
        errors.append("Missing closing </function_calls> tag")
    if "<function_call>" not in cleaned:
        errors.append("No <function_call> blocks found inside <function_calls>")
    elif "</function_call>" not in cleaned:
        errors.append("Missing closing </function_call> tag")
    fc_match = re.search(r"<function_calls>([\s\S]*?)</function_calls>", cleaned)
    if fc_match:
        fc_content = fc_match.group(1)
        if "<tool>" not in fc_content:
            errors.append("Missing <tool> tag inside function_call")
        if "<args_json>" not in fc_content and "<args>" not in fc_content:
            errors.append("Missing <args_json> or <args> tag inside function_call")
        args_json_match = re.search(r"<args_json>([\s\S]*?)</args_json>", fc_content)
        if args_json_match:
            args_content = args_json_match.group(1).strip()
            cdata_match = re.search(r"<!\[CDATA\[([\s\S]*?)\]\]>", args_content)
            json_to_parse = cdata_match.group(1) if cdata_match else args_content
            try:
                parsed = json.loads(json_to_parse)
                if not isinstance(parsed, dict):
                    errors.append(f"args_json must be a JSON object, got {type(parsed).__name__}")
            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON in args_json: {str(e)}")
    if not errors:
        errors.append("XML structure appears correct but parsing failed for unknown reason")
    return "; ".join(errors)


def _classify_fc_failure(content: str, trigger_signal: str) -> str:
    if find_last_trigger_signal_outside_think(content, trigger_signal) == -1:
        return "no_fc"
    cleaned = remove_think_blocks(content)
    pos = find_last_trigger_signal_outside_think(cleaned, trigger_signal)
    if pos == -1:
        return "no_fc"
    after_trigger = cleaned[pos:]
    has_open = "<" + "function_calls>" in after_trigger
    has_close = "</" + "function_calls>" in after_trigger
    if not has_open:
        return "syntax_error"
    if has_open and not has_close:
        return "truncated"
    return "syntax_error"


def get_fc_error_retry_prompt(original_response: str, error_details: str) -> str:
    return f"""Your previous response attempted to make a function call but the format was invalid or could not be parsed.

**Your original response:**
```
{original_response}
```

**Error details:**
{error_details}

**Instructions:**
Please retry and output the function call in the correct XML format. Remember:
1. Start with the trigger signal on its own line
2. Immediately follow with the <function_calls> XML block
3. Use <args_json> with valid JSON for parameters
4. Do not add any text after </function_calls>

Please provide the corrected function call now. DO NOT OUTPUT ANYTHING ELSE."""


def get_fc_continuation_prompt(truncated_content: str, error_details: str) -> str:
    tail = truncated_content[-1500:]
    fci_close = "</" + "function_call>"
    fc_close = "</" + "function_calls>"
    return (
        "Your previous response was cut off before the function call XML was complete.\n"
        "\n"
        "**Your truncated response (ending abruptly):**\n"
        "```\n"
        f"{tail}\n"
        "```\n"
        "\n"
        f"**What happened:** {error_details}\n"
        "\n"
        "**You have two options:**\n"
        "\n"
        "**Option A (PREFERRED — Continue writing):**\n"
        "Output ONLY the exact continuation from where you were cut off. Rules:\n"
        "- Start EXACTLY from the next character after the cutoff point — do not repeat ANY text, not even a single character\n"
        "- If the cutoff happened mid-word, start from the next character of that word, never repeat the partial character/word\n"
        "- Do NOT output any trigger signal or opening tags that were already present\n"
        f"- End with the proper closing tags ({fci_close}, {fc_close} as needed)\n"
        "- Do NOT add any explanation before or after\n"
        "\n"
        "**Option B (Only if you made an error earlier):**\n"
        "Start fresh with the complete function call from the trigger signal. "
        "Output the trigger signal on its own line, followed by the complete "
        "function_calls block.\n"
        "\n"
        "Choose Option A unless you believe your previous output contained errors that need correction."
    )


def _is_continuation_response(retry_content: str, trigger_signal: str) -> bool:
    cleaned = retry_content.strip()
    if trigger_signal in cleaned:
        return False
    fc_open = "<" + "function_calls>"
    if cleaned.lstrip().startswith(fc_open):
        return False
    return True


def _merge_truncated_and_continuation(truncated: str, continuation: str) -> str:
    return truncated.rstrip("\n") + continuation.lstrip("\n")


def preprocess_messages(messages: List[Dict[str, Any]], tools=None, mode: str = "xml") -> List[Dict[str, Any]]:
    tool_call_index = build_tool_call_index_from_messages(messages)
    processed = []
    for msg in messages:
        if not isinstance(msg, dict):
            processed.append(msg)
            continue
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id", "")
            tool_info = tool_call_index.get(tc_id, {})
            if tool_info:
                formatted = format_tool_result_for_ai(
                    tool_name=tool_info["name"],
                    tool_arguments=tool_info["arguments"],
                    result_content=msg.get("content") or "",
                )
            else:
                formatted = msg.get("content") or ""
            processed.append({"role": "user", "content": formatted})
        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            signal = get_trigger_signal()
            formatted_tc = format_assistant_tool_calls_for_ai(msg["tool_calls"], signal)
            original = msg.get("content") or ""
            final = f"{original}\n{formatted_tc}".strip()
            processed.append({"role": "assistant", "content": final})
        else:
            processed.append(msg)
    return processed


def build_tool_prompt(tools: List[Dict[str, Any]], mode: str = "xml") -> str:
    if mode == "xml":
        signal = get_trigger_signal()
        prompt, _ = generate_function_prompt(tools, signal)
        return prompt
    elif mode == "json":
        return _generate_json_prompt(tools)
    return ""


def _generate_json_prompt(tools: List[Dict[str, Any]]) -> str:
    tool_lines = []
    for i, tool in enumerate(tools):
        func = tool.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        detail_lines = []
        props = params.get("properties", {})
        required_list = params.get("required", [])
        for p_name, p_info in props.items():
            detail_lines.append(f"- {p_name}:")
            detail_lines.append(f"  - type: {p_info.get('type', 'any')}")
            if p_name in required_list:
                detail_lines.append("  - required: Yes")
            if p_info.get("description"):
                detail_lines.append(f"  - description: {p_info['description']}")
        detail_block = "\n".join(detail_lines) if detail_lines else "  No parameters"
        tool_lines.append(f"{i + 1}. **{name}**: {desc}\n{detail_block}")
    tools_list = "\n\n".join(tool_lines)
    return f"""You have access to the following available tools to help solve problems:

{tools_list}

When you need to use tools, you **MUST** respond with a JSON object in this EXACT format:

{{"tool_calls": [{{"id": "call_xxx", "type": "function", "function": {{"name": "tool_name", "arguments": "{{\"param\": \"value\"}}"}}}}]}}

CRITICAL RULES:
- The "arguments" field must be a JSON **string** (not a JSON object).
- Use parameter keys EXACTLY as defined.
- Each tool call must have a unique "id" starting with "call_".
- You MAY include normal text before the JSON object.
- Do NOT wrap the JSON in markdown code blocks."""


def format_tool_choice_prompt(tool_choice, tools: Optional[List[Dict[str, Any]]] = None) -> str:
    return safe_process_tool_choice(tool_choice, tools)


def parse_tool_calls(content: str, mode: str = "xml") -> Optional[List[Dict[str, Any]]]:
    if mode == "xml":
        signal = get_trigger_signal()
        parsed = parse_function_calls_xml(content, signal)
        if parsed:
            validation_error = validate_parsed_tools(parsed, _current_request_tools or [])
            if validation_error:
                logger.warning(f"Tool call validation failed: {validation_error}")
                return None
            return _convert_parsed_to_openai(parsed)
        return _parse_json_tool_calls(content)
    else:
        result = _parse_json_tool_calls(content)
        if result:
            return result
        signal = get_trigger_signal()
        parsed = parse_function_calls_xml(content, signal)
        if parsed:
            validation_error = validate_parsed_tools(parsed, _current_request_tools or [])
            if validation_error:
                logger.warning(f"Tool call validation failed: {validation_error}")
                return None
            return _convert_parsed_to_openai(parsed)
        return None


_current_request_tools: Optional[List[Dict[str, Any]]] = None


def set_current_tools(tools: Optional[List[Dict[str, Any]]]):
    global _current_request_tools
    _current_request_tools = tools


def _convert_parsed_to_openai(parsed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tool_calls = []
    for p in parsed:
        name = p.get("name", "")
        args = p.get("args", {})
        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
            },
        })
    return tool_calls


def _parse_json_tool_calls(content: str) -> Optional[List[Dict[str, Any]]]:
    clean = remove_think_blocks(content)
    # Strip markdown code blocks that models frequently wrap JSON in
    clean = re.sub(r'```(?:json)?\s*', '', clean)
    clean = re.sub(r'\s*```', '', clean)
    patterns = [
        r'\{[\s\n]*"tool_calls"[\s\n]*:[\s\n]*\[[\s\S]*?\][\s\n]*\}',
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.DOTALL)
        if match:
            try:
                json_str = match.group(0)
                decoder = json.JSONDecoder()
                parsed, _ = decoder.raw_decode(json_str)
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
                                "function": {"name": name, "arguments": args},
                            })
                    if tool_calls:
                        return tool_calls
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return None


def get_content_before_tool_call(content: str, mode: str = "xml") -> Optional[str]:
    if mode == "xml":
        signal = get_trigger_signal()
        pos = find_last_trigger_signal_outside_think(content, signal)
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
        pos = find_last_trigger_signal_outside_think(content, signal)
        if pos > 0:
            return content[:pos].rstrip()
        return None
