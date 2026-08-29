from __future__ import annotations
import asyncio
import json
from types import SimpleNamespace

from chatchat.core.event import Event
from chatchat.core.exceptions import MaxStepsError
from chatchat.core.tool_handler import TOOLS_ENTITY_ID
from chatchat.tools.base import ToolContext

_TOOL_CALL_TIMEOUT = 60


class AgentLoop:
    def __init__(self, client, tools, max_steps: int, thinking: bool, name: str = '',
                 agent=None, allowed_tools: set[str] | None = None, runtime=None):
        self.client = client
        self.tools = tools
        self.max_steps = max_steps
        self.thinking = thinking
        self._name = name
        self._agent = agent if agent is not None else SimpleNamespace(id=name)
        self._allowed = set(allowed_tools or [])
        self._runtime = runtime
        self._turn = 0
        self.usage = None

    async def run(self, text: str, context=None) -> str:
        """`client` owns the full conversation: each chat() call appends the
        user/tool messages it receives plus its own assistant reply. So every
        turn we hand over only the delta since the previous turn."""
        self.usage = None
        delta = list(context or []) + [{'role': 'user', 'content': text}]
        max_steps = self.max_steps if self.max_steps > 0 else float('inf')
        turn = 0
        while turn < max_steps:
            turn += 1
            async for _ in self.client.chat(
                delta,
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
            # client already appended the assistant tool_calls message; the
            # only thing left to send next turn are the tool results.
            delta = await self._execute_tool_calls(latest.tool_calls)
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

        runtime = self._runtime

        async def run_one(tc):
            try:
                arguments = json.loads(tc.arguments)
            except json.JSONDecodeError:
                return {
                    'role': 'tool',
                    'content': f'Error: invalid JSON arguments: {tc.arguments}',
                    'tool_call_id': tc.id,
                }
            payload = {
                'name': tc.name,
                'arguments': arguments,
                'ctx': ToolContext(agent=self._agent),
                'tools': self._allowed,
                'tool_call_id': tc.id,
            }
            try:
                result = await runtime.request(
                    source=self._name,
                    target_id=TOOLS_ENTITY_ID,
                    topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
                    data=payload,
                    timeout=_TOOL_CALL_TIMEOUT,
                )
            except Exception as e:
                # Isolate a single tool failure: timeout/dead tool must not
                # take down the rest of the round via asyncio.gather. Return a
                # well-formed tool message so the LLM can react and continue.
                result = {
                    'role': 'tool',
                    'content': f'Error calling tool "{tc.name}": {type(e).__name__}: {e}',
                    'tool_call_id': tc.id,
                }
            result.setdefault('tool_call_id', tc.id)
            return result

        return await asyncio.gather(*(run_one(tc) for tc in tool_calls))

    async def _emit(self, topic: str, data: dict = None):
        await self._runtime.publish(Event(
            topic=f'lifecycle:{topic}', source=self._name, data=data or {},
        ))
