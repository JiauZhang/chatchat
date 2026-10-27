# chatchat

A Python agent runtime: a `Team` of agents with tools, hooks, skills and
sub-agents — and the LLM client underneath it, speaking two API protocols.

## Install

```shell
pip install chatchat
```

Python 3.10 or newer.

## Configure

There is no built-in provider list. A provider is a profile — your data, in
`~/.chatchat/config.json` (`CHATCHAT_SECRET_FILE` moves the file):

```json
{
  "agnes": {
    "type": "openai",
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
| `type` | the API protocol: `openai` or `anthropic`. Selects the request encoding, the SSE parser and the auth header. Required |
| `base_url` | where to send requests. Required |
| `api_key` | the credential. Required |
| `rpm` | optional cap on requests per minute for this provider |

Environment variables override or replace profile entries:
`CHATCHAT_<NAME>_API_KEY`, `CHATCHAT_<NAME>_BASE_URL`, `CHATCHAT_<NAME>_TYPE`.

Or write entries from the command line:

```shell
chatchat config --provider agnes --type openai --base-url https://apihub.agnes-ai.com/v1 --api-key YOUR_API_KEY
chatchat config --provider agnes --rpm 60
chatchat config          # show the profiles, api keys masked
```

The file is written `0600`, and `chatchat config` warns when it is readable by
others.

## Chat in the terminal

```shell
$ chatchat run agnes/agnes-3.0-flash
user> Introduce yourself briefly.
assistant> Hello! I am a large language model ...
user> /exit
```

The model is one `provider/model` string. `--thinking` picks the reasoning
effort (`off`, `low`, `medium`, `high`, `max`); `--proxy` and `--timeout` apply
to the HTTP client.

## A team in the terminal

```shell
chatchat team agnes/agnes-3.0-flash --prompt "帮我写一段 DeepSeek 的介绍"
```

A lead hands work to teammates over the mailbox and writes the final answer.
`--no-hooks` runs without the configured hooks.

## Hooks

```shell
chatchat hooks
```

lists every hook that will run and where it came from: `~/.chatchat/settings.json`,
`.chatchat/settings.json` and `.chatchat/settings.local.json`.

## Examples

Each example is runnable and shows one shape. Every one takes
`--model provider/model` and defaults to `deepseek/deepseek-chat`
(`examples/tool.py` defaults to `zhipu/glm-4.7-flash`), so either configure a
profile by that name or pass your own.

```shell
python examples/client.py   --model agnes/agnes-3.0-flash  # the client alone: completion and chat
python examples/agent.py    --model agnes/agnes-3.0-flash  # one agent, no team
python examples/team.py     --model agnes/agnes-3.0-flash  # lead + teammate over a mailbox
python examples/agenttool.py --model agnes/agnes-3.0-flash # an agent spawning sub-agents
python examples/tool.py     --model agnes/agnes-3.0-flash  # your own tools and ToolContext
python examples/hooks.py    --model agnes/agnes-3.0-flash  # hooks around tool calls and turns
python examples/skill.py    --model agnes/agnes-3.0-flash  # a SKILL.md loaded on demand
```

## How a request is made

```
Client(model="agnes/agnes-3.0-flash")
        │  profile: type, base_url, api_key, rpm
        ├─ openai.py     → POST {base_url}/responses      Responses API
        └─ anthropic.py  → POST {base_url}/v1/messages    Messages API
        │
        ▼
SSE → Delta (content, reasoning, tool calls) → one accumulated Message
        │
        ├─ text only  → returned as str
        └─ tool calls → returned as list[ToolUse]; the caller runs them and
                        sends the results back in the next call
```

A call sends the whole conversation each time, with `store: false`; on the
Responses protocol the model's reasoning is replayed through
`reasoning.encrypted_content`, and on the Anthropic one message blocks pass
through verbatim while thinking is set per effort. History, compaction and the
tool loop above `Client` belong to the agent and team layers, not to the
transport.

A third-party endpoint needs no code — only a profile entry. Anything that
speaks the Responses or the Anthropic protocol works.

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
