import argparse
import asyncio

from chatchat.team.agents import run_agent

WRITER = '你是 writer，把用户给的主题用一句话成稿。'


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', default='deepseek')
    parser.add_argument('--model', default='deepseek-chat')
    parser.add_argument('--prompt', default='把「猫」写成一句简介。')
    args = parser.parse_args()

    print(await run_agent(args.prompt, provider=args.provider, model=args.model,
                          system_prompt=WRITER))


if __name__ == '__main__':
    asyncio.run(main())
