# chatchat — Agent Framework

Python agent framework with LLM tool calling, multi-agent orchestration, and a scheduler-based event-driven architecture.

## Install

```shell
pip install chatchat
```

## Quick Start

### Single Agent

```python
import asyncio
from chatchat.agent import AgentConfig, create_agent
from chatchat.tool import tool

@tool(
    name='get_weather', description='get weather for a city',
    parameters={
        'type': 'object',
        'properties': {
            'city': {'type': 'string', 'description': 'the city name, e.g., Shanghai'},
        },
        'required': ['city'],
    },
)
def get_weather(city):
    return f'{city} is Sunny.'

agent = create_agent(AgentConfig(
    name='assistant',
    provider='agnes', model='agnes-2.5-flash',
    instruction='You are a helpful assistant.',
    tools=[get_weather],
))

async def main():
    result = await agent.chat('How is the weather in Shanghai?')
    print(result)
    await agent.stop()

asyncio.run(main())
```

### Multi-Agent Team

Teams inherit from Agent and carry management tools (`create_agent`, `create_team`, `send_message`, `task_stop`). Sub-agents are created on demand by the leader and communicate through the scheduler via `runtime.request` / `reply`.

```python
import asyncio
from chatchat.team import TeamConfig, create_team
from chatchat.runtime import get_runtime, make_id

team = create_team(TeamConfig(
    name='lead',
    provider='agnes', model='agnes-2.5-flash',
    instruction='You are a tech lead. Use create_agent to delegate tasks to sub-agents.',
    agent_tools=[],
))

async def main():
    reply = await get_runtime().request(
        source=make_id(), target_id=team.id,
        topic=f'entity:team:{team.id}:text',
        data='write a tutorial to output.md', timeout=300,
    )
    print(reply)
    await team.stop()
    get_runtime().shutdown()

asyncio.run(main())
```

### Tools

Tools are registered with the `@tool` decorator. They run inside the AgentLoop; the LLM's tool calls are accumulated by index, executed, and fed back for further turns.

```python
from chatchat.tool import tool

@tool(
    name='add', description='add two numbers',
    parameters={
        'type': 'object',
        'properties': {
            'a': {'type': 'integer'},
            'b': {'type': 'integer'},
        },
        'required': ['a', 'b'],
    },
)
def add(a, b):
    return a + b
```

### Skills

Skills are directories containing a `SKILL.md`. Their instruction block is injected into the agent's system prompt.

```python
agent = create_agent(AgentConfig(
    name='skilled',
    provider='agnes', model='agnes-2.5-flash',
    instruction='You are a helpful assistant.',
    skills=['/path/to/skill_dir'],
))
```

## Architecture

- **Scheduler / Runtime** — core message router. Agent-to-Agent and delegation communication go through the scheduler using topic-based addressing (`entity:<kind>:<id>:<type>`), with blocking request/reply and fire-and-forget publish. Calling `agent.chat()` runs the agent loop directly in the caller.
- **Agent** — wraps an LLM client, a tool set, and the AgentLoop (streaming, tool-call accumulation, lifecycle hooks `start`/`step`/`end`/`error`).
- **Team** — an Agent with management tools; `leader_tools` configure the leader's tools, `agent_tools` configure tools given to created sub-agents.
- **Client / providers** — async streaming LLM clients (aiohttp) for `agnes`, `deepseek`, `openrouter`, `google`, `alibaba`, `baidu`, `zhipu`, `tencent`, `xunfei`, etc.

Observe runtime activity with `get_runtime().enable_logging('agent', 'team', 'client', 'tool')`. Lifecycle topics: `lifecycle:agent:start/step/end/error`, `lifecycle:client:start/step/end/error`, `lifecycle:tool:start/step/end/error`.

## Configuration

```shell
chatchat config --list
chatchat config <provider>.api_key=YOUR_API_KEY
chatchat run --provider agnes --model agnes-2.5-flash --thinking
```

Rate limits can be set programmatically:

```python
from chatchat.rate_limiter import set_rate_limits
set_rate_limits([
    {'provider': 'agnes', 'rpm': 20, 'tpm': 0, 'max_concurrent': 0},
])
```

## Examples

See [examples](./examples) for complete usage:

- `agent.py` — Interactive terminal chat with tool calling
- `team.py` — Leader team delegating tasks to dynamically created sub-agents
- `tool.py` — Raw client with tool calling
- `client.py` — Raw LLM client streaming usage
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
