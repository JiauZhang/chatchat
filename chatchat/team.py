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

    def _create_assign_task_tool(self):
        _step = 0

        def assign_task(task: str, member_name: str):
            nonlocal _step
            _step += 1
            self._current_depth += 1
            self._bus.emit('team:step', {'name': self.name, 'step': _step, 'member': member_name, 'task': task, 'mode': 'supervisor'})
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

        return Tool(
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
            tool=assign_task,
        )

    def chat(self, message: str) -> str:
        self._bus.emit('team:start', {'name': self.name, 'message': message, 'mode': 'supervisor'})
        assign_tool = self._create_assign_task_tool()
        assign_tool.set_event_bus(self._bus)
        original_tools = self.leader.tools
        if original_tools:
            self.leader.tools = Tools(*original_tools, assign_tool)
        else:
            self.leader.tools = Tools(assign_tool)
        try:
            result = self.leader.chat(message)
            if hasattr(result, '__iter__') and not isinstance(result, str):
                content = ''.join(result)
            else:
                content = result
            self._bus.emit('team:end', {'name': self.name, 'content': content, 'mode': 'supervisor'})
            return content
        finally:
            self.leader.tools = original_tools

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def pipeline(self, message: str):
        self._bus.emit('team:start', {'name': self.name, 'message': message, 'mode': 'pipeline'})
        result = message
        for i, agent in enumerate(self.members):
            self._bus.emit('team:step', {'name': self.name, 'step': i + 1, 'member': agent.name, 'mode': 'pipeline'})
            result = self._consume_chat(agent, f"处理以下任务，输出结果给下一个环节:\n{result}")
        self._bus.emit('team:end', {'name': self.name, 'content': result, 'mode': 'pipeline'})
        return result

    def parallel(self, tasks: dict[str, str]):
        self._bus.emit('team:start', {'name': self.name, 'tasks': tasks, 'mode': 'parallel'})
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
                self._bus.emit('team:step', {'name': self.name, 'member': name, 'mode': 'parallel'})
        self._bus.emit('team:end', {'name': self.name, 'results': results, 'mode': 'parallel'})
        return results