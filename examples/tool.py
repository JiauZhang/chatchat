import argparse
from chatchat.agent import Agent
from chatchat.tool import tool

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='zhipu')
parser.add_argument('--model', type=str, default='glm-4.7-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--non-streaming', action='store_true')
parser.add_argument('--thinking', action='store_true')
args = parser.parse_args()

http_options = {} if args.timeout is None else {'timeout': args.timeout}


@tool(
    name='get_weather', description='getting weather information for a specified city',
    parameters={
        'type': 'object',
        'properties': {
            'city': {
                'type': 'string',
                'description': 'the city name, e.g., Shanghai',
            }
        },
        'required': ['city'],
    },
)
def get_weather(city):
    return f'{city} is Sunny.'


@tool(
    name='get_datetime', description='getting current datetime',
)
def get_datetime():
    raise RuntimeError('get datetime failed.')


agent = Agent(
    provider=args.provider, model=args.model,
    instruction='You are a helpful assistant.',
    stream=not args.non_streaming,
    thinking=args.thinking,
    tools=[get_weather, get_datetime],
    name='assistant',
    description='A helpful assistant',
    http_options=http_options,
)

while True:
    prompt = input('user> ')
    if prompt == '/exit':
        break
    print('assistant> ', end='')
    result = agent(prompt)
    if args.non_streaming:
        print(result)
    else:
        for chunk in result:
            print(chunk, end='', flush=True)
    print()