from __future__ import annotations

import os

from jsonschema import validators


DEFAULT_RETRIES = 5

RETRY_ENV = 'MAX_STRUCTURED_OUTPUT_RETRIES'

STRUCTURED_OUTPUT_TOOL = 'StructuredOutput'


def retries() -> int:
    try:
        return max(1, int(os.environ.get(RETRY_ENV, DEFAULT_RETRIES)))
    except ValueError:
        return DEFAULT_RETRIES


def _type(schema) -> type:
    return validators.validator_for(schema)


def schema_problem(schema) -> str:
    try:
        _type(schema).check_schema(schema)
    except Exception as exc:
        return str(exc).splitlines()[0]
    return ''


def mismatch(schema, payload) -> str:
    errors = sorted(_type(schema)(schema).iter_errors(payload),
                    key=lambda error: list(error.absolute_path))
    parts = []
    for error in errors:
        path = '/'.join(str(part) for part in error.absolute_path) or 'root'
        parts.append(f'{path}: {error.message}')
    return ', '.join(parts)
