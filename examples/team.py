import argparse
import asyncio

from chatchat.team import Team

ROLE = '你是 {name}。收到 lead 的任务用一句话完成并 send_message 回给 team-lead。'
LEAD = '你是 team lead，把用户问题 send_message 发给 researcher，收到回信后汇总成一句最终答案还给用户。'


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', default='deepseek')
    parser.add_argument('--model', default='deepseek-chat')
    parser.add_argument('--prompt',
                        default='请 researcher 用一句话介绍 DeepSeek。')
    args = parser.parse_args()

    team = Team('demo', provider=args.provider, model=args.model,
                lead_instruction=LEAD)
    team.create_agent('researcher', instruction=ROLE.format(name='researcher'))

    print(await team.query(args.prompt))


if __name__ == '__main__':
    asyncio.run(main())
