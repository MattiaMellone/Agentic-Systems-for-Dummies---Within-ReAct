"""Agent module.
Defines: ToolSpec, ReActAgent.
Provides functions: _strip_code_fences, _stringify, _clean_final, _try_load_json_array, _try_load_json_action.

This code is organized for readability, maintainability, and testability."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from src.prompts import SYSTEM_PROMPT_TEMPLATE
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

@dataclass
class ToolSpec:
    """Tool spec class.

Encapsulates related behavior and state."""
    name: str
    description: str
    args_schema: Dict[str, Any]
    func: Callable[..., Any]
CODE_FENCE_RE = re.compile('^```[\\w-]*\\s*|\\s*```$', re.MULTILINE)
FINAL_RE = re.compile('Final Answer:\\s*(.+)$', re.IGNORECASE | re.DOTALL)

def _strip_code_fences(text: str) -> str:
    """Strip code fences.

Args:
    text: Input parameter.
Returns:
    Return value."""
    return CODE_FENCE_RE.sub('', text or '').strip()

def _stringify(obj: Any) -> str:
    """Stringify.

Args:
    obj: Input parameter.
Returns:
    Return value."""
    if obj is None:
        return '<none>'
    if isinstance(obj, (dict, list)):
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return str(obj)
    return str(obj)

def _clean_final(text: str) -> Optional[str]:
    """Clean final.

Args:
    text: Input parameter.
Returns:
    Return value."""
    m = FINAL_RE.search(text or '')
    if not m:
        return None
    body = _strip_code_fences(m.group(1).strip())
    for splitter in ['\nPlan:', '\nPLAN:', '\nPiano:', '\n```', '\n{', '\n[']:
        if splitter in body:
            body = body.split(splitter, 1)[0].strip()
    return body or None

def _try_load_json_array(text: str) -> List[Dict[str, Any]]:
    """Try load json array.

Args:
    text: Input parameter.
Returns:
    Return value."""
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        pass
    return []

def _try_load_json_action(text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """Try load json action.

Args:
    text: Input parameter.
    fallback: Input parameter.
Returns:
    Return value."""
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]
    except Exception:
        pass
    return fallback

class ReActAgent:
    """Re act agent class.

Encapsulates related behavior and state."""

    def __init__(self, tools: List[ToolSpec], model: str='gpt-4o-mini', temperature: float=0.2, max_replans: int=2, request_timeout: Optional[float]=60.0) -> None:
        """Init.

Args:
    tools: Input parameter.
    model: Input parameter.
    temperature: Input parameter.
    max_replans: Input parameter.
    request_timeout: Input parameter.
Returns:
    Return value."""
        if OpenAI is None:
            raise RuntimeError('OpenAI SDK not installed. Please `pip install openai`.')
        self.client = OpenAI()
        self.model = model
        self.temperature = temperature
        self.max_replans = max_replans
        self.request_timeout = request_timeout
        self.tools: Dict[str, ToolSpec] = {t.name: t for t in tools}
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(tool_list=self._pretty_tool_list(tools))

    def run(self, user_query: str, on_step: Optional[Callable[[str], None]]=None) -> str:
        """Run.

Args:
    user_query: Input parameter.
    on_step: Input parameter.
Returns:
    Return value."""
        replans = 0
        observations: List[str] = []
        plan = self._ask_for_plan(user_query, observations, on_step)
        while True:
            for idx, action in enumerate(plan):
                action = self._confirm_action(user_query, observations, action, on_step)
                tool_name = action.get('tool')
                args = action.get('args', {})
                if on_step:
                    on_step(f'Action: {tool_name}')
                    on_step(f'Action Input: {json.dumps(args, ensure_ascii=False)}')
                obs = self._exec_tool(tool_name, args)
                obs_str = f'Observation: {_stringify(obs)}'
                observations.append(obs_str)
                if on_step:
                    on_step(obs_str)
            final = self._ask_if_final(user_query, observations, on_step)
            if final is not None:
                if on_step:
                    on_step(f'Final Answer: {final}')
                return final
            replans += 1
            if replans > self.max_replans:
                fallback = 'I could not reach a final answer within the replanning limit.'
                if on_step:
                    on_step(f'Final Answer: {fallback}')
                return fallback
            plan = self._ask_for_plan(user_query, observations, on_step)

    def _exec_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Exec tool.

Args:
    tool_name: Input parameter.
    args: Input parameter.
Returns:
    Return value."""
        if tool_name not in self.tools:
            return {'error': f"Tool '{tool_name}' not available."}
        try:
            return self.tools[tool_name].func(**args)
        except Exception as e:
            return {'error': str(e)}

    def _ask_for_plan(self, query: str, observations: List[str], on_step: Optional[Callable[[str], None]]) -> List[Dict[str, Any]]:
        """Ask for plan.

Args:
    query: Input parameter.
    observations: Input parameter.
    on_step: Input parameter.
Returns:
    Return value."""
        msgs = [{'role': 'system', 'content': self.system_prompt}, {'role': 'user', 'content': query}]
        if observations:
            msgs.append({'role': 'assistant', 'content': '\n'.join(observations)})
        if on_step:
            on_step('Plan: requesting new action plan...')
        resp = self.client.chat.completions.create(model=self.model, temperature=self.temperature, messages=msgs, timeout=self.request_timeout)
        text = (resp.choices[0].message.content or '').strip()
        if on_step:
            on_step(f'Plan: {text}')
        return _try_load_json_array(text)

    def _confirm_action(self, query: str, observations: List[str], action: Dict[str, Any], on_step: Optional[Callable[[str], None]]) -> Dict[str, Any]:
        """Confirm action.

Args:
    query: Input parameter.
    observations: Input parameter.
    action: Input parameter.
    on_step: Input parameter.
Returns:
    Return value."""
        msgs = [{'role': 'system', 'content': self.system_prompt}, {'role': 'user', 'content': query}, {'role': 'assistant', 'content': '\n'.join(observations)}, {'role': 'assistant', 'content': f'Proposed next action: {json.dumps(action, ensure_ascii=False)}'}]
        resp = self.client.chat.completions.create(model=self.model, temperature=self.temperature, messages=msgs, timeout=self.request_timeout)
        text = (resp.choices[0].message.content or '').strip()
        if on_step:
            on_step(f'Confirm: {text}')
        return _try_load_json_action(text, action)

    def _ask_if_final(self, query: str, observations: List[str], on_step: Optional[Callable[[str], None]]) -> Optional[str]:
        """Ask if final.

Args:
    query: Input parameter.
    observations: Input parameter.
    on_step: Input parameter.
Returns:
    Return value."""
        msgs = [{'role': 'system', 'content': self.system_prompt}, {'role': 'user', 'content': query}, {'role': 'assistant', 'content': '\n'.join(observations)}, {'role': 'assistant', 'content': "Do you have enough info to provide Final Answer? Reply only with 'Final Answer: ...' or explain what's missing."}]
        resp = self.client.chat.completions.create(model=self.model, temperature=self.temperature, messages=msgs, timeout=self.request_timeout)
        text = (resp.choices[0].message.content or '').strip()
        if on_step:
            on_step(f'Check-Final: {text}')
        return _clean_final(text)

    @staticmethod
    def _pretty_tool_list(tools: List[ToolSpec]) -> str:
        """Pretty tool list.

Args:
    tools: Input parameter.
Returns:
    Return value."""
        return '\n'.join((f'- {t.name}: {t.description} (schema: {json.dumps(t.args_schema)})' for t in tools))
