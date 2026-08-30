import os, sys, argparse, random, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.agents.team import TeamConfig, create_team
from chatchat.agents.user import User
from chatchat.core.runtime import Runtime
from chatchat.core.rate_limiter import RateLimit
from chatchat.tools.base import tool, ToolContext


parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--players', type=int, default=8,
                    help='number of dice players in the knockout contest')
parser.add_argument('--timeout', type=int, default=600)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--thinking', action='store_true', default=False)
parser.add_argument('--max-steps', type=int, default=16,
                    help='max leader reasoning steps; raise if the contest stalls')
args = parser.parse_args()

http_options = {'timeout': args.timeout}
if args.proxy:
    http_options['proxy'] = args.proxy

rate_limit = RateLimit(rpm=20)


@tool(
    name='roll_dice',
    description='roll a six-sided die, returns an integer from 1 to 6',
    parameters={'type': 'object', 'properties': {}},
)
def _roll_dice(ctx: ToolContext = None):
    return str(random.randint(1, 6))


rt = Runtime()
rt.registry.register(_roll_dice)
rt.enable_logging('client', 'tool', 'agent', 'team')

team = create_team(TeamConfig(
    provider=args.provider, model=args.model,
    instruction=(
        f'You are the referee of a {args.players}-player dice knockout tournament. '
        'Run the entire contest on your own initiative: spawn dice players, have them roll '
        'concurrently, design the bracket yourself (pair up the current players each round, '
        'shuffle, give an odd player a bye, advance only the higher roll), retire eliminated '
        'players with task_stop, and repeat until one champion remains.'
    ),
    http_options=http_options, thinking=args.thinking,
    max_steps=args.max_steps,
    rate_limit=rate_limit,
    agent_tools=['roll_dice'],
), runtime=rt)


async def main():
    user = User(rt)  # 用户 = 一个可寻址的邮箱实体
    print('=' * 60)
    print(f'Team demo: 1 referee (team) + {args.players} autonomous dice players')
    print('=' * 60)
    try:
        await user.send(team.id, 'start the dice contest')
        # 纯消息：等团队经 send_message 回给自己的那一封为准（最终结果由 leader 自判何时发）。
        result = await user.receive(timeout=args.timeout)
        print(f'\n\nTeam result: {result if result else "empty"}')
    finally:
        await team.stop()
        await rt.shutdown()


if __name__ == '__main__':
    asyncio.run(main())