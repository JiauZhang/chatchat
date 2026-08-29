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
from chatchat.agents.agent import AgentConfig, create_agent
from chatchat.core.runtime import Runtime
from chatchat.core.ids import make_id
from chatchat.tools.base import tool

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

rt = Runtime()
rt.registry.register(get_weather)

agent = create_agent(AgentConfig(
    provider='agnes', model='agnes-2.5-flash',
    instruction='You are a helpful assistant.',
    tools=['get_weather'],
), runtime=rt)

async def main():
    reply = await rt.request(
        source=make_id(), target_id=agent.id,
        topic=f'entity:{agent.kind}:{agent.id}:text',
        data='How is the weather in Shanghai?', timeout=300,
    )
    print(reply)
    await agent.stop()
    await rt.shutdown()

asyncio.run(main())
```

> Every Runtime is self-contained (its own message router, tool table and tool handler) and must be created explicitly. Every interaction goes through it as an async event: `request` delivers a text message into the agent's mailbox, its process loop consumes it, and the reply resolves the pending future.

### Multi-Agent Team

Teams inherit from Agent and carry management tools (`create_agent`, `create_team`, `send_message`, `task_stop`). Sub-agents are created on demand by the leader and communicate through the Runtime via `request` / `publish`.

```python
import asyncio
from chatchat.agents.team import TeamConfig, create_team
from chatchat.core.runtime import Runtime
from chatchat.core.ids import make_id

rt = Runtime()

team = create_team(TeamConfig(
    provider='agnes', model='agnes-2.5-flash',
    instruction='You are a tech lead. Use create_agent to delegate tasks to sub-agents.',
    agent_tools=[],
), runtime=rt)

async def main():
    reply = await rt.request(
        source=make_id(), target_id=team.id,
        topic=f'entity:team:{team.id}:text',
        data='write a tutorial to output.md', timeout=300,
    )
    print(reply)
    await team.stop()
    await rt.shutdown()

asyncio.run(main())
```

### Tools

Tools are independent objects built with the `@tool` decorator, then mounted into a Runtime via `rt.registry.register(tool)`. Agent configs reference tools by name; the Runtime resolves them and runs calls inside the AgentLoop&ToolHandler.

```python
from chatchat.tools.base import tool

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

rt = Runtime()
rt.registry.register(add)
agent = create_agent(AgentConfig(
    provider='agnes', model='agnes-2.5-flash',
    instruction='You are a helpful assistant.',
    tools=['add'],
), runtime=rt)
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

- **Runtime** — one self-contained environment per application: message router, tool table (`registry`), tool executor and lifecycle. Every agent/team must be created with an explicit Runtime; there is no global default.
- **Agent** — wraps an LLM client, a tool set, and the AgentLoop (streaming, tool-call accumulation, lifecycle hooks `start`/`step`/`end`/`error`).
- **Team** — an Agent with management tools; `leader_tools` configure the leader's tools, `agent_tools` configure tools given to created sub-agents.
- **Client / providers** — async streaming LLM clients (aiohttp) for `agnes`, `deepseek`, `openrouter`, `google`, `alibaba`, `baidu`, `zhipu`, `tencent`, `xunfei`, etc.

Observe runtime activity with `rt.enable_logging('agent', 'team', 'client', 'tool')`. Lifecycle topics: `lifecycle:agent:start/step/end/error`, `lifecycle:client:start/step/end/error`, `lifecycle:tool:start/step/end/error`. Replies are routed by event source: `reply_to` resolves a pending request; otherwise a message sent with `expect_reply` gets a notification back to its sender.

## Configuration

```shell
chatchat config --list
chatchat config <provider>.api_key=YOUR_API_KEY
chatchat run --provider agnes --model agnes-2.5-flash --thinking
```

Rate limits are configured per-provider on the client config (no global
registry). The shared aiohttp session is global and managed by the runtime via
`init_transport()` / `close_transport()`.

```python
from chatchat.core.rate_limiter import RateLimit
from chatchat.providers.client import ClientConfig

config = ClientConfig(
    provider='agnes', model='agnes-2.5-flash', name='my-client',
    rate_limit=RateLimit(rpm=20, tpm=0, max_concurrency=0),
)
```

## Examples

See [examples](./examples) for complete usage:

- `agent.py` — Interactive terminal chat with tool calling
- `team.py` — Autonomous dice knockout: the leader spawns players and runs the bracket itself using create_agent / send_message / task_stop
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
