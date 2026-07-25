import argparse
from chatchat.client import Client

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
parser.add_argument('--timeout', type=int, default=30)
args = parser.parse_args()

client = Client(args.provider, args.model, http_options={'timeout': args.timeout})

result = client.chat([{'role': 'user', 'content': 'Hello, who are you?'}], stream=False)
print(f'non-streaming: {result.choices[0].message.content}\n')

print('streaming: ', end='')
for chunk in client.chat([{'role': 'user', 'content': 'Say hello in 3 words'}], stream=True):
    delta = chunk.choices[0].delta.content or ''
    print(delta, end='', flush=True)
print()