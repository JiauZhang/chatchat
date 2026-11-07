import argparse
import asyncio

from chatchat.client import Client
from chatchat.runtime.thinking import LEVELS, Thinking

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="deepseek/deepseek-chat")
parser.add_argument("--thinking", choices=LEVELS, default="medium")
parser.add_argument("--timeout", type=int, default=None)
parser.add_argument("--proxy", type=str, default=None)
args = parser.parse_args()


async def main():
    llm = Client(
        model=args.model,
        thinking=Thinking(args.thinking),
        http_options={"timeout": args.timeout, "proxy": args.proxy},
    )

    print("1. completion mode")
    print(await llm.complete("Hi"))

    print("\n2. chat mode (type /exit to leave)")
    while True:
        prompt = input("user> ")
        if prompt == "/exit":
            break
        print("\nassistant>")
        print(await llm.chat(prompt))


if __name__ == "__main__":
    asyncio.run(main())
