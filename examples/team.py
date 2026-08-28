import os, sys, argparse, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.team import TeamConfig, create_team
from chatchat.runtime import get_runtime
from chatchat.rate_limiter import RateLimit
from chatchat.tool import tool, ToolContext, get_registry


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


get_registry().register(_roll_dice)

get_runtime().enable_logging('client', 'tool', 'agent', 'team')

team = create_team(TeamConfig(
    name='lead',
    provider=args.provider, model=args.model,
    instruction=(
        f'You are the referee of a {args.players}-player dice knockout tournament. '
        'Run the entire contest on your own initiative: spawn dice players, have them roll '
        'concurrently, design the bracket yourself (pair up the current players each round, '
        'shuffle, give an odd player a bye, advance only the higher roll), retire eliminated '
        'players, and repeat until one champion remains. Then announce the champion and '
        'summarize each round\'s matches. Keep replies short.'
    ),
    http_options=http_options, thinking=args.thinking,
    max_steps=args.max_steps,
    rate_limit=rate_limit,
    agent_tools=['roll_dice'],
))


async def main():
    print('=' * 60)
    print(f'Team demo: 1 referee (team) + {args.players} autonomous dice players')
    print('=' * 60)
    try:
        r = await team.chat('start the dice contest')
        print(f'\n\nTeam result: {r if r else "empty"}')
    finally:
        await team.stop()
        await get_runtime().shutdown()


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
