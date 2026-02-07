import argparse
from chatchat import AI
from chatchat.agent import Agent

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='tencent')
parser.add_argument('--model', type=str, default='hunyuan-lite')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()

ai = AI(args.provider, model=args.model, client_kwargs={
    'timeout': args.timeout,
    'proxy': args.proxy,
})
agent = Agent(ai, '''
你是一个计算器，你只需要输出用户给你的数学运算的结果，不要输出其他内容！
'''
)

while True:
    prompt = input("user> ")
    if prompt == '\x04': # Ctrl+D
        break
    response = agent(prompt, stream=True)
    print('assistant> ', end='')
    for chunk in response:
        print(chunk.text, end="", flush=True)
    print()