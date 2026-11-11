import asyncio
from philo.utils.log import log
from philo.agent.context import ContextBuilder
from philo.config.pconfig import PhiloConfig
from philo.llm.base import PhiloLlmBase
from philo.infra.bus import InboundMessage, OutboundMessage


class PhiloChat(object):
    def __init__(self, pcfg: PhiloConfig):
        self.pcfg = pcfg
        self.llm: PhiloLlmBase = pcfg.llm
        self.contextBuilder = ContextBuilder(self.pcfg)
        # Token usage tracking
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

    async def processMessage(self, msg: InboundMessage):
        messages = self.contextBuilder.buildMessages(
            history=[],
            currentMessage=msg.content,
        )
        try:
            response = await self.llm.chat(
                messages=messages,
                tools=None,
                temperature=self.pcfg.temperature,
                maxTokens=self.pcfg.maxTokens,
                thinking=self.pcfg.thinking,
            )
            if response.usage:
                self.totalInputTokens += response.usage.get("prompt_tokens", 0)
                self.totalOutputTokens += response.usage.get("completion_tokens", 0)
                self.currentContextTokens = response.usage.get("prompt_tokens", 0)
                if self.currentContextTokens > self.maxContextTokens:
                    self.maxContextTokens = self.currentContextTokens
            content = response.content or "Done."
            reasoningContent = response.reasoningContent

        except Exception as e:
            log.red("Chat error: {}".format(e))
            content = f"Error: {str(e)}"
            reasoningContent = None

        self.lastReasoningContent = reasoningContent

        return OutboundMessage(
            channel=msg.channel,
            chatId=msg.chatId,
            content=content,
            metadata={**(msg.metadata or {}), "reasoningContent": reasoningContent},
        )

    async def chat(self, message: str) -> str:
        msg = InboundMessage(
            channel="direct",
            senderId="chat",
            chatId="default",
            content=message,
        )
        result = await self.processMessage(msg)
        return result.content

    def chatSync(self, message: str) -> str:
        return asyncio.run(self.chat(message))