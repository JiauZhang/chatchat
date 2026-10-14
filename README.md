# chatchat

A Python agent runtime: a `Team` of agents with tools, hooks, skills and
sub-agents — and the LLM client underneath it, speaking two API protocols.

## Install

```shell
pip install chatchat
```

## Configure

There is no built-in provider list. A provider is a profile — your data, in
`~/.chatchat/chatchat.json`:

```json
{
  "agnes": {
    "base_url": "https://apihub.agnes-ai.com/v1",
    "api_key": "YOUR_API_KEY"
  },
  "kimi": {
    "type": "anthropic",
    "base_url": "https://api.moonshot.ai",
    "api_key": "YOUR_API_KEY"
  }
}
```

| field | meaning |
|---|---|
| `base_url` | where to send requests. Required for custom profiles |
| `type` | the API protocol: `openai` (default) or `anthropic`. Selects the request encoding, the SSE parser and the auth header |
| `api_key` | the credential |

Two reserved names work with no `base_url` at all — they carry their own
official endpoints:

- `openai` → `https://api.openai.com/v1`
- `anthropic` → `https://api.anthropic.com` (and implies `type: anthropic`)

Environment variables override or replace profile entries:
`CHATCHAT_<NAME>_API_KEY`, `CHATCHAT_<NAME>_BASE_URL`, `CHATCHAT_<NAME>_TYPE`.

Or write entries from the command line:

```shell
chatchat config agnes.base_url=https://apihub.agnes-ai.com/v1
chatchat config agnes.api_key=YOUR_API_KEY
chatchat config --list
```

## Chat in the terminal

```shell
$ chatchat run agnes agnes-3.0-flash
user> Introduce yourself briefly.
assistant> Hello! I am a large language model ...
user> /exit
```

## Agent runtime

The same package runs a whole agent: a `Team` of agents, tools, hooks, skills
and sub-agents. Each example is runnable and shows one shape.

```shell
python examples/team.py --provider agnes --model agnes-3.0-flash  # lead + teammates over a mailbox
python examples/agenttool.py                                      # an agent spawning sub-agents
python examples/agent.py                                          # one agent, no team
python examples/tool.py                                           # your own tools and ToolContext
python examples/hooks.py                                          # hooks around tool calls and turns
```

## How a request flows

```
your messages (Claude-style blocks)
        │
        ▼
chatchat/protocols/   openai.py    → POST /chat/completions   (Bearer auth)
                      anthropic.py → POST /v1/messages        (x-api-key auth)
        │
        ▼
unified Delta stream back to the agent loop
```

A third-party endpoint needs no code — only a profile entry. Anything that
speaks the OpenAI or the Anthropic protocol works.

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
