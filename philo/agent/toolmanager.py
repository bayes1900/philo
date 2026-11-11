import asyncio
from typing import Any
from philo.tools.base import ToolBase


class ToolManager(object):
    def __init__(self):
        self.tools: dict[str, ToolBase] = {}
        self.errorHint = "\n\n[Analyze the error above and try a different approach.]"

    @property
    def toolNames(self) -> list[str]:
        return list(self.tools.keys())

    def __len__(self) -> int:
        return len(self.tools)

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def register(self, tool: ToolBase) -> None:
        self.tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self.tools.pop(name, None)

    def get(self, name: str) -> ToolBase | None:
        return self.tools.get(name)

    def has(self, name: str) -> bool:
        return name in self.tools

    def getToolsSchema(self) -> list[dict[str, Any]]:
        return [tool.getSchema() for tool in self.tools.values()]

    async def execute(self, name: str, params: dict[str, Any], context: dict[str, Any] = None) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.toolNames)}"
        try:
            params = tool.castParams(params)
            errors = tool.validateParams(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + self.errorHint
            if context:
                params["context"] = context
            result = await tool.execute(**params)
            return result
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + self.errorHint