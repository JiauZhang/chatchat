import json, argparse, random, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.scheduler import Scheduler
from chatchat.agent import Agent, AgentConfig
from chatchat.tool import tool

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=120)
args = parser.parse_args()

http_options = {'timeout': args.timeout}


@tool(
    name='query_stock', description='query current stock price by symbol',
    parameters={
        'type': 'object',
        'properties': {
            'symbol': {'type': 'string', 'description': 'stock symbol, e.g. AAPL, TSLA'},
        },
        'required': ['symbol'],
    },
)
def query_stock(symbol):
    prices = {'AAPL': 198.5, 'TSLA': 245.3, 'GOOG': 175.2, 'MSFT': 420.8}
    return f'{symbol} current price: ${prices.get(symbol.upper(), random.uniform(50, 500)):.2f}'


@tool(
    name='query_news', description='query recent news headlines',
    parameters={
        'type': 'object',
        'properties': {
            'topic': {'type': 'string', 'description': 'news topic'},
        },
        'required': ['topic'],
    },
)
def query_news(topic):
    headlines = [
        f'{topic}: Major breakthrough announced',
        f'{topic}: Market analysis shows growth trend',
        f'{topic}: New regulations impact industry',
    ]
    return '\n'.join(headlines)


scheduler = Scheduler()
agent = Agent(AgentConfig(
    name='analyst',
    provider=args.provider, model=args.model,
    http_options=http_options,
    instruction=(
        'You are a financial analyst. You have stock query and news query tools. '
        'For complex research tasks, delegate to sub-agents.'
    ),
    tools=[query_stock, query_news],
), scheduler)

result = agent.chat('What is the current price of AAPL and TSLA?')
print(f'\nanalyst result: {result}\n')

state = agent.state_dict()
with open('_agent_state.json', 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

with open('_agent_state.json', 'r', encoding='utf-8') as f:
    restored_state = json.load(f)

new_agent = Agent.from_state_dict(restored_state, scheduler=scheduler, tools=[query_stock, query_news])

result = new_agent.chat('What about GOOG?')
print(f'\nrestored agent result: {result}\n')

os.remove('_agent_state.json')