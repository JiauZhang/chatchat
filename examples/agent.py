import argparse
import asyncio

from chatchat.runtime.config import ModelConfig, RuntimeConfig
from chatchat.runtime.runtime import Runtime
from chatchat.runtime.thinking import LEVELS, Thinking

WRITER = "You are a writer. Turn the topic the user gives into one sentence."


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek/deepseek-chat")
    parser.add_argument("--thinking", choices=LEVELS, default="medium")
    parser.add_argument("--prompt", default="Describe a cat in one sentence.")
    args = parser.parse_args()

    runtime = Runtime(
        "agent",
        RuntimeConfig(instruction=WRITER, model=ModelConfig(name=args.model, thinking=Thinking(args.thinking))),
    )
    print(await runtime.conversation.query(args.prompt))


if __name__ == "__main__":
    asyncio.run(main())
