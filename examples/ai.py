import argparse
from chatchat import AI

parser = argparse.ArgumentParser()
parser.add_argument('--vendor', type=str, required=True)
parser.add_argument('--model', type=str, required=True)
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()

# `chatchat config --list` check supported vendors
ai = AI(args.vendor, model=args.model, client_kwargs={
    'timeout': args.timeout,
    'proxy': args.proxy,
})

# completion
response = ai.complete('Hi')
text = response if response.text is None else response.text
print(text, end='\n\n')

# chat
while True:
    prompt = input("user> ")
    if prompt == '\x04': # Ctrl+D
        exit()
    response = ai.chat(prompt)
    text = response if response.text is None else response.text
    print(f'assistant> {text}')