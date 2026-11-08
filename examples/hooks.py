import argparse
import asyncio

from chatchat.runtime.config import ModelConfig, RuntimeConfig
from chatchat.runtime.thinking import LEVELS, Thinking
from chatchat.team.team import Team

LEAD = (
    "You are the team lead. Break the user's question into tasks and send them with SendMessage; "
    "summarise the replies into one final answer."
)


def on_hooks(team):
    team.hooks.on("PreToolUse", fn=lambda i: print(f"    [hook] pre-tool: {i['tool_name']} input={i.get('tool_input')}"))
    team.hooks.on(
        "PostToolUse", fn=lambda i: print(f"    [hook] post-tool: {i['tool_name']} -> {str(i.get('tool_response'))[:60]}")
    )
    team.hooks.on("PostToolUseFailure", fn=lambda i: print(f"    [hook] tool FAILED: {i['tool_name']}: {i.get('error')}"))
    team.hooks.on("UserPromptSubmit", fn=lambda i: print(f"    [hook] user-prompt: {i['prompt'][:40]}"))
    team.hooks.on("Stop", fn=lambda i: print("    [hook] agent stop"))
    team.hooks.on("Notification", fn=lambda i: print(f"    [hook] notify {i['notification_type']}: {i['title']}"))
    team.hooks.on("SubagentStart", fn=lambda i: print(f"    [hook] subagent start: {i['agent_id']}"))
    team.hooks.on("SubagentStop", fn=lambda i: print(f"    [hook] subagent stop: {i['agent_id']}"))
    team.hooks.on("TaskCreated", fn=lambda i: print(f"    [hook] task created: {i['task_id']}"))
    team.hooks.on("TaskCompleted", fn=lambda i: print(f"    [hook] task completed: {i['task_id']} {i['task_subject']}"))
    team.hooks.on("TeammateIdle", fn=lambda i: print("    [hook] team idle"))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek/deepseek-chat")
    parser.add_argument("--thinking", choices=LEVELS, default="medium")
    parser.add_argument("--no-hooks", action="store_true")
    parser.add_argument("--prompt", default="Write a short introduction to DeepSeek with pros and cons.")
    args = parser.parse_args()

    team = Team(
        "hooks-demo",
        RuntimeConfig(
            model=ModelConfig(name=args.model, thinking=Thinking(args.thinking)),
            hooks=not args.no_hooks,
        ),
    )
    on_hooks(team)
    team.create_agent("researcher", "You are researcher: gather facts, verify them and report the findings.")
    team.create_agent("writer", "You are writer: turn the findings into a clean final draft.")

    answer = await team.conversation.query(args.prompt)
    print("\n=== lead final answer ===")
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
