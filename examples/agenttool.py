import argparse
import asyncio

from chatchat.team import Team

LEAD = ('你是 superagent 主 agent。对用户任务，用 create_agent(prompt=...) 把它派给 '
        '一个 sub-agent 完成，并把 sub-agent 的最终答复原样返回给用户，不要自己改写。')


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', default='deepseek')
    parser.add_argument('--model', default='deepseek-chat')
    parser.add_argument('--prompt', default='把「猫」写成一句简介。')
    args = parser.parse_args()

    team = Team('agenttool', provider=args.provider, model=args.model,
                lead_instruction=LEAD)
    print(await team.query(args.prompt))


if __name__ == '__main__':
    asyncio.run(main())
