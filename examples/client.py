import argparse
from chatchat.client import Client

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='tencent')
parser.add_argument('--model', type=str, default='hunyuan-lite')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()

# `chatchat config --list` check supported providers
llm = Client(args.provider, model=args.model, http_options={
    'timeout': args.timeout,
    'proxy': args.proxy,
})

# completion
print('1. completion mode\n')
prompt = 'Hi'
response = llm.complete(prompt)
text = response if response.text is None else response.text
print(f'user> {prompt}\nassistant> {text}\n')

# chat
print('2. chat mode\n')
while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    response = llm.chat(prompt)
    text = response if response.text is None else response.text
    print(f'assistant> {text}')

# stream mode
print('\n3. stream completion mode\n')
prompt = 'Generate 200 words to me about China.'
generation_options = {'stream': True}
response = llm.complete(prompt, generation_options=generation_options)
print(f'user> {prompt}\nassistant> ', end='')
for chunk in response:
    print(chunk, end="", flush=True)
print()

llm.clear()
print('\n4. stream chat mode\n')
while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    response = llm.chat(prompt, generation_options=generation_options)
    print('assistant> ', end='')
    for chunk in response:
        print(chunk, end="", flush=True)
    print()
