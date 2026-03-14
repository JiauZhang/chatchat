from chatchat.client import BaseClient
from conippets import json

class ZhipuClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'zhipu',
            'https://open.bigmodel.cn/api/paas/v4',
            http_options=http_options, model=model, instruction=instruction,
        )

    def handle_tool_calls(self, message, tools):
        tool_calls = message['tool_calls']
        tool_result_messages = []
        for tool_call in tool_calls:
            func = tool_call['function']
            name = func['name']
            args = json.loads(func['arguments'])
            id = tool_call['id']
            tool = tools[name]
            tool_result = tool(**args)
            tool_result_messages.append({'role': 'tool', 'content': tool_result, 'tool_call_id': id})
        return tool_result_messages

    def build_client_messages(self, *, model, messages, generation_options, tools=None):
        jmsg = super().build_client_messages(
            model=model, messages=messages, generation_options=generation_options,
            tools=tools,
        )
        thinking = 'enabled' if generation_options.get('thinking') else 'disabled'
        jmsg['thinking'] = {'type': thinking}
        return jmsg
