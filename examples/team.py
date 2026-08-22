import os, sys, argparse, asyncio, random, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.agent import AgentConfig
from chatchat.team import TeamConfig, create_team
from chatchat.runtime import get_runtime
from chatchat.tool import tool, ToolContext
from chatchat.rate_limiter import set_rate_limits


parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--timeout', type=int, default=600)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--thinking', action='store_true', default=False)
args = parser.parse_args()

http_options = {'timeout': args.timeout}
if args.proxy:
    http_options['proxy'] = args.proxy

set_rate_limits([{'provider': 'agnes', 'rpm': 20}])

game = {'players': [], 'current': [], 'rounds': [], 'created': False}
rolls = {}


@tool(
    name='roll_dice',
    description='roll a six-sided die, returns an integer from 1 to 6',
    parameters={'type': 'object', 'properties': {}},
)
def _roll_dice(ctx: ToolContext = None):
    value = random.randint(1, 6)
    rolls[ctx.agent.name] = value
    return str(value)


async def _roll(player_name):
    sub = team.sub_agents.get(player_name)
    if sub is None:
        return 0
    rolls.pop(player_name, None)
    try:
        await asyncio.wait_for(
            sub.chat('roll a six-sided die using roll_dice'),
            timeout=90,
        )
    except Exception:
        pass
    return rolls.get(player_name, 0)


async def _play_match(a, b):
    sa, sb = await asyncio.gather(_roll(a), _roll(b))
    return {'a': a, 'score_a': sa, 'b': b, 'score_b': sb,
            'winner': a if sa >= sb else b}


@tool(
    name='create_players',
    description='As referee, create the dice players for the knockout contest. Call this first. Returns the player names.',
    parameters={'type': 'object', 'properties': {
        'count': {'type': 'integer', 'description': 'number of players'},
    },
        'required': ['count']},
)
async def _create_players(count):
    if game['created']:
        return json.dumps({'players': game['players']}, ensure_ascii=False)
    subs = [
        team.create_sub_agent(AgentConfig(
            name=f'player{i}',
            instruction='You are a dice player. When asked to roll the die, call the roll_dice tool.',
            provider=args.provider, model=args.model,
            thinking=args.thinking, http_options=http_options,
            tools=[_roll_dice],
        )) for i in range(1, int(count) + 1)
    ]
    game['players'] = [s.name for s in subs]
    game['current'] = list(game['players'])
    game['created'] = True
    return json.dumps({'players': game['players']}, ensure_ascii=False)


@tool(
    name='roll_round',
    description='Run one knockout round: pair up the remaining players (n//2 pairs), each pair rolls dice concurrently and the higher roll advances; with an odd count the last player gets a bye. Returns the round matches with scores, the bye, and who advances. Call repeatedly until one player remains.',
    parameters={'type': 'object', 'properties': {}},
)
async def _roll_round():
    players = list(game['current'])
    if len(players) <= 1:
        return 'only one player left, call declare_winner'
    bye = players.pop() if len(players) % 2 == 1 else None
    random.shuffle(players)
    pairs = [(players[i], players[i + 1]) for i in range(0, len(players) - 1, 2)]
    matches = await asyncio.gather(*[_play_match(a, b) for a, b in pairs])
    winners = [m['winner'] for m in matches]
    if bye:
        winners.append(bye)
    game['rounds'].append({'pairs': matches, 'bye': bye})
    game['current'] = winners
    return json.dumps({
        'round': len(game['rounds']),
        'pairs': matches,
        'bye': bye,
        'next': winners,
    }, ensure_ascii=False)


@tool(
    name='declare_winner',
    description='Finalize the knockout: return the champion and all round results.',
    parameters={'type': 'object', 'properties': {}},
)
async def _declare_winner():
    if len(game['current']) != 1:
        return 'tournament not finished, call roll_round again'
    return json.dumps({
        'champion': game['current'][0],
        'rounds': game['rounds'],
    }, ensure_ascii=False)


get_runtime().enable_logging('client', 'tool', 'agent', 'team')

team = create_team(TeamConfig(
    name='lead',
    provider=args.provider, model=args.model,
    instruction='You are the referee of an 8-player dice knockout tournament. Create 8 players, then run knockout rounds where each pair rolls a six-sided die and the higher roll advances until a single champion remains. Announce the champion and each round\'s matches. Keep replies short.',
    http_options=http_options, thinking=args.thinking,
    max_steps=8,
    leader_tools=[_create_players, _roll_round, _declare_winner],
))


async def main():
    await asyncio.sleep(0.1)
    print('=' * 60)
    print('Team demo: 1 referee (team) + 8 players dice contest')
    print('=' * 60)
    try:
        r = await team.chat('start the dice contest')
        print(f'\n\nTeam result: {r if r else "empty"}')
    finally:
        await team.stop()
        get_runtime().shutdown()


if __name__ == '__main__':
    asyncio.run(main())
