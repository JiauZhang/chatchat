import json

from chatchat.client import Client
from chatchat.tool import Tools
from chatchat.types import Message, ToolCall, ProgressType
from chatchat.hook import _HookEmitter


class Agent(_HookEmitter):
    def __init__(
        self, *, provider, model, name=None, instruction=None,
        stream=True, thinking=False, tools=None, http_options=None,
    ):
        super().__init__()
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

    def chat(self, message: str):
        try:
            return self._chat_with_tools(self.client, message)
        except Exception as e:
            self._emit(
                ProgressType.AGENT_ERROR, name=self.name or '',
                content=str(e),
            )
            raise

    def clear(self):
        self.client.clear()

    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
        tool_results = []
        for tc in tool_calls:
            tool = self.tools[tc.name]
            args = json.loads(tc.arguments)
            result = tool(**args)
            tool_results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return tool_results

    def _chat_with_tools(self, client, text):
        self._emit(ProgressType.AGENT_START, name=self.name or '')
        if self.stream:
            return self._stream_chat(client, text)
        return self._nonstream_chat(client, text)

    def _nonstream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            response = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking,
                tools=self.tools,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                self._emit(ProgressType.AGENT_END, name=self.name or '')
                return msg.content
            tool_results = self._execute_tool_calls(msg.tool_calls)
            self._emit(ProgressType.AGENT_STEP, name=self.name or '', step=round)
            new_messages = tool_results

    def _stream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            stream = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking,
                tools=self.tools,
            )
            acc = Message()
            has_tool_calls = False
            for chunk in stream:
                acc.accumulate(chunk.choices[0].delta)
                if chunk.choices[0].delta.tool_calls:
                    has_tool_calls = True
                yield chunk.choices[0].delta.content or ''
            if not has_tool_calls:
                self._emit(ProgressType.AGENT_END, name=self.name or '')
                break
            tool_results = self._execute_tool_calls(acc.tool_calls)
            self._emit(ProgressType.AGENT_STEP, name=self.name or '', step=round)
            new_messages = tool_results


class SubAgent(_HookEmitter):
    def __init__(
        self, *, provider, model, name, description, instruction=None,
        stream=True, thinking=False, tools=None, http_options=None,
    ):
        super().__init__()
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

    def __call__(self, message: str):
        self._emit(ProgressType.TOOL_START, name=self.name)
        self._agent.clear()
        try:
            result = self._agent.chat(message)
        except Exception as e:
            self._emit(
                ProgressType.TOOL_ERROR, name=self.name,
                content=str(e),
            )
            return f'call tool {self.name} failed: {e}'
        self._emit(ProgressType.TOOL_END, name=self.name)
        return result