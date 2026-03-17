import argparse
from chatchat.client import Client
from chatchat.tool import tool, Tools

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='zhipu')
parser.add_argument('--model', type=str, default='glm-4.7-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--non-streaming', action='store_true')
parser.add_argument('--thinking', action='store_true')
args = parser.parse_args()

llm = Client(args.provider, model=args.model, http_options={'timeout': args.timeout})
generation_options = {'stream': not args.non_streaming, 'thinking': args.thinking}

def on_start(self, **kwargs):
    print(f'\n<tool>{self.name} {kwargs}</tool>\n')

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
    on_start=on_start,
)
def get_weather(city):
    return f'{city} is Sunny.'

def on_error(self, exception):
    print(f'\n<tool>{self.name} {exception}</tool>\n')

@tool(
    name='get_datetime', description='getting current datetime',
    on_error=on_error,
)
def get_datetime():
    raise RuntimeError()

tools = Tools(get_weather, get_datetime)
while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    response = llm.chat(prompt, generation_options=generation_options, tools=tools)
    print('assistant> ', end='')
    for chunk in response:
        print(chunk, end="", flush=True)
    print()
