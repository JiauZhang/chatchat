# Large Language Models Python API

Unified python API for multiple LLM providers including `alibaba`, `baidu`, `deepseek`, `google`, `tencent`, `xunfei`, `zhipu`, and `openrouter`.

## Install

```shell
pip install chatchat
```

## Quick Start

### Terminal Chat

```shell
$ chatchat run baidu ernie-lite-8k
user> Hello
assistant> Hello! How can I help you today?
user> /exit

$ chatchat run google gemini-2.5-flash --proxy YOUR_PROXY
user> Introduce yourself briefly.
assistant> Hello! I am a large language model...
user> /exit
```

### Python Client

```python
from chatchat.client import Client

llm = Client('tencent', model='hunyuan-lite')

# completion
response = llm.complete('Hi')

# chat
response = llm.chat('Hello')

# stream
for chunk in llm.complete('Hello', generation_options={'stream': True}):
    print(chunk, end='')
```

### Tool Calling & Agent

```python
from chatchat.tool import tool
from chatchat.agent import Agent

@tool(
    name='get_weather', description='get weather for a city',
    parameters={
        'type': 'object',
        'properties': {'city': {'type': 'string'}},
        'required': ['city'],
    }
)
def get_weather(city):
    return f'{city} is Sunny.'

agent = Agent('zhipu', model='glm-4.7-flash', tools=[get_weather])
response = agent('How is the weather in Shanghai?')
```

### SubAgent

```python
from chatchat.agent import SubAgent, Agent
from chatchat.tool import tool

@tool(
    name='query_ticket', description='query train tickets',
    parameters={
        'type': 'object',
        'properties': {
            'from_city': {'type': 'string'},
            'to_city': {'type': 'string'},
        },
        'required': ['from_city', 'to_city'],
    }
)
def query_ticket(from_city, to_city):
    ...

travel_agent = SubAgent(
    name='travel_agent',
    description='query tickets between cities',
    provider='zhipu', model='glm-4.7-flash',
    tools=[query_ticket],
)

agent = Agent('zhipu', model='glm-4.7-flash', tools=[travel_agent])
```

## Configuration

```shell
# set API key
chatchat config <provider>.api_key=YOUR_API_KEY

# list supported providers
chatchat config --list
```

> Refer to [examples](./examples) for more usage.

## Sponsor

<table align="center">
    <thead>
        <tr>
            <th colspan="2">公众号</th>
        </tr>
    </thead>
    <tbody align="center" valign="center">
        <tr>
            <td colspan="2"><img src="https://jiauzhang.github.io/ghstatic/images/ofa_m.png" style="height: 196px" alt="AliPay.png"></td>
        </tr>
    </tbody>
    <thead>
        <tr>
            <th>AliPay</th>
            <th>WeChatPay</th>
        </tr>
    </thead>
    <tbody align="center" valign="center">
        <tr>
            <td><img src="https://jiauzhang.github.io/AliPay.png" style="width: 196px; height: 196px" alt="AliPay.png"></td>
            <td><img src="https://jiauzhang.github.io/WeChatPay.png" style="width: 196px; height: 196px" alt="WeChatPay.png"></td>
        </tr>
    </tbody>
</table>
