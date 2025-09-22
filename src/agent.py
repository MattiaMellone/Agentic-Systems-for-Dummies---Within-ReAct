"""Agent module.
Defines: ToolSpec, ReActAgent.
Provides functions: _strip_code_fences, _stringify, _clean_final, _try_load_json_array, _try_load_json_action.

This code is organized for readability, maintainability, and testability.
"""

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

# ----------------------------
# Data structures & utilities
# ----------------------------

@dataclass
class ToolSpec:
    """Executable tool specification."""
    name: str
    description: str
    args_schema: Dict[str, Any]
    func: Callable[..., Any]

CODE_FENCE_RE = re.compile(r'^```[\w-]*\s*|\s*```$', re.MULTILINE)
FINAL_RE = re.compile(r'Final Answer:\s*(.+)$', re.IGNORECASE | re.DOTALL)

def _strip_code_fences(text: str) -> str:
    return CODE_FENCE_RE.sub('', text or '').strip()

def _stringify(obj: Any) -> str:
    if obj is None:
        return '<none>'
    if isinstance(obj, (dict, list)):
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return str(obj)
    return str(obj)

def _clean_final(text: str) -> Optional[str]:
    m = FINAL_RE.search(text or '')
    if not m:
        return None
    body = _strip_code_fences(m.group(1).strip())
    for splitter in ['\nPlan:', '\nPLAN:', '\nPiano:', '\n```', '\n{', '\n[']:
        if splitter in body:
            body = body.split(splitter, 1)[0].strip()
    return body or None

def _try_load_json_array(text: str) -> List[Dict[str, Any]]:
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

# ----------------------------
# ReAct Agent (step-by-step)
# ----------------------------

class ReActAgent:
    """ReAct agent with step-wise Reason→Act→Observe loop."""

    def __init__(
        self,
        tools: List[ToolSpec],
        model: str = 'gpt-4o-mini',
        temperature: float = 0.2,
        request_timeout: Optional[float] = 60.0,
        max_steps: int = 10,
    ) -> None:
        if OpenAI is None:
            raise RuntimeError('OpenAI SDK not installed. Please `pip install openai`.')
        self.client = OpenAI()
        self.model = model
        self.temperature = temperature
        self.request_timeout = request_timeout
        self.max_steps = max_steps
        self.tools: Dict[str, ToolSpec] = {t.name: t for t in tools}
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            tool_list=self._pretty_tool_list(tools)
        )

    # --------- public API ---------

    def run(self, user_query: str, on_step: Optional[Callable[[str], None]] = None) -> str:
        """Run a ReAct loop for up to max_steps."""
        observations: List[str] = []
        recent_actions: List[str] = []

        for _ in range(self.max_steps):
            decision = self._ask_next(user_query, observations, on_step)

            # Final answer?
            if "final" in decision:
                final = decision["final"]
                if on_step:
                    on_step(f"Final Answer: {final}")
                return final

            # Action?
            if "action" in decision:
                action = decision["action"]
                tool = action.get("tool")
                args = action.get("args") or {}
                if not isinstance(args, dict):
                    args = {}

                # Safety defaults (won't override provided args)
                args.setdefault("units", "metric")
                if tool in ("openmeteo_forecast", "date_parse") and "target_date" not in args:
                    args["target_date"] = "oggi"

                # Anti-loop: avoid repeating the exact same action+args too many times
                sig = json.dumps({"tool": tool, "args": args}, ensure_ascii=False, sort_keys=True)
                recent_actions.append(sig)
                if len(recent_actions) > 3:
                    recent_actions.pop(0)
                if len(recent_actions) == 3 and len(set(recent_actions)) == 1:
                    msg = "I’m stuck repeating the same action. Please rephrase or provide more details."
                    if on_step:
                        on_step(f"Final Answer: {msg}")
                    return msg

                if on_step:
                    on_step(f"Action: {tool}")
                    on_step(f"Action Input: {json.dumps(args, ensure_ascii=False)}")

                obs = self._exec_tool(tool, args)
                obs_json = _stringify(obs)

                turn_block = (
                    f"Action: {tool}\n"
                    f"Action Input: {json.dumps(args, ensure_ascii=False)}\n"
                    f"Observation: {obs_json}"
                )
                observations.append(turn_block)

                if on_step:
                    on_step(f"Observation: {obs_json}")
                continue

            # If model output is neither a valid action nor a final answer, note it and retry
            observations.append("Observation: model output not understood; please output a single JSON action or Final Answer.")
            if on_step:
                on_step("Warning: unparseable output; retrying.")

        # Fallback on step limit
        fallback = "I could not reach a final answer within the step limit."
        if on_step:
            on_step(f"Final Answer: {fallback}")
        return fallback

    # --------- internals ---------

    def _exec_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name not in self.tools:
            return {"error": f"Tool '{tool_name}' not available."}
        try:
            return self.tools[tool_name].func(**args)
        except Exception as e:
            return {"error": str(e)}

    def _ask_next(
        self,
        query: str,
        observations: List[str],
        on_step: Optional[Callable[[str], None]],
    ) -> Dict[str, Any]:
        msgs = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": query},
        ]
        if observations:
            msgs.append({"role": "assistant", "content": "\n".join(observations)})

        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=msgs,
            timeout=self.request_timeout,
        )
        text = (resp.choices[0].message.content or "").strip()
        if on_step:
            on_step(f"Next: {text}")
        return self._parse_action_or_final(text)

    def _parse_action_or_final(self, text: str) -> Dict[str, Any]:
        # Try Final Answer
        final = _clean_final(text)
        if final is not None:
            return {"final": final}

        # Try to parse a single JSON object action
        obj_candidates = _try_load_json_array(text)
        if len(obj_candidates) == 1 and isinstance(obj_candidates[0], dict):
            obj = obj_candidates[0]
            if "tool" in obj and "args" in obj and isinstance(obj["args"], dict):
                return {"action": obj}

        obj = _try_load_json_action(text, {})
        if obj and "tool" in obj and "args" in obj and isinstance(obj["args"], dict):
            return {"action": obj}

        return {"error": "unparseable"}

    @staticmethod
    def _pretty_tool_list(tools: List[ToolSpec]) -> str:
        return "\n".join(
            f"- {t.name}: {t.description} (schema: {json.dumps(t.args_schema)})"
            for t in tools
        )