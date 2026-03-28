import argparse
from chatchat.agent import Agent

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='zhipu')
parser.add_argument('--model', type=str, default='glm-4.7-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--non-streaming', action='store_true')
args = parser.parse_args()

agent = Agent(
    provider=args.provider, model=args.model, http_options={
        'timeout': args.timeout,
        'proxy': args.proxy,
    },
    skills=['.'],
    generation_options={'stream': not args.non_streaming},
)

while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    response = agent(prompt)
    print('assistant> ', end='')
    for chunk in response:
        print(chunk, end="", flush=True)
    print()
