from __future__ import annotations

import asyncio

from chatchat.tool import Tool, tool

MAX_QUESTIONS = 4
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_HEADER_CHARS = 12


def _question_problems(questions) -> str:
    if not isinstance(questions, list) or not questions:
        return "AskUserQuestion needs at least one question"
    if len(questions) > MAX_QUESTIONS:
        return f"AskUserQuestion takes at most {MAX_QUESTIONS} questions"
    for index, question in enumerate(questions, start=1):
        if not str((question or {}).get("question") or "").strip():
            return f"question {index} needs its text"
        header = str(question.get("header") or "")
        if not header.strip():
            return f"question {index} needs a header"
        if len(header) > MAX_HEADER_CHARS:
            return f"question {index} has a header over {MAX_HEADER_CHARS} characters"
        options = question.get("options") or []
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            return f"question {index} needs between {MIN_OPTIONS} and {MAX_OPTIONS} options"
        for option in options:
            label = str((option or {}).get("label") or "").strip()
            if not label:
                return f"question {index} has an option without a label"
            if not str(option.get("description") or "").strip():
                return f'question {index} has an option ("{label}") without a description'
    return ""


@tool(
    name="AskUserQuestion",
    description=f"""Ask the human 1 to {MAX_QUESTIONS} questions and wait for the answers, when a choice they can make
would change what you do.
Give each question {MIN_OPTIONS} to {MAX_OPTIONS} options worth picking; they can also answer in their own words.
When they have to compare concrete results, put the artifact on the option as preview.""",
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_QUESTIONS,
                "description": f"Questions to ask the user (1-{MAX_QUESTIONS}).",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": 'The complete question: clear, specific and ending with "?".',
                        },
                        "header": {
                            "type": "string",
                            "maxLength": MAX_HEADER_CHARS,
                            "description": f'Very short label shown as a chip/tag (max {MAX_HEADER_CHARS} chars), e.g. "Auth method".',
                        },
                        "multiSelect": {
                            "type": "boolean",
                            "default": False,
                            "description": "Allow several options to be picked. Use it when the choices are not mutually exclusive.",
                        },
                        "options": {
                            "type": "array",
                            "minItems": MIN_OPTIONS,
                            "maxItems": MAX_OPTIONS,
                            "description": f'The {MIN_OPTIONS}-{MAX_OPTIONS} choices. Do not add an "Other" option: one is offered automatically.',
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "Display text the user picks: one to five words naming the choice.",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "What the option means, or what happens if it is chosen, including the trade-off.",
                                    },
                                    "preview": {
                                        "type": "string",
                                        "description": "The artifact this option would produce, shown beside the options while it is picked. Use it when the user has to compare concrete results, not for a plain preference. Only single-select questions show previews.",
                                    },
                                },
                                "required": ["label", "description"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["question", "header", "options"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["questions"],
        "additionalProperties": False,
    },
)
async def ask_user(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    questions = input.get("questions") or []
    problem = _question_problems(questions)
    if problem:
        return f"Error: {problem}"
    await team.hooks.execute_elicitation_hooks(agent, str(questions[0].get("question") or ""))
    answers = team.ask_user(agent, questions)
    if asyncio.iscoroutine(answers):
        answers = await answers
    lines = []
    for index, question in enumerate(questions):
        answer = str(answers[index] if index < len(answers) else "")
        answer = answer or "no answer"
        lines.append(f"{question['question']}: {answer}")
    await team.hooks.execute_elicitation_result_hooks(agent, "\n".join(lines))
    return "The user answered:\n" + "\n".join(lines) + "\nCarry on with those answers."


def tools(team) -> list[Tool]:
    return [ask_user] if team.ask_user is not None else []
