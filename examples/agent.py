import argparse
from chatchat.client import Client
from chatchat.agent import Agent

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='tencent')
parser.add_argument('--model', type=str, default='hunyuan-lite')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()

llm = Client(args.provider, model=args.model, http_options={
    'timeout': args.timeout,
    'proxy': args.proxy,
})
agent = Agent(llm, '''
你是一个计算器，你只需要输出用户给你的数学运算的结果，不要输出其他内容！
'''
)

while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    response = agent(prompt, generation_options={'stream': True})
    print('assistant> ', end='')
    for chunk in response:
        print(chunk.text, end="", flush=True)
    print()