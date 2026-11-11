import os
import json
import asyncio
from philo.utils.log import log
from philo.agent.context import ContextBuilder
from philo.agent.toolmanager import ToolManager
from philo.agent.mcpmanager import McpManager
from philo.config.pconfig import PhiloConfig
from philo.llm.base import PhiloLlmBase
from philo.infra.bus import InboundMessage, OutboundMessage
from philo.infra.session import SessionManager, Session


class PhiloLoop(object):
    def __init__(self, pcfg: PhiloConfig):
        self.pcfg = pcfg
        self.llm: PhiloLlmBase = pcfg.llm
        self.sessionManager = SessionManager(self.pcfg.agentSpace)
        self.contextBuilder = ContextBuilder(self.pcfg)
        self.toolManager = self.initToolManager()
        logDir = self.pcfg.agentSpace / "logs" if self.pcfg.agentSpace is not None else None
        self.mcpManager = McpManager(self.toolManager, self.pcfg.mcpEntries, logDir=logDir)
        for tool in self.pcfg.extraTools:
            self.toolManager.register(tool)
        for skill in self.pcfg.extraSkills:
            self.contextBuilder.skills.addSkill(skill)
        self.consolidatingSessions: set[str] = set()
        self.consolidationTasks: set[asyncio.Task] = set()
        self.consolidationLocks: dict[str, asyncio.Lock] = {}
        self.totalInputTokens = 0
        self.totalOutputTokens = 0
        self.currentContextTokens = 0
        self.maxContextTokens = 0
        self.lastReasoningContent = None

    def getTokenUsageStats(self) -> dict:
        inputCost = (self.totalInputTokens / 1000000) * self.pcfg.inputTokenPrice
        outputCost = (self.totalOutputTokens / 1000000) * self.pcfg.outputTokenPrice
        totalCost = inputCost + outputCost
        contextWindow = self.llm.contextWindow
        contextUsagePercent = (self.currentContextTokens / contextWindow * 100) if contextWindow > 0 else 0
        maxContextUsagePercent = (self.maxContextTokens / contextWindow * 100) if contextWindow > 0 else 0
        return {
            "inputTokens": self.totalInputTokens,
            "outputTokens": self.totalOutputTokens,
            "totalTokens": self.totalInputTokens + self.totalOutputTokens,
            "inputCost": inputCost,
            "outputCost": outputCost,
            "totalCost": totalCost,
            "inputTokenPrice": self.pcfg.inputTokenPrice,
            "outputTokenPrice": self.pcfg.outputTokenPrice,
            "currentContextTokens": self.currentContextTokens,
            "maxContextTokens": self.maxContextTokens,
            "contextWindow": contextWindow,
            "contextUsagePercent": contextUsagePercent,
            "maxContextUsagePercent": maxContextUsagePercent,
        }

    def initToolManager(self):
        from philo.tools.exec import ExecTool
        from philo.tools.filesystem import ReadFileTool, WriteFileTool, ListDirTool, EditFileTool
        from philo.tools.message import MessageTool
        from philo.tools.websearch import BochaWebSearchTool, WebFetchTool
        toolManager = ToolManager()
        toolManager.register(ExecTool(workspace=self.pcfg.agentSpace, timeout=self.pcfg.execTimeout, pathAppends=self.pcfg.pathAppends))
        toolManager.register(ReadFileTool(workspace=self.pcfg.agentSpace, allowedDir=None))
        toolManager.register(ListDirTool(workspace=self.pcfg.agentSpace, allowedDir=None))
        toolManager.register(WriteFileTool(workspace=self.pcfg.agentSpace, allowedDir=self.pcfg.workspace))
        toolManager.register(EditFileTool(workspace=self.pcfg.agentSpace, allowedDir=self.pcfg.workspace))
        toolManager.register(MessageTool(bus=self.pcfg.bus))
        toolManager.register(WebFetchTool())
        if self.pcfg.bochaApiKey:
            toolManager.register(BochaWebSearchTool(apiKey=self.pcfg.bochaApiKey))
        return toolManager

    def checkMemoryConsolidation(self, session: Session):
        unconsolidated = len(session.messages) - session.nConsolidated
        if (unconsolidated >= self.pcfg.memoryWindow and session.sessionId not in self.consolidatingSessions):
            self.consolidatingSessions.add(session.sessionId)
            if session.sessionId not in self.consolidationLocks:
                self.consolidationLocks[session.sessionId] = asyncio.Lock()
            lock = self.consolidationLocks[session.sessionId]

            async def consolidateAndUnlock():
                try:
                    async with lock:
                        await self.contextBuilder.memory.consolidate(session, memoryWindow=self.pcfg.memoryWindow)
                finally:
                    self.consolidatingSessions.discard(session.sessionId)
                    task = asyncio.current_task()
                    if task is not None:
                        self.consolidationTasks.discard(task)
            task = asyncio.create_task(consolidateAndUnlock())
            self.consolidationTasks.add(task)

    async def processMessage(self, msg: InboundMessage, onProgressCallback=None):
        session = self.sessionManager.getSession(msg.sessionId, nobuf=self.pcfg.nobuf)
        history = session.getHistory(maxMessages=self.pcfg.memoryWindow)
        initialMessages = self.contextBuilder.buildMessages(
            history=history,
            currentMessage=msg.content,
            files=msg.files,
        )
        self.checkMemoryConsolidation(session)
        finalMsg = None
        messages = initialMessages
        newMessages = [initialMessages[-1]]
        try:
            finalMsg, _, messages = await self.innerLoop(
                msg,
                initialMessages,
                onProgressCallback,
                newMessages=newMessages,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.red("Inner loop error: {}".format(e))
            finalMsg = f"Error: {str(e)}"
        if finalMsg is None:
            finalMsg = "Done."
        session.addMessages(newMessages, 0)
        self.sessionManager.dumpSession(session)
        return OutboundMessage(
            channel=msg.channel,
            chatId=msg.chatId,
            content=finalMsg,
            metadata=msg.metadata,
        )

    def getCheckpointPath(self, sessionId):
        checkpointDir = os.path.join(self.pcfg.agentSpace, ".checkpoints")
        os.makedirs(checkpointDir, exist_ok=True)
        return os.path.join(checkpointDir, f"{sessionId}.json")

    def saveCheckpoint(self, sessionId, messages, iteration, msgData, newMessages=None):
        checkpointPath = self.getCheckpointPath(sessionId)
        checkpoint = {
            "sessionId": sessionId,
            "iteration": iteration,
            "messages": messages,
            "newMessages": newMessages or [],
            "msgData": msgData,
        }
        try:
            with open(checkpointPath, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.yellow("Failed to save checkpoint: {}", str(e))

    def loadCheckpoint(self, sessionId):
        checkpointPath = self.getCheckpointPath(sessionId)
        if not os.path.exists(checkpointPath):
            return None
        try:
            with open(checkpointPath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.yellow("Failed to load checkpoint: {}", str(e))
            return None

    def clearCheckpoint(self, sessionId):
        checkpointPath = self.getCheckpointPath(sessionId)
        if os.path.exists(checkpointPath):
            try:
                os.remove(checkpointPath)
            except Exception:
                pass

    def saveMessagesForDebug(self, messages, iteration, sessionId):
        debugDir = os.path.join(self.pcfg.agentSpace, ".debug")
        os.makedirs(debugDir, exist_ok=True)
        filename = f"messages_{sessionId}_iter{iteration}.json"
        filepath = os.path.join(debugDir, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.yellow("Failed to save debug messages: {}", str(e))

    async def innerLoop(self, msg, initialMessages, onProgressCallback, startIteration=0, startMessages=None, newMessages=None):
        messages = startMessages if startMessages is not None else initialMessages
        iteration = startIteration
        finalMsg = None
        currentContextTokens = 0
        toolsUsed: list[str] = []
        newMessages = [] if newMessages is None else newMessages
        self.saveMessagesForDebug(messages, iteration, msg.sessionId)

        msgData = {
            "channel": msg.channel,
            "senderId": msg.senderId,
            "chatId": msg.chatId,
            "content": msg.content,
            "files": msg.files,
            "sessionId": msg.sessionId,
            "metadata": msg.metadata,
        }

        while iteration < self.pcfg.maxToolIterations:
            iteration += 1

            contextWindow = self.llm.contextWindow
            if contextWindow > 0 and currentContextTokens > contextWindow * self.pcfg.contextWindowRatio:
                originalLen = len(messages)
                messages = await self.contextBuilder.pruneMessages(messages)
                if len(messages) < originalLen:
                    log.yellow("Context compressed: {} -> {} messages ({}% used)",
                               originalLen, len(messages),
                               int(currentContextTokens / contextWindow * 100))
                self.saveMessagesForDebug(messages, iteration, msg.sessionId)

            response = await self.llm.chat(
                messages=messages,
                tools=self.toolManager.getToolsSchema(),
                temperature=self.pcfg.temperature,
                maxTokens=self.pcfg.maxTokens,
                thinking=self.pcfg.thinking,
            )
            if response.usage:
                self.totalInputTokens += response.usage.get("prompt_tokens", 0)
                self.totalOutputTokens += response.usage.get("completion_tokens", 0)
                currentContextTokens = response.usage.get("prompt_tokens", 0)
                self.currentContextTokens = currentContextTokens
                if currentContextTokens > self.maxContextTokens:
                    self.maxContextTokens = currentContextTokens

            if response.hasToolCalls:
                if onProgressCallback is not None:
                    await onProgressCallback(msg, response.content)
                    if response.reasoningContent:
                        await onProgressCallback(msg, response.reasoningContent, reasoning=True)
                    if not any(tc.name == "ask_user" for tc in response.toolCalls):
                        await onProgressCallback(msg, response.formatToolHint(), toolHint=True)
                if response.reasoningContent:
                    self.lastReasoningContent = response.reasoningContent

                toolCallDictList = [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                    }
                } for tc in response.toolCalls]
                messages = self.contextBuilder.addAssistantMessage(
                    messages=messages,
                    content=response.content,
                    toolCalls=toolCallDictList,
                    reasoningContent=response.reasoningContent,
                )
                newMessages.append(messages[-1])
                self.saveMessagesForDebug(messages, iteration, msg.sessionId)
                for tc in response.toolCalls:
                    toolsUsed.append(tc.name)
                    args_str = json.dumps(tc.arguments, ensure_ascii=False)
                    log.inf("Tool call: {}({})", tc.name, args_str[:100])
                    context = {
                        "channel": msg.channel,
                        "chatId": msg.chatId,
                        "messageId": (msg.metadata.get("message_id") or msg.metadata.get("messageId")) if msg.metadata else None,
                    }
                    result = await self.toolManager.execute(tc.name, tc.arguments, context)
                    messages = self.contextBuilder.addToolResult(
                        messages=messages,
                        toolCallId=tc.id,
                        toolName=tc.name,
                        result=result,
                    )
                    newMessages.append(messages[-1])
                self.saveMessagesForDebug(messages, iteration, msg.sessionId)
                self.saveCheckpoint(msg.sessionId, messages, iteration, msgData, newMessages)
            else:
                if response.finishReason == "error":
                    log.red("LLM returned error: {}", (response.content or "")[:200])
                    finalMsg = response.content or "Sorry, I encountered an error calling the AI model."
                    break
                if response.reasoningContent:
                    self.lastReasoningContent = response.reasoningContent
                    if onProgressCallback is not None:
                        await onProgressCallback(msg, response.reasoningContent, reasoning=True)
                messages = self.contextBuilder.addAssistantMessage(
                    messages=messages,
                    content=response.content,
                    reasoningContent=response.reasoningContent,
                )
                newMessages.append(messages[-1])
                self.saveMessagesForDebug(messages, iteration, msg.sessionId)
                finalMsg = response.content
                break

        if finalMsg is None and iteration >= self.pcfg.maxToolIterations:
            log.yellow("Max iterations ({}) reached", self.pcfg.maxToolIterations)
            finalMsg = f"I reached the maximum number of tool call iterations ({self.pcfg.maxToolIterations}) without completing the task. You can try breaking the task into smaller steps."

        if finalMsg is not None:
            self.clearCheckpoint(msg.sessionId)

        return finalMsg, toolsUsed, messages

    async def resumeMessage(self, sessionId, onProgressCallback=None):
        checkpoint = self.loadCheckpoint(sessionId)
        if checkpoint is None:
            log.yellow("No checkpoint found for session: {}", sessionId)
            return None

        log.green("Resuming session {} from iteration {}", sessionId, checkpoint["iteration"])

        msgData = checkpoint["msgData"]
        msg = InboundMessage(
            channel=msgData["channel"],
            senderId=msgData.get("senderId", "unknown"),
            chatId=msgData["chatId"],
            content=msgData["content"],
            files=msgData.get("files"),
            metadata=msgData.get("metadata"),
        )

        session = self.sessionManager.getSession(sessionId, nobuf=self.pcfg.nobuf)
        self.checkMemoryConsolidation(session)

        finalMsg = None
        messages = checkpoint["messages"]
        newMessages = checkpoint.get("newMessages")
        if newMessages is None:
            history = session.getHistory(maxMessages=self.pcfg.memoryWindow)
            newMessages = messages[1 + len(history):]
        try:
            finalMsg, _, messages = await self.innerLoop(
                msg,
                initialMessages=[],
                onProgressCallback=onProgressCallback,
                startIteration=checkpoint["iteration"],
                startMessages=messages,
                newMessages=newMessages,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.red("Resume inner loop error: {}", str(e))
            finalMsg = f"Error: {str(e)}"

        if finalMsg is None:
            finalMsg = "Done."

        session.addMessages(newMessages, 0)
        self.sessionManager.dumpSession(session)

        return OutboundMessage(
            channel=msg.channel,
            chatId=msg.chatId,
            content=finalMsg,
            metadata=msg.metadata,
        )

    def hasCheckpoint(self, sessionId) -> bool:
        checkpoint = self.loadCheckpoint(sessionId)
        return checkpoint is not None

    def listCheckpoints(self) -> list[dict]:
        checkpointDir = os.path.join(self.pcfg.agentSpace, ".checkpoints")
        if not os.path.exists(checkpointDir):
            return []
        checkpoints = []
        for filename in os.listdir(checkpointDir):
            if filename.endswith(".json"):
                filepath = os.path.join(checkpointDir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    checkpoints.append({
                        "sessionId": data.get("sessionId"),
                        "iteration": data.get("iteration"),
                        "messageCount": len(data.get("messages", [])),
                    })
                except Exception:
                    continue
        return checkpoints