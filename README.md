# chatchat — Agent Framework

Python agent framework with LLM tool calling, multi-agent orchestration, and event-driven architecture.

## Install

```shell
pip install chatchat
```

## Quick Start

### Single Agent

```python
from chatchat.agent import Agent
from chatchat.event import EventBus
from chatchat.tool import tool

bus = EventBus()
bus.start()
bus.subscribe('agent:*', lambda e: print(f'[{e.topic}] {e.source}: {e.data}'))

@tool(
    name='get_weather', description='get weather for a city',
    parameters={
        'type': 'object',
        'properties': {
            'city': {
                'type': 'string',
                'description': 'the city name, e.g., Shanghai',
            }
        },
        'required': ['city'],
    }
)
def get_weather(city):
    return f'{city} is Sunny.'

agent = Agent(
    name='assistant',
    provider='deepseek', model='deepseek-v4-flash',
    event_bus=bus, tools=[get_weather],
)
agent.chat('How is the weather in Shanghai?')
bus.stop()
```

### Multi-Agent Team

```python
from chatchat.agent import Agent
from chatchat.event import EventBus
from chatchat.team import Team

bus = EventBus()
bus.start()

worker = Agent(name='worker', provider='deepseek', model='deepseek-v4-flash' event_bus=bus)
leader = Agent(name='leader', provider='deepseek', model='deepseek-v4-flash', event_bus=bus)

team = Team(name='my_team', leader=leader, event_bus=bus)
team.add_member(worker)
result = team.chat('Complete the task')
```

### Pipeline

```python
team = Team(name='pipeline', leader=agent_a, event_bus=bus)
team.add_member(agent_b)
team.add_member(agent_c)
result = team.pipeline('Process this')
```

### Parallel

```python
tasks = {'worker_a': 'Task for A', 'worker_b': 'Task for B'}
results = team.parallel(tasks)
```

## EventBus

Event-driven architecture. All agent, tool, and team events are emitted through a shared EventBus:

| Topic | Source | Description |
|-------|--------|-------------|
| `agent:start` | agent name | Agent receives a message |
| `agent:step` | agent name | Agent executes tool calls |
| `agent:end` | agent name | Agent completes response |
| `agent:error` | agent name | Agent encountered error |
| `tool:start` | agent name | Tool begins execution |
| `tool:end` | agent name | Tool completes execution |
| `tool:error` | agent name | Tool encountered error |
| `client:step` | agent name | LLM streaming chunk |
| `team:start` | team name | Team receives a task |
| `team:step` | team name | Team delegates to member |
| `team:end` | team name | Team completes task |

## Configuration

```shell
chatchat config <provider>.api_key=YOUR_API_KEY
chatchat config --list
```

## Examples

See [examples](./examples) for complete usage:

- `agent.py` — Interactive terminal chat with tool calling
- `team.py` — Supervisor, pipeline, and parallel orchestration modes
- `tool.py` — Custom tool with progress reporting
- `client.py` — Raw LLM client usage
- `state.py` — Agent state serialization and restoration
- `interact.py` — Interactive tool confirmation
- `progress.py` — Streaming progress with custom tools

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