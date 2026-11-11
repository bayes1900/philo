import re
import json
import time
import asyncio
import httpx
import openai
from openai import AsyncOpenAI
from philo.llm.base import PhiloLlmBase, LLMResponse, ToolCallRequest
from philo.utils.log import log


class PhiloOpenAiLlm(PhiloLlmBase):
    # Pattern for parsing text-embedded tool calls (e.g., DeepSeek format)
    # Format: <|tool_calls_section_begin|> <|tool_call_begin|> functions.name:id <|tool_call_argument_begin|> {json} <|tool_call_end|>
    TOOL_CALL_PATTERN = re.compile(
        r'<\|tool_call_begin\|>\s*'
        r'functions\.([^:]+):(\d+)'  # function name and id
        r'\s*<\|tool_call_argument_begin\|>\s*'
        r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'  # json object with optional single-level nesting
        r'\s*<\|tool_call_end\|>',
        re.DOTALL
    )
    TOOL_CALLS_SECTION_BEGIN = '<|tool_calls_section_begin|>'

    # Pattern for parsing text-embedded reasoning content (e.g., DeepSeek format)
    # Format: <!think>reasoning content</!think>
    THINK_PATTERN = re.compile(r'<!think>(.*?)</!think>', re.DOTALL)

    MAX_RETRY_FALLBACK = 5

    def isRetryableError(self, error) -> bool:
        statusCode = getattr(error, "status_code", None)
        if statusCode is None:
            response = getattr(error, "response", None)
            statusCode = getattr(response, "status_code", None)
        if statusCode is not None:
            return statusCode == 429 or statusCode >= 500
        return isinstance(error, (
            openai.APIConnectionError,
            openai.APITimeoutError,
            httpx.TimeoutException,
            httpx.NetworkError,
            asyncio.TimeoutError,
            ConnectionError,
        ))

    def __init__(self, modelName, contextWindow, url, apiKey="", maxRetry=None):
        self.modelName = modelName
        self.contextWindow = contextWindow
        self.client = AsyncOpenAI(
            api_key=apiKey,
            base_url=url,
        )
        self.maxRetry = maxRetry

    def extractContent(self, response) -> str | None:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            if hasattr(message, "content") and message.content:
                return message.content
        return None

    def extractReasoningContent(self, response) -> str | None:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            if hasattr(message, "reasoning") and message.reasoning:
                return message.reasoning
            if hasattr(message, "reasoning_content") and message.reasoning_content:
                return message.reasoning_content
        return None

    def extractToolCalls(self, response) -> list[ToolCallRequest]:
        toolCalls = []
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    if isinstance(tc.function.arguments, dict):
                        args = tc.function.arguments
                    elif isinstance(tc.function.arguments, str):
                        try:
                            args = json.loads(tc.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    else:
                        args = {}
                    toolCalls.append(ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    ))
        return toolCalls

    def extractTextEmbeddedToolCalls(self, content: str | None) -> list[ToolCallRequest]:
        if not content or self.TOOL_CALLS_SECTION_BEGIN not in content:
            return []

        toolCalls = []
        for match in self.TOOL_CALL_PATTERN.finditer(content):
            name = match.group(1).strip()
            call_id = match.group(2).strip()
            args_str = match.group(3).strip()

            try:
                arguments = json.loads(args_str)
            except json.JSONDecodeError:
                arguments = {}

            toolCalls.append(ToolCallRequest(
                id=call_id,
                name=name,
                arguments=arguments,
            ))

        return toolCalls

    def extractTextEmbeddedReasoning(self, content: str | None) -> tuple[str | None, str | None]:
        if not content:
            return content, None

        match = self.THINK_PATTERN.search(content)
        if not match:
            return content, None

        reasoning = match.group(1).strip()
        cleaned = self.THINK_PATTERN.sub('', content).strip()

        return cleaned, reasoning

    def extractFinishReason(self, response) -> str:
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "finish_reason") and choice.finish_reason:
                return choice.finish_reason
        return "stop"

    def extractUsage(self, response, secs) -> dict[str, int]:
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
                "speed": int(response.usage.completion_tokens / secs) if secs > 0 else 0,
            }
            return usage
        return {}

    async def chat(self, messages, tools=None, **kwargs) -> LLMResponse:
        t0 = time.time()
        errored = False
        ee = None
        response = None
        retryCount = 0
        maxRetryInterval = 300  # 5 minutes
        effectiveMaxRetry = self.maxRetry if self.maxRetry is not None else self.MAX_RETRY_FALLBACK

        while True:
            try:
                params = {
                    "model": self.modelName,
                    "messages": messages,
                }
                if tools is not None and len(tools) > 0:
                    params["tools"] = tools
                if "temperature" in kwargs:
                    params["temperature"] = kwargs["temperature"]
                if "maxTokens" in kwargs and kwargs["maxTokens"] is not None:
                    params["max_tokens"] = kwargs["maxTokens"]
                else:
                    params["max_tokens"] = 8192
                if "thinking" in kwargs and kwargs["thinking"] is not None:
                    thinkingVal = kwargs["thinking"]
                    extraBody = {}
                    if thinkingVal == "disable":
                        extraBody["chat_template_kwargs"] = {"thinking": False}
                    elif thinkingVal == "enabled":
                        extraBody["chat_template_kwargs"] = {"thinking": True}
                    elif thinkingVal == "max":
                        extraBody["chat_template_kwargs"] = {"thinking": True}
                        params["reasoning_effort"] = "max"
                    else:
                        extraBody["chat_template_kwargs"] = {"thinking": True}
                        params["reasoning_effort"] = thinkingVal
                    extraBody["separate_reasoning"] = True
                    params["extra_body"] = extraBody
                response = await self.client.chat.completions.create(**params)
                if retryCount > 0:
                    log.green("LLM call recovered after {} retries", retryCount)
                errored = False
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not self.isRetryableError(e):
                    raise
                retryCount += 1
                if retryCount >= effectiveMaxRetry:
                    errored = True
                    ee = e
                    break
                delay = min(retryCount * 5, maxRetryInterval)
                log.red("LLM call failed (attempt {}), retrying in {}s: {}", retryCount, delay, e)
                await asyncio.sleep(delay)
        if errored and ee is not None:
            raise ee
        t1 = time.time()

        content = self.extractContent(response)
        toolCalls = self.extractToolCalls(response)
        reasoningContent = self.extractReasoningContent(response)

        if not toolCalls:
            toolCalls = self.extractTextEmbeddedToolCalls(content)

        if not reasoningContent:
            content, reasoningContent = self.extractTextEmbeddedReasoning(content)

        return LLMResponse(
            content=content,
            toolCalls=toolCalls,
            finishReason=self.extractFinishReason(response),
            usage=self.extractUsage(response, t1 - t0),
            reasoningContent=reasoningContent,
        )