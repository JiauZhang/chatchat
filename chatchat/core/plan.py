from __future__ import annotations

import os
from pathlib import Path

ENTER_TEXT = (
    'Entered plan mode. Explore the codebase and design the approach first: '
    'no write or state-changing tool runs until the plan is approved. Write '
    'the plan to {path}, then call ExitPlanMode to present it.')

APPROVE = 'Yes, implement it'

AUTO_ACCEPT = 'Yes, and apply the edits without asking'

KEEP_PLANNING = 'No, keep planning'


def plans_dir() -> Path:
    home = (os.environ.get('CHATCHAT_HOME')
            or os.environ.get('PYCLAW_HOME') or '~/.pyclaw')
    return Path(home).expanduser() / 'plans'


def plan_file(team) -> Path:
    override = getattr(team, 'plan_path', None)
    return Path(override) if override else plans_dir() / f'{team.name}.md'


def read_plan(team) -> str:
    try:
        return plan_file(team).read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def plan_question() -> dict:
    return {'question': 'Approve this plan?',
            'header': 'Plan',
            'options': [{'label': APPROVE,
                         'description': 'Leave plan mode and start implementing.'},
                        {'label': AUTO_ACCEPT,
                         'description': 'Leave plan mode; file edits run '
                                        'without asking.'},
                        {'label': KEEP_PLANNING,
                         'description': 'Stay in plan mode.'}]}
