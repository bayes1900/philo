import base64
import mimetypes
from pathlib import Path
from typing import Any
from jinja2 import Environment, StrictUndefined
from philo.agent.memory import MemoryStore
from philo.agent.skillsloader import SkillsLoader
from philo.utils.misc import detectImageMime, getYaml
from philo.utils.yamlio import YamlLoader


class ContextBuilder(object):
    def __init__(self, pcfg):
        self.pcfg = pcfg
        self.memory = MemoryStore(pcfg)
        self.skills = SkillsLoader(pcfg)
        self.yamlTemplate = YamlLoader(getYaml("context.yaml"))
        self.systemPromptGen = Environment(undefined=StrictUndefined).from_string(self.yamlTemplate["system"])
        self.initSoul()

    def initSoul(self):
        if self.pcfg.soul is None:
            self.soul = None
            return
        try:
            path = Path(self.pcfg.soul)
            self.soul = path.read_text()
        except Exception:
            self.soul = self.pcfg.soul

    def buildSystemPrompt(self) -> str:
        workspace = str(self.pcfg.agentSpace.absolute()) if self.pcfg.agentSpace else None
        return self.systemPromptGen.render(
            soul=self.soul,
            workspace=workspace,
            memory=self.memory.getMemoryContext(),
            skillsSummary=self.skills.buildSkillsSummary(),
            skillsInline=self.skills.buildInlineSkills(),
            mode=self.pcfg.mode,
        )

    def buildMessages(
        self,
        history: list[dict[str, Any]],
        currentMessage: str,
        files: list[str] | None = None,
    ):
        userContent = self.buildUserContent(currentMessage, files)
        return [
            {"role": "system", "content": self.buildSystemPrompt()},
            *history,
            {"role": "user", "content": userContent},
        ]

    def buildUserContent(self, text, files) -> str | list[dict[str, Any]]:
        if files is None or len(files) == 0:
            return text
        images = []
        for path in files:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            mime = detectImageMime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        if len(images) == 0:
            return text
        return images + [{"type": "text", "text": text}]

    def addToolResult(self, messages, toolCallId, toolName, result):
        messages.append({"role": "tool", "tool_call_id": toolCallId, "name": toolName, "content": result})
        return messages

    def addAssistantMessage(self, messages, content, toolCalls=None, reasoningContent=None):
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if toolCalls:
            msg["tool_calls"] = toolCalls
            msg["tool_used"] = [x["function"]["name"] for x in toolCalls]
        if reasoningContent is not None:
            msg["reasoning_content"] = reasoningContent
        messages.append(msg)
        return messages

    async def pruneMessages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Prune messages to prevent context overflow.

        Strategy:
        1. Always keep system message (index 0)
        2. Always keep the last user message
        3. Keep recent assistant+tool pairs (configurable)
        4. Summarize middle messages using LLM

        Returns:
            Pruned messages list
        """
        if len(messages) <= self.pcfg.minKeepMessages:
            return messages

        # Find indices of key messages
        systemIdx = 0
        lastUserIdx = None
        toolPairBoundaries = []  # List of (assistant_idx, last_tool_idx) pairs

        i = 1
        while i < len(messages):
            msg = messages[i]
            if msg.get("role") == "user":
                lastUserIdx = i
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Found an assistant message with tool calls
                assistantIdx = i
                # Find all corresponding tool results
                j = i + 1
                lastToolIdx = i
                while j < len(messages) and messages[j].get("role") == "tool":
                    lastToolIdx = j
                    j += 1
                toolPairBoundaries.append((assistantIdx, lastToolIdx))
                i = j
                continue
            i += 1

        # If no user message found, keep all messages
        if lastUserIdx is None:
            return messages

        # Determine which tool pairs to keep (most recent ones)
        keepPairs = self.pcfg.keepRecentToolPairs
        if keepPairs <= 0:
            recentPairs = []
        elif len(toolPairBoundaries) > keepPairs:
            recentPairs = toolPairBoundaries[-keepPairs:]
        else:
            recentPairs = toolPairBoundaries

        # Build set of indices to keep
        keepIndices = {systemIdx, lastUserIdx}
        for assistantIdx, lastToolIdx in recentPairs:
            for idx in range(assistantIdx, lastToolIdx + 1):
                keepIndices.add(idx)

        # If we're keeping most messages anyway, return as-is
        if len(keepIndices) >= len(messages) - 2:
            return messages

        # Collect messages to summarize (those not in keepIndices)
        toSummarize = []
        for i, msg in enumerate(messages):
            if i not in keepIndices:
                toSummarize.append(msg)

        # Generate summary using LLM
        summary = await self.summarizeMessages(toSummarize)

        # Build pruned message list
        pruned = [messages[systemIdx]]  # System message

        # Insert summary after system message
        if summary:
            summaryMsg = {
                "role": "user",
                "content": "[Previous conversation summary]\n" + summary
            }
            pruned.append(summaryMsg)

        # Add kept messages (excluding system which is already added)
        for i, msg in enumerate(messages):
            if i in keepIndices and i != systemIdx:
                pruned.append(msg)

        return pruned

    async def summarizeMessages(self, messages: list[dict[str, Any]]) -> str:
        """Summarize a list of messages using LLM.

        Args:
            messages: List of messages to summarize

        Returns:
            Summary string
        """
        if not messages:
            return ""

        # Build text representation of messages
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multi-part content
                textParts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        textParts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        textParts.append(part)
                content = " ".join(textParts)
            if content:
                # Truncate very long content
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"[{role}]: {content}")
            # Include tool call info
            if role == "assistant" and msg.get("tool_calls"):
                toolNames = [tc.get("function", {}).get("name", "unknown") for tc in msg["tool_calls"]]
                lines.append(f"[{role} called tools]: {', '.join(toolNames)}")
            if role == "tool":
                toolName = msg.get("name", "unknown")
                lines.append(f"[tool result from {toolName}]")

        if not lines:
            return ""

        conversationText = "\n".join(lines)

        # Use LLM to generate summary
        summaryPrompt = (
            "Please summarize the following conversation history concisely. "
            "Focus on key information, decisions made, and important context that would be useful for continuing the conversation. "
            "Keep the summary brief but informative.\n\n"
            f"Conversation:\n{conversationText}"
        )

        try:
            response = await self.pcfg.llm.chat(
                messages=[{"role": "user", "content": summaryPrompt}],
                temperature=0.3,
                maxTokens=self.pcfg.maxTokens,
                thinking=self.pcfg.thinking,
            )
            return response.content or ""
        except Exception as e:
            # Fallback: return a truncated version of the conversation
            return f"[Summary unavailable due to error: {str(e)[:50]}]\n{conversationText[:500]}..."
