import asyncio
from typing import Any
from tqdm import tqdm
from philo.utils.misc import createShmDir


async def react(
    message: str,
    soul=None,
    workspace=None,
    index=0,
    tools=None,
    skills=None,
    thinking=None,
    maxTokens=None,
    temperature=None,
) -> dict[str, Any]:
    from philo.cfgops.o0 import pcfg
    from philo.agent.loop import PhiloLoop
    from philo.infra.bus import InboundMessage

    pcfg = pcfg()
    pcfg.cfgname = "api_react_{}".format(index)
    pcfg.oneshotInput = message
    pcfg.verbose = False
    pcfg.workspace = createShmDir("philox") if workspace is None else workspace
    if soul is not None:
        pcfg.soul = soul
    if tools is not None:
        pcfg.extraTools = tools
    if skills is not None:
        pcfg.extraSkills = skills
    if thinking is not None:
        pcfg.thinking = thinking
    if maxTokens is not None:
        pcfg.maxTokens = maxTokens
    if temperature is not None:
        pcfg.temperature = temperature
    pcfg.finalize()

    loop = PhiloLoop(pcfg)

    msg = InboundMessage(
        channel="api",
        senderId="react",
        chatId=pcfg.cfgname,
        content=message,
    )
    try:
        await loop.mcpManager.checkConnection()
        result = await loop.processMessage(msg)
        stats = loop.getTokenUsageStats()
        succeeded = not result.content.startswith("Error:")
        return {
            "succeeded": succeeded,
            "content": result.content,
            "reasoningContent": loop.lastReasoningContent,
            "usage": {
                "inputTokens": stats["inputTokens"],
                "outputTokens": stats["outputTokens"],
                "totalTokens": stats["totalTokens"],
                "totalCost": stats["totalCost"],
            }
        }
    finally:
        await loop.mcpManager.disconnect()
        if hasattr(pcfg.llm, 'client') and hasattr(pcfg.llm.client, 'close'):
            await pcfg.llm.client.close()


async def chat(message: str, soul=None, thinking=None, maxTokens=None, temperature=None) -> dict[str, Any]:
    from philo.cfgops.o0 import pcfg
    from philo.agent.chat import PhiloChat

    pcfg = pcfg()
    pcfg.cfgname = "api_chat"
    pcfg.mode = "chat"
    pcfg.verbose = False
    if soul is not None:
        pcfg.soul = soul
    if thinking is not None:
        pcfg.thinking = thinking
    if maxTokens is not None:
        pcfg.maxTokens = maxTokens
    if temperature is not None:
        pcfg.temperature = temperature
    pcfg.finalize()

    chat = PhiloChat(pcfg)
    try:
        content = await chat.chat(message)
        stats = chat.getTokenUsageStats()
        reasoningContent = chat.lastReasoningContent
        succeeded = not content.startswith("Error:")
        return {
            "succeeded": succeeded,
            "content": content,
            "reasoningContent": reasoningContent,
            "usage": {
                "inputTokens": stats["inputTokens"],
                "outputTokens": stats["outputTokens"],
                "totalTokens": stats["totalTokens"],
                "totalCost": stats["totalCost"],
            }
        }
    finally:
        if hasattr(pcfg.llm, 'client') and hasattr(pcfg.llm.client, 'close'):
            await pcfg.llm.client.close()


def reactSync(message: str, soul=None, workspace=None, tools=None, skills=None, thinking=None, maxTokens=None, temperature=None) -> dict[str, Any]:
    return asyncio.run(react(message, soul, workspace, tools=tools, skills=skills, thinking=thinking, maxTokens=maxTokens, temperature=temperature))


def chatSync(message: str, soul=None, thinking=None, maxTokens=None, temperature=None) -> dict[str, Any]:
    return asyncio.run(chat(message, soul, thinking=thinking, maxTokens=maxTokens, temperature=temperature))


def reactBatch(messages: list[str], soul=None, workspace=None, maxConn=20, tools=None, skills=None, thinking=None, maxTokens=None, temperature=None) -> list[dict[str, Any]]:
    async def run_batch():
        semaphore = asyncio.Semaphore(maxConn)
        results = [None] * len(messages)
        pbar = tqdm(total=len(messages), desc="React Batch [{}]".format(maxConn), unit="msg", ncols=80)
        async def run_with_semaphore(msg, idx):
            async with semaphore:
                try:
                    result = await react(msg, soul, workspace, index=idx, tools=tools, skills=skills, thinking=thinking, maxTokens=maxTokens, temperature=temperature)
                    return idx, result
                finally:
                    pbar.update(1)
        tasks = [run_with_semaphore(msg, i) for i, msg in enumerate(messages)]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        pbar.close()
        for idx, item in enumerate(completed):
            if isinstance(item, Exception):
                results[idx] = {
                    "succeeded": False,
                    "content": f"Error: {str(item)}",
                    "reasoningContent": None,
                    "usage": {
                        "inputTokens": 0,
                        "outputTokens": 0,
                        "totalTokens": 0,
                        "totalCost": 0.0,
                    }
                }
            else:
                _, result = item
                results[idx] = result
        return results
    return asyncio.run(run_batch())


def chatBatch(messages: list[str], soul=None, maxConn=20, thinking=None, maxTokens=None, temperature=None) -> list[dict[str, Any]]:
    async def run_batch():
        semaphore = asyncio.Semaphore(maxConn)
        results = [None] * len(messages)
        pbar = tqdm(total=len(messages), desc="Chat Batch [{}]".format(maxConn), unit="msg", ncols=80)
        async def run_with_semaphore(msg, idx):
            async with semaphore:
                try:
                    result = await chat(msg, soul, thinking=thinking, maxTokens=maxTokens, temperature=temperature)
                    return idx, result
                finally:
                    pbar.update(1)
        tasks = [run_with_semaphore(msg, i) for i, msg in enumerate(messages)]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        pbar.close()
        for idx, item in enumerate(completed):
            if isinstance(item, Exception):
                results[idx] = {
                    "succeeded": False,
                    "content": f"Error: {str(item)}",
                    "reasoningContent": None,
                    "usage": {
                        "inputTokens": 0,
                        "outputTokens": 0,
                        "totalTokens": 0,
                        "totalCost": 0.0,
                    }
                }
            else:
                _, result = item
                results[idx] = result
        return results
    return asyncio.run(run_batch())
