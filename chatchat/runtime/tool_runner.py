"""Running the tools the model asked for, and answering it with what they said.

A tool call is one thing the model wants done; the answer is what came of
it. Between the two there is the tool's own result, and sometimes more
context the tool wants to add - the two travel together, which is why they
are gathered here rather than at the call site.
"""

from chatchat.hooks.events import AGENT_TOOL_CALL, emit


class ToolOutcome:
    """What one tool call produced."""

    def __init__(self, tool_use_id: str, content, additional_context: str = ""):
        self.tool_use_id = tool_use_id
        self.content = content
        self.additional_context = additional_context

    def as_result(self) -> dict:
        return {"type": "tool_result", "tool_use_id": self.tool_use_id, "content": self.content}


class ToolRunner:
    """Runs the tools a turn asked for, in the order they were asked for."""

    def __init__(self, *, execute, agent_name: str):
        self._execute = execute
        self._agent_name = agent_name

    async def run(self, calls) -> list:
        """Run each call and say what it produced.

        The result the model gets back is the tool's text and any blocks it
        returned; the extra context a tool asked for rides along as another
        block rather than replacing what the tool said.
        """
        outcomes = []
        for call in calls:
            emit(AGENT_TOOL_CALL, agent=self._agent_name, tool=call.name, input=call.input, tool_use_id=call.id)
            outcome = await self._execute(call)
            content = outcome.text
            if outcome.blocks:
                content = ([{"type": "text", "text": outcome.text}] if outcome.text else []) + list(outcome.blocks)
            outcomes.append(ToolOutcome(call.id, content, outcome.additional_context))
        return outcomes

    @staticmethod
    def as_message(outcomes) -> dict:
        """The message that answers the model: what each tool said, and what
        the tools wanted to add."""
        results = []
        for outcome in outcomes:
            results.append(outcome.as_result())
            if outcome.additional_context:
                results.append({"type": "text", "text": outcome.additional_context})
        return {"role": "user", "content": results}
