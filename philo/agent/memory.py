import json
from pathlib import Path
from jinja2 import Environment, StrictUndefined
from philo.utils.log import log
from philo.llm.base import PhiloLlmBase
from philo.infra.session import Session
from philo.utils.misc import getYaml
from philo.utils.yamlio import YamlLoader


class MemoryStore(object):
    @classmethod
    def getSaveMemoryTool(cls):
        return [{
            "type": "function",
            "function": {
                "name": "save_memory",
                "description": "Save the memory consolidation result to persistent storage.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "history_entry": {
                            "type": "string",
                            "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                            "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                        },
                        "memory_update": {
                            "type": "string",
                            "description": "Full updated long-term memory as markdown. Include all existing "
                            "facts plus new ones. Return unchanged if nothing new.",
                        },
                    },
                    "required": ["history_entry", "memory_update"],
                },
            },
        }]

    def __init__(self, pcfg):
        self.pcfg = pcfg
        self.llm: PhiloLlmBase = pcfg.llm
        self.memoryDir: Path | None = None
        self.memoryFile: Path | None = None
        self.historyFile: Path | None = None
        if pcfg.agentSpace is not None:
            self.memoryDir = pcfg.agentSpace / "memory"
            self.memoryDir.mkdir(parents=True, exist_ok=True)
            self.memoryFile = self.memoryDir / "MEMORY.md"
            self.historyFile = self.memoryDir / "HISTORY.md"
        self.yamlTemplate = YamlLoader(getYaml("memory.yaml"))
        self.systemPromptGen = Environment(undefined=StrictUndefined).from_string(self.yamlTemplate["system"])
        self.userPromptGen = Environment(undefined=StrictUndefined).from_string(self.yamlTemplate["user"])

    def readLongTerm(self) -> str:
        if self.memoryFile is None or not self.memoryFile.exists():
            return ""
        return self.memoryFile.read_text(encoding="utf-8")

    def writeLongTerm(self, content: str) -> None:
        if self.memoryFile is None:
            return
        self.memoryFile.write_text(content, encoding="utf-8")

    def appendHistory(self, entry: str) -> None:
        if self.historyFile is None:
            return
        with open(self.historyFile, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def getMemoryContext(self) -> str:
        if self.memoryFile is None:
            return "(disabled)"
        longTerm = self.readLongTerm()
        return f"## Long-term Memory\n{longTerm}" if longTerm else "(empty)"

    async def consolidate(self, session: Session, archiveAll=False, memoryWindow=50) -> bool:
        messageCount = len(session.messages)
        if archiveAll:
            oldMessages = session.messages
            keepCount = 0
            log.inf("Memory consolidation (archive all): {} messages", messageCount)
        else:
            keepCount = memoryWindow // 2
            if messageCount <= keepCount:
                return True
            if messageCount - session.nConsolidated <= 0:
                return True
            oldMessages = session.messages[session.nConsolidated : messageCount - keepCount]
            if not oldMessages:
                return True
            log.inf("Memory consolidation: {} to consolidate, {} keep", len(oldMessages), keepCount)

        lines = []
        for m in oldMessages:
            if not m.get("content") and not m.get("tool_calls"):
                continue
            tools = f" [tools: {', '.join(m['tool_used'])}]" if m.get("tool_used") else ""
            roleText = m["role"].upper()
            contentText = m.get("content", "")
            lines.append(f"{roleText}{tools}: {contentText}")

        currentMemory = self.readLongTerm() or "(empty)"
        systemPrompt = self.systemPromptGen.render()
        userPrompt = self.userPromptGen.render(
            currentMemory=currentMemory,
            conversation="\n".join(lines)
        )
        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": systemPrompt},
                    {"role": "user", "content": userPrompt},
                ],
                tools=self.getSaveMemoryTool(),
                maxTokens=self.pcfg.maxTokens,
                thinking=self.pcfg.thinking,
            )
            if not response.hasToolCalls:
                log.red("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.toolCalls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            if isinstance(args, list):
                if args and isinstance(args[0], dict):
                    args = args[0]
                else:
                    log.red("Memory consolidation: unexpected arguments as empty or non-dict list: {}".format(args))
                    return False
            if not isinstance(args, dict):
                log.red("Memory consolidation: unexpected arguments type {}", args)
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.appendHistory(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != currentMemory:
                    self.writeLongTerm(update)

            session.nConsolidated = 0 if archiveAll else messageCount - keepCount
            log.inf("Done memory consolidation: {} messages, nconsolidated={}", messageCount, session.nConsolidated)
            return True

        except Exception as e:
            log.red("Failed to consolidate memory: {}".format(e))
            return False
