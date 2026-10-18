import argparse
import asyncio

from chatchat.team.team import Team

WRITER = "你是 writer，把用户给的主题用一句话成稿。"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek/deepseek-chat")
    parser.add_argument("--prompt", default="把「猫」写成一句简介。")
    args = parser.parse_args()

    team = Team("agent", model=args.model, lead_instruction=WRITER)
    print(await team.query(args.prompt))


if __name__ == "__main__":
    asyncio.run(main())
