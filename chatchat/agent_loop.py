from __future__ import annotations
import json
from typing import Any, Generator

from chatchat.runtime import get_runtime
from chatchat.types import Message as AccMessage


class AgentLoop:
    def __init__(self, client, tools, max_turns: int, thinking: bool, name: str = ''):
        self.client = client
        self.tools = tools
        self.max_turns = max_turns
        self.thinking = thinking
        self._name = name
        self._turn = 0

    def run(self, text: str) -> str:
        new_messages = [{'role': 'user', 'content': text}]
        max_iter = self.max_turns if self.max_turns > 0 else float('inf')
        turn = 0
        while turn < max_iter:
            turn += 1
            gen = self.client.chat(
                new_messages,
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
        self._turn += 1
        self._emit('agent:step', {
            'step': self._turn,
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
        get_runtime().emit(topic, data, name=self._name)