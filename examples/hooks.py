import argparse
import asyncio

from chatchat.client import Client
from chatchat.team.team import Team, LEAD_NAME

LEAD = '你是 team lead，负责把用户问题分解并发给合适的 teammate。用 send_message 派发任务，等回信后再汇总成最终答案。'


def on_hooks(team):
    team.hooks.on('PreToolUse', fn=lambda i: print(f'    [hook] pre-tool: {i["tool_name"]} input={i.get("tool_input")}'))
    team.hooks.on('PostToolUse', fn=lambda i: print(f'    [hook] post-tool: {i["tool_name"]} -> {str(i.get("tool_response"))[:60]}'))
    team.hooks.on('PostToolUseFailure', fn=lambda i: print(f'    [hook] tool FAILED: {i["tool_name"]}: {i.get("error")}'))
    team.hooks.on('UserPromptSubmit', fn=lambda i: print(f'    [hook] user-prompt: {i["prompt"][:40]}'))
    team.hooks.on('Stop', fn=lambda i: print('    [hook] agent stop'))
    team.hooks.on('Notification', fn=lambda i: print(f'    [hook] notify {i["notification_type"]}: {i["title"]}'))
    team.hooks.on('SubagentStart', fn=lambda i: print(f'    [hook] subagent start: {i["agent_id"]}'))
    team.hooks.on('SubagentStop', fn=lambda i: print(f'    [hook] subagent stop: {i["agent_id"]}'))
    team.hooks.on('TaskCreated', fn=lambda i: print(f'    [hook] task created: {i["task_id"]}'))
    team.hooks.on('TaskCompleted', fn=lambda i: print(f'    [hook] task completed: {i["task_id"]} {i["task_subject"]}'))
    team.hooks.on('TeammateIdle', fn=lambda i: print('    [hook] team idle'))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', default='deepseek')
    parser.add_argument('--model', default='deepseek-chat')
    parser.add_argument('--thinking', action='store_true')
    parser.add_argument('--no-hooks', action='store_true')
    parser.add_argument('--prompt', default='帮我写一段 DeepSeek 的介绍和优缺点，200字以内。')
    args = parser.parse_args()

    client = Client(args.provider, model=args.model, instruction=LEAD,
                    thinking=args.thinking)
    team = Team('hooks-demo', client, hooks=not args.no_hooks)
    on_hooks(team)
    team.add('researcher', '你是 researcher，负责搜集事实、查证、研究，输出清晰的研究结论。')
    team.add('writer', '你是 writer，负责把成果整理成流畅、成稿的正文。')
    for a in team.agents.values():
        a.start()

    answer = await team.query(args.prompt)
    print('\n=== lead 最终答复 ===')
    print(answer)


if __name__ == '__main__':
    asyncio.run(main())
