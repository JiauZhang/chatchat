from __future__ import annotations
import json
from typing import Any, Generator

from chatchat.types import Message as AccMessage


class AgentLoop:
    def __init__(self, client, tools, max_turns: int, thinking: bool, emit_fn):
        self.client = client
        self.tools = tools
        self.max_turns = max_turns
        self.thinking = thinking
        self._emit_fn = emit_fn
        self._step = 0

    def run(self, text: str) -> str:
        new_messages = [{'role': 'user', 'content': text}]
        for _ in range(self.max_turns):
            gen = self.client.chat(
                new_messages,
                stream=True,
                thinking=self.thinking,
                tools=self.tools,
            )
            acc = AccMessage()
            for chunk in gen:
                acc.accumulate(chunk.choices[0].delta)
            if not acc.tool_calls:
                return acc.content
            new_messages = self._execute_tool_calls(acc.tool_calls)
        return '已达到最大迭代次数'

    def _execute_tool_calls(self, tool_calls: list) -> list[dict]:
        self._step += 1
        self._emit('agent:step', {
            'step': self._step,
            'tool_calls': [
                {'name': tc.name, 'arguments': tc.arguments}
                for tc in tool_calls
            ],
        })
        results = []
        for tc in tool_calls:
            tool = self.tools[tc.name]
            kwargs = json.loads(tc.arguments)
            result = tool(**kwargs)
            if isinstance(result, Generator):
                result = ''.join(result)
            results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return results

    def _emit(self, topic: str, data: dict = None):
        if self._emit_fn:
            self._emit_fn(topic, data or {})