import argparse, random
from chatchat.client import Client
from chatchat.agent import Agent
from chatchat.tool import tool

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='zhipu')
parser.add_argument('--model', type=str, default='glm-4.7-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--non-streaming', action='store_true')
args = parser.parse_args()

@tool(
    name='query_train_ticket', description='query how many train tickets from a specified city to another city',
    parameters={
        'type': 'object',
        'properties': {
            'from_city': {
                'type': 'string',
                'description': 'the city name, e.g., Shanghai',
            },
            'to_city': {
                'type': 'string',
                'description': 'the city name, e.g., Beijing',
            }
        },
        'required': ['from_city', 'to_city'],
    }
)
def query_train_ticket(from_city, to_city):
    return f'{from_city} to {to_city} has {random.randint(1, 10)} tickets.'

@tool(
    name='query_ticket_price', description='query the ticket price from a specified city to another city',
    parameters={
        'type': 'object',
        'properties': {
            'from_city': {
                'type': 'string',
                'description': 'the city name, e.g., Beijing',
            },
            'to_city': {
                'type': 'string',
                'description': 'the city name, e.g., Nanjing',
            }
        },
        'required': ['from_city', 'to_city'],
    }
)
def query_ticket_price(from_city, to_city):
    return f'the ticket from {from_city} to {to_city} is {random.randint(100, 200)} RMB.'

llm = Client(args.provider, model=args.model, http_options={
    'timeout': args.timeout,
    'proxy': args.proxy,
})
travel_agent = Agent(
    name='travel_agent',
    description='query tickets and fares between cities',
    client=llm,
    tools=[query_train_ticket, query_ticket_price],
    generation_options={'stream': not args.non_streaming},
)

llm = Client(args.provider, model=args.model, http_options={
    'timeout': args.timeout,
    'proxy': args.proxy,
})
agent = Agent(
    name='super_agent', description='',
    client=llm, tools=[travel_agent],
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