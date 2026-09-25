from __future__ import annotations

import dataclasses
import os

MODES = ('off', 'on', 'adaptive')

LEVELS = ('low', 'medium', 'high')

BUDGET_ENV = 'MAX_THINKING_TOKENS'


@dataclasses.dataclass(frozen=True)
class Thinking:
    mode: str = 'on'
    budget: int = 0
    effort: str = ''

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f'thinking mode must be one of {MODES}, '
                             f'not {self.mode!r}')
        if self.effort and self.effort not in LEVELS:
            raise ValueError(f'effort must be one of {LEVELS} or empty, '
                             f'not {self.effort!r}')
        if int(self.budget) < 0:
            raise ValueError('a thinking budget cannot be negative')

    @classmethod
    def from_env(cls, mode: str | None = None, budget: int | None = None,
                 effort: str = '') -> 'Thinking':
        raw = os.environ.get(BUDGET_ENV)
        if budget is None:
            budget = int(raw) if raw and raw.isdigit() else 0
        if mode is None:
            mode = 'off' if str(raw or '') == '0' else 'on'
        return cls(mode=mode, budget=budget, effort=effort)

    @property
    def enabled(self) -> bool:
        return self.mode != 'off'

    def request(self) -> dict:
        payload: dict = {}
        if self.mode == 'off':
            payload['thinking'] = {'type': 'disabled'}
        elif self.mode == 'adaptive':
            payload['thinking'] = {'type': 'adaptive'}
        elif self.budget:
            payload['thinking'] = {'type': 'enabled',
                                   'budget_tokens': self.budget}
        else:
            payload['thinking'] = {'type': 'enabled'}
        if self.effort and self.mode != 'off':
            payload['reasoning_effort'] = self.effort
        return payload

    def label(self) -> str:
        if self.mode == 'off':
            return 'thinking off'
        part = (f'{self.budget}' if self.mode == 'on' and self.budget
                else self.mode)
        return f'thinking {part}' + (f' \u00b7 effort {self.effort}'
                                     if self.effort else '')
