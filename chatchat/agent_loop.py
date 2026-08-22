from __future__ import annotations
import json
from types import SimpleNamespace

from chatchat.runtime import Event, get_runtime
from chatchat.tool import ToolContext
from chatchat.exceptions import MaxStepsError


class AgentLoop:
    def __init__(self, client, tools, max_steps: int, thinking: bool, name: str = '', agent=None):
        self.client = client
        self.tools = tools
        self.max_steps = max_steps
        self.thinking = thinking
        self._name = name
        self._agent = agent if agent is not None else SimpleNamespace(name=name)
        self._turn = 0
        self.usage = None

    async def run(self, text: str, context=None) -> str:
        self.usage = None
        new_messages = list(context or []) + [{'role': 'user', 'content': text}]
        max_steps = self.max_steps if self.max_steps > 0 else float('inf')
        turn = 0
        while turn < max_steps:
            turn += 1
            async for _ in self.client.chat(
                new_messages,
                thinking=self.thinking,
                tools=self.tools,
            ):
                pass
            usage = getattr(self.client, 'latest_usage', None)
            if usage:
                self.usage = usage if self.usage is None else self.usage + usage
            latest = self.client.latest
            if latest is None or not latest.tool_calls:
                return latest.content if latest else ''
            new_messages = await self._execute_tool_calls(latest.tool_calls)
        raise MaxStepsError(
            f'{self._name} exceeded max_steps={max_steps}'
        )

    async def _execute_tool_calls(self, tool_calls: list) -> list[dict]:
        self._turn += 1
        data = {
            'step': self._turn,
            'tool_calls': [
                {'name': tc.name, 'arguments': tc.arguments}
                for tc in tool_calls
            ],
        }
        await self._emit('agent:step', data)
        results = []
        for tc in tool_calls:
            if self.tools is None or tc.name not in self.tools:
                results.append({
                    'role': 'tool',
                    'content': f'Error: unknown tool "{tc.name}"',
                    'tool_call_id': tc.id,
                })
                continue
            try:
                kwargs = json.loads(tc.arguments)
            except json.JSONDecodeError:
                results.append({
                    'role': 'tool',
                    'content': f'Error: invalid JSON arguments: {tc.arguments}',
                    'tool_call_id': tc.id,
                })
                continue
            result = await self.tools[tc.name](
                ctx=ToolContext(agent=self._agent), **kwargs)
            results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return results

    async def _emit(self, topic: str, data: dict = None):
        await get_runtime().publish(Event(
            topic=f'lifecycle:{topic}', source=self._name, data=data or {},
        ))