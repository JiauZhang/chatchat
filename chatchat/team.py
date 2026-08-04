from __future__ import annotations
import threading
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any

from chatchat.worker import Worker, WorkerConfig
from chatchat.tool import Tool
from chatchat.message import ID, Message


@dataclass
class TeamConfig:
    name: str
    leader: WorkerConfig
    members: list[WorkerConfig | TeamConfig] | None = None


class Team(Worker):
    def __init__(self, config: TeamConfig, scheduler):
        Worker.__init__(self, WorkerConfig(name=config.name), scheduler)
        self.id = ID(uid=config.name, kind='team', name=config.name)

        self._leader = Worker(config.leader, scheduler)
        scheduler.register(self._leader)
        self._members: list[Worker | Team] = []

        for m in (config.members or []):
            self._add_member_entry(m)

        self._init_leader_tools()
        for t in self._leader_tools:
            self._leader._add_tool(t)

    def _add_member_entry(self, cfg):
        if isinstance(cfg, WorkerConfig):
            worker = Worker(cfg, self.scheduler)
            self.scheduler.register(worker)
            self._members.append(worker)
        else:
            team = Team(cfg, self.scheduler)
            self.scheduler.register(team)
            self._members.append(team)

    def _init_leader_tools(self):
        def T(name, description, tool_func, properties=None, required=None):
            return Tool(
                name=name, source=self._leader.name, event_bus=None,
                description=description, tool=tool_func,
                parameters={'type': 'object', 'properties': properties or {}, 'required': required or []} if properties else None,
            )
        self._leader_tools = [
            T('list_members', '查看当前团队所有可用成员。', self._list_members),
            T('send_msg', '向成员发送消息。参数: member_name, message, blocking(可选)', self._send_msg,
              {'member_name': {'type': 'string'}, 'message': {'type': 'string'}, 'blocking': {'type': 'boolean', 'description': '是否等待回复（默认 false）'}},
              ['member_name', 'message']),
            T('assign_task', '分配任务给成员。参数: task_id, description, member_name', self._assign_task,
              {'task_id': {'type': 'string'}, 'description': {'type': 'string'}, 'member_name': {'type': 'string'}},
              ['task_id', 'description', 'member_name']),
            T('create_agent', '创建一个新的 Agent 成员并加入团队。参数: name, instruction, model(可选)', self._create_agent,
              {'name': {'type': 'string'}, 'instruction': {'type': 'string'}, 'model': {'type': 'string', 'description': '模型名（可选）'}},
              ['name', 'instruction']),
            T('create_team', '创建一个新的子 Team 并加入团队。参数: name, leader_name, leader_instruction', self._create_team,
              {'name': {'type': 'string'}, 'leader_name': {'type': 'string'}, 'leader_instruction': {'type': 'string'}},
              ['name', 'leader_name', 'leader_instruction']),
        ]

    def find_member(self, name: str) -> Worker | None:
        if self._leader.name == name:
            return self._leader
        for m in self._members:
            if m.name == name:
                return m
            if isinstance(m, Team):
                found = m.find_member(name)
                if found:
                    return found
        return None

    @property
    def leader(self) -> Worker:
        return self._leader

    @property
    def members(self) -> list[Worker]:
        result = []
        for m in self._members:
            if isinstance(m, Team):
                result.append(m.leader)
            else:
                result.append(m)
        return result

    def handle_message(self, msg: Message) -> Any:
        if msg.type == 'text':
            return self._leader.handle_message(msg)
        if msg.type == 'signal':
            for m in self._members:
                s = self.scheduler
                s.send(Message(sender=self.id, recipient=m.id, type='signal', subtype=msg.subtype))
            return self._leader.handle_message(msg)
        if msg.type == 'request':
            if msg.subtype == 'list_members':
                names = [m.name for m in self._members]
                if isinstance(self._leader, Worker):
                    names.insert(0, self._leader.name)
                return {'members': names}
            if msg.subtype == 'status':
                return {
                    'name': self.id.name,
                    'leader': self._leader.name,
                    'member_count': len(self._members),
                }
        return None

    def start(self):
        Worker.start(self)
        self._leader.start()
        for m in self._members:
            m.start()

    def stop(self, timeout: float = 2.0):
        for m in self._members:
            m.stop(timeout=0)
        self._leader.stop(timeout=0)
        Worker.stop(self, timeout=timeout)

    def add_member(self, config: WorkerConfig | TeamConfig):
        self._add_member_entry(config)
        if isinstance(config, WorkerConfig):
            self._members[-1].start()

    def _list_members(self) -> str:
        if not self._members:
            return '暂无成员'
        lines = [f'当前团队 ({self.id.name}): 负责人 {self._leader.name}']
        for m in self._members:
            if isinstance(m, Team):
                lines.append(f'  - Team({m.id.name}): {m.leader.name}')
            else:
                lines.append(f'  - {m.name}')
        return '\n'.join(lines)

    def _send_msg(self, member_name: str, message: str, blocking: bool = False) -> str:
        target = self.find_member(member_name)
        if not target:
            return f'错误：未找到成员 "{member_name}"'
        msg = Message(sender=self._leader.id, recipient=target.id, type='text', payload=message)
        if blocking:
            try:
                reply = self.scheduler.request(msg, timeout=30)
                return f'来自 {member_name} 的回复: {reply.payload}'
            except Exception as e:
                return f'等待 {member_name} 回复超时: {e}'
        self.scheduler.send(msg)
        return f'消息已发送给 {member_name}'

    def _assign_task(self, task_id: str, description: str, member_name: str) -> str:
        target = self.find_member(member_name)
        if not target:
            return f'错误：未找到成员 "{member_name}"'
        msg = Message(
            sender=self._leader.id,
            recipient=target.id,
            type='text',
            payload=f'你被分配了一个新任务:\ntask_id: {task_id}\n描述: {description}\n请执行此任务。',
        )
        self.scheduler.send(msg)
        return f'任务 {task_id} 已分配给 {member_name}'

    def _create_agent(self, name: str, instruction: str, model: str = None) -> str:
        provider = self._leader._agent.provider if self._leader._agent else None
        model = model or (self._leader._agent.model if self._leader._agent else None)
        cfg = WorkerConfig(name=name, provider=provider, model=model, instruction=instruction)
        worker = Worker(cfg, self.scheduler)
        self.scheduler.register(worker)
        self._members.append(worker)
        worker.start()
        return f'成功创建 Agent "{name}"'

    def _create_team(self, name: str, leader_name: str, leader_instruction: str) -> str:
        provider = self._leader._agent.provider if self._leader._agent else None
        model = self._leader._agent.model if self._leader._agent else None
        leader_cfg = WorkerConfig(name=leader_name, provider=provider, model=model, instruction=leader_instruction)
        team = Team(TeamConfig(name=name, leader=leader_cfg), self.scheduler)
        self.scheduler.register(team)
        self._members.append(team)
        team.start()
        return f'成功创建 Team "{name}"，负责人 "{leader_name}"'