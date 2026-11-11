import asyncio
from typing import Any
from philo.utils.log import log
from philo.tools.base import ToolBase


class McpToolWrapper(ToolBase):
    def __init__(self, session, entry, toolDef):
        self.session = session
        self.entry = entry
        self.toolDef = toolDef
        self.toolName = f"mcp_{entry.name}_{toolDef.name}"
        self.toolDescription = toolDef.description or toolDef.name
        self.toolParameters = self.convert2LlmSchema(toolDef.inputSchema or {"type": "object", "properties": {}})

    def convert2LlmSchema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Normalize MCP schema to be compatible with LLM tool calling format."""
        result = {"type": schema.get("type", "object")}
        if "properties" in schema:
            props = {}
            for key, prop in schema["properties"].items():
                normalizedProp = {}
                # Use description if present, otherwise fall back to title
                if "description" in prop:
                    normalizedProp["description"] = prop["description"]
                elif "title" in prop:
                    normalizedProp["description"] = prop["title"]
                # Copy other standard fields
                for field in ["type", "enum", "default", "minimum", "maximum", "minLength", "maxLength", "items"]:
                    if field in prop:
                        normalizedProp[field] = prop[field]
                props[key] = normalizedProp
            result["properties"] = props
        if "required" in schema:
            result["required"] = schema["required"]
        return result

    @property
    def name(self) -> str:
        return self.toolName

    @property
    def description(self) -> str:
        return self.toolDescription

    @property
    def parameters(self) -> dict[str, Any]:
        return self.toolParameters

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types
        try:
            result = await asyncio.wait_for(
                self.session.call_tool(self.toolDef.name, arguments=kwargs),
                timeout=self.entry.timeout,
            )
        except asyncio.TimeoutError:
            log.red("MCP tool '{}' timed out after {}s", self.name, self.entry.timeout)
            return f"(MCP tool call timed out after {self.entry.timeout}s)"
        except asyncio.CancelledError:
            # MCP SDK's anyio cancel scopes can leak CancelledError on timeout/failure.
            # Re-raise only if our task was externally cancelled (e.g. /stop).
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            log.red("MCP tool '{}' was cancelled by server/SDK", self.name)
            return "(MCP tool call was cancelled)"
        except Exception as exc:
            log.red(
                "MCP tool '{}' failed: {}: {}",
                self.name,
                type(exc).__name__,
                exc,
            )
            return f"(MCP tool call failed: {type(exc).__name__})"

        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"
