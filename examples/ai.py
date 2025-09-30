import argparse
from chatchat import AI

parser = argparse.ArgumentParser()
parser.add_argument('--vendor', type=str, default='tencent')
parser.add_argument('--model', type=str, default='hunyuan-lite')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()

# `chatchat config --list` check supported vendors
ai = AI(args.vendor, model=args.model, client_kwargs={
    'timeout': args.timeout,
    'proxy': args.proxy,
})

# completion
print('1. completion mode\n')
prompt = 'Hi'
response = ai.complete(prompt)
text = response if response.text is None else response.text
print(f'user> {prompt}\nassistant> {text}\n')

# chat
print('2. chat mode\n')
while True:
    prompt = input("user> ")
    if prompt == '\x04': # Ctrl+D
        break
    response = ai.chat(prompt)
    text = response if response.text is None else response.text
    print(f'assistant> {text}')

# stream mode
print('\n3. stream completion mode\n')
prompt = 'Generate 200 words to me about China.'
response = ai.complete(prompt, stream=True)
print(f'user> {prompt}\nassistant> ', end='')
for chunk in response:
    print(chunk.text, end="", flush=True)
print()

ai.clear()
print('\n4. stream chat mode\n')
while True:
    prompt = input("user> ")
    if prompt == '\x04': # Ctrl+D
        break
    response = ai.chat(prompt, stream=True)
    print('assistant> ', end='')
    for chunk in response:
        print(chunk.text, end="", flush=True)
    print()
