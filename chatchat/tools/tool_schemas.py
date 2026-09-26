from chatchat.knowledge.skills import listing_budget
from chatchat.runtime.structured import STRUCTURED_OUTPUT_TOOL
from chatchat.tool import ToolContext, describe_tools

class TeamSchemasMixin:
    def tool_schemas(self, context: ToolContext) -> list[dict]:
        team_tools = [
            {'name': 'Agent',
             'description': self._create_agent_description(),
             'input_schema': {'type': 'object',
                              'properties': {'prompt': {'type': 'string'},
                                             'instruction': {'type': 'string'},
                                             'subagent_type': {'type': 'string'},
                                             'name': {'type': 'string',
                                                      'description': 'Optional '
                                                      'name for a persistent '
                                                      'teammate (team mode): '
                                                      'stays alive with a '
                                                      'mailbox; message it via '
                                                      'SendMessage. Omit for '
                                                      'a one-off sub-agent.'},
                                             'model': {'type': 'string',
                                                       'description': 'Optional '
                                                       'model override for the '
                                                       'spawned agent.'},
                                             'run_in_background': {
                                                 'type': 'boolean',
                                                 'description': 'Set true for a '
                                                 'one-off sub-agent whose work '
                                                 'should not hold this turn '
                                                 'open. The answer arrives in '
                                                 'your inbox when it finishes.'}},
                              'required': ['prompt']}},
        ]
        if self.multi_agent:
            team_tools += [
                {'name': 'SendMessage',
                 'description': 'Send a message to a teammate by name (or "*" to '
                                'broadcast). Messages are delivered to their mailbox '
                                'and injected on their next idle turn.',
                 'input_schema': {'type': 'object',
                                  'properties': {'to': {'type': 'string'},
                                                 'message': {'type': 'string'}},
                                  'required': ['to', 'message']}},
                {'name': 'TaskOutput',
                 'description': 'Read what a background task has produced: a '
                                'background shell command\'s output, or a '
                                'sub-agent\'s answer. Waits for the task by '
                                'default, so a timeout report means it is '
                                'still running.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'task_id': {'type': 'string'},
                                      'block': {'type': 'boolean'},
                                      'timeout': {'type': 'integer'}},
                                  'required': ['task_id']}},
                {'name': 'TaskStop',
                 'description': 'Permanently stop a background task or one of '
                                'your own sub-agents, by its task id.',
                 'input_schema': {'type': 'object',
                                  'properties': {'task_id': {'type': 'string'}},
                                  'required': ['task_id']}},
                {'name': 'TeamCreate',
                 'description': 'Gather the work under one named team. The '
                                'team and its task list are the same thing: '
                                'every task you create from now on belongs to '
                                'it, and so does every teammate you spawn. '
                                'Call it once, before the work is divided.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'team_name': {'type': 'string'},
                                      'description': {'type': 'string'}},
                                  'required': ['team_name']}},
                {'name': 'TeamDelete',
                 'description': 'Throw away the current team and its task list '
                                'once the work is done. It refuses while a '
                                'teammate is still running, so stop them '
                                'first with TaskStop.',
                 'input_schema': {'type': 'object', 'properties': {}}},
            ]
        if self.tasks is not None:
            team_tools += [
                {'name': 'TaskCreate',
                 'description': 'Add a task to the team list so the work is '
                                'tracked and claimable. Use it for anything '
                                'with more than one step; give a short '
                                'imperative subject and the full description.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'subject': {'type': 'string'},
                                      'description': {'type': 'string'},
                                      'active_form': {
                                          'type': 'string',
                                          'description': 'Present continuous '
                                          'label shown while it is running'},
                                      'metadata': {'type': 'object'}},
                 'required': ['subject', 'description']}},
                {'name': 'TaskList',
                 'description': 'List every task with its status, owner and '
                                'open blockers. Check it before creating so '
                                'work is not duplicated.',
                 'input_schema': {'type': 'object', 'properties': {}}},
                {'name': 'TaskGet',
                 'description': 'Read one task in full.',
                 'input_schema': {'type': 'object',
                                  'properties': {'task_id': {'type': 'string'}},
                                  'required': ['task_id']}},
                {'name': 'TaskUpdate',
                 'description': 'Change a task: move it through pending, '
                                'in_progress and completed, hand it to an '
                                'owner, or link it with add_blocks / '
                                'add_blocked_by. status "deleted" removes it. '
                                'Mark a task in_progress before starting it.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'task_id': {'type': 'string'},
                                      'subject': {'type': 'string'},
                                      'description': {'type': 'string'},
                                      'active_form': {'type': 'string'},
                                      'status': {'type': 'string',
                                                 'enum': ['pending',
                                                          'in_progress',
                                                          'completed',
                                                          'deleted']},
                                      'owner': {'type': 'string'},
                                      'metadata': {'type': 'object'},
                                      'add_blocks': {'type': 'array',
                                                     'items': {
                                                         'type': 'string'}},
                                      'add_blocked_by': {'type': 'array',
                                                         'items': {
                                                             'type': 'string'}}},
                                  'required': ['task_id']}},
            ]
        if self.ask_user is not None:
            team_tools += [
                {'name': 'EnterPlanMode',
                 'description': 'Ask to switch this session into plan mode '
                                'before starting anything but a trivial '
                                'change. In plan mode nothing that writes or '
                                'changes state runs, so you can explore and '
                                'design the approach and have it approved '
                                'before touching the project.',
                 'input_schema': {'type': 'object', 'properties': {}}},
                {'name': 'ExitPlanMode',
                 'description': 'Present the plan you wrote to the user and '
                                'leave plan mode once they approve it.',
                 'input_schema': {'type': 'object', 'properties': {}}},
            ]
            team_tools.append(
                {'name': 'AskUserQuestion',
                 'description': 'Ask the human one to four questions and wait '
                                'for the answers, when a choice they can make '
                                'would change what you do. Give each question '
                                'two to four options worth picking; they can '
                                'also answer in their own words. When they '
                                'have to compare concrete results, put the '
                                'artifact on the option as preview.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'questions': {
                                          'type': 'array',
                                          'items': {
                                              'type': 'object',
                                              'properties': {
                                                  'question': {'type': 'string'},
                                                  'header': {'type': 'string'},
                                                  'multiSelect': {
                                                      'type': 'boolean'},
                                                  'options': {
                                                      'type': 'array',
                                                      'items': {
                                                          'type': 'object',
                                                          'properties': {
                                                              'label': {
                                                                  'type': 'string'},
                                                              'description': {
                                                                  'type': 'string'},
                                                              'preview': {
                                                                  'type': 'string',
                                                                  'description': 'The artifact this option would produce, shown beside the options while it is picked. Use it when the user has to compare concrete results, not for a plain preference. Only single-select questions show previews.'}},
                                                          'required': ['label']}}},
                                              'required': ['question',
                                                          'options']}}},
                                  'required': ['questions']}})
        if self.can_worktree:
            team_tools += [
                {'name': 'EnterWorktree',
                 'description': 'Only when the user asks for a worktree: make '
                                'an isolated git worktree under '
                                '.pyclaw/worktrees and move this session into '
                                'it, so the work cannot touch the checked-out '
                                'directory. Needs a git repository or '
                                'WorktreeCreate/WorktreeRemove hooks, and not '
                                'already be in one. A worktree of that name '
                                'that is still on disk is entered again rather '
                                'than recreated.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'name': {'type': 'string',
                                               'description': 'Optional. '
                                                              'Letters, digits, '
                                                              'dots, dashes and '
                                                              'underscores, '
                                                              'divided by "/"; '
                                                              'up to 64 '
                                                              'characters. A '
                                                              'readable name is '
                                                              'picked when it '
                                                              'is left out, and '
                                                              'this session '
                                                              'keeps using '
                                                              'it.'}}}},
                {'name': 'ExitWorktree',
                 'description': 'Leave the worktree this session moved into, '
                                'back to the original directory. Only worktrees '
                                'this session entered; one made by hand or in '
                                'another conversation is left alone. action '
                                '"keep" leaves the directory and its branch on '
                                'disk, "remove" deletes both. remove refuses '
                                'while the worktree holds uncommitted files or '
                                'commits of its own.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'action': {'type': 'string',
                                                 'enum': ['keep', 'remove']},
                                      'discard_changes': {
                                          'type': 'boolean',
                                          'description': 'Only with "remove": '
                                                         'throw away the '
                                                         'uncommitted files and '
                                                         'the commits no branch '
                                                         'else has. Ask the '
                                                         'user first.'}},
                                  'required': ['action']}},
            ]
        skills = self.skills.for_model()
        if skills:
            team_tools.append(
                {'name': 'Skill',
                 'description': 'Load the full instructions of one skill when '
                                'the task at hand is one it covers. The '
                                'listing below only says what each skill is '
                                'for; the steps come from this call.\n\n'
                                'Available skills:\n'
                                + self.skills.listing(
                                    listing_budget(self.context_window)),
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'skill': {'type': 'string',
                                                'description': 'The name from '
                                                               'the listing.'},
                                      'args': {'type': 'string',
                                               'description': 'What the skill '
                                                              'should work on.'}},
                                  'required': ['skill']}})
        if self.cron is not None:
            team_tools += [
                {'name': 'CronCreate',
                 'description': 'Schedule a prompt to be enqueued at a cron '
                                'time. Five fields, local time: minute hour '
                                'day-of-month month day-of-week. A recurring job fires on every match '
                                'until deleted; a one-shot fires at the next '
                                'match and then disappears. durable keeps it '
                                'in the project across restarts.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'cron': {'type': 'string'},
                                      'prompt': {'type': 'string'},
                                      'recurring': {'type': 'boolean'},
                                      'durable': {'type': 'boolean'}},
                                  'required': ['cron', 'prompt']}},
                {'name': 'CronList',
                 'description': 'Show every scheduled prompt with its id, '
                                'schedule and whether it is durable.',
                 'input_schema': {'type': 'object', 'properties': {}}},
                {'name': 'CronDelete',
                 'description': 'Cancel a scheduled prompt by its id.',
                 'input_schema': {'type': 'object',
                                  'properties': {'id': {'type': 'string'}},
                                  'required': ['id']}},
            ]
        if self.output_schema is not None:
            team_tools.append(
                {'name': STRUCTURED_OUTPUT_TOOL,
                 'description': 'Return your final answer as the structured '
                                'payload below. Call it exactly once, at the '
                                'end of the work; nothing you say in prose '
                                'counts as the answer.\n\nThe payload must '
                                'match this schema.',
                 'input_schema': self.output_schema})
        names = {tool['name'] for tool in team_tools}
        return team_tools + [tool for tool in
                             describe_tools(self._injected_tools, context)
                             if tool['name'] not in names]
