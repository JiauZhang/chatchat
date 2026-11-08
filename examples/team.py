import argparse
import asyncio

from chatchat.runtime.config import ModelConfig, RuntimeConfig
from chatchat.runtime.thinking import LEVELS, Thinking
from chatchat.team.team import Team

ROLE = "You are {name}. Finish the task the lead sends you in one sentence and reply with SendMessage."
LEAD = "You are the team lead. Send the question to researcher with SendMessage, then summarise the reply."


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek/deepseek-chat")
    parser.add_argument("--thinking", choices=LEVELS, default="medium")
    parser.add_argument("--prompt", default="Ask researcher to introduce DeepSeek in one sentence.")
    args = parser.parse_args()

    team = Team(
        "demo",
        RuntimeConfig(instruction=LEAD, model=ModelConfig(name=args.model, thinking=Thinking(args.thinking))),
    )
    team.create_agent("researcher", instruction=ROLE.format(name="researcher"))

    print(await team.conversation.query(args.prompt))


if __name__ == "__main__":
    asyncio.run(main())
