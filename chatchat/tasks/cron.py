from __future__ import annotations

from datetime import datetime, timedelta

RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))

FIELDS = ('minute', 'hour', 'day_of_month', 'month', 'day_of_week')

MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
          'Oct', 'Nov', 'Dec')

DAYS = ('Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat')

MINUTES = list(range(60))

HOURS = list(range(24))

MONTH_DAYS = list(range(1, 32))

MONTH_NUMBERS = list(range(1, 13))

WEEK = list(range(7))

DAYS_AHEAD = 366


def _integer(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _part(text: str, low: int, high: int) -> list[int] | None:
    sunday = (low, high) == (0, 6)

    def legal(value: int) -> bool:
        return low <= value <= (7 if sunday else high)

    def normal(value: int) -> int:
        return 0 if sunday and value == 7 else value

    if text == '*':
        return list(range(low, high + 1))
    if text.startswith('*/'):
        step = _integer(text[2:])
        if step is None or step < 1:
            return None
        return list(range(low, high + 1, step))
    head, _, tail = text.partition('-')
    if tail:
        first, last = _integer(head), _integer(tail.split('/')[0])
        if first is None or last is None or not legal(first) or not legal(last):
            return None
        if first > last:
            return None
        step = 1
        if '/' in tail:
            step = _integer(tail.split('/')[1])
            if step is None or step < 1:
                return None
        return sorted({normal(value)
                       for value in range(first, last + 1, step)})
    value = _integer(text)
    if value is None or not legal(value):
        return None
    return [normal(value)]


def _field(text: str, low: int, high: int) -> list[int] | None:
    values: set[int] = set()
    for part in text.split(','):
        expanded = _part(part, low, high) if part else None
        if expanded is None:
            return None
        values.update(expanded)
    return sorted(values) if values else None


def parse(expression: str) -> dict | None:
    parts = str(expression or '').split()
    if len(parts) != 5:
        return None
    expanded = []
    for text, (low, high) in zip(parts, RANGES):
        values = _field(text, low, high)
        if values is None:
            return None
        expanded.append(values)
    return dict(zip(FIELDS, expanded))


def _day_matches(fields: dict, day: datetime, dom_pinned: bool,
                 dow_pinned: bool) -> bool:
    if day.month not in fields['month']:
        return False
    by_month = day.day in fields['day_of_month']
    by_week = (day.weekday() + 1) % 7 in fields['day_of_week']
    if dom_pinned and dow_pinned:
        return by_month or by_week
    if dom_pinned:
        return by_month
    if dow_pinned:
        return by_week
    return True


def next_run(fields: dict, after: datetime) -> datetime | None:
    dom_pinned = len(fields['day_of_month']) < len(MONTH_DAYS)
    dow_pinned = len(fields['day_of_week']) < len(WEEK)
    day = after.replace(hour=0, minute=0, second=0, microsecond=0)
    limit = after + timedelta(days=DAYS_AHEAD)
    for _ in range(DAYS_AHEAD + 1):
        if _day_matches(fields, day, dom_pinned, dow_pinned):
            for hour in fields['hour']:
                for minute in fields['minute']:
                    when = day.replace(hour=hour, minute=minute)
                    if after < when <= limit:
                        return when
        day += timedelta(days=1)
    return None


def _step(values: list[int]) -> int | None:
    if len(values) < 2:
        return None
    step = values[1] - values[0]
    if step < 1 or values != list(range(values[0], values[-1] + 1, step)):
        return None
    return step


def _numbers(values: list[int], offset: int = 0) -> str:
    return ', '.join(str(value + offset) for value in values)


def _names(values: list[int], table, offset: int = 0) -> str:
    return ', '.join(table[value - offset] for value in values)


def _short(values: list[int], full: list[int]) -> bool:
    return len(values) < len(full)


def _at(minutes: list[int], hours: list[int]) -> str:
    if not _short(minutes, MINUTES) and not _short(hours, HOURS):
        return ''
    clock = (_numbers(hours) if _short(hours, HOURS)
             else f'{hours[0]:02d}')
    if _short(minutes, MINUTES):
        if len(minutes) == 1 and len(hours) == 1:
            clock = f'{hours[0]:02d}:{minutes[0]:02d}'
        else:
            clock = f'{clock}:{_numbers(minutes)}'
    else:
        clock = f'{clock}:00'
    return f' at {clock}'


def human(expression: str) -> str:
    fields = parse(expression)
    if fields is None:
        return str(expression)
    minutes, hours = fields['minute'], fields['hour']
    dom, month, dow = (fields['day_of_month'], fields['month'],
                       fields['day_of_week'])
    every = (_short(month, MONTH_NUMBERS)
             or _short(dom, MONTH_DAYS) or _short(dow, WEEK))
    when = _at(minutes, hours)
    if not every:
        if not _short(minutes, MINUTES) and not _short(hours, HOURS):
            return 'every minute'
        step = _step(minutes)
        if step and not _short(hours, HOURS):
            return f'every {step} minutes' if step > 1 else 'every minute'
        if not _short(hours, HOURS):
            return f'every hour{when}'
        return f'every day{when}'
    if _short(month, MONTH_NUMBERS):
        days = _numbers(dom) if _short(dom, MONTH_DAYS) else 'every day'
        return (f'every year on {_names(month, MONTHS, 1)} {days}{when}')
    if _short(dom, MONTH_DAYS) and _short(dow, WEEK):
        return (f'monthly on {_numbers(dom)}, or every '
                f'{_names(dow, DAYS)}{when}')
    if _short(dom, MONTH_DAYS):
        return f'monthly on {_numbers(dom)}{when}'
    return f'every {_names(dow, DAYS)}{when}'
