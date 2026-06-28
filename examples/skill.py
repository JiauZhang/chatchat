import os, argparse, subprocess
from chatchat.agent import Agent, SubAgent
from chatchat.tool import tool
from chatchat.types import Progress, ProgressType

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--non-streaming', action='store_true')
args = parser.parse_args()

@tool(
    name='execute_shell_command',
    description='执行一条 shell 命令并返回其标准输出和标准错误。注意：该命令会直接在系统上运行，请避免使用危险操作。',
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令，例如 'ls -l' 或 'echo hello'"
            }
        },
        "required": ["command"],
    },
)
def execute_shell_command(command):
    print(f'execute shell command: {command}')
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[STDERR]\n" + result.stderr
        if not output.strip():
            output = "(无输出)"
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"错误：命令执行超过30秒超时。"
    except Exception as e:
        return f"执行命令时发生异常：{str(e)}"

@tool(
    name='write_file',
    description='将文本内容写入指定路径的文件（会覆盖已有文件）。',
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文件的绝对或相对路径，例如 './output.txt' 或 '/home/user/data.log'"
            },
            "content": {
                "type": "string",
                "description": "要写入文件的文本内容"
            }
        },
        "required": ["file_path", "content"],
    },
)
def write_file(file_path, content):
    print(f'execute write_file: {file_path}, {len(content)}')
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"成功写入文件：{file_path} (共 {len(content)} 字符)"
    except Exception as e:
        return f"写入文件失败：{str(e)}"

agent = Agent(
    provider=args.provider, model=args.model, http_options={
        'timeout': args.timeout,
        'proxy': args.proxy,
    },
    tools=[
        SubAgent.from_skill(
            os.path.dirname(__file__), provider=args.provider, model=args.model,
            available_tools=[execute_shell_command, write_file],
        ),
        execute_shell_command,
        write_file,
    ],
    stream=not args.non_streaming,
)

def on_progress(progress):
    if progress.type == ProgressType.AGENT_START:
        print(f'\n[agent {progress.agent or ""} start]')
    elif progress.type == ProgressType.AGENT_STEP:
        print(f'\n[agent {progress.agent or ""} step {progress.step}]')
    elif progress.type == ProgressType.AGENT_END:
        print(f'\n[agent {progress.agent or ""} end]')
    elif progress.type == ProgressType.TOOL_START:
        print(f'\n[agent {progress.agent or ""} using tool {progress.tool_name}]')
    elif progress.type == ProgressType.TOOL_END:
        print(f'\n[agent {progress.agent or ""} tool {progress.tool_name} done]')

while True:
    prompt = input("user> ")
    if prompt == '/exit':
        break
    response = agent.chat(prompt, on_progress=on_progress)
    print('assistant> ', end='')
    for chunk in response:
        print(chunk, end="", flush=True)
    print()