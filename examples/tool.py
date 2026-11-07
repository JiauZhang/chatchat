import argparse
import asyncio
from pathlib import Path

from chatchat.runtime.runtime import Runtime
from chatchat.runtime.thinking import LEVELS, Thinking
from chatchat.tool import ToolContext, tool


def on_start(self, **kwargs):
    print(f"\n<tool>{self.name} {kwargs}</tool>\n")


def on_error(self, exception):
    print(f"\n<tool>{self.name} {exception}</tool>\n")


@tool(
    name="get_weather",
    description="getting weather information for a specified city",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "the city name, e.g., Shanghai",
            }
        },
        "required": ["city"],
    },
    on_start=on_start,
)
def get_weather(context: ToolContext, city: str):
    return f"{city} is Sunny."


@tool(
    name="get_datetime",
    description="getting current datetime",
    on_error=on_error,
)
def get_datetime(context: ToolContext):
    raise RuntimeError("get datetime failed.")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek/deepseek-chat")
    parser.add_argument("--thinking", choices=LEVELS, default="medium")
    parser.add_argument("--prompt", default="What is the weather in Shanghai?")
    args = parser.parse_args()

    runtime = Runtime(
        "tools",
        model=args.model,
        thinking=Thinking(args.thinking),
        tools=[get_weather, get_datetime],
        tool_context=ToolContext(cwd=Path.cwd()),
        lead_instruction="Use the tools when they answer the question.",
    )
    print(await runtime.conversation.query(args.prompt))


if __name__ == "__main__":
    asyncio.run(main())
