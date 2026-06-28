import json
import types

from chatchat.client import Client
from chatchat.tool import Tools
from chatchat.types import Message, ToolCall, Progress, ProgressType


class Agent:
    def __init__(
        self, *, provider, model, name=None, instruction=None,
        stream=True, thinking=False, tools=None, http_options=None,
    ):
        self.provider = provider
        self.model = model
        self.instruction = instruction
        self.http_options = http_options or {}
        self.name = name
        self.stream = stream
        self.thinking = thinking
        self.tools = Tools(*tools) if tools else None
        self.client = Client(
            provider=self.provider, model=self.model, instruction=self.instruction,
            http_options=self.http_options,
        )

    def chat(self, message: str, on_progress=None):
        try:
            return self._chat_with_tools(self.client, message, on_progress=on_progress)
        except Exception as e:
            if on_progress:
                on_progress(Progress(
                    type=ProgressType.AGENT_ERROR, agent=self.name or '',
                    content=str(e),
                ))
            raise

    def clear(self):
        self.client.clear()

    def _execute_tool_calls(self, tool_calls: list[ToolCall], on_progress=None) -> list[dict]:
        tool_results = []
        for tc in tool_calls:
            tool = self.tools[tc.name]
            args = json.loads(tc.arguments)
            if on_progress:
                on_progress(Progress(
                    type=ProgressType.TOOL_START, tool_name=tc.name,
                    agent=self.name or '',
                ))
            try:
                result = tool(**args, on_progress=on_progress)
            except Exception as e:
                if on_progress:
                    on_progress(Progress(
                        type=ProgressType.TOOL_ERROR, tool_name=tc.name,
                        agent=self.name or '', content=str(e),
                    ))
                result = f'call tool {tc.name} failed: {e}'
            if isinstance(result, types.GeneratorType):
                result = ''.join(result)
            if on_progress:
                on_progress(Progress(
                    type=ProgressType.TOOL_END, tool_name=tc.name,
                    agent=self.name or '',
                ))
            tool_results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return tool_results

    def _chat_with_tools(self, client, text, on_progress=None):
        if on_progress:
            on_progress(Progress(
                type=ProgressType.AGENT_START, agent=self.name or '',
            ))
        if self.stream:
            return self._stream_chat(client, text, on_progress=on_progress)
        return self._nonstream_chat(client, text, on_progress=on_progress)

    def _nonstream_chat(self, client, text, on_progress=None):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            response = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking,
                tools=self.tools, on_progress=on_progress, step=round,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                if on_progress:
                    on_progress(Progress(
                        type=ProgressType.AGENT_END, agent=self.name or '',
                    ))
                return msg.content
            tool_results = self._execute_tool_calls(msg.tool_calls, on_progress=on_progress)
            if on_progress:
                on_progress(Progress(
                    type=ProgressType.AGENT_STEP, agent=self.name or '',
                    step=round,
                ))
            new_messages = tool_results

    def _stream_chat(self, client, text, on_progress=None):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            stream = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking,
                tools=self.tools, on_progress=on_progress, step=round,
            )
            acc = Message()
            has_tool_calls = False
            for chunk in stream:
                acc.accumulate(chunk.choices[0].delta)
                if chunk.choices[0].delta.tool_calls:
                    has_tool_calls = True
                yield chunk.choices[0].delta.content or ''
            if not has_tool_calls:
                if on_progress:
                    on_progress(Progress(
                        type=ProgressType.AGENT_END, agent=self.name or '',
                    ))
                break
            tool_results = self._execute_tool_calls(acc.tool_calls, on_progress=on_progress)
            if on_progress:
                on_progress(Progress(
                    type=ProgressType.AGENT_STEP, agent=self.name or '',
                    step=round,
                ))
            new_messages = tool_results


class SubAgent:
    def __init__(
        self, *, provider, model, name, description, instruction=None,
        stream=True, thinking=False, tools=None, http_options=None,
    ):
        self.name = name
        self.description = description
        self._agent = Agent(
            provider=provider, model=model, name=name,
            instruction=instruction, stream=stream, thinking=thinking,
            tools=tools, http_options=http_options,
        )

    @staticmethod
    def from_skill(skill_path, *, provider, model, stream=True, thinking=False,
                   http_options=None, available_tools=None):
        from chatchat.skill import Skill
        skill = Skill(skill_path)
        skill_tools = []
        if skill.allowed_tools:
            if not available_tools:
                raise ValueError(
                    f"Skill '{skill.name}' requires tools {skill.allowed_tools}, "
                    f"but available_tools is not provided"
                )
            for name in skill.allowed_tools:
                match = next((t for t in available_tools if t.name == name), None)
                if not match:
                    raise ValueError(
                        f"Skill '{skill.name}' requires tool '{name}', "
                        f"not found in available_tools"
                    )
                skill_tools.append(match)

        return SubAgent(
            name=skill.name, description=skill.description,
            instruction=skill.instruction,
            tools=skill_tools,
            provider=provider, model=model,
            stream=stream, thinking=thinking,
            http_options=http_options,
        )

    def to_dict(self):
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'message': {
                            'type': 'string',
                            'description': 'Accurately and concisely state what you want it to do.',
                        }
                    },
                    'required': ['message'],
                }
            }
        }

    def __call__(self, message: str, on_progress=None):
        self._agent.clear()
        return self._agent.chat(message, on_progress=on_progress)