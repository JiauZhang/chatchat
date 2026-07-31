from __future__ import annotations

from chatchat.agent import Agent
from chatchat.tool import Tool, Tools


class Team:
    def __init__(self, *, name, leader, event_bus, max_depth=5):
        self.name = name
        self.leader = leader
        self._bus = event_bus
        self.max_depth = max_depth
        self._current_depth = 0
        self._members: list[Agent | 'Team'] = []
        self._assign_tool = Tool(
            name='assign_task',
            description='将子任务分配给 Team 中的其他成员执行。参数: task (任务描述), member_name (目标成员名称)',
            parameters={
                'type': 'object',
                'properties': {
                    'task': {'type': 'string', 'description': '任务描述'},
                    'member_name': {'type': 'string', 'description': '目标成员名称'},
                },
                'required': ['task', 'member_name'],
            },
            tool=self._assign_task,
            source=self.leader.name,
        )

    def _emit(self, topic: str, data: dict = None):
        self._bus.emit(topic, data or {}, source=self.name)

    @property
    def members(self) -> list[Agent]:
        return [
            m if isinstance(m, Agent) else m.leader
            for m in self._members
        ]

    @property
    def is_leaf(self) -> bool:
        return all(isinstance(m, Agent) for m in self._members)

    def add_member(self, member: Agent | 'Team'):
        if self._members:
            if type(member) != type(self._members[0]):  # noqa: E721
                raise TypeError("不能混合添加 Agent 和 Team 成员")
        self._members.append(member)

    def find_member(self, name: str) -> Agent | None:
        if self.leader.name == name:
            return self.leader
        for m in self._members:
            if isinstance(m, Agent):
                if m.name == name:
                    return m
            else:
                if m.leader.name == name:
                    return m.leader
                found = m.find_member(name)
                if found:
                    return found
        return None

    def _consume_chat(self, target, message: str) -> str:
        result = target.chat(message)
        if hasattr(result, '__iter__') and not isinstance(result, str):
            return ''.join(result)
        return result

    def _assign_task(self, task: str, member_name: str) -> str:
        self._current_depth += 1
        self._emit('team:step', {'name': self.name, 'content': f'assign_task {task} to {member_name}'})
        if self._current_depth > self.max_depth:
            self._current_depth -= 1
            return f"错误：委托深度超过限制 ({self.max_depth})"

        target = self.find_member(member_name)
        if not target:
            self._current_depth -= 1
            return f"错误：未找到成员 '{member_name}'"

        try:
            return self._consume_chat(target, task)
        finally:
            self._current_depth -= 1

    def chat(self, message: str) -> str:
        self._emit('team:start', {'name': self.name, 'message': message, 'mode': 'supervisor'})
        self._assign_tool.set_event_bus(self._bus)
        original_tools = self.leader.tools
        if original_tools:
            self.leader.tools = Tools(*original_tools, self._assign_tool)
        else:
            self.leader.tools = Tools(self._assign_tool)
        try:
            result = self.leader.chat(message)
            if hasattr(result, '__iter__') and not isinstance(result, str):
                content = ''.join(result)
            else:
                content = result
            self._emit('team:end', {'name': self.name, 'content': content, 'mode': 'supervisor'})
            return content
        finally:
            self.leader.tools = original_tools

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def pipeline(self, message: str):
        self._emit('team:start', {'name': self.name, 'message': message, 'mode': 'pipeline'})
        result = message
        for i, agent in enumerate(self.members):
            self._emit('team:step', {'name': self.name, 'content': f'pipeline step {i+1}: {agent.name}'})
            result = self._consume_chat(agent, f"处理以下任务，输出结果给下一个环节:\n{result}")
        self._emit('team:end', {'name': self.name, 'content': result, 'mode': 'pipeline'})
        return result

    def parallel(self, tasks: dict[str, str]):
        self._emit('team:start', {'name': self.name, 'tasks': tasks, 'mode': 'parallel'})
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(self._consume_chat, self.find_member(name), task): name
                for name, task in tasks.items()
            }
            results = {}
            for future in as_completed(futures):
                name = futures[future]
                results[name] = future.result()
                self._emit('team:step', {'name': self.name, 'content': f'parallel done: {name}'})
        self._emit('team:end', {'name': self.name, 'results': results, 'mode': 'parallel'})
        return results