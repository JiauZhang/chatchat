import argparse
from chatchat.client import Client

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=30)
args = parser.parse_args()

client = Client(
    provider=args.provider, model=args.model,
    http_options={'timeout': args.timeout},
)

print('streaming: ', end='')
for chunk in client.chat([{'role': 'user', 'content': 'Say hello in 3 words'}]):
    delta = chunk.choices[0].delta.content or ''
    print(delta, end='', flush=True)
print()