from typing import Any

from philo.tools.base import ToolBase


class AskUserTool(ToolBase):
    def __init__(self, askUser):
        self.askUser = askUser

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return (
            "Ask the user a question and wait for their answer. "
            "Use this only when essential information is missing and you cannot proceed safely. "
            "Ask one concise question at a time."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user",
                    "minLength": 1,
                }
            },
            "required": ["question"],
        }

    async def execute(self, question: str, **kwargs: Any) -> str:
        try:
            answer = await self.askUser(question)
        except Exception as e:
            return f"Error asking user: {e}"
        if answer is None or not str(answer).strip():
            return "(no answer)"
        return str(answer).strip()
