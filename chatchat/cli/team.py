import asyncio

from chatchat.client import Client
from chatchat.team import Team, LEAD_NAME

MEMBER = '你是一个协作 team 的成员。可 send_message(to=teammate 或 "*", message=...)。规矩：收到任务先做完再回信；不要把同一件事重复发；没有新输入不要主动广播；等 lead 给具体任务再动手。'
RESEARCHER = MEMBER + '你是 researcher，负责搜集事实、查证、研究，输出清晰的研究结论。'
WRITER = MEMBER + '你是 writer，负责把成果整理成流畅、成稿的正文。'
LEAD = '你是 team lead，负责把用户问题分解并发给合适的 teammate（researcher 研究 / writer 写作）。一次并行下发子任务，然后结束本轮等回信；没收到对方新的 teammate_message 前不要重复广播；各方都回信后再汇总成一份最终答案。'


async def _run(args):
    provider, model = args.params

    def client_for(inst):
        return Client(provider, model=model, instruction=inst, thinking=args.thinking,
                      http_options={'proxy': args.proxy, 'timeout': args.timeout})

    team = Team('demo', client_for(LEAD), hooks=not args.no_hooks)
    for name, inst in [('researcher', RESEARCHER), ('writer', WRITER)]:
        team.add(name, client_for(inst))
    for a in team.agents.values():
        a.start()
    answer = await team.query(args.prompt)
    print('\n=== lead 最终答复 ===')
    print(answer)


def parse_config(args):
    if args.params:
        asyncio.run(_run(args))


def cli_team(subparser):
    p = subparser.add_parser('team', help='Multi-agent team')
    p.add_argument('params', type=str, nargs=2)
    p.add_argument('--proxy', type=str, default=None)
    p.add_argument('--timeout', type=float, default=None)
    p.add_argument('--thinking', action='store_true')
    p.add_argument('--no-hooks', action='store_true')
    p.add_argument('--prompt', type=str, default='帮我写一段 DeepSeek 的介绍和优缺点，200字以内。')
    p.set_defaults(parser=parse_config)