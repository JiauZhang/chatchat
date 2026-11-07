"""Closed sets live in one enum, so a value cannot drift between modules."""

from chatchat.runtime.agent_memory import AgentMemory
from chatchat.runtime.enums import CompletionStatus, IdleReason, MemoryScope, MessageType
from chatchat.tasks.enums import ClaimReason, TaskAction, TaskRunStatus, TaskRunType, TaskStatus
from chatchat.tasks.task_list import TaskList
from chatchat.tools.builtin.tasks import task_update


ENUMS = (
    TaskStatus,
    TaskRunStatus,
    TaskRunType,
    TaskAction,
    ClaimReason,
    MemoryScope,
    IdleReason,
    CompletionStatus,
    MessageType,
)


def test_every_enum_has_one_value_per_member():
    for enum in ENUMS:
        values = tuple(member.value for member in enum)
        assert len(values) == len(enum)
        assert all(isinstance(value, str) and value for value in values)


def test_task_status_and_task_run_status_are_not_the_same_set():
    assert set(TaskStatus.values()) != set(TaskRunStatus.values())
    assert "in_progress" in TaskStatus.values()
    assert "running" in TaskRunStatus.values()


def test_the_task_update_schema_takes_its_values_from_the_enum():
    assert task_update.parameters["properties"]["status"]["enum"] == list(TaskAction.values())


def test_an_unknown_memory_scope_is_refused_by_name(tmp_path):
    memory = AgentMemory(roots={"user": tmp_path})
    try:
        memory.directory("reviewer", "galaxy")
    except ValueError as exc:
        assert "galaxy" in str(exc)
    else:
        raise AssertionError("an unknown scope should not resolve to a directory")


def test_an_unknown_status_on_disk_falls_back_to_pending(tmp_path):
    tasks = TaskList(tmp_path / "tasks")
    tasks.directory.mkdir(parents=True)
    (tasks.directory / "1.json").write_text('{"id": "1", "subject": "s", "description": "d", "status": "galaxy"}')
    assert tasks.get("1").status == TaskStatus.PENDING


def test_claim_reasons_are_the_enum_members(tmp_path):
    tasks = TaskList(tmp_path / "tasks2")
    claim = tasks.claim("missing", "worker")
    assert claim.reason == ClaimReason.TASK_NOT_FOUND
