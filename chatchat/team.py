from __future__ import annotations
import time
from dataclasses import dataclass
from queue import Queue

from chatchat.agent import Agent, AgentConfig
from chatchat.actor import Actor, Action, ResourcePool
from chatchat.task import Task, TaskStatus
from chatchat.tool import Tool, Tools


@dataclass
class TeamConfig:
    name: str
    leader: AgentConfig
    members: list[AgentConfig] | list[TeamConfig] | None = None


class Team(Actor):
    def __init__(self, *, name, event_bus, leader: AgentConfig, members: list[AgentConfig] | list[TeamConfig] | None = None,
                 resource_pool: ResourcePool | None = None,
                 provider: str | None = None, model: str | None = None):
        Actor.__init__(self, name=name, event_bus=event_bus)
        self._provider = provider
        self._model = model
        self._resource_pool = resource_pool or ResourcePool()
        self._tasks: dict[str, Task] = {}
        self._current_caller: str = ""
        self._pending_replies: dict[str, Queue] = {}

        # --- Leader tools ---
        _ln = leader.name
        self._assign_tool = Tool(name='assign_task', source=_ln, event_bus=event_bus,
            description='将子任务分配给 Team 中的其他成员执行。参数: task_id (任务ID), member_name (目标成员名称)',
            parameters={'type': 'object', 'properties': {
                'task_id': {'type': 'string', 'description': '任务ID'},
                'member_name': {'type': 'string', 'description': '目标成员名称'},
            }, 'required': ['task_id', 'member_name']},
            tool=self._assign_task,
        )
        self._spawn_tool = Tool(name='spawn_agent', source=_ln, event_bus=event_bus,
            description='创建一个新的 Agent 成员并加入团队。参数: name (名称), instruction (角色指令), model (模型名, 可选)',
            parameters={'type': 'object', 'properties': {
                'name': {'type': 'string', 'description': 'Agent 名称'},
                'instruction': {'type': 'string', 'description': '角色指令'},
                'model': {'type': 'string', 'description': '模型名（可选，默认使用当前模型）'},
            }, 'required': ['name', 'instruction']},
            tool=self._spawn_agent,
        )
        self._create_team_tool = Tool(name='create_team', source=_ln, event_bus=event_bus,
            description='创建一个新的子 Team 并加入团队。参数: name (子团队名称), leader_name (负责人名称), leader_instruction (负责人指令)',
            parameters={'type': 'object', 'properties': {
                'name': {'type': 'string', 'description': '子团队名称'},
                'leader_name': {'type': 'string', 'description': '负责人名称'},
                'leader_instruction': {'type': 'string', 'description': '负责人角色指令'},
            }, 'required': ['name', 'leader_name', 'leader_instruction']},
            tool=self._create_team,
        )
        self._create_task_tool = Tool(name='create_task', source=_ln, event_bus=event_bus,
            description='创建一个任务。参数: description (任务描述), depends_on (依赖的任务ID列表, 可选)',
            parameters={'type': 'object', 'properties': {
                'description': {'type': 'string', 'description': '任务描述'},
                'depends_on': {'type': 'array', 'items': {'type': 'string'}, 'description': '依赖的任务ID列表（可选）'},
            }, 'required': ['description']},
            tool=self._create_task,
        )
        self._get_task_tool = Tool(name='get_task', source=_ln, event_bus=event_bus,
            description='查询任务状态。参数: task_id (任务ID)',
            parameters={'type': 'object', 'properties': {
                'task_id': {'type': 'string', 'description': '任务ID'},
            }, 'required': ['task_id']},
            tool=self._get_task,
        )
        self._list_tasks_tool = Tool(name='list_tasks', source=_ln, event_bus=event_bus,
            description='列出所有任务，可按状态和负责人筛选。参数: status (状态, 可选), owner (负责人名称, 可选)',
            parameters={'type': 'object', 'properties': {
                'status': {'type': 'string', 'description': '筛选状态（可选）'},
                'owner': {'type': 'string', 'description': '筛选负责人（可选）'},
            }},
            tool=self._list_tasks,
        )
        self._update_task_tool = Tool(name='update_task', source=_ln, event_bus=event_bus,
            description='更新任务状态。参数: task_id (任务ID), status (新状态), result (执行结果, 可选), error (错误信息, 可选)',
            parameters={'type': 'object', 'properties': {
                'task_id': {'type': 'string', 'description': '任务ID'},
                'status': {'type': 'string', 'description': '新状态: created/assigned/in_progress/completed/failed'},
                'result': {'type': 'string', 'description': '执行结果（可选）'},
                'error': {'type': 'string', 'description': '错误信息（可选）'},
            }, 'required': ['task_id', 'status']},
            tool=self._update_task,
        )
        self._send_message_tool = Tool(name='send_message', source=_ln, event_bus=event_bus,
            description='向同团队的其他成员发送消息并等待回复，用于成员间协作沟通。参数: member_name (目标成员名称), message (消息内容)',
            parameters={'type': 'object', 'properties': {
                'member_name': {'type': 'string', 'description': '目标成员名称'},
                'message': {'type': 'string', 'description': '消息内容'},
            }, 'required': ['member_name', 'message']},
            tool=self._send_message,
        )

        self._leader = Agent(
            event_bus=event_bus,
            name=leader.name, provider=leader.provider or self._provider, model=leader.model or self._model,
            instruction=leader.instruction, stream=leader.stream,
            thinking=leader.thinking, tools=leader.tools,
            skills=leader.skills, http_options=leader.http_options,
        )
        # 永久注入 Leader 管理工具，不再运行时临时注入
        self._inject_leader_tools()

        self._members: list[Agent | Team] = []
        if members:
            for m in members:
                if isinstance(m, AgentConfig):
                    agent = Agent(
                        event_bus=event_bus,
                        name=m.name, provider=m.provider or self._provider, model=m.model or self._model,
                        instruction=m.instruction, stream=m.stream,
                        thinking=m.thinking, tools=m.tools,
                        skills=m.skills, http_options=m.http_options,
                    )
                    self._inject_agent_tools(agent)
                    self._members.append(agent)
                else:
                    self._members.append(Team(
                        name=m.name, event_bus=event_bus,
                        leader=m.leader, members=m.members,
                        provider=self._provider, model=self._model,
                    ))

    @property
    def leader(self) -> Agent:
        return self._leader

    def _emit(self, topic: str, data: dict = None):
        self._bus.emit(topic, data or {}, source=self._name)

    def _on_message(self, action: Action) -> str:
        if action.type in ('chat', 'task_assigned', 'peer_message'):
            return self._handle_supervise(action.payload)
        raise ValueError(f"Unknown action type: {action.type}")

    def start(self):
        Actor.start(self)
        self._leader.start()
        for m in self._members:
            m.start()

    def stop(self, timeout: float = 5.0):
        for m in self._members:
            m.stop(timeout=0)
        self._leader.stop(timeout=0)
        Actor.stop(self, timeout=timeout)

    @property
    def members(self) -> list[Agent]:
        return [
            m if isinstance(m, Agent) else m.leader
            for m in self._members
        ]

    @property
    def is_leaf(self) -> bool:
        return all(isinstance(m, Agent) for m in self._members)

    def add_member(self, config: AgentConfig | TeamConfig):
        if self._members:
            existing_is_agent = isinstance(self._members[0], Agent)
            if isinstance(config, AgentConfig) != existing_is_agent:
                raise TypeError("不能混合添加 Agent 和 Team 成员")
        if isinstance(config, AgentConfig):
            agent = Agent(
                event_bus=self._bus,
                name=config.name, provider=config.provider or self._provider, model=config.model or self._model,
                instruction=config.instruction, stream=config.stream,
                thinking=config.thinking, tools=config.tools,
                skills=config.skills, http_options=config.http_options,
            )
            self._inject_agent_tools(agent)
            self._members.append(agent)
        else:
            self._members.append(Team(
                name=config.name, event_bus=self._bus,
                leader=config.leader, members=config.members,
                provider=self._provider, model=self._model,
            ))

    def find_member(self, name: str) -> Agent | None:
        if self._leader.name == name:
            return self._leader
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

    # ---- Task management tools ----

    def _create_task(self, description: str, depends_on: list[str] = None) -> str:
        task = Task(description=description, depends_on=depends_on or [])
        self._tasks[task.id] = task
        self._emit('team:step', {'name': self._name, 'content': f'created task {task.id}: {description}'})
        return f"任务已创建。ID: {task.id}, 描述: {description}, 状态: {task.status.value}"

    def _get_task(self, task_id: str) -> str:
        task = self._tasks.get(task_id)
        if not task:
            return f"错误：未找到任务 '{task_id}'"
        deps = f", 依赖: {task.depends_on}" if task.depends_on else ""
        result = f", 结果: {task.result}" if task.result else ""
        return (f"任务 {task.id}: {task.description} | 状态: {task.status.value}"
                f" | 负责人: {task.owner or '未分配'}{deps}{result}")

    def _list_tasks(self, status: str = None, owner: str = None) -> str:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        if owner:
            tasks = [t for t in tasks if t.owner == owner]
        if not tasks:
            return "暂无任务"
        lines = [f"共 {len(tasks)} 个任务:"]
        for t in tasks:
            deps = f" [依赖: {t.depends_on}]" if t.depends_on else ""
            lines.append(f"  - {t.id}: {t.description} ({t.status.value}) {t.owner}{deps}")
        return '\n'.join(lines)

    def _update_task(self, task_id: str, status: str, result: str = None, error: str = None) -> str:
        task = self._tasks.get(task_id)
        if not task:
            return f"错误：未找到任务 '{task_id}'"
        try:
            task.status = TaskStatus(status)
        except ValueError:
            return f"错误：无效的状态 '{status}'"
        task.updated_at = time.time()
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        self._emit('team:step', {'name': self._name, 'content': f'task {task_id} -> {status}'})
        return f"任务 {task_id} 状态已更新为 {status}"

    # ---- Agent-to-Agent communication ----

    def _send_message(self, member_name: str, message: str) -> str:
        target = self.find_member(member_name)
        if not target:
            return f"错误：未找到成员 '{member_name}'"
        caller = self._current_caller or self._leader.name
        if member_name == caller:
            return f"错误：不能给自己发送消息，请指定其他成员名称"

        # 如果目标正在等待回复，此消息视为回复，直接放入目标回复队列
        if member_name in self._pending_replies:
            other_reply = self._pending_replies.pop(member_name)
            other_reply.put(message)
            return f"回复已发送给 {member_name}"

        self._emit('team:step', {
            'name': self._name,
            'content': f'peer_message {caller} -> {member_name}',
        })

        # 新消息：创建回复队列，将消息放入目标 mailbox 并等待回复
        reply_queue = Queue()
        self._pending_replies[caller] = reply_queue
        prev_caller = self._current_caller
        self._current_caller = member_name
        action = Action(
            type='peer_message',
            payload=f"[{caller} -> {member_name}] {message}",
        )
        target._mailbox.put((action, reply_queue))
        try:
            result = reply_queue.get()
            return self._coerce_str(result)
        finally:
            self._pending_replies.pop(caller, None)
            self._current_caller = prev_caller

    # ---- Internal methods ----

    def _coerce_str(self, result) -> str:
        if hasattr(result, '__iter__') and not isinstance(result, str):
            return ''.join(result)
        return str(result) if result else ""

    def _handle_supervise(self, message: str) -> str:
        self._emit('team:start', {'name': self._name, 'message': message, 'mode': 'supervisor'})
        self._current_caller = self._leader.name
        try:
            result = self._leader.chat(message)
            content = self._coerce_str(result)
            self._emit('team:end', {'name': self._name, 'content': content, 'mode': 'supervisor'})
            return content
        finally:
            self._current_caller = ""

    def _assign_task(self, task_id: str, member_name: str) -> str:
        task = self._tasks.get(task_id)
        if not task:
            return f"错误：未找到任务 '{task_id}'"
        if task.depends_on:
            for dep_id in task.depends_on:
                dep = self._tasks.get(dep_id)
                if not dep or dep.status != TaskStatus.COMPLETED:
                    return f"错误：依赖任务 '{dep_id}' 未完成"
        target = self.find_member(member_name)
        if not target:
            return f"错误：未找到成员 '{member_name}'"
        task.owner = member_name
        task.status = TaskStatus.ASSIGNED
        task.updated_at = time.time()
        self._emit('team:step', {'name': self._name, 'content': f'assign_task {task_id} to {member_name}'})
        prev_caller = self._current_caller
        self._current_caller = member_name
        try:
            result = target.chat(
                f"任务ID: {task_id}\n描述: {task.description}\n请执行此任务并报告结果。",
                action_type='task_assigned',
            )
            result_str = self._coerce_str(result)
            task.status = TaskStatus.COMPLETED
            task.result = result_str
            task.updated_at = time.time()
            self._emit('team:step', {'name': self._name, 'content': f'task {task_id} completed by {member_name}'})
            return f"任务 {task_id} 已完成。结果: {result_str}"
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.updated_at = time.time()
            return f"错误：成员 '{member_name}' 执行任务时出错: {e}"
        finally:
            self._current_caller = prev_caller

    def _spawn_agent(self, name: str, instruction: str, model: str = None) -> str:
        if not self._resource_pool.can_spawn_agent():
            return f"错误：Agent 资源已耗尽（已使用 {self._resource_pool.used_agents}/{self._resource_pool.max_agents}）"
        agent = Agent(
            event_bus=self._bus,
            name=name, provider=self._leader.provider,
            model=model or self._leader.model,
            instruction=instruction,
        )
        self._inject_agent_tools(agent)
        self._resource_pool.used_agents += 1
        self._members.append(agent)
        agent.start()
        self._emit('team:step', {'name': self._name, 'content': f'spawned agent {name}'})
        return f"成功创建 Agent '{name}'"

    def _create_team(self, name: str, leader_name: str, leader_instruction: str) -> str:
        if not self._resource_pool.can_spawn_team():
            return f"错误：Team 资源已耗尽（已使用 {self._resource_pool.used_teams}/{self._resource_pool.max_teams}）"
        leader_cfg = AgentConfig(
            name=leader_name, provider=self._leader.provider,
            model=self._leader.model, instruction=leader_instruction,
        )
        team = Team(
            name=name, event_bus=self._bus, leader=leader_cfg,
            resource_pool=self._resource_pool,
        )
        self._resource_pool.used_teams += 1
        self._members.append(team)
        team.start()
        self._emit('team:step', {'name': self._name, 'content': f'created team {name}'})
        return f"成功创建 Team '{name}'，负责人 '{leader_name}'"

    def _agent_tools(self) -> list[Tool]:
        """Agent 可用的工具列表（包括 Leader 和普通成员）。"""
        return [
            self._update_task_tool,
            self._send_message_tool,
        ]

    def _inject_agent_tools(self, agent: Agent):
        """将公共工具注入到 Agent 中。"""
        common = self._agent_tools()
        if agent.tools:
            agent.tools = Tools(*agent.tools, *common)
        else:
            agent.tools = Tools(*common)

    def _inject_leader_tools(self):
        """将 Leader 管理工具永久注入到 Leader 中。"""
        org_tools = [
            self._assign_tool, self._spawn_tool, self._create_team_tool,
            self._create_task_tool, self._get_task_tool, self._list_tasks_tool,
            self._update_task_tool, self._send_message_tool,
        ]
        if self._leader.tools:
            self._leader.tools = Tools(*self._leader.tools, *org_tools)
        else:
            self._leader.tools = Tools(*org_tools)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()