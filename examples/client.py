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
new_messages = [{'role': 'user', 'content': prompt}]
response = llm.chat(new_messages)
print(f'user> {prompt}\nassistant> {response.choices[0].message.content}\n')

# chat
print('2. chat mode\n')
while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    new_messages = [{'role': 'user', 'content': prompt}]
    response = llm.chat(new_messages)
    print(f'assistant> {response.choices[0].message.content}')

# stream completion
print('\n3. stream completion mode\n')
prompt = 'Generate 200 words to me about China.'
new_messages = [{'role': 'user', 'content': prompt}]
response = llm.chat(new_messages, stream=True)
print(f'user> {prompt}\nassistant> ', end='')
for chunk in response:
    print(chunk.choices[0].delta.content or '', end='', flush=True)
print()

llm.clear()
print('\n4. stream chat mode\n')
while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    new_messages = [{'role': 'user', 'content': prompt}]
    response = llm.chat(new_messages, stream=True)
    print('assistant> ', end='')
    for chunk in response:
        print(chunk.choices[0].delta.content or '', end='', flush=True)
    print()